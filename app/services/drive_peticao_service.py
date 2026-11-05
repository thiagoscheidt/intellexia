"""Petições protocoladas compartilhadas pelo Google Drive → ficha no formato do lote .md.

O escritório compartilha com a conta de serviço, arquivo por arquivo, o PDF de
cada petição protocolada. O Drive não entrega caminho de pasta nem número de
processo; a ficha sai do nome do arquivo e do texto
(``PeticaoProtocoladaAgent``) e tem **as mesmas chaves de ``dados`` do
``lote_md_import_service``** — autora, tribunal, orgao, peca, protocolo,
teses, processo, link, drive_id —, para a gravação na Base e nas Peças-modelo
ser a mesma do lote e a petição vinda do Drive ficar igual à que veio por ele.

Duas etapas, como no lote: ``planejar`` só lê (lista o Drive e cruza com o
que já existe — sem baixar, sem IA) e ``executar`` grava. Cada arquivo vira:

- **registrar**: já está na Base ou nas Peças-modelo (veio pelo lote .md, com o
  mesmo id do Drive no link) — só ganha a linha em ``drive_ingestions``, para a
  tela do Drive mostrar "importado", sem IA e sem duplicar;
- **importar**: novo — baixa, lê a ficha com IA e grava pelo caminho do lote
  (``_criar_na_base``: categoria "Petições protocoladas", indexado no Qdrant e
  no Meilisearch, link do Drive; impugnação também em ``_criar_peca``);
- **pular**: a tela do Drive já tem registro dele (importado, ou recusado e
  esperando alguém escolher o destino à mão).

O escritório também compartilha as **decisões** (sentença, acórdão, decisão em
ED…), e essas vão para a fila da Base de Jurisprudência, que tem a leitura
própria. O nome do arquivo decide primeiro (``tipo_pelo_nome``: palavra de
decisão e sem "PROTOCOLO" — as petições do escritório sempre trazem), sem
gastar a leitura da petição; o que o nome não resolve, o agente classifica
(``tipo_documento``). A fila é lida aqui mesmo (``ler_decisoes``), porque a
thread que a tela usaria morre junto com o script.

Só o que não é petição nem decisão (teste, anexo) fica para a pessoa: registro
de **triagem** na tela ("Importação automática · Escolha o destino"), sem fingir
que foi mandado a uma base. Falha passageira (rede, Drive fora, limite do
provedor de IA) não é registrada — a próxima rodada tenta de novo.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from flask import current_app

from app.models import DriveIngestion, ImpugnacaoReferenceModel, JurisprudenceUpload, KnowledgeBase, User, db
from app.services import ai_model_settings_service
from app.services import drive_ingestion_service as telas
from app.services import google_drive_client as gdrive
from app.services import jurisprudence_upload_service as envios_jurisprudencia
from app.services import jurisprudence_normalizer as norm
from app.services import lote_md_import_service as lote
from app.services.jurisprudence_upload_service import id_do_drive
from app.services.lote_md_import_service import CATEGORIA_BASE, processo_do_texto

REGISTRAR, IMPORTAR, PULAR = 'registrar', 'importar', 'pular'
DESTINO_BASE = DriveIngestion.DEST_BASE_CONHECIMENTO
DESTINO_PECA = DriveIngestion.DEST_PECA_MODELO
DESTINO_DECISAO = DriveIngestion.DEST_DECISAO
DESTINO_TRIAGEM = DriveIngestion.DEST_TRIAGEM
TIPOS_ACEITOS = ('pdf', 'docx', 'gdoc')
PETICAO, DECISAO, OUTRO = 'peticao', 'decisao', 'outro'

# Como o escritório nomeia as decisões no Drive: "Sentença", "SENTENÇAED2",
# "SETENÇA" (sic), "Acórdão", "ACÓRDÃOSTJINT", "Decisão monocrática",
# "DECRESP"/"DECRESPED" (decisão em REsp). Comparado sem acento e em caixa alta.
_DECISAO_NO_NOME = re.compile(r'(?<![A-Z])(SENTENCA|SETENCA|ACORDAO|DECISAO|DECRESP)')
# As petições protocoladas sempre trazem "PROTOCOLO" — e uma delas pode citar a
# decisão que ataca ("ED ao Acórdão _ PROTOCOLO.pdf"), por isso ele vence.
_PETICAO_NO_NOME = re.compile(r'PROTOCOLO')
# Registro antigo de "não é petição" (antes de as decisões terem rota):
# ``reabrir_recusados`` o apaga para a próxima rodada classificar de novo.
_PREFIXO_RECUSA = 'Não importado automaticamente:'


def _sem_acento(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', texto or '') if not unicodedata.combining(c)).upper()


def tipo_pelo_nome(nome: str) -> Optional[str]:
    """``'decisao'`` quando o nome diz que é decisão; None quando não resolve.

    Nunca diz "petição" pelo nome: a petição precisa da ficha do agente de
    qualquer jeito, e só ele separa a petição de um documento de teste.
    """
    nome = _sem_acento(nome)
    if _PETICAO_NO_NOME.search(nome):
        return None
    return DECISAO if _DECISAO_NO_NOME.search(nome) else None


def texto_do_pdf(caminho: str) -> str:
    """Texto do PDF, páginas separadas por quebra de página. Sem IA."""
    import pdfplumber

    with pdfplumber.open(caminho) as pdf:
        return '\f'.join((pagina.extract_text() or '') for pagina in pdf.pages)


def pecas_conhecidas(law_firm_id: int, limite: int = 40) -> list[str]:
    """Os tipos de peça mais usados na Base — o vocabulário que o agente deve seguir.

    Vem do que já está gravado (o lote pôs o tipo da peça nas tags), para as
    novas petições caírem nos mesmos nomes e o filtro por tipo continuar útil.
    """
    linhas = (db.session.query(KnowledgeBase.tags, db.func.count())
              .filter(KnowledgeBase.law_firm_id == law_firm_id,
                      KnowledgeBase.category == CATEGORIA_BASE,
                      KnowledgeBase.tags.isnot(None), KnowledgeBase.is_active.is_(True))
              .group_by(KnowledgeBase.tags)
              .order_by(db.func.count().desc())
              .limit(limite).all())
    return [tags for tags, _ in linhas if tags]


def link_do_drive(meta: dict) -> str:
    return meta.get('webViewLink') or f"https://drive.google.com/file/d/{meta['id']}/view"


def ficha(law_firm_id: int, caminho: str, meta: dict, *, agente=None,
          user_id: Optional[int] = None) -> dict:
    """``dados`` no formato do lote para o PDF baixado em ``caminho``.

    O número do processo vem da regra do lote (``processo_do_texto``); o da IA
    só entra quando a regra não acha nenhum **e** o número está no texto — um
    número que não aparece na peça seria invenção. Levanta
    ``ExtracaoFalhou`` do agente.
    """
    from app.agents.drive.peticao_protocolada_agent import PeticaoProtocoladaAgent

    texto = texto_do_pdf(caminho)
    if agente is None:
        agente = PeticaoProtocoladaAgent(
            model_name=ai_model_settings_service.get_model(law_firm_id, 'drive_peticao_extractor'))
    lido = agente.extrair(texto, meta.get('name') or '', pecas_referencia=pecas_conhecidas(law_firm_id),
                          law_firm_id=law_firm_id, user_id=user_id)

    processo = processo_do_texto(texto)
    origem_processo = 'regra'
    if not processo and lido.get('processo'):
        digitos_ia = norm.numero_cnj(lido['processo'])
        no_texto = {norm.numero_cnj(m) for m in _numeros(texto)}
        if digitos_ia and digitos_ia in no_texto:
            processo, origem_processo = norm.formatar_cnj(digitos_ia), 'ia'

    tipo = lido.get('tipo_documento')
    if tipo not in (PETICAO, DECISAO, OUTRO):
        tipo = PETICAO if lido.get('eh_peticao') else OUTRO
    return {
        'tipo': tipo,
        'eh_peticao': tipo == PETICAO,
        'processo': processo,
        'origem_processo': origem_processo if processo else None,
        'autora': (lido.get('autora') or '').strip(),
        'tribunal': (lido.get('tribunal') or '').strip(),
        'orgao': (lido.get('orgao_julgador') or '').strip(),
        'peca': (lido.get('peca') or '').strip().upper(),
        'protocolo': (lido.get('data_protocolo') or '').strip(),
        'teses': (lido.get('teses') or '').strip(),
        'observacao': (lido.get('observacao') or '').strip(),
        'paginas': str(texto.count('\f') + 1),
        'paginas_ocr': '0',
        'link': link_do_drive(meta)[:500],
        'drive_id': meta['id'],
    }


def _numeros(texto: str) -> list[str]:
    import re

    return re.findall(r'\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}', texto)


# ── Importação automática ─────────────────────────────────────────────────────


@dataclass
class Plano:
    meta: dict
    acao: str
    motivo: str = ''
    kb_id: Optional[int] = None
    peca_id: Optional[int] = None
    upload_id: Optional[int] = None  # fila da Jurisprudência
    resultado: str = ''
    ok: Optional[bool] = None
    extra: dict = field(default_factory=dict)

    @property
    def nome(self) -> str:
        return self.meta.get('name') or self.meta.get('id')


def usuario_da_importacao(law_firm_id: int) -> Optional[User]:
    """Dono dos registros criados na Base/Peças-modelo: o 1º admin (como no lote).

    Na tela do Drive o envio aparece como "importação automática" — lá o
    ``created_by`` fica vazio de propósito.
    """
    return (User.query.filter_by(law_firm_id=law_firm_id, role='admin', is_active=True)
            .order_by(User.id).first())


def planejar(law_firm_id: int, *, drive=None) -> list[Plano]:
    """O que a importação faria com cada arquivo compartilhado. Só lê."""
    drive = drive or gdrive.cliente()
    arquivos = [a for a in drive.listar() if gdrive.tipo_do_arquivo(a.get('mimeType')) in TIPOS_ACEITOS]

    registrados = {fid for (fid,) in db.session.query(DriveIngestion.drive_file_id)
                   .filter(DriveIngestion.law_firm_id == law_firm_id)}
    kb_por_drive, a_retomar = {}, {}
    for kb_id, url, status, tipo in (KnowledgeBase.query.with_entities(
            KnowledgeBase.id, KnowledgeBase.source_url, KnowledgeBase.processing_status, KnowledgeBase.file_type)
            .filter(KnowledgeBase.law_firm_id == law_firm_id, KnowledgeBase.is_active.is_(True),
                    KnowledgeBase.source_url.isnot(None))):
        fid = id_do_drive(url)
        if not fid:
            continue
        if status != 'completed' and (tipo or '').upper() != 'MD':
            # Importação automática que parou na indexação (Qdrant fora do ar…):
            # retoma o mesmo registro em vez de criar outro.
            a_retomar[fid] = kb_id
        else:
            kb_por_drive.setdefault(fid, kb_id)
    pecas_por_drive = {fid: pid for pid, fid in ImpugnacaoReferenceModel.query.with_entities(
        ImpugnacaoReferenceModel.id, ImpugnacaoReferenceModel.source_drive_file_id).filter(
        ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
        ImpugnacaoReferenceModel.source_drive_file_id.isnot(None))}

    planos = []
    for meta in arquivos:
        fid = meta['id']
        if fid in registrados:
            planos.append(Plano(meta, PULAR, 'já registrado na tela do Google Drive'))
        elif fid in a_retomar:
            planos.append(Plano(meta, IMPORTAR, 'retomar: a indexação não terminou na rodada anterior',
                                kb_id=a_retomar[fid], peca_id=pecas_por_drive.get(fid)))
        elif fid in kb_por_drive or fid in pecas_por_drive:
            planos.append(Plano(meta, REGISTRAR, 'já está na base (veio pelo lote .md)',
                                kb_id=kb_por_drive.get(fid), peca_id=pecas_por_drive.get(fid)))
        else:
            planos.append(Plano(meta, IMPORTAR, 'novo: decisão pelo nome → Jurisprudência'
                                if tipo_pelo_nome(meta.get('name')) == DECISAO else 'novo: ler com IA e gravar'))
    return planos


def _registrar(law_firm_id: int, plano: Plano, *, sha=None) -> None:
    if plano.kb_id:
        telas._gravar(law_firm_id, plano.meta['id'], DESTINO_BASE, plano.nome, None,
                      target_id=plano.kb_id, sha=sha)
    if plano.peca_id:
        telas._gravar(law_firm_id, plano.meta['id'], DESTINO_PECA, plano.nome, None,
                      target_id=plano.peca_id, sha=sha)


def _triagem(law_firm_id: int, plano: Plano, motivo: str, *, sha=None) -> None:
    """Deixa o arquivo para a pessoa escolher o destino — sem fingir envio a uma base."""
    telas._gravar(law_firm_id, plano.meta['id'], DESTINO_TRIAGEM, plano.nome, None, sha=sha,
                  erro=f'{_PREFIXO_RECUSA} {motivo}. Escolha o destino em "Ingerir em…".')


def _enviar_decisao(law_firm_id: int, plano: Plano, caminho: str, nome: str, sha: str, usuario: User) -> None:
    """Enfileira na Base de Jurisprudência, pela mesma porta do "Ingerir em…".

    Só enfileira: a leitura é do ``ler_decisoes``, no mesmo script.
    """
    tipo = gdrive.tipo_do_arquivo(plano.meta.get('mimeType'))
    motivo = telas.motivo_indisponivel(DESTINO_DECISAO, tipo)
    if motivo:
        _triagem(law_firm_id, plano, f'é decisão, mas {motivo[0].lower()}{motivo[1:].rstrip(".")}', sha=sha)
        plano.ok, plano.resultado = False, f'decisão em formato que a Jurisprudência não lê ({motivo})'
        return
    try:
        upload_id, mensagem = telas._para_decisao(
            law_firm_id=law_firm_id, caminho=caminho, nome=nome, tipo=tipo, user_id=usuario.id,
            iniciar_leitura=False)
    except telas.EnvioRecusado as erro:
        db.session.rollback()
        telas._gravar(law_firm_id, plano.meta['id'], DESTINO_DECISAO, plano.nome, None, erro=str(erro))
        plano.ok, plano.resultado = False, f'Jurisprudência recusou: {erro}'
        return
    telas._gravar(law_firm_id, plano.meta['id'], DESTINO_DECISAO, plano.nome, None,
                  target_id=upload_id, sha=sha)
    plano.upload_id = upload_id
    plano.ok, plano.resultado = True, f'Jurisprudência #{upload_id}: {mensagem}'


def _importar(law_firm_id: int, plano: Plano, usuario: User, drive, agente) -> None:
    pasta = os.path.join(telas.PASTA_TEMPORARIA, str(law_firm_id))
    caminho = None
    try:
        caminho, nome, sha = drive.baixar(plano.meta['id'], pasta, meta=plano.meta)
        if tipo_pelo_nome(plano.nome) == DECISAO:
            # O nome resolve: sem a leitura da petição, direto para a fila.
            _enviar_decisao(law_firm_id, plano, caminho, nome, sha, usuario)
            return

        retomando_kb, retomando_peca = plano.kb_id, plano.peca_id
        mesmo = (KnowledgeBase.query.filter_by(law_firm_id=law_firm_id, file_hash=sha, is_active=True)
                 .filter(KnowledgeBase.id != (retomando_kb or 0)).first())
        if mesmo is not None:
            # Conteúdo idêntico já na base (outro upload do mesmo PDF): aponta para ele.
            plano.kb_id = mesmo.id
            _registrar(law_firm_id, plano, sha=sha)
            plano.ok, plano.resultado = True, f'conteúdo idêntico ao arquivo #{mesmo.id} da Base; só registrado'
            return

        dados = ficha(law_firm_id, caminho, plano.meta, agente=agente)
        plano.extra = dados
        if dados['tipo'] == DECISAO:
            _enviar_decisao(law_firm_id, plano, caminho, nome, sha, usuario)
            return
        if dados['tipo'] != PETICAO:
            motivo = dados['observacao'] or 'não é petição protocolada nem decisão'
            _triagem(law_firm_id, plano, motivo.rstrip('.'), sha=sha)
            plano.ok, plano.resultado = False, f'nem petição nem decisão ({motivo}); deixado para escolha manual'
            return

        item = lote.Item(origem='peticao', acao=lote.BASE_CONHECIMENTO, arquivo=nome, linha=0,
                         caminho=Path(caminho), sha=sha, dados=dados,
                         destino=lote.DESTINO_BASE, alvo_id=retomando_kb)
        lote._criar_na_base(item, law_firm_id, usuario.id)
        plano.kb_id = item.criado_id
        mensagens = [f'Base de Conhecimento #{item.criado_id}']
        if lote._eh_impugnacao(dados['peca']):
            peca = lote.Item(origem='peticao', acao=lote.PECA_MODELO, arquivo=nome, linha=0,
                             caminho=item.caminho, sha=sha, dados=dados, destino=lote.DESTINO_PECAS,
                             alvo_id=retomando_peca)
            lote._criar_peca(peca, law_firm_id, usuario.id, processar=True)
            plano.peca_id = peca.criado_id
            mensagens.append(f'peça-modelo #{peca.criado_id}')
        _registrar(law_firm_id, plano, sha=sha)
        plano.ok, plano.resultado = True, ' + '.join(mensagens)
    finally:
        if caminho and os.path.exists(caminho):
            os.remove(caminho)  # a base guardou a cópia dela


_SINAIS_PASSAGEIROS = ('connection refused', 'connection reset', 'connection aborted', 'timed out',
                       'temporarily unavailable', 'temporary failure', 'name or service not known',
                       'service unavailable', '502', '503', '504')


def _passageira(erro: Exception) -> bool:
    """Falha de infraestrutura (conexão, serviço fora), não do arquivo."""
    if isinstance(erro, (ConnectionError, TimeoutError)):
        return True
    texto = str(erro).lower()
    return any(sinal in texto for sinal in _SINAIS_PASSAGEIROS)


def executar(law_firm_id: int, planos: list[Plano], *, drive=None, agente=None,
             limite: Optional[int] = None) -> list[Plano]:
    """Grava o que ``planejar`` decidiu. Um arquivo com problema não para os outros.

    As decisões ficam na fila da Jurisprudência: ``ler_decisoes`` as lê depois.
    """
    from app.agents.drive.peticao_protocolada_agent import ExtracaoFalhou, SemTexto

    drive = drive or gdrive.cliente()
    usuario = usuario_da_importacao(law_firm_id)
    if usuario is None:
        raise RuntimeError('O escritório não tem administrador ativo para ser o dono dos registros.')
    importados = 0
    for plano in planos:
        if plano.acao == PULAR:
            continue
        if plano.acao == REGISTRAR:
            _registrar(law_firm_id, plano)
            plano.ok, plano.resultado = True, 'registrado como importado (já estava na base)'
            continue
        if limite is not None and importados >= limite:
            plano.resultado = 'ficou para a próxima rodada (limite)'
            continue
        importados += 1
        try:
            _importar(law_firm_id, plano, usuario, drive, agente)
        except SemTexto as erro:
            db.session.rollback()
            _triagem(law_firm_id, plano, str(erro).rstrip('.'))
            plano.ok, plano.resultado = False, str(erro)
        except (gdrive.DriveErro, ExtracaoFalhou) as erro:
            # Passageiro (Drive fora, limite do provedor, IA sem resposta): sem
            # registro, a próxima rodada tenta de novo.
            db.session.rollback()
            plano.ok, plano.resultado = False, f'tentará de novo: {erro}'
        except Exception as erro:
            db.session.rollback()
            if _passageira(erro):
                # Qdrant/Meilisearch/embeddings fora do ar: o registro da Base
                # ficou com status de erro e a próxima rodada o retoma.
                plano.ok, plano.resultado = False, f'tentará de novo (serviço indisponível): {erro}'
                continue
            current_app.logger.exception(f'[DrivePeticao] {plano.meta.get("id")}')
            _triagem(law_firm_id, plano, f'falha na importação automática ({erro})')
            plano.ok, plano.resultado = False, f'falhou: {erro}'
    return planos


def ler_decisoes(law_firm_id: int, planos: list[Plano], *, agente=None) -> list[Plano]:
    """Lê, aqui mesmo, as decisões que ``executar`` pôs na fila da Jurisprudência.

    Síncrono de propósito: a thread que a tela dispara morreria com o script.
    O que falhar fica "falhou" na fila (a tela da Jurisprudência tem "tentar de
    novo") e o ``scripts/process_jurisprudence_uploads.py`` retoma o que um
    restart deixar "na fila".
    """
    usuario = usuario_da_importacao(law_firm_id)
    for plano in planos:
        if not plano.upload_id:
            continue
        try:
            upload = envios_jurisprudencia.processar(law_firm_id, plano.upload_id,
                                                     user_id=usuario.id if usuario else None, agente=agente)
        except Exception as erro:
            db.session.rollback()
            current_app.logger.exception(f'[DrivePeticao] leitura da decisão {plano.upload_id}')
            plano.ok, plano.resultado = False, f'Jurisprudência #{plano.upload_id}: leitura falhou ({erro})'
            continue
        if upload is None:
            continue
        rotulo = {
            JurisprudenceUpload.STATUS_DONE: 'decisão lida',
            JurisprudenceUpload.STATUS_REVIEW: 'em "revisar" (duplicata)',
            JurisprudenceUpload.STATUS_FAILED: f'leitura falhou ({upload.error_message})',
        }.get(upload.status, upload.status)
        plano.ok = upload.status != JurisprudenceUpload.STATUS_FAILED
        plano.resultado = f'Jurisprudência #{plano.upload_id}: {rotulo}'
    return planos


def reabrir_recusados(law_firm_id: int) -> int:
    """Apaga as recusas da importação automática, para a próxima rodada reclassificar.

    Antes de as decisões terem rota, todo PDF que não era petição ficava com
    erro em "Base de Conhecimento" e o ``planejar`` não olhava mais para ele.
    Só mexe no que a importação automática gravou (``created_by`` vazio): o
    que uma pessoa enviou ou recusou fica como está. Devolve quantos reabriu.
    """
    recusas = DriveIngestion.query.filter(
        DriveIngestion.law_firm_id == law_firm_id,
        DriveIngestion.created_by_id.is_(None),
        db.or_(
            DriveIngestion.destination == DESTINO_TRIAGEM,
            db.and_(DriveIngestion.destination == DESTINO_BASE,
                    DriveIngestion.status == DriveIngestion.STATUS_ERRO,
                    DriveIngestion.error_message.like(f'{_PREFIXO_RECUSA}%')),
        ))
    total = recusas.count()
    recusas.delete(synchronize_session=False)
    db.session.commit()
    return total
