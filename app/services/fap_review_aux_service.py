"""
Serviço de extração dirigida dos documentos auxiliares do Revisor FAP — fonte única.

Orquestra: âncoras de benefícios (planilha, com fallback por regex na petição),
cache das extrações por SHA-256 do arquivo e montagem do payload da tela e do
bloco de contexto entregue ao agente revisor.

As extrações rodam SEQUENCIALMENTE (não em asyncio.gather): TokenUsageService e o
cache compartilham a sessão SQLAlchemy da thread, e commits intercalados entre
corrotinas corromperiam a transação.
"""

import copy
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from flask import current_app

from app.agents.fap_review.auxiliary_extractor_agent import FapAuxiliaryDocumentExtractorAgent
from app.models import db, FapReviewAuxExtraction

try:
    from openpyxl import load_workbook
except ImportError:  # openpyxl é dependência do projeto; guarda defensiva
    load_workbook = None

_TEXT_EXTENSIONS = {'.pdf', '.docx', '.txt'}
_SPREADSHEET_EXTENSIONS = {'.xlsx'}
_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
_MAX_DOCS = int(os.environ.get('FAP_REVIEW_AUX_MAX_DOCS', '10'))
_MAX_TEXT_CHARS = int(os.environ.get('FAP_REVIEW_AUX_MAX_TEXT_CHARS', '40000'))

# Bump ao mudar o prompt do extrator — invalida o cache de extrações antigas.
_EXTRACTOR_PROMPT_VERSION = '1'


def _normalize_number(value) -> str:
    return re.sub(r'\D+', '', str(value or ''))


def build_benefit_anchors(spreadsheet_rows: list[dict] | None,
                          petition_text: str | None) -> tuple[list[dict], str]:
    """Monta a lista de benefícios-âncora. Planilha tem prioridade; sem ela,
    tenta achar NBs (10 dígitos) no texto da petição."""
    anchors: list[dict] = []
    seen: dict[str, dict] = {}

    if spreadsheet_rows:
        for row in spreadsheet_rows:
            normalized = str(row.get('benefit_number_normalized') or '').strip()
            if not normalized:
                continue
            thesis = str(row.get('thesis') or '').strip()
            entry = seen.get(normalized)
            if entry:
                if thesis and thesis not in entry['theses']:
                    entry['theses'].append(thesis)
                continue
            entry = {
                'benefit_number': str(row.get('benefit_number') or normalized),
                'benefit_number_normalized': normalized,
                'theses': [thesis] if thesis else [],
            }
            seen[normalized] = entry
            anchors.append(entry)
        if anchors:
            return anchors, 'spreadsheet'

    if petition_text:
        for candidate in re.findall(r'\d[\d\.\s\-\/]{8,18}\d', petition_text):
            normalized = _normalize_number(candidate)
            if len(normalized) != 10 or normalized in seen:
                continue
            entry = {
                'benefit_number': ' '.join(candidate.split()),
                'benefit_number_normalized': normalized,
                'theses': [],
            }
            seen[normalized] = entry
            anchors.append(entry)
        if anchors:
            return anchors, 'petition_text'

    return [], 'none'


def anchors_fingerprint(anchors: list[dict]) -> str:
    """Hash estável (independe de ordem) da lista de âncoras — compõe a chave do cache."""
    parts = sorted(
        f"{a.get('benefit_number_normalized', '')}:{'|'.join(sorted(a.get('theses') or []))}"
        for a in anchors
    )
    base = f"v{_EXTRACTOR_PROMPT_VERSION};" + ';'.join(parts)
    return hashlib.sha256(base.encode('utf-8')).hexdigest()


def compute_file_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def get_cached_extraction(law_firm_id: int, file_sha256: str,
                          extractor_model: str, fingerprint: str) -> dict | None:
    row = FapReviewAuxExtraction.query.filter_by(
        law_firm_id=law_firm_id,
        file_sha256=file_sha256,
        extractor_model=extractor_model,
        anchors_fingerprint=fingerprint,
    ).first()
    if not row:
        return None
    try:
        parsed = json.loads(row.extraction_json)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def store_extraction(law_firm_id: int, file_sha256: str, file_name: str,
                     extractor_model: str, fingerprint: str, extraction: dict) -> None:
    """Grava/atualiza o cache. Faz commit — chamar fora de transação aberta."""
    existing = FapReviewAuxExtraction.query.filter_by(
        law_firm_id=law_firm_id,
        file_sha256=file_sha256,
        extractor_model=extractor_model,
        anchors_fingerprint=fingerprint,
    ).first()
    if existing:
        existing.extraction_json = json.dumps(extraction, ensure_ascii=False)
        existing.file_name = file_name
    else:
        db.session.add(FapReviewAuxExtraction(
            law_firm_id=law_firm_id,
            file_sha256=file_sha256,
            file_name=file_name,
            extractor_model=extractor_model,
            anchors_fingerprint=fingerprint,
            extraction_json=json.dumps(extraction, ensure_ascii=False),
        ))
    db.session.commit()


