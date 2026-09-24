"""Fila dos PDFs de decisões lidos pela IA — fonte única da tela "Enviar
decisões", do reprocessamento de uma decisão e do script de retomada.

Cada PDF vira uma linha em `jurisprudence_uploads`, processada em thread de
segundo plano (padrão do módulo: a leitura leva de 20 s a alguns minutos). O
motivo da falha fica na linha, com "tentar de novo" — na ferramenta anterior
os erros iam para uma aba com status "PENDENTE" que ninguém atualizava.

Duplicata nunca é descartada em silêncio: mesmo processo e instância vai para
"revisar", com a leitura guardada em `extracted_json`, e o advogado decide
entre manter a da base, substituir ou guardar as duas.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
from werkzeug.utils import secure_filename

from app.models import (
    db,
    JurisprudenceDecision,
    JurisprudenceThesis,
    JurisprudenceUpload,
    jurisprudence_decision_theses,
)
from app.services import jurisprudence_index_service as indice
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as svc

UPLOAD_BASE_DIR = os.path.join('uploads', 'jurisprudence')
TRAVADA_MINUTOS = 20
MAX_BYTES = 60 * 1024 * 1024
MAX_ARQUIVOS = 50
MAX_ARQUIVOS_LOTE = 300


class ArquivoRecusado(ValueError):
    pass


def _pasta(law_firm_id: int) -> str:
    pasta = os.path.join(UPLOAD_BASE_DIR, str(law_firm_id), 'pdfs')
    os.makedirs(pasta, exist_ok=True)
    return pasta


def salvar_pdf(law_firm_id: int, arquivo) -> tuple[str, str, str]:
    """Grava o PDF enviado. Devolve (caminho, nome original, sha256).

    Confere a assinatura %PDF antes de aceitar: extensão sozinha não prova nada.
    """
    nome = arquivo.filename or 'decisao.pdf'
    if not nome.lower().endswith('.pdf'):
        raise ArquivoRecusado(f'{nome}: só PDF.')
    conteudo = arquivo.read()
    if not conteudo.startswith(b'%PDF'):
        raise ArquivoRecusado(f'{nome}: o arquivo não é um PDF válido.')
    if len(conteudo) > MAX_BYTES:
        raise ArquivoRecusado(f'{nome}: maior que {MAX_BYTES // (1024 * 1024)} MB.')
    carimbo = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    caminho = os.path.join(_pasta(law_firm_id), f'{carimbo}_{secure_filename(nome) or "decisao.pdf"}')
    with open(caminho, 'wb') as destino:
        destino.write(conteudo)
    return caminho, nome[:255], hashlib.sha256(conteudo).hexdigest()


def receber(law_firm_id: int, arquivos, user_id: Optional[int] = None) -> tuple[list[int], list[str]]:
    """Enfileira os PDFs e dispara a leitura. Devolve (ids enfileirados, recusas)."""
    ids, recusas = [], []
    for arquivo in list(arquivos)[:MAX_ARQUIVOS]:
        if not arquivo or not arquivo.filename:
            continue
        try:
            caminho, nome, assinatura = salvar_pdf(law_firm_id, arquivo)
        except ArquivoRecusado as erro:
            recusas.append(str(erro))
            continue
        upload = JurisprudenceUpload(
            law_firm_id=law_firm_id, original_filename=nome, file_path=caminho,
            file_hash=assinatura, created_by_id=user_id, status=JurisprudenceUpload.STATUS_QUEUED,
        )
        # Arquivo idêntico a um já lido: não gasta IA, pergunta o que fazer.
        igual = (JurisprudenceUpload.query
                 .filter(JurisprudenceUpload.law_firm_id == law_firm_id,
                         JurisprudenceUpload.file_hash == assinatura,
                         JurisprudenceUpload.decision_id.isnot(None))
                 .order_by(JurisprudenceUpload.id.desc()).first())
        if igual is not None and igual.decision is not None:
            upload.status = JurisprudenceUpload.STATUS_REVIEW
            upload.duplicate_of_id = igual.decision_id
            upload.error_message = 'Arquivo idêntico a um já lido.'
        db.session.add(upload)
        db.session.flush()
        if upload.status == JurisprudenceUpload.STATUS_QUEUED:
            ids.append(upload.id)
    if len(list(arquivos)) > MAX_ARQUIVOS:
        recusas.append(f'Só os primeiros {MAX_ARQUIVOS} arquivos foram aceitos neste envio.')
    db.session.commit()
    disparar(law_firm_id, ids, user_id)
    return ids, recusas


def disparar(law_firm_id: int, upload_ids: list[int], user_id: Optional[int] = None) -> None:
    if not upload_ids:
        return
    threading.Thread(
        target=_rodar,
        args=(current_app._get_current_object(), law_firm_id, list(upload_ids), user_id),
        daemon=True,
        name=f'jurisprudence-upload-{upload_ids[0]}',
    ).start()


def _rodar(app_obj, law_firm_id: int, upload_ids: list[int], user_id: Optional[int]) -> None:
    with app_obj.app_context():
        try:
            for upload_id in upload_ids:
                try:
                    processar(law_firm_id, upload_id, user_id=user_id)
                except Exception as erro:
                    app_obj.logger.error(f'[JurisprudenceUpload] {upload_id}: {erro}')
                    db.session.rollback()
        finally:
            db.session.remove()


def teses_de_referencia(law_firm_id: int, limite: int = 80) -> list[str]:
    """As teses mais usadas do escritório, para a IA reaproveitar o nome."""
    contagem = (db.session.query(JurisprudenceThesis.name, db.func.count())
                .join(jurisprudence_decision_theses,
                      jurisprudence_decision_theses.c.thesis_id == JurisprudenceThesis.id)
                .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                        JurisprudenceThesis.merged_into_id.is_(None))
                .group_by(JurisprudenceThesis.id, JurisprudenceThesis.name)
                .order_by(db.func.count().desc())
                .limit(limite).all())
    return [nome for nome, _ in contagem]


def processar(law_firm_id: int, upload_id: int, *, user_id: Optional[int] = None, agente=None) -> JurisprudenceUpload:
    """Lê um PDF da fila. Síncrono — a thread e o script chamam isto."""
    from app.agents.jurisprudence.decision_extractor_agent import (
        ExtracaoFalhou,
        JurisprudenceDecisionExtractorAgent,
    )
    from app.services import ai_model_settings_service

    upload = JurisprudenceUpload.query.filter_by(id=upload_id, law_firm_id=law_firm_id).first()
    if upload is None or upload.status not in (JurisprudenceUpload.STATUS_QUEUED, JurisprudenceUpload.STATUS_FAILED):
        return upload
    upload.status = JurisprudenceUpload.STATUS_PROCESSING
    upload.started_at = datetime.now()
    upload.finished_at = None
    upload.error_message = None
    upload.attempts = (upload.attempts or 0) + 1
    db.session.commit()

    modelo = ai_model_settings_service.get_model(law_firm_id, 'jurisprudence_extractor')
    agente = agente or JurisprudenceDecisionExtractorAgent(model_name=modelo)
    try:
        lido = agente.extrair(upload.file_path, teses_referencia=teses_de_referencia(law_firm_id),
                              law_firm_id=law_firm_id, user_id=user_id or upload.created_by_id)
    except ExtracaoFalhou as erro:
        return _falhou(upload, str(erro))
    except Exception as erro:
        current_app.logger.error(f'[JurisprudenceUpload] {upload.id} erro inesperado: {erro}')
        return _falhou(upload, 'Erro inesperado na leitura. Tente de novo; se persistir, avise o suporte.')

    upload.model_used = getattr(agente, 'model_name', modelo)
    upload.extracted_json = _serializavel(lido)
    resolvedor = svc.ResolvedorDeTeses(law_firm_id)

    # Reprocessamento de uma decisão existente: atualiza no lugar.
    if upload.decision_id and upload.decision is not None:
        svc.atualizar_da_ia(upload.decision, lido, resolvedor,
                            ementa_modo=lido.get('ementa_modo'), extraction_model=upload.model_used)
        return _concluiu(upload, upload.decision)

    campos = svc.normalizar_registro(lido)
    exata = svc.mesma_decisao(law_firm_id, campos['processo_digits'], campos['tipo_documento'],
                              campos['data_julgamento'])
    parecida = exata or svc.mesma_instancia(law_firm_id, campos['processo_digits'], campos['tipo_documento'])
    if parecida is not None:
        upload.status = JurisprudenceUpload.STATUS_REVIEW
        upload.duplicate_of_id = parecida.id
        upload.error_message = None
        upload.finished_at = datetime.now()
        db.session.commit()
        return upload

    decisao = svc.criar_decisao(
        law_firm_id, lido, source=JurisprudenceDecision.SOURCE_PDF, resolvedor=resolvedor,
        user_id=upload.created_by_id, pdf_path=upload.file_path,
        original_filename=upload.original_filename, extraction_model=upload.model_used,
        ementa_modo=lido.get('ementa_modo'),
    )
    db.session.flush()
    return _concluiu(upload, decisao)


def _serializavel(lido: dict) -> dict:
    return {k: v for k, v in lido.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}


def _concluiu(upload: JurisprudenceUpload, decisao: JurisprudenceDecision) -> JurisprudenceUpload:
    decisao.search_text = svc.montar_texto_de_busca(decisao)
    upload.decision_id = decisao.id
    upload.status = JurisprudenceUpload.STATUS_DONE
    upload.error_message = None
    upload.finished_at = datetime.now()
    db.session.commit()
    # Já na thread da leitura: extrai o inteiro teor e indexa. Falha aqui fica
    # no status do índice da decisão — a leitura já está concluída e gravada.
    indice.preparar_e_indexar(decisao)
    db.session.commit()
    return upload


def _falhou(upload: JurisprudenceUpload, mensagem: str) -> JurisprudenceUpload:
    db.session.rollback()
    upload = db.session.get(JurisprudenceUpload, upload.id)
    upload.status = JurisprudenceUpload.STATUS_FAILED
    upload.error_message = mensagem[:2000]
    upload.finished_at = datetime.now()
    db.session.commit()
    return upload


# ── Ações da tela ─────────────────────────────────────────────────────

def _upload(law_firm_id: int, upload_id: int) -> JurisprudenceUpload:
    upload = JurisprudenceUpload.query.filter_by(id=upload_id, law_firm_id=law_firm_id).first()
    if upload is None:
        raise LookupError('Arquivo não encontrado na fila.')
    return upload


def travada(upload: JurisprudenceUpload) -> bool:
    """Leitura 'processing' parada há muito tempo: a thread morreu (restart)."""
    return (upload.status == JurisprudenceUpload.STATUS_PROCESSING and upload.started_at is not None
            and datetime.now() - upload.started_at > timedelta(minutes=TRAVADA_MINUTOS))


def tentar_de_novo(law_firm_id: int, upload_id: int, user_id: Optional[int] = None) -> None:
    upload = _upload(law_firm_id, upload_id)
    if upload.status == JurisprudenceUpload.STATUS_PROCESSING and not travada(upload):
        raise ValueError('Esse arquivo ainda está sendo lido.')
    # Ler de novo descarta a leitura anterior e a suspeita de duplicata: a
    # nova leitura decide de novo.
    upload.status = JurisprudenceUpload.STATUS_QUEUED
    upload.error_message = None
    upload.duplicate_of_id = None
    upload.extracted_json = None
    db.session.commit()
    disparar(law_firm_id, [upload.id], user_id)


def resolver_duplicata(law_firm_id: int, upload_id: int, acao: str, user_id: Optional[int] = None) -> Optional[int]:
    """manter | substituir | guardar_ambas. Devolve o id da decisão resultante."""
    upload = _upload(law_firm_id, upload_id)
    if upload.status != JurisprudenceUpload.STATUS_REVIEW:
        raise ValueError('Esse arquivo não está aguardando decisão.')
    existente = upload.duplicate_of
    resolvedor = svc.ResolvedorDeTeses(law_firm_id)

    if acao == 'manter':
        if existente is not None and not existente.pdf_path:
            existente.pdf_path = upload.file_path          # a da base ganha o PDF
            existente.texto_integral = None
            existente.original_filename = existente.original_filename or upload.original_filename
        decisao = existente
    elif acao == 'substituir':
        if existente is None or not upload.extracted_json:
            raise ValueError('Não há leitura para substituir — tente ler de novo.')
        existente.texto_integral = None                    # PDF novo, texto novo
        svc.atualizar_da_ia(existente, upload.extracted_json, resolvedor,
                            pdf_path=upload.file_path, original_filename=upload.original_filename,
                            extraction_model=upload.model_used,
                            ementa_modo=upload.extracted_json.get('ementa_modo'))
        decisao = existente
    elif acao == 'guardar_ambas':
        if not upload.extracted_json:
            raise ValueError('Não há leitura para guardar — tente ler de novo.')
        decisao = svc.criar_decisao(
            law_firm_id, upload.extracted_json, source=JurisprudenceDecision.SOURCE_PDF,
            resolvedor=resolvedor, user_id=user_id or upload.created_by_id,
            pdf_path=upload.file_path, original_filename=upload.original_filename,
            extraction_model=upload.model_used, ementa_modo=upload.extracted_json.get('ementa_modo'))
        db.session.flush()
    else:
        raise ValueError('Ação desconhecida.')

    if decisao is not None:
        decisao.search_text = svc.montar_texto_de_busca(decisao)
    upload.decision_id = decisao.id if decisao is not None else None
    upload.status = JurisprudenceUpload.STATUS_DONE
    upload.finished_at = datetime.now()
    db.session.commit()
    if decisao is not None:
        indice.agendar(law_firm_id, [decisao.id])
    return upload.decision_id


def descartar(law_firm_id: int, upload_id: int) -> None:
    upload = _upload(law_firm_id, upload_id)
    if upload.status == JurisprudenceUpload.STATUS_PROCESSING and not travada(upload):
        raise ValueError('Esse arquivo ainda está sendo lido.')
    caminho = upload.file_path
    em_uso = JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id, pdf_path=caminho).first()
    db.session.delete(upload)
    db.session.commit()
    if caminho and not em_uso and os.path.exists(caminho):
        try:
            os.remove(caminho)
        except OSError:
            pass


def reprocessar_decisao(law_firm_id: int, decisao: JurisprudenceDecision, user_id: Optional[int] = None) -> JurisprudenceUpload:
    """Lê de novo o PDF de uma decisão; o corrigido à mão é preservado."""
    if not decisao.pdf_path or not os.path.exists(decisao.pdf_path):
        raise ValueError('Essa decisão não tem PDF no sistema. Anexe o PDF para reprocessar.')
    em_andamento = JurisprudenceUpload.query.filter(
        JurisprudenceUpload.law_firm_id == law_firm_id,
        JurisprudenceUpload.decision_id == decisao.id,
        JurisprudenceUpload.status.in_([JurisprudenceUpload.STATUS_QUEUED, JurisprudenceUpload.STATUS_PROCESSING]),
    ).first()
    if em_andamento is not None and not travada(em_andamento):
        return em_andamento
    upload = JurisprudenceUpload(
        law_firm_id=law_firm_id, original_filename=decisao.original_filename or os.path.basename(decisao.pdf_path),
        file_path=decisao.pdf_path, decision_id=decisao.id, created_by_id=user_id,
        status=JurisprudenceUpload.STATUS_QUEUED,
    )
    db.session.add(upload)
    db.session.commit()
    disparar(law_firm_id, [upload.id], user_id)
    return upload


def anexar_pdf(law_firm_id: int, decisao: JurisprudenceDecision, arquivo) -> None:
    caminho, nome, _ = salvar_pdf(law_firm_id, arquivo)
    _anexar(decisao, caminho, nome)
    db.session.commit()
    indice.agendar(law_firm_id, [decisao.id])


def _anexar(decisao: JurisprudenceDecision, caminho: str, nome: str) -> None:
    decisao.pdf_path = caminho
    decisao.original_filename = decisao.original_filename or nome
    decisao.pdf_error = None
    decisao.texto_integral = None      # PDF novo: o inteiro teor é extraído de novo
    decisao.texto_paginas = None
    decisao.index_status = decisao.INDEX_PENDENTE


def _chave_do_arquivo(nome: str) -> str:
    return norm.chave(os.path.splitext(os.path.basename(nome or ''))[0])


def anexar_em_lote(law_firm_id: int, arquivos) -> dict:
    """Casa cada PDF com a decisão importada da planilha pelo nome do arquivo.

    A planilha guarda o nome do PDF de cada decisão (`nome_arquivo`); quem tem a
    pasta "processados" do Drive envia tudo de uma vez e cada arquivo cai na sua
    decisão. Casa só com decisão ainda sem PDF — nunca troca PDF em silêncio.
    """
    sem_pdf: dict[str, list[JurisprudenceDecision]] = {}
    for decisao in (JurisprudenceDecision.query
                    .filter(JurisprudenceDecision.law_firm_id == law_firm_id,
                            JurisprudenceDecision.pdf_path.is_(None),
                            JurisprudenceDecision.original_filename.isnot(None)).all()):
        sem_pdf.setdefault(_chave_do_arquivo(decisao.original_filename), []).append(decisao)

    anexadas, sem_par, recusas, ids = 0, [], [], []
    for arquivo in list(arquivos)[:MAX_ARQUIVOS_LOTE]:
        if not arquivo or not arquivo.filename:
            continue
        alvo = sem_pdf.pop(_chave_do_arquivo(arquivo.filename), None)
        if not alvo:
            sem_par.append(arquivo.filename)
            continue
        try:
            caminho, nome, _ = salvar_pdf(law_firm_id, arquivo)
        except ArquivoRecusado as erro:
            recusas.append(str(erro))
            continue
        for decisao in alvo:           # mesma decisão repetida na planilha: as duas ganham o PDF
            _anexar(decisao, caminho, nome)
            ids.append(decisao.id)
        anexadas += len(alvo)
    db.session.commit()
    indice.agendar(law_firm_id, ids)
    return {'anexadas': anexadas, 'sem_par': sem_par, 'recusas': recusas}


# ── PDFs no Drive (decisões importadas da planilha) ───────────────────

_DRIVE_ID = re.compile(r'/d/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})')
DRIVE_PAUSA_SEGUNDOS = 1.5      # a mesma pausa da importação de peças-modelo
DRIVE_BLOQUEIOS_PARA_PARAR = 3  # pasta sem compartilhamento: todos vão falhar igual
_drive_em_andamento: set[int] = set()


def id_do_drive(link: Optional[str]) -> Optional[str]:
    m = _DRIVE_ID.search(link or '')
    return (m.group(1) or m.group(2)) if m else None


def drive_em_andamento(law_firm_id: int) -> bool:
    return law_firm_id in _drive_em_andamento


def buscar_no_drive(law_firm_id: int) -> int:
    """Dispara o download dos PDFs das decisões importadas. Devolve quantas estão na fila."""
    pendentes = [d.id for d in JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id,
        JurisprudenceDecision.pdf_path.is_(None),
        JurisprudenceDecision.drive_link.isnot(None)).all() if id_do_drive(d.drive_link)]
    if not pendentes or law_firm_id in _drive_em_andamento:
        return 0
    _drive_em_andamento.add(law_firm_id)
    threading.Thread(target=_rodar_drive,
                     args=(current_app._get_current_object(), law_firm_id, pendentes),
                     daemon=True, name=f'jurisprudence-drive-{law_firm_id}').start()
    return len(pendentes)


def baixar_do_drive(law_firm_id: int, decision_ids: list[int], *, baixar=None, pausa: float = DRIVE_PAUSA_SEGUNDOS) -> dict:
    """Síncrono (a thread e os testes chamam isto). `baixar` é injetável."""
    import time
    from app.services.impugnacao_import_service import DriveAccessError, download_drive_file
    baixar = baixar or download_drive_file
    baixadas, falhas, bloqueios_seguidos, parou = 0, 0, 0, False
    for decision_id in decision_ids:
        decisao = JurisprudenceDecision.query.filter_by(id=decision_id, law_firm_id=law_firm_id).first()
        if decisao is None or decisao.pdf_path:
            continue
        try:
            caminho, nome, _ = baixar(id_do_drive(decisao.drive_link), _pasta(law_firm_id))
            with open(caminho, 'rb') as f:
                if not f.read(4).startswith(b'%PDF'):
                    os.remove(caminho)
                    raise DriveAccessError('O arquivo do Drive não é um PDF.')
            _anexar(decisao, caminho, nome)
            db.session.commit()
            indice.preparar_e_indexar(decisao)
            db.session.commit()
            baixadas += 1
            bloqueios_seguidos = 0
        except DriveAccessError as erro:
            db.session.rollback()
            decisao = db.session.get(JurisprudenceDecision, decision_id)
            decisao.pdf_error = str(erro)[:2000]
            db.session.commit()
            falhas += 1
            bloqueios_seguidos = bloqueios_seguidos + 1 if 'compartilhamento' in str(erro) else 0
            if bloqueios_seguidos >= DRIVE_BLOQUEIOS_PARA_PARAR:
                parou = True
                break
        if pausa:
            time.sleep(pausa)
    return {'baixadas': baixadas, 'falhas': falhas, 'parou_por_bloqueio': parou}


def _rodar_drive(app_obj, law_firm_id: int, decision_ids: list[int]) -> None:
    with app_obj.app_context():
        try:
            baixar_do_drive(law_firm_id, decision_ids)
        except Exception as erro:
            app_obj.logger.error(f'[JurisprudenceDrive] {law_firm_id}: {erro}')
        finally:
            _drive_em_andamento.discard(law_firm_id)
            db.session.remove()


def cobertura(law_firm_id: int) -> dict:
    """Quanto da base tem inteiro teor e está no índice — o painel da tela de envio."""
    D = JurisprudenceDecision
    base = D.query.filter(D.law_firm_id == law_firm_id)
    total = base.count()
    return {
        'total': total,
        'com_pdf': base.filter(D.pdf_path.isnot(None)).count(),
        'com_texto': base.filter(D.texto_paginas.isnot(None)).count(),
        'indexadas': base.filter(D.index_status == D.INDEX_INDEXADA).count(),
        'erro_indice': base.filter(D.index_status == D.INDEX_ERRO).count(),
        'sem_pdf_com_link': base.filter(D.pdf_path.is_(None), D.drive_link.isnot(None)).count(),
        'sem_pdf': base.filter(D.pdf_path.is_(None)).count(),
        'drive_erros': base.filter(D.pdf_path.is_(None), D.pdf_error.isnot(None)).count(),
        'ultimo_erro_drive': (base.filter(D.pdf_error.isnot(None)).order_by(D.updated_at.desc())
                              .with_entities(D.pdf_error).first() or [None])[0],
        'drive_em_andamento': drive_em_andamento(law_firm_id),
    }


def painel(law_firm_id: int, limite: int = 100) -> dict:
    uploads = (JurisprudenceUpload.query.filter_by(law_firm_id=law_firm_id)
               .order_by(JurisprudenceUpload.id.desc()).limit(limite).all())
    contagem = {s: 0 for s in ('queued', 'processing', 'done', 'review', 'failed')}
    linhas = []
    for u in uploads:
        estado = 'failed' if travada(u) else u.status
        contagem[estado] = contagem.get(estado, 0) + 1
        linhas.append({
            'upload': u,
            'estado': estado,
            'mensagem': ('A leitura parou no meio (o servidor pode ter reiniciado). Tente de novo.'
                         if travada(u) else u.error_message),
            'lido': _resumo_da_leitura(u),
        })
    return {'linhas': linhas, 'contagem': contagem,
            'ativos': contagem['queued'] + contagem['processing']}


def _resumo_da_leitura(u: JurisprudenceUpload) -> Optional[dict]:
    fonte = u.decision if u.decision is not None and u.status == JurisprudenceUpload.STATUS_DONE else None
    if fonte is not None:
        return {
            'tipo': norm.TIPO_LABELS_CURTOS.get(fonte.tipo_documento or '', ''),
            'tribunal': fonte.tribunal, 'orgao': fonte.orgao_julgador,
            'resultado': fonte.resultado, 'teses': len(fonte.theses),
        }
    if u.extracted_json:
        campos = svc.normalizar_registro(u.extracted_json)
        return {
            'tipo': norm.TIPO_LABELS_CURTOS.get(campos['tipo_documento'] or '', ''),
            'tribunal': campos['tribunal'], 'orgao': campos['orgao_julgador'],
            'resultado': campos['resultado'], 'teses': len(campos['teses_brutas_json']),
        }
    return None
