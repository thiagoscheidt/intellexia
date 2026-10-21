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

Documento que a IA diz não ser petição (decisão, teste, anexo) não entra em
base nenhuma: fica registrado com erro na tela, para alguém decidir. Falha
passageira (rede, Drive fora, limite do provedor de IA) não é registrada — a
próxima rodada tenta de novo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from flask import current_app

from app.models import DriveIngestion, ImpugnacaoReferenceModel, KnowledgeBase, User, db
from app.services import ai_model_settings_service
from app.services import drive_ingestion_service as telas
from app.services import google_drive_client as gdrive
from app.services import jurisprudence_normalizer as norm
from app.services import lote_md_import_service as lote
from app.services.jurisprudence_upload_service import id_do_drive
from app.services.lote_md_import_service import CATEGORIA_BASE, processo_do_texto

REGISTRAR, IMPORTAR, PULAR = 'registrar', 'importar', 'pular'
DESTINO_BASE = DriveIngestion.DEST_BASE_CONHECIMENTO
DESTINO_PECA = DriveIngestion.DEST_PECA_MODELO
TIPOS_ACEITOS = ('pdf', 'docx', 'gdoc')


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

    return {
        'eh_peticao': bool(lido.get('eh_peticao')),
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
            planos.append(Plano(meta, IMPORTAR, 'novo: ler com IA e gravar'))
    return planos


def _registrar(law_firm_id: int, plano: Plano, *, sha=None) -> None:
    if plano.kb_id:
        telas._gravar(law_firm_id, plano.meta['id'], DESTINO_BASE, plano.nome, None,
                      target_id=plano.kb_id, sha=sha)
    if plano.peca_id:
        telas._gravar(law_firm_id, plano.meta['id'], DESTINO_PECA, plano.nome, None,
                      target_id=plano.peca_id, sha=sha)


def _importar(law_firm_id: int, plano: Plano, usuario: User, drive, agente) -> None:
    pasta = os.path.join(telas.PASTA_TEMPORARIA, str(law_firm_id))
    caminho = None
    try:
        caminho, nome, sha = drive.baixar(plano.meta['id'], pasta, meta=plano.meta)
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
        if not dados['eh_peticao']:
            motivo = dados['observacao'] or 'o conteúdo não é de petição protocolada'
            telas._gravar(law_firm_id, plano.meta['id'], DESTINO_BASE, plano.nome, None,
                          erro=f'Não importado automaticamente: {motivo}. Escolha o destino à mão.')
            plano.ok, plano.resultado = False, f'não é petição ({motivo}); deixado para escolha manual'
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
    """Grava o que ``planejar`` decidiu. Um arquivo com problema não para os outros."""
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
            telas._gravar(law_firm_id, plano.meta['id'], DESTINO_BASE, plano.nome, None,
                          erro=f'Não importado automaticamente: {erro}')
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
            telas._gravar(law_firm_id, plano.meta['id'], DESTINO_BASE, plano.nome, None,
                          erro=f'Falha na importação automática: {erro}')
            plano.ok, plano.resultado = False, f'falhou: {erro}'
    return planos