def _spreadsheet_to_text(file_path: str) -> str:
    if not load_workbook:
        raise ImportError('openpyxl não está instalado')
    workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
    try:
        lines: list[str] = []
        for worksheet in workbook.worksheets:
            lines.append(f'[ABA: {worksheet.title}]')
            for row in worksheet.iter_rows(values_only=True):
                cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if cells:
                    lines.append(' | '.join(cells))
        return '\n'.join(lines)
    finally:
        workbook.close()


async def run_auxiliary_extractions(*, law_firm_id: int,
                                    user_id: int | None = None,
                                    documents: list[dict],
                                    spreadsheet_rows: list[dict] | None,
                                    petition_text: str | None,
                                    extract_text_fn,
                                    openai_api_key: str | None = None) -> tuple[dict, list[dict]]:
    """Extrai todos os documentos auxiliares e retorna (payload da tela, docs p/ o revisor)."""
    anchors, anchor_source = build_benefit_anchors(spreadsheet_rows, petition_text)
    fingerprint = anchors_fingerprint(anchors)

    valid_docs = [d for d in documents if isinstance(d, dict) and d.get('path')]
    skipped = [str(d.get('name') or Path(str(d.get('path'))).name) for d in valid_docs[_MAX_DOCS:]]
    if skipped:
        current_app.logger.warning(
            'FAP aux: %s documentos acima do limite FAP_REVIEW_AUX_MAX_DOCS=%s foram pulados: %s',
            len(skipped), _MAX_DOCS, ', '.join(skipped))
    valid_docs = valid_docs[:_MAX_DOCS]

    agent = FapAuxiliaryDocumentExtractorAgent(openai_api_key=openai_api_key)
    results: list[dict] = []

    for doc in valid_docs:
        path = str(doc['path'])
        name = str(doc.get('name') or Path(path).name)
        try:
            if not Path(path).exists():
                raise FileNotFoundError(f'Arquivo não encontrado: {path}')

            sha = compute_file_sha256(path)
            cached = get_cached_extraction(law_firm_id, sha, agent.model_name, fingerprint)
            if cached is not None:
                results.append({
                    'file_name': name,
                    'from_cache': True,
                    'extraction': conferir_extracao(cached, texto_de_referencia(path, extract_text_fn)),
                    'error': None,
                })
                continue

            extension = Path(path).suffix.lower()
            document_text = None
            if extension == '.xls':
                raise ValueError('Formato .xls não suportado — converta a planilha para .xlsx')
            if extension in _SPREADSHEET_EXTENSIONS:
                document_text = _spreadsheet_to_text(path)
            elif extension in _TEXT_EXTENSIONS:
                try:
                    document_text = extract_text_fn(path)
                except Exception as text_error:
                    current_app.logger.warning('FAP aux: extração de texto falhou (%s): %s', name, text_error)
                    document_text = None
            truncated = False
            if document_text and len(document_text) > _MAX_TEXT_CHARS:
                truncated = True
                current_app.logger.info(
                    'FAP aux: texto de %s truncado em %s caracteres', name, _MAX_TEXT_CHARS)
                document_text = document_text[:_MAX_TEXT_CHARS]
            if not document_text and extension not in (_IMAGE_EXTENSIONS | {'.pdf'}):
                raise ValueError('Não foi possível extrair texto do arquivo')

            extraction = await agent.extract(
                file_path=path,
                file_name=name,
                document_text=document_text,
                benefit_anchors=anchors,
                law_firm_id=law_firm_id,
                user_id=user_id,
            )
            extraction_dict = extraction.model_dump(mode='json')
            store_extraction(law_firm_id, sha, name, agent.model_name, fingerprint, extraction_dict)
            results.append({
                'file_name': name,
                'from_cache': False,
                'extraction': conferir_extracao(extraction_dict, texto_de_referencia(path, extract_text_fn)),
                'error': None,
                'truncated': truncated,
            })
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning('FAP aux: extração falhou (%s): %s', name, exc)
            results.append({'file_name': name, 'from_cache': False, 'extraction': None, 'error': str(exc)})

    payload = build_review_payload(results, anchors, anchor_source, skipped)
    payload['tokens_used'] = agent.total_tokens_used
    payload['cost_usd'] = float(agent.total_cost_usd)
    agent_documents = build_agent_documents(results)
    return payload, agent_documents


