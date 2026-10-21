"""Arquivos do Google Drive (conta de serviço) → bases do IntellexIA.

Fonte única da tela `/settings/google-drive`. A lista é **ao vivo**: cada
abertura pergunta ao Drive o que está compartilhado e cruza com
`drive_ingestions`, que registra o que já foi enviado e para onde.

Cada destino entra pela porta que a própria base já usa — nada de motor novo:

- peça-modelo  → `ImpugnacaoReferenceModel` + `ingest_reference` em thread,
                 como o upload manual;
- decisão      → fila da Base de Jurisprudência (`receber_baixado`);
- base de conhecimento → `KnowledgeBase` `pending`, que o
                 `scripts/process_knowledge_base.py` processa.

A situação mostrada vem da linha de destino, nunca de cópia guardada aqui:
assim a tela não diz "concluído" de algo que a base marcou como falho.

A credencial é da instalação, e não do escritório: `GOOGLE_DRIVE_LAW_FIRM_ID`
diz de quem são os arquivos, e só esse escritório vê a tela.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Callable, Optional

from flask import current_app
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app.models import (
    db,
    DriveIngestion,
    ImpugnacaoReferenceModel,
    JurisprudenceUpload,
    KnowledgeBase,
)
from app.services import google_drive_client as gdrive
from app.services import jurisprudence_upload_service as envios_jurisprudencia

MAX_POR_ENVIO = 20
PASTA_TEMPORARIA = os.path.join('uploads', 'drive_ingestions')

DESTINOS = {
    DriveIngestion.DEST_PECA_MODELO: 'Peça-modelo',
    DriveIngestion.DEST_DECISAO: 'Decisão (Jurisprudência)',
    DriveIngestion.DEST_BASE_CONHECIMENTO: 'Base de Conhecimento',
}
TIPO_ROTULO = {'pdf': 'PDF', 'docx': 'DOCX', 'gdoc': 'Google Docs'}
# Extensão com que o arquivo chega à base (Google Docs é exportado em PDF).
_EXTENSAO = {'pdf': 'pdf', 'docx': 'docx', 'gdoc': 'pdf'}

SITUACOES = {
    'na_fila': ('Na fila', 'secondary'),
    'processando': ('Processando', 'info'),
    'concluido': ('Concluído', 'success'),
    'revisar': ('Revisar', 'warning'),
    'falhou': ('Falhou', 'danger'),
    'erro': ('Erro no envio', 'danger'),
    'removido': ('Removido da base', 'light'),
}


class EnvioRecusado(Exception):
    pass


# ── Configuração ──────────────────────────────────────────────────────

def situacao_da_configuracao(law_firm_id: int) -> str:
    """'ok', 'nao_configurado', 'sem_escritorio' ou 'outro_escritorio'."""
    if not gdrive.configurado():
        return 'nao_configurado'
    dono = gdrive.law_firm_id_configurado()
    if dono is None:
        return 'sem_escritorio'
    return 'ok' if dono == law_firm_id else 'outro_escritorio'


def motivo_indisponivel(destino: str, tipo: Optional[str]) -> Optional[str]:
    """Por que o arquivo não pode ir para o destino (None = pode)."""
    if tipo is None:
        return 'Tipo de arquivo não aceito: só PDF, DOCX ou Google Docs.'
    if destino == DriveIngestion.DEST_DECISAO and tipo == 'docx':
        return 'A Base de Jurisprudência só lê PDF.'
    return None


# ── Situação na base de destino ───────────────────────────────────────

def _situacoes(law_firm_id: int, registros: list[DriveIngestion]) -> dict[int, dict]:
    """Situação de cada envio, lida em lote da base de destino."""
    por_destino: dict[str, list[int]] = {}
    for r in registros:
        if r.status == DriveIngestion.STATUS_ENVIADO and r.target_id:
            por_destino.setdefault(r.destination, []).append(r.target_id)

    pecas = {p.id: p for p in ImpugnacaoReferenceModel.query.filter(
        ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
        ImpugnacaoReferenceModel.id.in_(por_destino.get(DriveIngestion.DEST_PECA_MODELO) or [0]))}
    uploads = {u.id: u for u in JurisprudenceUpload.query.filter(
        JurisprudenceUpload.law_firm_id == law_firm_id,
        JurisprudenceUpload.id.in_(por_destino.get(DriveIngestion.DEST_DECISAO) or [0]))}
    kbs = {k.id: k for k in KnowledgeBase.query.filter(
        KnowledgeBase.law_firm_id == law_firm_id,
        KnowledgeBase.id.in_(por_destino.get(DriveIngestion.DEST_BASE_CONHECIMENTO) or [0]))}

    saida = {}
    for r in registros:
        situacao, erro, link = 'removido', None, None
        if r.status == DriveIngestion.STATUS_ERRO:
            situacao, erro = 'erro', r.error_message
        elif r.destination == DriveIngestion.DEST_PECA_MODELO and r.target_id in pecas:
            p = pecas[r.target_id]
            situacao = {'processing': 'processando', 'failed': 'falhou'}.get(p.ingestion_status, 'concluido')
            erro = p.ingestion_error if situacao == 'falhou' else None
            link = ('impugnacao_references.reference_detail', {'ref_id': p.id})
        elif r.destination == DriveIngestion.DEST_DECISAO and r.target_id in uploads:
            u = uploads[r.target_id]
            situacao = {
                JurisprudenceUpload.STATUS_QUEUED: 'na_fila',
                JurisprudenceUpload.STATUS_PROCESSING: 'processando',
                JurisprudenceUpload.STATUS_DONE: 'concluido',
                JurisprudenceUpload.STATUS_REVIEW: 'revisar',
                JurisprudenceUpload.STATUS_FAILED: 'falhou',
            }.get(u.status, 'na_fila')
            erro = u.error_message if situacao in ('falhou', 'revisar') else None
            link = (('jurisprudence.decisao', {'decision_id': u.decision_id}) if u.decision_id
                    else ('jurisprudence.enviar', {}))
        elif r.destination == DriveIngestion.DEST_BASE_CONHECIMENTO and r.target_id in kbs:
            k = kbs[r.target_id]
            if k.is_active:
                situacao = {'pending': 'na_fila', 'processing': 'processando',
                            'error': 'falhou'}.get(k.processing_status, 'concluido')
                erro = k.processing_error_message if situacao == 'falhou' else None
                link = ('knowledge_base.details', {'file_id': k.id})
        rotulo, cor = SITUACOES[situacao]
        saida[r.id] = {
            'id': r.id, 'destino': r.destination, 'destino_rotulo': DESTINOS.get(r.destination, r.destination),
            'situacao': situacao, 'situacao_rotulo': rotulo, 'cor': cor, 'erro': erro, 'link': link,
            # Sem pessoa: quem enviou foi a importação automática (drive_peticao_service).
            'enviado_em': r.created_at, 'quem': r.created_by.name if r.created_by else 'importação automática',
        }
    return saida


def _ativo(envio: dict) -> bool:
    """Envio que ainda ocupa o destino (erro e item removido liberam)."""
    return envio['situacao'] not in ('erro', 'removido')


# ── Tela ──────────────────────────────────────────────────────────────

def _quando(valor: Optional[str]) -> Optional[datetime]:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def painel(law_firm_id: int, *, drive=None) -> dict:
    estado = situacao_da_configuracao(law_firm_id)
    resultado = {'estado': estado, 'conta': None, 'erro': None, 'arquivos': [], 'pastas': [],
                 'orfaos': [], 'total': 0, 'pendentes': 0, 'destinos': DESTINOS}
    if estado != 'ok':
        return resultado

    registros = (DriveIngestion.query.filter_by(law_firm_id=law_firm_id)
                 .order_by(DriveIngestion.id.asc()).all())
    situacoes = _situacoes(law_firm_id, registros)
    envios_por_arquivo: dict[str, list[dict]] = {}
    nomes: dict[str, str] = {}
    for r in registros:
        envios_por_arquivo.setdefault(r.drive_file_id, []).append(situacoes[r.id])
        nomes[r.drive_file_id] = r.file_name

    try:
        drive = drive or gdrive.cliente()
        resultado['conta'] = drive.conta
        itens = drive.listar()
    except gdrive.DriveErro as erro:
        resultado['estado'] = 'erro'
        resultado['erro'] = str(erro)
        itens = []

    pastas = {i['id']: i['name'] for i in itens if i.get('mimeType') == gdrive.MIME_PASTA}
    vistos = set()
    for item in itens:
        if item.get('mimeType') == gdrive.MIME_PASTA:
            continue
        vistos.add(item['id'])
        tipo = gdrive.tipo_do_arquivo(item.get('mimeType'))
        envios = envios_por_arquivo.get(item['id'], [])
        ocupados = {e['destino'] for e in envios if _ativo(e)}
        destinos = [{
            'chave': chave, 'rotulo': rotulo,
            'motivo': 'Já enviado para cá.' if chave in ocupados else motivo_indisponivel(chave, tipo),
        } for chave, rotulo in DESTINOS.items()]
        quem = item.get('sharingUser') or (item.get('owners') or [{}])[0]
        pasta = next((pastas[p] for p in item.get('parents') or [] if p in pastas), None)
        resultado['arquivos'].append({
            'id': item['id'], 'nome': item.get('name') or item['id'], 'tipo': tipo,
            'tipo_rotulo': TIPO_ROTULO.get(tipo, (item.get('mimeType') or '').rsplit('/', 1)[-1]),
            'tamanho': int(item['size']) if str(item.get('size') or '').isdigit() else None,
            'compartilhado_por': quem.get('displayName') or quem.get('emailAddress'),
            'compartilhado_por_email': quem.get('emailAddress'),
            'compartilhado_em': _quando(item.get('sharedWithMeTime') or item.get('modifiedTime')),
            'pasta': pasta, 'link': item.get('webViewLink'),
            'envios': envios, 'destinos': destinos,
            'pendente': not any(_ativo(e) for e in envios),
        })

    # Mais recente primeiro; depois agrupa por pasta (sort estável mantém a data).
    resultado['arquivos'].sort(key=lambda a: a['compartilhado_em'] or datetime.min, reverse=True)
    resultado['arquivos'].sort(key=lambda a: (a['pasta'] is not None, a['pasta'] or ''))
    resultado['pastas'] = sorted(pastas.values())
    resultado['total'] = len(resultado['arquivos'])
    resultado['pendentes'] = sum(1 for a in resultado['arquivos'] if a['pendente'])
    if resultado['estado'] == 'ok':
        resultado['orfaos'] = [{'id': fid, 'nome': nomes[fid], 'envios': envios}
                               for fid, envios in envios_por_arquivo.items() if fid not in vistos]
    return resultado


# ── Envio ─────────────────────────────────────────────────────────────

def _iniciar_peca(law_firm_id: int, ref_id: int) -> None:
    # A mesma thread do upload manual de peça-modelo.
    from app.blueprints.impugnacao_references import _spawn_reference_ingestion
    _spawn_reference_ingestion(law_firm_id, ref_id, is_new=True)


def _destino_final(pasta: str, nome: str, extensao: str, carimbo_no_fim: bool = False) -> tuple[str, str]:
    """Caminho na pasta da base e o nome original garantido com a extensão."""
    if not nome.lower().endswith(f'.{extensao}'):
        nome = f'{nome}.{extensao}'
    os.makedirs(pasta, exist_ok=True)
    seguro = secure_filename(nome) or f'arquivo.{extensao}'
    carimbo = datetime.now().strftime('%Y%m%d_%H%M%S')
    if carimbo_no_fim:  # padrão do upload da base de conhecimento
        raiz, ext = os.path.splitext(seguro)
        return os.path.join(pasta, f'{raiz}_{carimbo}{ext}'), nome
    return os.path.join(pasta, f'{carimbo}_{seguro}'), nome


def _para_peca_modelo(law_firm_id, caminho, nome, sha, file_id, tipo, user_id, iniciar_peca, **_):
    existente = ImpugnacaoReferenceModel.query.filter(
        ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
        or_(ImpugnacaoReferenceModel.source_drive_file_id == file_id,
            ImpugnacaoReferenceModel.file_hash == sha)).first()
    if existente is not None:
        return existente.id, f'Já existia como peça-modelo ("{existente.title}").'
    extensao = _EXTENSAO[tipo]
    pasta = os.path.join('uploads', 'impugnacao_references', str(law_firm_id))
    final, nome = _destino_final(pasta, nome, extensao)
    shutil.move(caminho, final)
    titulo = os.path.splitext(nome)[0].replace('_', ' ').replace('-', ' ').strip() or 'Peça-Modelo'
    peca = ImpugnacaoReferenceModel(
        law_firm_id=law_firm_id, user_id=user_id, title=titulo[:250],
        original_filename=nome[:255], file_path=final, file_size=os.path.getsize(final),
        file_type=extensao, file_hash=sha, source_drive_file_id=file_id,
        status='active', ingestion_status='processing',
    )
    db.session.add(peca)
    db.session.commit()
    iniciar_peca(law_firm_id, peca.id)
    return peca.id, 'Peça-modelo criada; a leitura e a indexação rodam em segundo plano.'


def _para_decisao(law_firm_id, caminho, nome, tipo, user_id, **_):
    if not nome.lower().endswith('.pdf'):
        nome = f'{nome}.pdf'
    try:
        upload = envios_jurisprudencia.receber_baixado(law_firm_id, caminho, nome, user_id)
    except envios_jurisprudencia.ArquivoRecusado as erro:
        raise EnvioRecusado(str(erro)) from erro
    if upload.status == JurisprudenceUpload.STATUS_REVIEW:
        return upload.id, 'Arquivo idêntico a uma decisão já lida: está em "revisar" na Jurisprudência.'
    return upload.id, 'Na fila de leitura da Base de Jurisprudência.'


def _para_base_conhecimento(law_firm_id, caminho, nome, sha, tipo, user_id, compartilhado_por, **_):
    existente = KnowledgeBase.query.filter_by(law_firm_id=law_firm_id, file_hash=sha, is_active=True).first()
    if existente is not None:
        return existente.id, f'Já estava na Base de Conhecimento ("{existente.original_filename}").'
    extensao = _EXTENSAO[tipo]
    pasta = os.path.join('uploads', 'knowledge_base', str(law_firm_id))
    final, nome = _destino_final(pasta, nome, extensao, carimbo_no_fim=True)
    shutil.move(caminho, final)
    origem = f' — compartilhado por {compartilhado_por}' if compartilhado_por else ''
    item = KnowledgeBase(
        user_id=user_id, law_firm_id=law_firm_id, original_filename=secure_filename(nome) or nome[:255],
        file_path=final, file_size=os.path.getsize(final), file_type=extensao.upper(), file_hash=sha,
        description=f'Recebido do Google Drive{origem}.', processing_status='pending',
    )
    db.session.add(item)
    db.session.commit()
    return item.id, 'Na fila de processamento da Base de Conhecimento.'


_ENTREGAS = {
    DriveIngestion.DEST_PECA_MODELO: _para_peca_modelo,
    DriveIngestion.DEST_DECISAO: _para_decisao,
    DriveIngestion.DEST_BASE_CONHECIMENTO: _para_base_conhecimento,
}


def _registro(law_firm_id: int, file_id: str, destino: str) -> Optional[DriveIngestion]:
    return DriveIngestion.query.filter_by(law_firm_id=law_firm_id, drive_file_id=file_id,
                                          destination=destino).first()


def _gravar(law_firm_id, file_id, destino, nome, user_id, *, target_id=None, sha=None, erro=None):
    registro = _registro(law_firm_id, file_id, destino)
    if registro is None:
        registro = DriveIngestion(law_firm_id=law_firm_id, drive_file_id=file_id, destination=destino)
        db.session.add(registro)
    registro.file_name = (nome or file_id)[:255]
    registro.created_by_id = user_id
    registro.target_id = target_id
    registro.file_hash = sha
    registro.status = DriveIngestion.STATUS_ERRO if erro else DriveIngestion.STATUS_ENVIADO
    registro.error_message = erro
    db.session.commit()
    return registro


def _ingerir_um(law_firm_id, file_id, destino, user_id, drive, iniciar_peca) -> dict:
    registro = _registro(law_firm_id, file_id, destino)
    nome = registro.file_name if registro else file_id
    if registro is not None and _ativo(_situacoes(law_firm_id, [registro])[registro.id]):
        return {'nome': nome, 'ok': False, 'mensagem': f'Já enviado para {DESTINOS[destino]}.'}

    caminho = None
    try:
        meta = drive.metadados(file_id)
        nome = meta.get('name') or file_id
        tipo = gdrive.tipo_do_arquivo(meta.get('mimeType'))
        motivo = motivo_indisponivel(destino, tipo)
        if motivo:
            raise EnvioRecusado(motivo)
        caminho, nome, sha = drive.baixar(file_id, os.path.join(PASTA_TEMPORARIA, str(law_firm_id)), meta=meta)
        quem = meta.get('sharingUser') or (meta.get('owners') or [{}])[0]
        target_id, mensagem = _ENTREGAS[destino](
            law_firm_id=law_firm_id, caminho=caminho, nome=nome, sha=sha, file_id=file_id, tipo=tipo,
            user_id=user_id, iniciar_peca=iniciar_peca,
            compartilhado_por=quem.get('displayName') or quem.get('emailAddress'))
    except (gdrive.DriveErro, EnvioRecusado) as erro:
        db.session.rollback()
        _gravar(law_firm_id, file_id, destino, nome, user_id, erro=str(erro))
        return {'nome': nome, 'ok': False, 'mensagem': str(erro)}
    except Exception as erro:  # um arquivo com problema não derruba o lote
        db.session.rollback()
        current_app.logger.exception(f'[DriveIngestion] {file_id} → {destino}')
        _gravar(law_firm_id, file_id, destino, nome, user_id, erro=f'Falha inesperada: {erro}')
        return {'nome': nome, 'ok': False, 'mensagem': f'Falha inesperada: {erro}'}
    finally:
        if caminho and os.path.exists(caminho):
            os.remove(caminho)  # sobra do download quando a base não ficou com o arquivo

    _gravar(law_firm_id, file_id, destino, nome, user_id, target_id=target_id, sha=sha)
    return {'nome': nome, 'ok': True, 'mensagem': mensagem}


def ingerir(law_firm_id: int, file_ids: list[str], destino: str, user_id: int, *,
            drive=None, iniciar_peca: Optional[Callable[[int, int], None]] = None) -> list[dict]:
    """Baixa cada arquivo e entrega ao destino. Um resultado por arquivo."""
    if destino not in DESTINOS:
        raise ValueError(f'Destino desconhecido: {destino}')
    if situacao_da_configuracao(law_firm_id) != 'ok':
        raise gdrive.DriveNaoConfigurado('Integração com o Google Drive não configurada para este escritório.')
    drive = drive or gdrive.cliente()
    iniciar_peca = iniciar_peca or _iniciar_peca
    unicos = list(dict.fromkeys(f for f in file_ids if f))
    resultados = [_ingerir_um(law_firm_id, fid, destino, user_id, drive, iniciar_peca)
                  for fid in unicos[:MAX_POR_ENVIO]]
    if len(unicos) > MAX_POR_ENVIO:
        resultados.append({'nome': f'{len(unicos) - MAX_POR_ENVIO} arquivo(s)', 'ok': False,
                           'mensagem': f'Ficaram de fora: o limite é {MAX_POR_ENVIO} por envio.'})
    return resultados


def tentar_de_novo(law_firm_id: int, ingestion_id: int, user_id: int, **kwargs) -> Optional[dict]:
    registro = DriveIngestion.query.filter_by(id=ingestion_id, law_firm_id=law_firm_id).first()
    if registro is None:
        return None
    return ingerir(law_firm_id, [registro.drive_file_id], registro.destination, user_id, **kwargs)[0]
