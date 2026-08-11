"""
Ingestão do Diário Oficial da União.

Orquestra as três camadas: pede bytes ao inlabs_client, grava em disco, chama o
dou_xml_parser e faz upsert no banco, registrando a execução em DouSyncRun.

Duas propriedades sustentam o módulo:

  * **Idempotência** — o hash da matéria é UNIQUE e o upsert casa por
    (edition_id, art_id, id_materia). Reprocessar um dia é UPDATE, nunca
    INSERT duplicado.
  * **Janela de reverificação** — o INLABS reescreve datas passadas (edições
    republicadas, suplementos acrescentados depois). Um cron que só olha "hoje"
    perde isso. Toda execução reconfere os últimos DOU_RECHECK_DAYS dias
    comparando o SHA-256 do ZIP com content_signature.

A ordem em ingest_date importa: o hash é calculado **antes** de gravar o
arquivo. Gravar antes de comparar sobrescreveria um arquivo íntegro por um
download possivelmente truncado.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import defusedxml.ElementTree as ElementTree
from defusedxml.common import DefusedXmlException

from sqlalchemy import func

from app.models import db, DouEdition, DouArticle, DouSyncRun
from app.services import inlabs_client
from app.services.dou_xml_parser import parse_article_xml

logger = logging.getLogger(__name__)

BASE_UPLOAD_DIR = Path('uploads/dou')
DEFAULT_RECHECK_DAYS = 7
DEFAULT_PDF_RETENTION_MONTHS = 24


def secoes_configuradas() -> tuple[str, ...]:
    """Seções a capturar. DOU_SECOES no .env sobrescreve; padrão é todas."""
    bruto = os.environ.get('DOU_SECOES', '').strip()
    if not bruto:
        return DouEdition.XML_SECTIONS
    secoes = tuple(s.strip().upper() for s in bruto.split(',') if s.strip())
    return secoes or DouEdition.XML_SECTIONS


def recheck_days() -> int:
    try:
        return int(os.environ.get('DOU_RECHECK_DAYS', DEFAULT_RECHECK_DAYS))
    except ValueError:
        return DEFAULT_RECHECK_DAYS


def storage_dir(data: date) -> Path:
    """uploads/dou/YYYY/MM/DD — sempre relativo (dev e produção têm raízes diferentes)."""
    return BASE_UPLOAD_DIR / data.strftime('%Y') / data.strftime('%m') / data.strftime('%d')


def _pdf_secao(secao: str) -> str | None:
    """DO1 → do1. Seções extras (DO1E) não têm PDF próprio: o do1 já as contempla."""
    secao = secao.upper()
    if secao.endswith('E'):
        return None
    return secao.lower() if secao.lower() in DouEdition.PDF_SECTIONS else None


# ----------------------------------------------------------------- ingestão

def ingest_zip_bytes(edition: DouEdition, zip_bytes: bytes) -> tuple[int, int]:
    """Descompacta o ZIP, parseia cada XML e faz upsert. Devolve (inseridas, atualizadas).

    Um XML malformado — ou hostil — não derruba a edição inteira: a matéria é
    registrada em log e o laço segue para a próxima.
    """
    inseridas = atualizadas = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith('.xml'):
                continue
            try:
                artigos = parse_article_xml(z.read(nome))
            except ElementTree.ParseError as exc:
                logger.warning('DOU: XML inválido em %s (%s) — pulando', nome, exc)
                continue
            except DefusedXmlException as exc:
                # DTD ou expansão de entidades: XML hostil, não apenas quebrado.
                # Registra em nível de erro para aparecer no log de produção.
                logger.error('DOU: XML hostil recusado em %s (%s) — pulando', nome, exc)
                continue

            for dados in artigos:
                existente = DouArticle.query.filter_by(
                    edition_id=edition.id,
                    art_id=dados['art_id'],
                    id_materia=dados['id_materia'],
                ).first()

                if existente is None:
                    db.session.add(DouArticle(edition_id=edition.id, **dados))
                    inseridas += 1
                elif existente.hash != dados['hash']:
                    for campo, valor in dados.items():
                        setattr(existente, campo, valor)
                    atualizadas += 1

    return inseridas, atualizadas


def _baixar_pdf(client, data: date, secao: str, edition: DouEdition, destino: Path) -> None:
    """Baixa o PDF assinado da seção, quando ela tem um. Falha aqui não derruba o XML."""
    pdf_secao = _pdf_secao(secao)
    if not pdf_secao:
        return
    try:
        conteudo = client.download_pdf(data, pdf_secao)
    except inlabs_client.InlabsError as exc:
        logger.warning('DOU: PDF %s %s falhou (%s) — XML preservado', data, secao, exc)
        return
    if conteudo is None:
        return

    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / inlabs_client.pdf_filename(data, pdf_secao)
    caminho.write_bytes(conteudo)
    edition.pdf_path = str(caminho)
    edition.pdf_bytes = len(conteudo)
    edition.pdf_purged_at = None


def ingest_date(data: date, secoes=None, with_pdf: bool = True,
                dry_run: bool = False, client=None) -> dict:
    """Captura uma data inteira. Devolve o resumo agregado das seções.

    Commit por (dia, seção): uma execução interrompida retoma sem perder o que
    já fez e sem duplicar.
    """
    secoes = tuple(secoes) if secoes else secoes_configuradas()
    client = client or inlabs_client.InlabsClient()

    resumo = {
        'data': data.isoformat(), 'edicoes_baixadas': 0, 'materias_inseridas': 0,
        'materias_atualizadas': 0, 'nao_publicados': 0, 'erros': 0,
        'inalterado': True, 'detalhes': [],
    }

    for secao in secoes:
        try:
            conteudo = client.download_xml_zip(data, secao)
        except inlabs_client.InlabsError as exc:
            logger.error('DOU: download de %s %s falhou: %s', data, secao, exc)
            resumo['erros'] += 1
            resumo['inalterado'] = False
            if not dry_run:
                _marcar_erro(data, secao, str(exc))
            resumo['detalhes'].append({'secao': secao, 'resultado': 'erro', 'erro': str(exc)})
            continue

        if conteudo is None:
            resumo['nao_publicados'] += 1
            if not dry_run:
                _marcar_status(data, secao, DouEdition.STATUS_NOT_PUBLISHED)
            resumo['detalhes'].append({'secao': secao, 'resultado': 'nao_publicado'})
            continue

        assinatura = hashlib.sha256(conteudo).hexdigest()
        edition = _obter_edicao(data, secao) if not dry_run else None

        # Assinatura igual → o ZIP não mudou. Descarta sem tocar disco nem banco.
        if edition is not None and edition.content_signature == assinatura \
                and edition.status == DouEdition.STATUS_PARSED:
            resumo['detalhes'].append({'secao': secao, 'resultado': 'inalterado'})
            continue

        resumo['inalterado'] = False
        resumo['edicoes_baixadas'] += 1

        if dry_run:
            resumo['detalhes'].append({'secao': secao, 'resultado': 'baixaria',
                                       'bytes': len(conteudo)})
            continue

        # Nada vai para o disco antes de provar que é um ZIP. A gravação
        # acontecia antes do parse, e o rollback do banco não desfaz escrita em
        # disco: quando o INLABS devolveu a página HTML do portal para uma data
        # de fim de semana, ficaram 12 arquivos .zip que eram HTML. Qualquer
        # download corrompido ou truncado cairia no mesmo buraco.
        if not zipfile.is_zipfile(io.BytesIO(conteudo)):
            amostra = conteudo[:80].decode('utf-8', 'replace').replace('\n', ' ')
            mensagem = (f'resposta do INLABS não é um ZIP '
                        f'({len(conteudo)} bytes; começa com "{amostra}")')
            logger.error('DOU: %s %s — %s', data, secao, mensagem)
            resumo['erros'] += 1
            _marcar_erro(data, secao, mensagem)
            resumo['detalhes'].append({'secao': secao, 'resultado': 'erro',
                                       'erro': mensagem})
            continue

        try:
            destino = storage_dir(data)
            destino.mkdir(parents=True, exist_ok=True)
            caminho_zip = destino / inlabs_client.xml_filename(data, secao)
            caminho_zip.write_bytes(conteudo)

            edition.zip_path = str(caminho_zip)
            edition.zip_bytes = len(conteudo)
            edition.content_signature = assinatura
            edition.status = DouEdition.STATUS_DOWNLOADED
            edition.baixado_em = datetime.now()
            edition.error_message = None
            db.session.flush()

            inseridas, atualizadas = ingest_zip_bytes(edition, conteudo)

            # flush antes de contar: as matérias novas ainda estão pendentes na
            # sessão e não apareceriam no COUNT
            db.session.flush()
            edition.qtd_materias = DouArticle.query.filter_by(edition_id=edition.id).count()
            edition.status = DouEdition.STATUS_PARSED
            edition.processado_em = datetime.now()

            if with_pdf:
                _baixar_pdf(client, data, secao, edition, destino)

            db.session.commit()

            # Índice de busca: alimentado depois do commit, e de propósito sem
            # try/except aqui — index_articles já trata a própria falha e
            # devolve 0. A captura não pode passar a depender do Meilisearch.
            from app.services import dou_search_service
            dou_search_service.index_articles(
                DouArticle.query.filter_by(edition_id=edition.id).all()
            )

            resumo['materias_inseridas'] += inseridas
            resumo['materias_atualizadas'] += atualizadas
            resumo['detalhes'].append({
                'secao': secao, 'resultado': 'ok',
                'inseridas': inseridas, 'atualizadas': atualizadas,
            })

        except Exception as exc:  # noqa: BLE001 — erro de uma seção não derruba as outras
            db.session.rollback()
            logger.exception('DOU: falha ao processar %s %s', data, secao)
            resumo['erros'] += 1
            _marcar_erro(data, secao, str(exc))
            resumo['detalhes'].append({'secao': secao, 'resultado': 'erro', 'erro': str(exc)})

    return resumo


def _obter_edicao(data: date, secao: str) -> DouEdition:
    edition = DouEdition.query.filter_by(data_publicacao=data, secao=secao).first()
    if edition is None:
        edition = DouEdition(data_publicacao=data, secao=secao,
                             status=DouEdition.STATUS_PENDING)
        db.session.add(edition)
        db.session.flush()
    return edition


def _marcar_status(data: date, secao: str, status: str) -> None:
    edition = _obter_edicao(data, secao)
    # Nunca rebaixar uma edição já processada para "não publicado"
    if edition.status != DouEdition.STATUS_PARSED:
        edition.status = status
    db.session.commit()


def _marcar_erro(data: date, secao: str, mensagem: str) -> None:
    """Falha nunca é registrada como sucesso: a próxima execução tenta de novo."""
    try:
        edition = _obter_edicao(data, secao)
        edition.status = DouEdition.STATUS_ERROR
        edition.error_message = mensagem[:2000]
        db.session.commit()
    except Exception:
        db.session.rollback()


# ---------------------------------------------------------------- execuções

def _executar(modo: str, datas, with_pdf: bool, dry_run: bool) -> DouSyncRun:
    """Roda a ingestão sobre uma lista de datas, com auditoria em DouSyncRun."""
    # Os contadores são inicializados explicitamente, e não pelo default da
    # coluna: em dry-run o objeto nunca é gravado, o default do INSERT nunca
    # roda, e os atributos ficariam None — o primeiro `+=` estouraria TypeError.
    run = DouSyncRun(modo=modo, status=DouSyncRun.STATUS_RUNNING,
                     data_inicial=min(datas) if datas else None,
                     data_final=max(datas) if datas else None,
                     edicoes_baixadas=0, materias_inseridas=0,
                     materias_atualizadas=0, nao_publicados=0, erros=0)
    if not dry_run:
        db.session.add(run)
        db.session.commit()

    client = inlabs_client.InlabsClient()
    detalhes = []

    try:
        client.login()
    except inlabs_client.InlabsError as exc:
        logger.error('DOU: login no INLABS falhou: %s', exc)
        run.status = DouSyncRun.STATUS_ERROR
        run.erros = 1
        run.finalizado_em = datetime.now()
        run.detalhe_json = {'erro': str(exc)}
        if not dry_run:
            db.session.commit()
        return run

    for data in datas:
        resumo = ingest_date(data, with_pdf=with_pdf, dry_run=dry_run, client=client)
        run.edicoes_baixadas += resumo['edicoes_baixadas']
        run.materias_inseridas += resumo['materias_inseridas']
        run.materias_atualizadas += resumo['materias_atualizadas']
        run.nao_publicados += resumo['nao_publicados']
        run.erros += resumo['erros']
        detalhes.append(resumo)

    run.finalizado_em = datetime.now()
    run.detalhe_json = {'dias': detalhes}
    if run.erros == 0:
        run.status = DouSyncRun.STATUS_SUCCESS
    elif run.materias_inseridas or run.materias_atualizadas or run.edicoes_baixadas:
        run.status = DouSyncRun.STATUS_PARTIAL
    else:
        run.status = DouSyncRun.STATUS_ERROR

    if not dry_run:
        db.session.commit()
    return run


def sync_recent(recheck: int | None = None, hoje: date | None = None,
                with_pdf: bool = True, dry_run: bool = False,
                modo: str = DouSyncRun.MODO_CRON) -> DouSyncRun:
    """Modo do cron: hoje mais a janela de reverificação dos dias anteriores."""
    hoje = hoje or date.today()
    janela = recheck if recheck is not None else recheck_days()
    datas = [hoje - timedelta(days=i) for i in range(janela + 1)]
    return _executar(modo, sorted(datas), with_pdf, dry_run)


def backfill(desde: date, ate: date | None = None,
             with_pdf: bool = True, dry_run: bool = False) -> DouSyncRun:
    """Resgate histórico. Commit por dia — interrompível e retomável."""
    ate = ate or date.today()
    datas = []
    cursor = desde
    while cursor <= ate:
        datas.append(cursor)
        cursor += timedelta(days=1)
    return _executar(DouSyncRun.MODO_BACKFILL, datas, with_pdf, dry_run)


def ingest_single_date(data: date, with_pdf: bool = True,
                       dry_run: bool = False) -> DouSyncRun:
    """Reprocessa uma data específica (botão da tela e --data do CLI)."""
    return _executar(DouSyncRun.MODO_MANUAL, [data], with_pdf, dry_run)


# ------------------------------------------------------------------- saúde

# Quantos dias úteis de atraso toleramos antes de acusar que a captura parou.
# Dois, e não um, para um feriado sozinho não disparar alarme falso.
TOLERANCIA_DIAS_UTEIS = 2


def _dias_uteis_entre(inicio: date, fim: date) -> int:
    """Dias úteis estritamente entre as duas datas. O DOU não sai fim de semana."""
    dias = 0
    cursor = inicio + timedelta(days=1)
    while cursor < fim:
        if cursor.weekday() < 5:
            dias += 1
        cursor += timedelta(days=1)
    return dias


def health_counters() -> dict:
    """Pendências da captura, para o chip da header. Dois COUNT com índice.

    O DOU não tem fila de trabalho — ninguém "resolve" o Diário Oficial, e um
    contador de matérias só cresceria. O que pede ação é a captura ter falhado
    ou parado, e é só isso que este contador reporta.

    Chaves: ``com_erro`` (edições a reprocessar), ``parada`` (o cron não roda),
    ``ultima_data`` e ``badge`` (há algo a mostrar).
    """
    com_erro = DouEdition.query.filter_by(status=DouEdition.STATUS_ERROR).count()

    ultima = (db.session.query(func.max(DouEdition.data_publicacao))
              .filter(DouEdition.status == DouEdition.STATUS_PARSED).scalar())

    # Acervo vazio não é captura parada: é instalação sem credencial ainda.
    # Acusar aqui seria alarme para quem nunca ligou o módulo.
    parada = bool(ultima) and _dias_uteis_entre(ultima, date.today()) >= TOLERANCIA_DIAS_UTEIS

    return {
        'com_erro': com_erro,
        'parada': parada,
        'ultima_data': ultima,
        'badge': bool(com_erro) or parada,
    }


# ----------------------------------------------------------------- retenção

def purge_old_pdfs(retention_months: int | None = None) -> int:
    """Remove PDFs mais antigos que a janela de retenção. XML e texto nunca são podados.

    Sem isso, ~32 GB/ano esgotam o disco de um servidor compartilhado com
    produção em cerca de três anos.
    """
    if retention_months is None:
        try:
            retention_months = int(os.environ.get(
                'DOU_PDF_RETENTION_MONTHS', DEFAULT_PDF_RETENTION_MONTHS))
        except ValueError:
            retention_months = DEFAULT_PDF_RETENTION_MONTHS

    if retention_months <= 0:      # 0 = nunca podar
        return 0

    limite = date.today() - timedelta(days=retention_months * 30)
    edicoes = DouEdition.query.filter(
        DouEdition.data_publicacao < limite,
        DouEdition.pdf_path.isnot(None),
        DouEdition.pdf_purged_at.is_(None),
    ).all()

    podados = 0
    for edicao in edicoes:
        caminho = Path(edicao.pdf_path)
        try:
            if caminho.exists():
                caminho.unlink()
            edicao.pdf_purged_at = datetime.now()
            podados += 1
        except OSError as exc:
            logger.warning('DOU: não foi possível remover %s: %s', caminho, exc)

    db.session.commit()
    logger.info('DOU: %d PDF(s) podados (retenção de %d meses)', podados, retention_months)
    return podados