# ── FB-03: conferência dos números extraídos contra o próprio documento ──
#
# O extrator às vezes devolve dígitos trocados ou data impossível. Não há como
# o modelo se corrigir sozinho, mas dá para conferir: todo número do valor
# extraído tem de estar escrito no documento. O que não está vira "não
# confirmado" na tela e chega assim ao revisor, que não o trata como fato.
#
# A referência do PDF é a camada de texto lida pelo PyMuPDF, não o markdown do
# Docling que o modelo recebeu: o Docling remonta formulário e tabela, e
# conferir contra ele deixaria passar justamente o número que ele embaralhou.
# Sem texto (PDF escaneado, imagem) sobra o trecho que o próprio modelo citou —
# mais fraco, mas ainda pega valor que não bate com a própria citação.

_NUMERO = re.compile(r'\d+(?:[./\-]\d+)*')
_DATA = re.compile(r'^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2}|\d{4})$')
# "B91", "22 - Tipo": número de um dígito aparece em qualquer documento e não
# prova nada; a partir de dois já separa valor certo de valor trocado.
_MINIMO_DIGITOS = 2


def _data_do_token(token: str):
    """(ano, mês, dia) se o token tem forma de data — válida ou não —, senão None."""
    m = _DATA.match(token)
    if not m:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    if len(ano) == 2:
        limite = datetime.now().year % 100 + 1
        ano = (2000 if int(ano) <= limite else 1900) + int(ano)
    return int(ano), mes, dia


def _data_valida(partes) -> bool:
    ano, mes, dia = partes
    if not 1900 <= ano <= datetime.now().year + 1:
        return False
    try:
        date(ano, mes, dia)
    except ValueError:
        return False
    return True


def _formas_do_texto(texto: str) -> set:
    """Todos os números do texto: só dígitos e, quando for data, a data em si."""
    formas = set()
    for token in _NUMERO.findall(texto or ''):
        formas.add(('n', re.sub(r'\D', '', token)))
        partes = _data_do_token(token)
        if partes and _data_valida(partes):
            formas.add(('d', partes))
    return formas


def conferir_fato(valor: str, referencia: str, trecho: str | None) -> dict | None:
    """Confere os números de um valor extraído. None quando não há o que conferir."""
    tokens = [t for t in _NUMERO.findall(str(valor or ''))
              if len(re.sub(r'\D', '', t)) >= _MINIMO_DIGITOS]
    if not tokens:
        return None

    datas_invalidas = [t for t in tokens if (p := _data_do_token(t)) and not _data_valida(p)]
    if datas_invalidas:
        return {'status': 'data_invalida', 'base': None, 'faltando': datas_invalidas}

    if referencia and referencia.strip():
        base, formas = 'documento', _formas_do_texto(referencia)
    elif trecho and trecho.strip():
        base, formas = 'trecho', _formas_do_texto(trecho)
    else:
        return None

    faltando = []
    for token in tokens:
        partes = _data_do_token(token)
        if ('n', re.sub(r'\D', '', token)) in formas or (partes and ('d', partes) in formas):
            continue
        faltando.append(token)
    return {'status': 'nao_confirmado' if faltando else 'confirmado', 'base': base, 'faltando': faltando}


def conferir_extracao(extraction: dict, referencia: str) -> dict:
    """Cópia da extração com ``check`` em cada fato numérico. O original fica
    intacto porque é ele que vai para o cache."""
    conferida = copy.deepcopy(extraction or {})
    for benefit in conferida.get('related_benefits') or []:
        if not isinstance(benefit, dict):
            continue
        for fact in benefit.get('facts') or []:
            if not isinstance(fact, dict):
                continue
            check = conferir_fato(fact.get('value'), referencia, fact.get('source_excerpt'))
            if check:
                fact['check'] = check
    return conferida


def texto_de_referencia(path: str, extract_text_fn) -> str:
    """Texto contra o qual os números são conferidos. Vazio quando não há."""
    extension = Path(path).suffix.lower()
    try:
        if extension == '.pdf':
            import fitz  # PyMuPDF

            with fitz.open(path) as documento:
                return '\n'.join(pagina.get_text() for pagina in documento)
        if extension in _SPREADSHEET_EXTENSIONS:
            return _spreadsheet_to_text(path)
        if extension in _TEXT_EXTENSIONS:
            return extract_text_fn(path) or ''
    except Exception as exc:
        current_app.logger.warning('FAP aux: texto de conferência indisponível (%s): %s', path, exc)
    return ''


def _aviso_de_conferencia(check: dict | None) -> str:
    """Marca que acompanha o fato no bloco do revisor."""
    if not check:
        return ''
    faltando = ', '.join(check.get('faltando') or [])
    if check['status'] == 'data_invalida':
        return f' [NÃO CONFIRMADO: data impossível ({faltando}) — leitura do documento provavelmente errada]'
    if check['status'] == 'nao_confirmado':
        onde = 'no documento' if check.get('base') == 'documento' else 'no trecho citado'
        return f' [NÃO CONFIRMADO: {faltando} não aparece {onde} — tratar como incerto]'
    return ''


def build_review_payload(results: list[dict], anchors: list[dict],
                         anchor_source: str, skipped: list[str]) -> dict:
    """Payload persistido em result_json['auxiliary_documents_review'] e lido pela tela."""
    theses_map = {a['benefit_number_normalized']: a.get('theses') or [] for a in anchors}
    documents: list[dict] = []
    matched_count = 0

    for item in results:
        extraction = item.get('extraction') or {}
        related: list[dict] = []
        for benefit in extraction.get('related_benefits') or []:
            if not isinstance(benefit, dict):
                continue
            normalized = _normalize_number(benefit.get('benefit_number'))
            related.append({
                'benefit_number': str(benefit.get('benefit_number') or ''),
                'benefit_number_normalized': normalized,
                'theses': theses_map.get(normalized, []),
                'in_anchor_list': normalized in theses_map,
                'match_reason': str(benefit.get('match_reason') or ''),
                'facts': [
                    {
                        'label': str(fact.get('label') or ''),
                        'value': str(fact.get('value') or ''),
                        'source_excerpt': str(fact.get('source_excerpt') or '') or None,
                        'check': fact.get('check'),
                    }
                    for fact in (benefit.get('facts') or []) if isinstance(fact, dict)
                ],
            })

        if item.get('error'):
            status = 'error'
        elif related:
            status = 'matched'
            matched_count += 1
        else:
            status = 'unmatched'

        documents.append({
            'file_name': item.get('file_name') or '',
            'document_type': str(extraction.get('document_type') or 'OUTRO'),
            'status': status,
            'related_benefits': related,
            'general_summary': str(extraction.get('general_summary') or ''),
            'potential_divergences': [str(d) for d in extraction.get('potential_divergences') or []],
            'from_cache': bool(item.get('from_cache')),
            'truncated': bool(item.get('truncated')),
            'error': item.get('error'),
        })

    return {
        'anchor_source': anchor_source,
        'total_documents': len(results),
        'matched_documents': matched_count,
        'documents': documents,
        'skipped_documents': list(skipped or []),
    }


def build_agent_documents(results: list[dict]) -> list[dict]:
    """Converte extrações em [{'name', 'content_summary'}] para o prompt do revisor."""
    agent_docs: list[dict] = []
    for item in results:
        name = item.get('file_name') or 'arquivo_sem_nome'
        extraction = item.get('extraction')
        if not extraction:
            agent_docs.append({'name': name})
            continue

        lines = [f"Tipo: {extraction.get('document_type') or 'OUTRO'}"]
        summary = str(extraction.get('general_summary') or '').strip()
        if summary:
            lines.append(f"Resumo: {summary}")
        for benefit in extraction.get('related_benefits') or []:
            if not isinstance(benefit, dict):
                continue
            lines.append(
                f"Benefício {benefit.get('benefit_number')} — vínculo: {benefit.get('match_reason') or 'não informado'}")
            for fact in benefit.get('facts') or []:
                if not isinstance(fact, dict):
                    continue
                excerpt = fact.get('source_excerpt')
                suffix = f' (trecho: "{excerpt}")' if excerpt else ''
                lines.append(f"  - {fact.get('label')}: {fact.get('value')}{suffix}"
                             f"{_aviso_de_conferencia(fact.get('check'))}")
        for divergence in extraction.get('potential_divergences') or []:
            lines.append(f"Possível divergência: {divergence}")

        agent_docs.append({'name': name, 'content_summary': '\n'.join(lines)})
    return agent_docs
