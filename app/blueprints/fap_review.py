"""
Blueprint: FAP Review - Módulo de Revisão de Petição Inicial FAP

Rotas principais:
- /fap-review - Dashboard principal
- /fap-review/revision - Revisão de petições
- /fap-review/training - Gerenciamento de treinamento
- /fap-review/settings - Configurações do módulo
"""

import difflib
import logging
import os
import json
import shutil
import threading
import asyncio
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from io import BytesIO
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, current_app, flash, has_request_context, jsonify, redirect, render_template, request, session, url_for, send_file
from werkzeug.utils import secure_filename
from sqlalchemy import and_, func, case, or_
from sqlalchemy.orm import joinedload

from app.models import (
    db, User, LawFirm,
    FapReviewPetition,
    FapReviewPromptVersion, FapReviewReferenceVersion, FapReviewSetting,
    FapReviewExecution, FapReviewIgnoredFinding, FapReviewAuditLog,
    FapReviewFindingCheck, FapReviewTrainingMessage,
)
from app.agents.fap_review import (
    FapPetitionReviewerAgent,
    FapTrainingApplySubAgent,
    FapTrainingDiffGrouperAgent,
    FapTrainingChatAgent,
)
from app.services.openrouter_models_service import fetch_openrouter_text_models_for_info
from app.services import fap_review_service as _svc
from app.services import fap_training_diff_service as _diff_svc
from app.services import fap_review_aux_service as _aux_svc
from app.utils.document_utils import render_docx_preview_html
from app.utils.timezone import now_sp

logger = logging.getLogger(__name__)

# Document processing
try:
    from docling.document_converter import DocumentConverter
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


fap_review_bp = Blueprint('fap_review', __name__, url_prefix='/fap-review')

# Configurações
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}
ALLOWED_AUXILIARY_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'png', 'jpg', 'jpeg'}
ALLOWED_BENEFITS_SPREADSHEET_EXTENSIONS = {'xlsx'}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
READ_ONLY_PROMPT_TYPES = {'revisor_output_format'}
READ_ONLY_REFERENCE_TYPES = {'project_instructions'}
# Rótulos e regras de workflow vivem no serviço (compartilhados com o MCP).
PETITION_WORKFLOW_STATUSES = _svc.PETITION_WORKFLOW_STATUSES


def _get_file_extension(filename: str) -> str:
    """Obtém extensão normalizada do arquivo."""
    if not filename or '.' not in filename:
        return ''
    return f".{filename.rsplit('.', 1)[1].lower()}"


def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """Verifica se arquivo tem extensão permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def _to_decimal_or_none(value) -> Decimal | None:
    """Converte custo em Decimal, devolvendo None quando não há valor utilizável.

    O custo é opcional: o agente devolve None quando o TokenUsageService não
    resolve o preço do modelo (ex.: modelo fora de `_DEFAULT_PRICING_PER_1K` com
    a consulta de preços do OpenRouter indisponível). `Decimal(str(None))`
    estoura ConversionSyntax e derrubava uma revisão já concluída — contabilidade
    de custo não pode invalidar o trabalho do revisor.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        logger.warning("Custo ignorado por não ser numérico: %r", value)
        return None


def get_current_law_firm_id() -> int:
    """Obtém ID do escritório da sessão"""
    return session.get('law_firm_id')


def require_law_firm(f):
    """Decorator para garantir que há escritório na sessão"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Acesso negado', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    
    return decorated_function


def require_admin_user(f):
    """Decorator para garantir que é admin"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('auth.login'))
        
        user = User.query.get(user_id)
        if not user or user.role != 'admin':
            flash('Acesso negado: privilégio de administrador necessário', 'error')
            return redirect(url_for('fap_review.index'))
        
        return f(*args, **kwargs)
    
    return decorated_function


def _get_fap_setting(law_firm_id: int) -> FapReviewSetting:
    """Obtém ou cria configuração padrão do FAP Review"""
    setting = FapReviewSetting.query.filter_by(law_firm_id=law_firm_id).first()
    
    if not setting:
        setting = FapReviewSetting(
            law_firm_id=law_firm_id,
            reviewer_model='gpt-4o-mini',
            training_model='gpt-4o-mini',
            reviewer_temperature=0.0,  # Temperature=0.0 com seed para determinismo garantido
            training_temperature=0.7,
            reviewer_enabled=True,
            training_enabled=True
        )
        db.session.add(setting)
        db.session.commit()
    
    return setting


def _log_audit(law_firm_id: int, action: str, entity_type: str,
               entity_id: int = None, description: str = "",
               old_value: str = "", new_value: str = "",
               user_id: int | None = None):
    """Registra ação de auditoria com o usuário da sessão (regra no serviço).

    ``user_id`` explícito permite auditar fora de requisição (ex.: revisão
    rodando em thread de background, onde não há sessão Flask).
    """
    if user_id is None and has_request_context():
        user_id = session.get('user_id')
    _svc.log_audit(law_firm_id, user_id, action, entity_type,
                   entity_id, description, old_value, new_value)


def _create_upload_directory(law_firm_id: int, subdir: str = "") -> Path:
    """Cria diretório de upload se não existir"""
    base_dir = Path('uploads/fap_review') / str(law_firm_id)
    if subdir:
        base_dir = base_dir / subdir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


# Marcador inserido no texto extraído onde o DOCX tem imagem embutida (prints de
# telas do FAP, CATs, extratos). Sem ele, a IA apontava "documento em falta" para
# provas presentes no documento como imagem.
IMAGE_MARKER = '[IMAGEM ANEXADA NO DOCUMENTO]'


def _extract_text_from_document(filepath: str) -> str:
    """Extrai texto de um documento (PDF, DOCX ou TXT)."""
    filepath = Path(filepath)
    extension = filepath.suffix.lower()
    text = ""
    
    try:
        if extension == '.pdf':
            # Tentar Docling primeiro (melhor qualidade)
            if HAS_DOCLING:
                try:
                    converter = DocumentConverter()
                    doc_result = converter.convert(str(filepath))
                    text = doc_result.document.export_to_markdown()
                except Exception as e:
                    current_app.logger.warning(f"Docling falhou: {e}, tentando PyPDF2")
                    # Fallback para PyPDF2
                    if PyPDF2:
                        with open(filepath, 'rb') as f:
                            reader = PyPDF2.PdfReader(f)
                            for page in reader.pages:
                                text += page.extract_text() + "\n"
            elif PyPDF2:
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
            else:
                raise ImportError("PyPDF2 não está instalado")
        
        elif extension == '.docx':
            if DocxDocument:
                try:
                    # Conta imagens/objetos embutidos em qualquer XML de parágrafo
                    # (w:drawing = DrawingML moderno; w:pict = VML legado;
                    #  w:object = OLE incorporado) — o formato da imagem é indiferente.
                    def _embedded_image_count(xml: str) -> int:
                        return xml.count('<w:drawing') + xml.count('<w:pict') + xml.count('<w:object')

                    doc = DocxDocument(filepath)
                    for para in doc.paragraphs:
                        text += para.text + "\n"
                        # Imagens embutidas (prints de telas do FAP, CATs etc.)
                        # viram marcador para a IA saber que a prova está presente
                        image_count = _embedded_image_count(para._p.xml)
                        if image_count:
                            text += (IMAGE_MARKER + "\n") * image_count
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                cell_text = cell.text
                                if any(_embedded_image_count(p._p.xml) for p in cell.paragraphs):
                                    cell_text = (cell_text + ' ' + IMAGE_MARKER).strip()
                                text += cell_text + " | "
                            text += "\n"
                except Exception as e:
                    raise ValueError(f"Erro ao ler DOCX: {e}")
            else:
                raise ImportError("python-docx não está instalado")

        elif extension == '.doc':
            raise ValueError("Arquivos .doc não são suportados no FAP Review. Envie em PDF ou DOCX.")
        
        elif extension == '.txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        
        else:
            raise ValueError(f"Tipo de arquivo não suportado: {extension}")
        
        # Limpar espaços em branco excessivos
        text = '\n'.join([line.strip() for line in text.split('\n') if line.strip()])
        
        return text
    
    except Exception as e:
        current_app.logger.error(f"Erro ao extrair texto: {e}")
        raise


def _normalize_spreadsheet_header(value: object) -> str:
    """Normaliza cabeçalhos de planilha para busca resiliente.

    Além de acento e caixa, derruba pontuação: "Nº", "TESE(S)" e "N° do
    Benefício" viram texto comparável sem uma entrada de alias para cada
    variação de digitação.
    """
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    ascii_text = re.sub(r'[^a-z0-9]+', ' ', ascii_text.lower())
    return ' '.join(ascii_text.split())


# Cada escritório nomeia a coluna do seu jeito. A lista está em ordem de
# preferência: a primeira que existir na aba é a usada.
_BENEFIT_HEADER_ALIASES = (
    'numero do beneficio',
    'numero beneficio',
    'n do beneficio',
    'no do beneficio',
    'n beneficio',
    'nb',
    'beneficio',
)
_THESIS_HEADER_ALIASES = ('tese', 'teses')


def _find_header_index(header_map: dict[str, int], aliases: tuple[str, ...]) -> int | None:
    """Índice da primeira coluna cujo cabeçalho casa com um dos nomes aceitos."""
    for alias in aliases:
        if alias in header_map:
            return header_map[alias]
    return None


def _find_thesis_index(header_map: dict[str, int]) -> int | None:
    """Índice da coluna da tese, aceitando singular, plural e sufixos.

    Casa "TESE", "TESES", "TESE(S)" e "TESES APLICADAS" — mas pela primeira
    palavra, nunca por substring: as vizinhas ("OBS", "Número da CAT") não
    podem ser confundidas com a coluna da tese.
    """
    exact = _find_header_index(header_map, _THESIS_HEADER_ALIASES)
    if exact is not None:
        return exact

    for header, index in header_map.items():
        if header.split(' ', 1)[0] in _THESIS_HEADER_ALIASES:
            return index
    return None


def _format_benefit_number(value: object) -> str:
    """Formata número de benefício preservando apenas o valor legível."""
    if value is None:
        return ''

    if isinstance(value, bool):
        return ''

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def _normalize_benefit_number(value: object) -> str:
    """Normaliza número de benefício para comparação textual."""
    return re.sub(r'\D+', '', _format_benefit_number(value))


def _document_mentions_benefit_number(document_text: str, normalized_benefit_number: str) -> bool:
    """Verifica se o documento menciona o benefício com tolerância a pontuação e separadores."""
    if not document_text or not normalized_benefit_number:
        return False

    # Aceita formatos como 1234567890, 123.456.789-0, 123 456 789 0 ou variações com separadores.
    separator_pattern = r'[\s\.\-\/_;,:\(\)\[\]]*'
    digit_pattern = separator_pattern.join(re.escape(digit) for digit in normalized_benefit_number)
    pattern = rf'(?<!\d){digit_pattern}(?!\d)'
    return re.search(pattern, document_text) is not None


def _parse_benefits_spreadsheet(filepath: str) -> list[dict[str, str]]:
    """Lê a planilha de benefícios (todas as abas) e retorna as linhas com tese preenchida.

    Planilhas reais costumam ter uma aba por vigência (2021, 2022, ...); abas sem
    as colunas esperadas (ex.: anotações) são ignoradas.
    """
    if not load_workbook:
        raise ImportError('openpyxl não está instalado')

    workbook = load_workbook(filename=filepath, read_only=True, data_only=True)

    try:
        rows: list[dict[str, str]] = []
        sheets_with_columns = 0
        rejected_sheets: list[str] = []

        for worksheet in workbook.worksheets:
            header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if not header_row:
                rejected_sheets.append(f'{worksheet.title}: aba vazia')
                continue

            # Cabeçalho repetido (a planilha real tem "OBS" três vezes): a
            # primeira ocorrência vence, não a última.
            header_map: dict[str, int] = {}
            for index, value in enumerate(header_row):
                normalized = _normalize_spreadsheet_header(value)
                if normalized:
                    header_map.setdefault(normalized, index)

            benefit_idx = _find_header_index(header_map, _BENEFIT_HEADER_ALIASES)
            thesis_idx = _find_thesis_index(header_map)

            if benefit_idx is None or thesis_idx is None:
                missing = []
                if benefit_idx is None:
                    missing.append('o número do benefício')
                if thesis_idx is None:
                    missing.append('a tese')
                rejected_sheets.append(f'{worksheet.title}: falta {" e ".join(missing)}')
                continue
            sheets_with_columns += 1

            for row in worksheet.iter_rows(min_row=2, values_only=True):
                thesis = ' '.join(str(row[thesis_idx] or '').strip().split()) if thesis_idx < len(row) else ''
                if not thesis:
                    continue

                benefit_number = _format_benefit_number(row[benefit_idx] if benefit_idx < len(row) else '')
                normalized_benefit_number = _normalize_benefit_number(benefit_number)
                if not normalized_benefit_number:
                    continue

                rows.append({
                    'benefit_number': benefit_number,
                    'benefit_number_normalized': normalized_benefit_number,
                    'thesis': thesis,
                    'sheet_name': worksheet.title,
                })

        if not sheets_with_columns:
            # Diz o que faltou em cada aba: sem isso, "cabeçalho com outro nome"
            # e "cabeçalho fora da primeira linha" dão a mesma mensagem.
            detalhe = '; '.join(rejected_sheets[:8])
            if len(rejected_sheets) > 8:
                detalhe += f'; e mais {len(rejected_sheets) - 8} aba(s)'
            raise ValueError(
                'Nenhuma aba da planilha tem as duas colunas obrigatórias na primeira '
                'linha: o número do benefício ("Número do Benefício") e a tese '
                f'("TESE" ou "TESES"). Abas lidas — {detalhe}.'
            )

        return rows
    finally:
        workbook.close()


def _load_execution_benefits_spreadsheet(execution) -> dict | None:
    """Lê o registro da planilha de benefícios persistido na execução."""
    if not execution or not getattr(execution, 'benefits_spreadsheet_json', None):
        return None
    try:
        data = json.loads(execution.benefits_spreadsheet_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get('path') else None


def _list_execution_files(execution) -> dict:
    """Arquivos enviados de uma execução (auxiliares, planilha, comparado) para links de download."""
    aux_files: list[dict] = []
    try:
        raw_docs = json.loads(execution.auxiliary_documents_json or '[]')
    except (TypeError, json.JSONDecodeError):
        raw_docs = []
    for index, doc in enumerate(raw_docs):
        if isinstance(doc, dict) and doc.get('path'):
            aux_files.append({
                'index': index,
                'name': str(doc.get('name') or Path(str(doc['path'])).name),
            })

    spreadsheet = _load_execution_benefits_spreadsheet(execution)
    return {
        'aux': aux_files,
        'spreadsheet_name': str(spreadsheet.get('name') or Path(str(spreadsheet['path'])).name) if spreadsheet else '',
        'has_compared': bool(str(execution.compared_document_path or '').strip()),
    }


def _copy_reused_revision_files(previous_execution, upload_dir, timestamp: str,
                                reuse_auxiliary: bool, reuse_benefits: bool) -> tuple[list[dict], dict | None]:
    """Copia auxiliares/planilha da revisão anterior para a nova execução.

    Copia (em vez de referenciar) para cada execução permanecer autocontida no
    disco. Arquivos ausentes são ignorados sem erro.
    """
    upload_dir = Path(upload_dir)
    auxiliary_files: list[dict] = []

    if reuse_auxiliary and previous_execution and previous_execution.auxiliary_documents_json:
        try:
            prior_docs = json.loads(previous_execution.auxiliary_documents_json)
        except (TypeError, json.JSONDecodeError):
            prior_docs = []
        for index, doc in enumerate(prior_docs if isinstance(prior_docs, list) else []):
            source = Path(str(doc.get('path') or ''))
            if not doc.get('path') or not source.is_file():
                continue
            original_name = str(doc.get('name') or source.name)
            destination = upload_dir / f'{timestamp}reuse_aux_{index}_{secure_filename(original_name)}'
            shutil.copy2(source, destination)
            auxiliary_files.append({'name': original_name, 'path': str(destination)})

    benefits_spreadsheet = None
    if reuse_benefits:
        prior_benefits = _load_execution_benefits_spreadsheet(previous_execution)
        if prior_benefits:
            source = Path(str(prior_benefits['path']))
            if source.is_file():
                original_name = str(prior_benefits.get('name') or source.name)
                destination = upload_dir / f'{timestamp}reuse_benefits_{secure_filename(original_name)}'
                shutil.copy2(source, destination)
                benefits_spreadsheet = {'name': original_name, 'path': str(destination)}

    return auxiliary_files, benefits_spreadsheet


def _build_benefits_spreadsheet_review(
    spreadsheet_path: str,
    spreadsheet_filename: str,
    document_text: str,
    checked_document_label: str,
) -> dict:
    """Gera checagem determinística dos benefícios da planilha contra o documento."""
    rows = _parse_benefits_spreadsheet(spreadsheet_path)

    items: list[dict[str, object]] = []
    found_count = 0

    for row in rows:
        found_in_document = _document_mentions_benefit_number(
            document_text=document_text,
            normalized_benefit_number=row['benefit_number_normalized'],
        )
        if found_in_document:
            found_count += 1

        items.append({
            'benefit_number': row['benefit_number'],
            'thesis': row['thesis'],
            'sheet_name': row.get('sheet_name', ''),
            'found_in_document': found_in_document,
        })

    return {
        'source_filename': spreadsheet_filename,
        'checked_document_label': checked_document_label,
        'total_rows_with_theses': len(items),
        'found_count': found_count,
        'missing_count': max(len(items) - found_count, 0),
        'items': items,
    }


# _normalize_finding_field -> app/services/fap_review_service.py (fonte única)
_normalize_finding_field = _svc.normalize_finding_field

# _build_finding_fingerprint -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_build_finding_fingerprint = _svc.build_finding_fingerprint

def _get_ignored_finding_fingerprints(law_firm_id: int, law_firm_document_identifier: str) -> set[str]:
    """Retorna fingerprints de achados marcados como não úteis para o documento."""
    if not law_firm_document_identifier:
        return set()

    rows = FapReviewIgnoredFinding.query.filter_by(
        law_firm_id=law_firm_id,
        law_firm_document_identifier=law_firm_document_identifier,
    ).with_entities(FapReviewIgnoredFinding.finding_fingerprint).all()
    return {str(row[0]) for row in rows if row and row[0]}


def _build_prior_attention_points(
    law_firm_id: int,
    petition_id: int | None,
    law_firm_document_identifier: str,
    current_execution_id: int,
) -> str | None:
    """Resume os pontos de atenção da última revisão concluída do mesmo documento."""
    if not petition_id and not law_firm_document_identifier:
        return None

    previous_execution_query = FapReviewExecution.query.filter(
        FapReviewExecution.law_firm_id == law_firm_id,
        FapReviewExecution.execution_type == 'revision',
        FapReviewExecution.status == 'completed',
        FapReviewExecution.id != current_execution_id,
        FapReviewExecution.result_json.isnot(None),
    )

    if petition_id:
        previous_execution_query = previous_execution_query.filter(
            FapReviewExecution.petition_id == petition_id,
        )
    else:
        previous_execution_query = previous_execution_query.filter(
            FapReviewExecution.law_firm_document_identifier == law_firm_document_identifier,
        )

    previous_execution = previous_execution_query.order_by(
        FapReviewExecution.completed_at.desc(),
        FapReviewExecution.id.desc(),
    ).first()

    if not previous_execution or not previous_execution.result_json:
        return None

    try:
        result_payload = json.loads(previous_execution.result_json)
    except (TypeError, json.JSONDecodeError):
        current_app.logger.warning(
            'Falha ao interpretar o histórico da execução %s para o identificador %s',
            previous_execution.id,
            law_firm_document_identifier,
        )
        return None

    ignored_fingerprints = _get_ignored_finding_fingerprints(
        law_firm_id=law_firm_id,
        law_firm_document_identifier=law_firm_document_identifier,
    )
    lines: list[str] = []

    for finding in result_payload.get('findings') or []:
        finding_fingerprint = _build_finding_fingerprint(finding)
        if finding_fingerprint and finding_fingerprint in ignored_fingerprints:
            continue

        description = str(finding.get('description') or '').strip()
        if not description:
            continue

        severity = str(finding.get('severity') or 'ATENÇÃO').strip().upper()
        location = str(finding.get('location') or '').strip()
        correction = str(finding.get('correction') or '').strip()
        manual_reference = str(finding.get('manual_reference') or '').strip()

        parts = [f'- [{severity}] {description}']
        if location:
            parts.append(f'Local: {location}')
        if correction:
            parts.append(f'Correção esperada: {correction}')
        if manual_reference:
            parts.append(f'Referência manual: {manual_reference}')
        lines.append(' | '.join(parts))

    for missing_document in result_payload.get('missing_documents') or []:
        document_type = str(missing_document.get('document_type') or '').strip()
        if not document_type:
            continue

        thesis = str(missing_document.get('thesis') or '').strip()
        manual_reference = str(missing_document.get('manual_reference') or '').strip()
        parts = [f'- [DOCUMENTO] {document_type}']
        if thesis:
            parts.append(f'Tese relacionada: {thesis}')
        if manual_reference:
            parts.append(f'Referência manual: {manual_reference}')
        lines.append(' | '.join(parts))

    if not lines:
        return (
            '__NO_ACTIVE_PRIOR_ATTENTION_POINTS__\n'
            'Os pontos de atenção anteriores deste identificador foram marcados como não úteis '
            'e não devem ser cobrados novamente nesta revisão.'
        )

    return '\n'.join(lines)


def _start_review_in_background(execution_id: int, law_firm_id: int, petition_file_path: str,
                                compared_file_path: str | None = None,
                                benefits_spreadsheet: dict | None = None) -> None:
    """Dispara o agente revisor numa thread e devolve o controle imediatamente.

    A chamada à LLM leva 1-2 min; processar dentro da requisição estoura os
    timeouts de proxy (Cloudflare ~100s). O POST retorna na hora e a tela de
    resultado acompanha o status (auto-refresh).

    Usado tanto pelo envio de uma revisão nova quanto pelo reprocessamento de
    uma que falhou — o tratamento de falha da thread mora só aqui.
    """
    app_obj = current_app._get_current_object()

    def _run_review_in_background():
        with app_obj.app_context():
            try:
                _execute_reviewer_agent(
                    execution_id,
                    law_firm_id,
                    petition_file_path,
                    compared_file_path,
                    benefits_spreadsheet=benefits_spreadsheet,
                )
            except Exception as agent_error:
                app_obj.logger.error(f"Erro na execução do agente: {agent_error}")
                # _execute_reviewer_agent já marca 'failed'; garante o estado
                try:
                    background_execution = FapReviewExecution.query.get(execution_id)
                    if background_execution and background_execution.status == 'processing':
                        background_execution.status = 'failed'
                        background_execution.error_message = str(agent_error)
                        db.session.commit()
                except Exception:
                    db.session.rollback()
            finally:
                db.session.remove()

    threading.Thread(
        target=_run_review_in_background,
        daemon=True,
        name=f'fap-review-{execution_id}',
    ).start()


def _execute_reviewer_agent(execution_id: int, law_firm_id: int, petition_file_path: str,
                           compared_file_path: str = None,
                           benefits_spreadsheet: dict | None = None) -> dict:
    """Executa o agente revisor e armazena resultado"""
    try:
        execution = FapReviewExecution.query.get(execution_id)
        if not execution:
            raise ValueError(f"Execução {execution_id} não encontrada")
        
        # Carregar configurações
        setting = _get_fap_setting(law_firm_id)
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY não configurada")
        
        # Carregar referências ativas
        manual = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='manual_fap',
            is_active=True
        ).first()
        
        cases = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='casos_referencia',
            is_active=True
        ).first()
        
        project_instructions = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='project_instructions',
            is_active=True
        ).first()

        # Carregar prompts ativos do revisor
        reviewer_identity_prompt = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type='revisor_identity',
            is_active=True
        ).first()

        reviewer_rules_prompt = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type='revisor_rules',
            is_active=True
        ).first()

        reviewer_output_format_prompt = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type='revisor_output_format',
            is_active=True
        ).first()

        # Snapshot das versões usadas nesta execução (rastreabilidade)
        execution.used_versions_json = json.dumps(
            _svc.collect_active_versions(law_firm_id), ensure_ascii=False)
        # Gravado ANTES de rodar: se a execução falhar no meio, ainda queremos
        # saber com que modelo ela falhou.
        execution.model_name = setting.reviewer_model
        db.session.commit()

        # Instanciar agente revisor
        agent = FapPetitionReviewerAgent(
            openai_api_key=openai_api_key,
            model=setting.reviewer_model,
            temperature=setting.reviewer_temperature
        )
        
        # Carregar referências no agente
        agent.load_reference_documents(
            manual_md=manual.content if manual else "",
            cases_md=cases.content if cases else "",
            project_instructions_md=project_instructions.content if project_instructions else ""
        )
        
        # Executar análise (async)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            petition_extension = Path(petition_file_path).suffix.lower()
            petition_text = _extract_text_from_document(petition_file_path) if petition_extension in {'.docx', '.txt'} else None
            prior_attention_points = _build_prior_attention_points(
                law_firm_id=law_firm_id,
                petition_id=execution.petition_id,
                law_firm_document_identifier=execution.law_firm_document_identifier or '',
                current_execution_id=execution.id,
            )

            compared_text = None
            if compared_file_path:
                compared_extension = Path(compared_file_path).suffix.lower()
                compared_text = _extract_text_from_document(compared_file_path) if compared_extension in {'.docx', '.txt'} else None

            # ===== Extração dirigida dos documentos auxiliares (opcional) =====
            aux_review_payload = None
            auxiliary_agent_docs = None
            try:
                aux_docs = json.loads(execution.auxiliary_documents_json or '[]')
            except (TypeError, json.JSONDecodeError):
                aux_docs = []
            if aux_docs:
                spreadsheet_rows = None
                if benefits_spreadsheet and benefits_spreadsheet.get('path'):
                    try:
                        spreadsheet_rows = _parse_benefits_spreadsheet(str(benefits_spreadsheet['path']))
                    except Exception as spreadsheet_error:
                        current_app.logger.warning(
                            'FAP aux: planilha ilegível para âncoras (execução %s): %s',
                            execution_id, spreadsheet_error)
                anchor_text = (
                    (compared_text or petition_text)
                    if compared_file_path and execution.comparative_analysis
                    else petition_text
                )
                try:
                    aux_review_payload, auxiliary_agent_docs = loop.run_until_complete(
                        _aux_svc.run_auxiliary_extractions(
                            law_firm_id=law_firm_id,
                            user_id=execution.user_id,
                            documents=aux_docs,
                            spreadsheet_rows=spreadsheet_rows,
                            petition_text=anchor_text,
                            extract_text_fn=_extract_text_from_document,
                            openai_api_key=openai_api_key,
                        )
                    )
                except Exception as aux_error:
                    # Falha na extração NUNCA derruba a revisão.
                    current_app.logger.warning(
                        'FAP aux: extração dos auxiliares falhou (execução %s): %s',
                        execution_id, aux_error)
                    aux_review_payload = {
                        'anchor_source': 'none',
                        'total_documents': len(aux_docs),
                        'matched_documents': 0,
                        'documents': [],
                        'skipped_documents': [],
                        'error': str(aux_error),
                    }
                    auxiliary_agent_docs = None

            if compared_file_path and execution.comparative_analysis:
                # Análise comparativa
                result = loop.run_until_complete(
                    agent.review_petition_comparative(
                        original_petition_file_path=petition_file_path,
                        revised_petition_file_path=compared_file_path,
                        original_petition_text=petition_text,
                        revised_petition_text=compared_text,
                        prior_attention_points=prior_attention_points,
                        auxiliary_documents=auxiliary_agent_docs,
                        reviewer_identity=reviewer_identity_prompt.content if reviewer_identity_prompt else "",
                        reviewer_rules=reviewer_rules_prompt.content if reviewer_rules_prompt else "",
                        reviewer_output_format=reviewer_output_format_prompt.content if reviewer_output_format_prompt else "",
                        execution_id=execution.id,
                        user_id=execution.user_id,
                        law_firm_id=law_firm_id,
                    )
                )
            else:
                # Análise simples
                result = loop.run_until_complete(
                    agent.review_petition_single_version(
                        petition_file_path=petition_file_path,
                        petition_text=petition_text,
                        prior_attention_points=prior_attention_points,
                        auxiliary_documents=auxiliary_agent_docs,
                        reviewer_identity=reviewer_identity_prompt.content if reviewer_identity_prompt else "",
                        reviewer_rules=reviewer_rules_prompt.content if reviewer_rules_prompt else "",
                        reviewer_output_format=reviewer_output_format_prompt.content if reviewer_output_format_prompt else "",
                        execution_id=execution.id,
                        user_id=execution.user_id,
                        law_firm_id=law_firm_id,
                    )
                )

            result_payload = result.model_dump(mode='json')

            if aux_review_payload is not None:
                result_payload['auxiliary_documents_review'] = aux_review_payload

            if benefits_spreadsheet and benefits_spreadsheet.get('path'):
                target_document_path = compared_file_path if compared_file_path and execution.comparative_analysis else petition_file_path
                target_document_text = compared_text if compared_file_path and execution.comparative_analysis else petition_text
                if not target_document_text:
                    target_document_text = _extract_text_from_document(target_document_path)

                checked_document_label = (
                    'Documento revisado'
                    if compared_file_path and execution.comparative_analysis
                    else (execution.main_document_filename or 'Documento principal')
                )

                try:
                    result_payload['benefits_spreadsheet_review'] = _build_benefits_spreadsheet_review(
                        spreadsheet_path=str(benefits_spreadsheet['path']),
                        spreadsheet_filename=str(benefits_spreadsheet.get('name') or Path(benefits_spreadsheet['path']).name),
                        document_text=target_document_text,
                        checked_document_label=checked_document_label,
                    )
                except Exception as spreadsheet_error:
                    current_app.logger.warning(
                        'Falha ao processar planilha de beneficios da execucao %s: %s',
                        execution_id,
                        spreadsheet_error,
                    )
                    result_payload['benefits_spreadsheet_review'] = {
                        'source_filename': str(benefits_spreadsheet.get('name') or Path(benefits_spreadsheet['path']).name),
                        'checked_document_label': checked_document_label,
                        'error': str(spreadsheet_error),
                        'items': [],
                        'total_rows_with_theses': 0,
                        'found_count': 0,
                        'missing_count': 0,
                    }
            
            # Armazenar resultado
            execution.result_json = json.dumps(result_payload, ensure_ascii=False, indent=2)
            execution.status = 'completed'
            execution.completed_at = datetime.now()
            
            # Se o resultado tem tokens, armazenar
            if hasattr(result, 'tokens_used'):
                execution.tokens_used = result.tokens_used
            result_cost = _to_decimal_or_none(getattr(result, 'cost_usd', None))
            if result_cost is not None:
                execution.cost_usd = result_cost

            # Soma tokens/custo das extrações auxiliares ao total da execução
            if aux_review_payload and aux_review_payload.get('tokens_used'):
                execution.tokens_used = (execution.tokens_used or 0) + int(aux_review_payload['tokens_used'])
            aux_cost = _to_decimal_or_none((aux_review_payload or {}).get('cost_usd'))
            if aux_cost is not None:
                execution.cost_usd = (execution.cost_usd or Decimal('0')) + aux_cost

            _sync_petition_after_revision(execution)
            
            db.session.commit()
            
            # Log de auditoria
            _log_audit(law_firm_id, 'revision_completed', 'execution', execution_id,
                      'Revisão concluída com sucesso', user_id=execution.user_id)
            
            return {'success': True, 'execution_id': execution_id}
        
        finally:
            loop.close()
    
    except Exception as e:
        current_app.logger.error(f"Erro ao executar agente revisor: {e}")
        
        # Atualizar status para falha
        try:
            execution = FapReviewExecution.query.get(execution_id)
            if execution:
                execution.status = 'failed'
                execution.error_message = str(e)
                execution.completed_at = datetime.now()
                _sync_petition_after_revision(execution)
                db.session.commit()
                
                _log_audit(law_firm_id, 'revision_failed', 'execution', execution_id,
                          f'Erro: {str(e)[:200]}', user_id=execution.user_id)
        except Exception as inner_e:
            current_app.logger.error(f"Erro ao registrar falha: {inner_e}")
        
        raise


def _get_active_reference(law_firm_id: int, reference_type: str) -> FapReviewReferenceVersion | None:
    """Obtém a versão ativa mais recente de uma referência."""
    return FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
        is_active=True,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()


def _append_reference_version(
    law_firm_id: int,
    user_id: int,
    reference_type: str,
    new_content: str,
    activate: bool = True,
) -> FapReviewReferenceVersion:
    """Cria uma nova versão de referência, opcionalmente ativando-a."""
    latest = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()

    next_version = (latest.version_number + 1) if latest else 1

    if activate:
        FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type=reference_type,
            is_active=True,
        ).update({'is_active': False})

    version = FapReviewReferenceVersion(
        law_firm_id=law_firm_id,
        version_number=next_version,
        reference_type=reference_type,
        content=new_content,
        is_active=activate,
        created_by_id=user_id,
    )
    db.session.add(version)
    return version


# _build_petition_title -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_build_petition_title = _svc.build_petition_title

# _derive_petition_workflow_status -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_derive_petition_workflow_status = _svc.derive_petition_workflow_status

# _sync_petition_after_revision -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_sync_petition_after_revision = _svc.sync_petition_after_revision

def _build_petition_status_badge(workflow_status: str) -> dict[str, str]:
    """Retorna classes e label para o status da petição na UI."""
    mapping = {
        'new': {'class': 'secondary', 'icon': 'bi bi-plus-circle'},
        'in_review': {'class': 'warning', 'icon': 'bi bi-hourglass-split'},
        'awaiting_adjustments': {'class': 'danger', 'icon': 'bi bi-pencil-square'},
        'awaiting_approval': {'class': 'info', 'icon': 'bi bi-person-check'},
        'ready_for_filing': {'class': 'success', 'icon': 'bi bi-check-circle'},
        'filed': {'class': 'primary', 'icon': 'bi bi-send-check'},
        'archived': {'class': 'dark', 'icon': 'bi bi-archive'},
    }
    status_key = workflow_status if workflow_status in mapping else 'new'
    return {
        'label': PETITION_WORKFLOW_STATUSES.get(status_key, 'Nova'),
        **mapping[status_key],
    }


# _load_execution_result_payload -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_load_execution_result_payload = _svc.load_execution_result_payload

# _calculate_lawyer_score -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_calculate_lawyer_score = _svc.calculate_lawyer_score

# _translate_user_role -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_translate_user_role = _svc.translate_user_role

# _normalize_finding_severity -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_normalize_finding_severity = _svc.normalize_finding_severity

# _translate_finding_category -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_translate_finding_category = _svc.translate_finding_category

def _propagate_petition_identifier_change(
    law_firm_id: int,
    petition: FapReviewPetition,
    old_identifier: str,
    new_identifier: str,
) -> None:
    """Propaga a troca do Id Wrike para execuções e feedbacks associados à petição."""
    if not old_identifier or old_identifier == new_identifier:
        return

    FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        petition_id=petition.id,
    ).update({'law_firm_document_identifier': new_identifier}, synchronize_session=False)

    ignored_findings = FapReviewIgnoredFinding.query.filter_by(
        law_firm_id=law_firm_id,
        law_firm_document_identifier=old_identifier,
    ).all()

    for ignored_finding in ignored_findings:
        duplicated_row = FapReviewIgnoredFinding.query.filter_by(
            law_firm_id=law_firm_id,
            law_firm_document_identifier=new_identifier,
            finding_fingerprint=ignored_finding.finding_fingerprint,
        ).first()

        if duplicated_row:
            db.session.delete(ignored_finding)
            continue

        ignored_finding.law_firm_document_identifier = new_identifier
        ignored_finding.updated_at = datetime.now()


# _build_lawyer_statistics -> app/services/fap_review_service.py (fonte única, usada também pelo MCP)
_build_lawyer_statistics = _svc.build_lawyer_statistics

# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS PRINCIPAIS
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.app_context_processor
def inject_fap_review_pending_counts():
    """Badge do Revisor na header (barato: um count agrupado com índice).

    Sensível ao papel: o badge soma o que exige ação de quem está olhando —
    "aguardando ajustes" para todos; "aguardando aprovação" só para admin.
    """
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return {'fap_review_pending_counts': None}
    try:
        counts = _svc.count_pending_review_queues(law_firm_id)
    except Exception:
        return {'fap_review_pending_counts': None}

    is_admin = session.get('user_role') == 'admin'
    badge = (counts['in_review'] + counts['awaiting_adjustments']
             + (counts['awaiting_approval'] if is_admin else 0))
    return {'fap_review_pending_counts': {**counts, 'badge': badge, 'is_admin': is_admin}}


@fap_review_bp.route('/')
@require_law_firm
def index():
    """Dashboard principal do módulo"""
    law_firm_id = get_current_law_firm_id()

    total_petitions = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id).count()
    ready_petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
        workflow_status='ready_for_filing',
    ).count()
    in_review_petitions = FapReviewPetition.query.filter(
        FapReviewPetition.law_firm_id == law_firm_id,
        FapReviewPetition.workflow_status.in_(['new', 'in_review']),
    ).count()
    awaiting_adjustments_petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
        workflow_status='awaiting_adjustments',
    ).count()
    awaiting_approval_petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
        workflow_status='awaiting_approval',
    ).count()
    total_revisions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        execution_type='revision',
    ).count()

    _priority_order = case(
        (FapReviewPetition.workflow_status == 'awaiting_adjustments', 0),
        (FapReviewPetition.workflow_status == 'awaiting_approval', 1),
        (FapReviewPetition.workflow_status.in_(['new', 'in_review']), 2),
        (FapReviewPetition.workflow_status == 'ready_for_filing', 3),
        else_=4
    )

    petitions = FapReviewPetition.query.options(
        joinedload(FapReviewPetition.latest_revision).joinedload(FapReviewExecution.user),
    ).filter_by(
        law_firm_id=law_firm_id,
    ).order_by(
        _priority_order,
        FapReviewPetition.updated_at.desc(),
        FapReviewPetition.id.desc(),
    ).all()

    now = datetime.now()

    def _status_age_days(petition) -> int:
        reference = petition.status_changed_at or petition.updated_at or petition.created_at
        return max(0, (now - reference).days) if reference else 0

    def _latest_findings_count(petition):
        execution = petition.latest_revision
        if not execution or execution.status != 'completed':
            return None
        payload = _load_execution_result_payload(execution)
        findings = payload.get('findings')
        return len(findings) if isinstance(findings, list) else None

    petition_rows = [
        {
            'petition': petition,
            'latest_revision': petition.latest_revision,
            'latest_reviewer_name': petition.latest_revision.user.name if petition.latest_revision and petition.latest_revision.user else None,
            'latest_reviewer_picture': petition.latest_revision.user.google_picture_url if petition.latest_revision and petition.latest_revision.user else None,
            'status_badge': _build_petition_status_badge(petition.workflow_status),
            'status_age_days': _status_age_days(petition),
            'findings_count': _latest_findings_count(petition),
        }
        for petition in petitions
    ]

    return render_template('fap_review/index.html',
                          total_petitions=total_petitions,
                          ready_petitions=ready_petitions,
                          in_review_petitions=in_review_petitions,
                          awaiting_adjustments_petitions=awaiting_adjustments_petitions,
                          awaiting_approval_petitions=awaiting_approval_petitions,
                          total_revisions=total_revisions,
                          petition_rows=petition_rows)


@fap_review_bp.route('/revision', methods=['GET', 'POST'])
@require_law_firm
def revision():
    """Página de revisão de petições"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        try:
            # Validar upload de arquivo principal
            if 'main_document' not in request.files:
                return jsonify({'error': 'Documento principal não fornecido'}), 400
            
            main_file = request.files['main_document']
            if main_file.filename == '':
                return jsonify({'error': 'Arquivo vazio'}), 400

            main_extension = _get_file_extension(main_file.filename)
            if main_extension == '.doc':
                return jsonify({'error': 'Arquivos .doc não são suportados no FAP Review. Envie em PDF ou DOCX.'}), 400
            
            if not allowed_file(main_file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                return jsonify({'error': 'Tipo de arquivo não permitido'}), 400

            petition_id = request.form.get('petition_id', type=int)
            petition_title = str(request.form.get('petition_title', '')).strip()
            petition = None
            law_firm_document_identifier = str(
                request.form.get('law_firm_document_identifier', '')
            ).strip()

            if petition_id:
                petition = FapReviewPetition.query.filter_by(
                    id=petition_id,
                    law_firm_id=law_firm_id,
                ).first()
                if not petition:
                    return jsonify({'error': 'Petição selecionada não encontrada.'}), 404
                law_firm_document_identifier = petition.office_document_identifier
            else:
                law_firm_document_identifier, identifier_error = _svc.validate_wrike_identifier(
                    law_firm_document_identifier)
                if identifier_error:
                    return jsonify({'error': identifier_error}), 400
                petition = FapReviewPetition.query.filter_by(
                    law_firm_id=law_firm_id,
                    office_document_identifier=law_firm_document_identifier,
                ).first()

            if petition and petition.workflow_status in _svc.NEW_REVISION_BLOCKED_STATUSES:
                status_label = PETITION_WORKFLOW_STATUSES.get(petition.workflow_status, petition.workflow_status)
                unlock_hint = (
                    'Um administrador deve aprová-la ou devolvê-la para ajustes.'
                    if petition.workflow_status == 'awaiting_approval'
                    else 'Um administrador pode reabri-la para ajustes.'
                )
                return jsonify({
                    'error': f'Esta petição está "{status_label}" e não aceita nova revisão. {unlock_hint}'
                }), 403


            # Salvar arquivo principal
            upload_dir = _create_upload_directory(law_firm_id, 'revisions')
            filename = secure_filename(main_file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = upload_dir / filename
            main_file.save(str(filepath))
            
            # Processar documentos auxiliares
            auxiliary_count = 0
            auxiliary_files = []
            if 'auxiliary_documents' in request.files:
                files = request.files.getlist('auxiliary_documents')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, ALLOWED_AUXILIARY_EXTENSIONS):
                        aux_filename = secure_filename(file.filename)
                        aux_filename = timestamp + f'aux_{auxiliary_count}_' + aux_filename
                        aux_filepath = upload_dir / aux_filename
                        file.save(str(aux_filepath))
                        auxiliary_files.append({
                            'name': file.filename,
                            'path': str(aux_filepath)
                        })
                        auxiliary_count += 1

            benefits_spreadsheet = None
            if 'benefits_spreadsheet' in request.files:
                spreadsheet_file = request.files['benefits_spreadsheet']
                if spreadsheet_file and spreadsheet_file.filename:
                    if not allowed_file(spreadsheet_file.filename, ALLOWED_BENEFITS_SPREADSHEET_EXTENSIONS):
                        return jsonify({'error': 'A planilha de benefícios deve estar em formato .xlsx.'}), 400

                    spreadsheet_filename = secure_filename(spreadsheet_file.filename)
                    spreadsheet_filename = timestamp + 'benefits_' + spreadsheet_filename
                    spreadsheet_filepath = upload_dir / spreadsheet_filename
                    spreadsheet_file.save(str(spreadsheet_filepath))
                    benefits_spreadsheet = {
                        'name': spreadsheet_file.filename,
                        'path': str(spreadsheet_filepath),
                    }
            
            # Reuso de arquivos da revisão anterior (opcional, por checkbox)
            reuse_previous_auxiliary = request.form.get('reuse_previous_auxiliary') == '1'
            reuse_previous_benefits = request.form.get('reuse_previous_benefits') == '1'
            if petition and (reuse_previous_auxiliary or reuse_previous_benefits):
                previous_execution = FapReviewExecution.query.filter_by(
                    petition_id=petition.id,
                    execution_type='revision',
                ).order_by(
                    FapReviewExecution.revision_number.desc(),
                    FapReviewExecution.id.desc(),
                ).first()
                reused_aux, reused_benefits = _copy_reused_revision_files(
                    previous_execution,
                    upload_dir,
                    timestamp,
                    reuse_auxiliary=reuse_previous_auxiliary,
                    # Upload novo de planilha tem prioridade sobre o reuso
                    reuse_benefits=reuse_previous_benefits and benefits_spreadsheet is None,
                )
                for doc in reused_aux:
                    auxiliary_files.append(doc)
                    auxiliary_count += 1
                if reused_benefits:
                    benefits_spreadsheet = reused_benefits

            # Verificar se há análise comparativa
            compared_document = None
            comparative_analysis = False
            if 'compared_document' in request.files:
                compared_file = request.files['compared_document']
                if compared_file and compared_file.filename:
                    compared_extension = _get_file_extension(compared_file.filename)
                    if compared_extension == '.doc':
                        return jsonify({'error': 'Arquivos .doc não são suportados no FAP Review. Envie em PDF ou DOCX.'}), 400

                if compared_file and compared_file.filename and allowed_file(compared_file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                    compared_filename = secure_filename(compared_file.filename)
                    compared_filename = timestamp + 'compared_' + compared_filename
                    compared_filepath = upload_dir / compared_filename
                    compared_file.save(str(compared_filepath))
                    compared_document = str(compared_filepath)
                    comparative_analysis = True

            petition_created = False
            petition_created_title = ''
            if not petition:
                petition = FapReviewPetition(
                    law_firm_id=law_firm_id,
                    created_by_id=user_id,
                    office_document_identifier=law_firm_document_identifier,
                    title=_build_petition_title(
                        petition_title,
                        fallback_filename=main_file.filename,
                        fallback_identifier=law_firm_document_identifier,
                    ),
                    workflow_status='in_review',
                )
                db.session.add(petition)
                db.session.flush()
                petition_created = True
                petition_created_title = petition.title

            next_revision_number = FapReviewExecution.query.filter_by(
                petition_id=petition.id,
                execution_type='revision',
            ).count() + 1
            
            # Criar registro de execução
            execution = FapReviewExecution(
                law_firm_id=law_firm_id,
                user_id=user_id,
                petition_id=petition.id,
                execution_type='revision',
                status='processing',
                revision_number=next_revision_number,
                main_document_path=str(filepath),
                main_document_filename=main_file.filename,
                law_firm_document_identifier=law_firm_document_identifier,
                auxiliary_documents_count=auxiliary_count,
                auxiliary_documents_json=json.dumps(auxiliary_files),
                benefits_spreadsheet_json=json.dumps(benefits_spreadsheet, ensure_ascii=False) if benefits_spreadsheet else None,
                comparative_analysis=comparative_analysis,
                compared_document_path=compared_document
            )
            db.session.add(execution)
            db.session.flush()
            petition.latest_revision_id = execution.id
            petition.revision_count = max(petition.revision_count or 0, next_revision_number)
            if petition.workflow_status != 'in_review':
                petition.workflow_status = 'in_review'
                petition.status_changed_at = datetime.now()
            petition.updated_at = datetime.now()
            db.session.commit()

            if petition_created:
                _log_audit(
                    law_firm_id,
                    'petition_created',
                    'petition',
                    petition.id,
                    f'Petição criada: {petition_created_title}',
                )
            
            # Log de auditoria
            _log_audit(law_firm_id, 'revision_started', 'execution', execution.id,
                      f'Revisão iniciada: {main_file.filename}')
            
            # ===== INVOCAR AGENTE REVISOR (em segundo plano) =====
            petition_file_path = str(filepath)

            if not Path(petition_file_path).exists():
                raise ValueError("Arquivo principal não encontrado para análise")

            compared_file_path = None
            if comparative_analysis and compared_document:
                compared_file_path = compared_document
                if not Path(compared_file_path).exists():
                    raise ValueError("Arquivo comparado não encontrado para análise")

            execution_id_value = execution.id
            petition_id_value = petition.id

            _start_review_in_background(
                execution_id_value,
                law_firm_id,
                petition_file_path,
                compared_file_path,
                benefits_spreadsheet=benefits_spreadsheet,
            )

            return jsonify({
                'success': True,
                'petition_id': petition_id_value,
                'execution_id': execution_id_value,
                'message': 'Revisão iniciada com sucesso'
            })
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao processar upload: {e}")
            return jsonify({'error': str(e)}), 500
    
    # GET - Exibir página
    setting = _get_fap_setting(law_firm_id)
    petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
    ).order_by(
        FapReviewPetition.updated_at.desc(),
        FapReviewPetition.id.desc(),
    ).all()
    selected_petition_id = request.args.get('petition_id', type=int)
    selected_petition = None
    if selected_petition_id:
        selected_petition = FapReviewPetition.query.filter_by(
            id=selected_petition_id,
            law_firm_id=law_firm_id,
        ).first()

    return render_template(
        'fap_review/revision.html',
        setting=setting,
        petitions=petitions,
        selected_petition=selected_petition,
        petition_status_labels=PETITION_WORKFLOW_STATUSES,
    )


@fap_review_bp.route('/revision/<int:execution_id>', methods=['GET'])
@require_law_firm
def revision_result(execution_id: int):
    """Exibe resultado de uma revisão"""
    law_firm_id = get_current_law_firm_id()
    
    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    # Watchdog: a revisão roda em thread; se o processo web for reiniciado no
    # meio, a execução ficaria presa em "processando" para sempre.
    if _svc.is_execution_stuck(execution):
        execution.status = 'failed'
        execution.error_message = ('Processamento interrompido (tempo excedido — provável reinício '
                                   'do servidor). Envie a revisão novamente.')
        execution.completed_at = datetime.now()
        _sync_petition_after_revision(execution)
        db.session.commit()

    petition = execution.petition
    document_identifier = (
        petition.office_document_identifier
        if petition and petition.office_document_identifier
        else execution.law_firm_document_identifier
    )
    
    result_data = {}
    if execution.result_json:
        try:
            result_data = json.loads(execution.result_json)
        except json.JSONDecodeError:
            result_data = {}

    used_versions = {}
    if execution.used_versions_json:
        try:
            used_versions = json.loads(execution.used_versions_json)
        except (TypeError, json.JSONDecodeError):
            used_versions = {}

    ignored_finding_indices: list[int] = []
    if document_identifier and result_data.get('findings'):
        ignored_fingerprints = _get_ignored_finding_fingerprints(
            law_firm_id=law_firm_id,
            law_firm_document_identifier=document_identifier,
        )
        ignored_finding_indices = [
            index
            for index, finding in enumerate(result_data.get('findings') or [], start=1)
            if _build_finding_fingerprint(finding) in ignored_fingerprints
        ]

    prior_revision_count = 0
    if execution.petition_id:
        prior_revision_count = FapReviewExecution.query.filter(
            FapReviewExecution.law_firm_id == law_firm_id,
            FapReviewExecution.execution_type == 'revision',
            FapReviewExecution.petition_id == execution.petition_id,
            FapReviewExecution.id != execution.id,
        ).count()
    elif execution.law_firm_document_identifier:
        prior_revision_count = FapReviewExecution.query.filter(
            FapReviewExecution.law_firm_id == law_firm_id,
            FapReviewExecution.execution_type == 'revision',
            FapReviewExecution.law_firm_document_identifier == execution.law_firm_document_identifier,
            FapReviewExecution.id != execution.id,
        ).count()

    manual_reference = _get_active_reference(law_firm_id, 'manual_fap')
    manual_content = (manual_reference.content if manual_reference else '').strip()

    checked_finding_indices = sorted(
        row.finding_index
        for row in FapReviewFindingCheck.query.filter_by(execution_id=execution.id).all()
    )
    total_findings = len(result_data.get('findings') or [])
    triage_complete = _svc.is_triage_complete(
        total_findings,
        set(checked_finding_indices),
        set(ignored_finding_indices),
    )

    execution_superseded = _svc.is_execution_superseded(execution)

    execution_files = _list_execution_files(execution)
    # Primeira ocorrência vence em caso de nomes duplicados (reversed => menor índice prevalece)
    aux_links_by_name = {
        aux['name']: url_for('fap_review.revision_auxiliary_document',
                             execution_id=execution.id, doc_index=aux['index'])
        for aux in reversed(execution_files['aux'])
    }

    return render_template('fap_review/revision_result.html',
                          execution=execution,
                          model_label=_svc.describe_model_name(execution.model_name),
                          sanitizer_discards=(result_data or {}).get('sanitizer_discards') or [],
                          petition=petition,
                          petition_status_badge=_build_petition_status_badge(petition.workflow_status) if petition else None,
                          result_data=result_data,
                          used_versions=used_versions,
                          prior_revision_count=prior_revision_count,
                          ignored_finding_indices=ignored_finding_indices,
                          checked_finding_indices=checked_finding_indices,
                          triage_complete=triage_complete,
                          execution_superseded=execution_superseded,
                          execution_files=execution_files,
                          aux_links_by_name=aux_links_by_name,
                          manual_content=manual_content,
                          manual_reference=manual_reference)


@fap_review_bp.route('/petitions/<int:petition_id>', methods=['GET'])
@require_law_firm
def petition_detail(petition_id: int):
    """Exibe o histórico agregado de revisões de uma petição."""
    law_firm_id = get_current_law_firm_id()

    petition = FapReviewPetition.query.filter_by(
        id=petition_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    revisions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        petition_id=petition.id,
        execution_type='revision',
    ).order_by(
        FapReviewExecution.created_at.desc(),
        FapReviewExecution.id.desc(),
    ).all()

    revision_summary = {
        'completed': sum(1 for revision in revisions if revision.status == 'completed'),
        'processing': sum(1 for revision in revisions if revision.status == 'processing'),
        'failed': sum(1 for revision in revisions if revision.status == 'failed'),
        'comparative': sum(1 for revision in revisions if revision.comparative_analysis),
        'latest_completed_at': next(
            (
                revision.completed_at or revision.updated_at or revision.created_at
                for revision in revisions
                if revision.status == 'completed'
            ),
            None,
        ),
    }

    execution_ids = [revision.id for revision in revisions]
    audit_filters = [and_(
        FapReviewAuditLog.entity_type == 'petition',
        FapReviewAuditLog.entity_id == petition.id,
    )]
    if execution_ids:
        audit_filters.append(and_(
            FapReviewAuditLog.entity_type == 'execution',
            FapReviewAuditLog.entity_id.in_(execution_ids),
        ))
    audit_entries = FapReviewAuditLog.query.filter(
        FapReviewAuditLog.law_firm_id == law_firm_id,
        or_(*audit_filters),
    ).order_by(
        FapReviewAuditLog.created_at.desc(),
        FapReviewAuditLog.id.desc(),
    ).limit(50).all()

    latest_executive_summary = None
    latest = petition.latest_revision
    if latest and latest.status == 'completed':
        summary = _load_execution_result_payload(latest).get('executive_summary')
        if isinstance(summary, dict):
            latest_executive_summary = summary

    revision_files = {revision.id: _list_execution_files(revision) for revision in revisions}

    return render_template(
        'fap_review/petition_detail.html',
        petition=petition,
        revisions=revisions,
        revision_files=revision_files,
        revision_summary=revision_summary,
        latest_executive_summary=latest_executive_summary,
        audit_entries=audit_entries,
        status_badge=_build_petition_status_badge(petition.workflow_status),
        petition_status_labels=PETITION_WORKFLOW_STATUSES,
    )


@fap_review_bp.route('/petitions/<int:petition_id>/update', methods=['POST'])
@require_law_firm
def petition_update_details(petition_id: int):
    """Permite editar os principais campos cadastrais da petição."""
    law_firm_id = get_current_law_firm_id()

    petition = FapReviewPetition.query.filter_by(
        id=petition_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    payload = request.get_json(silent=True) or {}
    new_title = ' '.join(str(payload.get('title') or '').split())
    new_identifier = ' '.join(str(payload.get('office_document_identifier') or '').split())

    if not new_title:
        return jsonify({'error': 'Informe o título da petição.'}), 400
    if len(new_title) > 255:
        return jsonify({'error': 'O título da petição pode ter no máximo 255 caracteres.'}), 400

    # Formato só é cobrado quando o Id muda: petição antiga pode ter identificador
    # não numérico, e exigi-lo aqui travaria uma edição de título que não tem
    # nada a ver com isso. Id novo ou alterado passa pela regra cheia.
    if new_identifier != petition.office_document_identifier:
        new_identifier, identifier_error = _svc.validate_wrike_identifier(new_identifier)
        if identifier_error:
            return jsonify({'error': identifier_error}), 400
    elif not new_identifier:
        return jsonify({'error': 'Informe o Id Wrike da petição.'}), 400

    duplicated_petition = FapReviewPetition.query.filter(
        FapReviewPetition.law_firm_id == law_firm_id,
        FapReviewPetition.office_document_identifier == new_identifier,
        FapReviewPetition.id != petition.id,
    ).first()
    if duplicated_petition:
        return jsonify({'error': 'Já existe outra petição com este Id Wrike.'}), 400

    old_title = petition.title
    old_identifier = petition.office_document_identifier

    if new_title == old_title and new_identifier == old_identifier:
        return jsonify({
            'success': True,
            'petition': {
                'title': petition.title,
                'office_document_identifier': petition.office_document_identifier,
            },
        })

    try:
        petition.title = new_title
        petition.office_document_identifier = new_identifier
        petition.updated_at = datetime.now()

        if new_identifier != old_identifier:
            _propagate_petition_identifier_change(
                law_firm_id=law_firm_id,
                petition=petition,
                old_identifier=old_identifier,
                new_identifier=new_identifier,
            )

        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao atualizar dados da petição: {error}')
        return jsonify({'error': 'Não foi possível atualizar os dados da petição.'}), 500

    _log_audit(
        law_firm_id,
        'petition_updated',
        'petition',
        petition.id,
        'Campos principais da petição atualizados.',
        old_value=json.dumps({'title': old_title, 'office_document_identifier': old_identifier}, ensure_ascii=False),
        new_value=json.dumps({'title': petition.title, 'office_document_identifier': petition.office_document_identifier}, ensure_ascii=False),
    )

    return jsonify({
        'success': True,
        'petition': {
            'title': petition.title,
            'office_document_identifier': petition.office_document_identifier,
        },
    })


@fap_review_bp.route('/petitions/<int:petition_id>/reusable-files', methods=['GET'])
@require_law_firm
def petition_reusable_files(petition_id: int):
    """Arquivos da última revisão da petição reutilizáveis num novo envio (formulário)."""
    law_firm_id = get_current_law_firm_id()

    petition = FapReviewPetition.query.filter_by(
        id=petition_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    previous = FapReviewExecution.query.filter_by(
        petition_id=petition.id,
        execution_type='revision',
    ).order_by(
        FapReviewExecution.revision_number.desc(),
        FapReviewExecution.id.desc(),
    ).first()

    auxiliary_names: list[str] = []
    benefits_name = None
    if previous:
        try:
            prior_docs = json.loads(previous.auxiliary_documents_json or '[]')
        except (TypeError, json.JSONDecodeError):
            prior_docs = []
        auxiliary_names = [
            str(doc.get('name') or Path(str(doc['path'])).name)
            for doc in (prior_docs if isinstance(prior_docs, list) else [])
            if isinstance(doc, dict) and doc.get('path') and Path(str(doc['path'])).is_file()
        ]
        prior_benefits = _load_execution_benefits_spreadsheet(previous)
        if prior_benefits and Path(str(prior_benefits['path'])).is_file():
            benefits_name = str(prior_benefits.get('name') or Path(str(prior_benefits['path'])).name)

    return jsonify({
        'auxiliary_documents': auxiliary_names,
        'benefits_spreadsheet': benefits_name,
    })


@fap_review_bp.route('/petitions/<int:petition_id>/revisions-summary', methods=['GET'])
@require_law_firm
def petition_revisions_summary(petition_id: int):
    """Resumo compacto das revisões anteriores da petição (coluna lateral do envio)."""
    law_firm_id = get_current_law_firm_id()

    petition = FapReviewPetition.query.filter_by(
        id=petition_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    executions = FapReviewExecution.query.options(
        joinedload(FapReviewExecution.user),
    ).filter_by(
        petition_id=petition.id,
        execution_type='revision',
    ).order_by(
        FapReviewExecution.revision_number.desc(),
        FapReviewExecution.id.desc(),
    ).limit(5).all()

    items = []
    for execution in executions:
        payload = _load_execution_result_payload(execution)
        summary = payload.get('executive_summary') or {}
        benefits_review = payload.get('benefits_spreadsheet_review') or {}

        benefits = None
        if benefits_review.get('total_rows_with_theses'):
            benefits = {
                'found': benefits_review.get('found_count', 0),
                'total': benefits_review.get('total_rows_with_theses', 0),
            }

        items.append({
            'execution_id': execution.id,
            'revision_number': execution.revision_number,
            'status': execution.status,
            'superseded': _svc.is_execution_superseded(execution),
            'user_name': execution.user.name if execution.user else None,
            'created_at': execution.created_at.strftime('%d/%m/%Y %H:%M') if execution.created_at else None,
            'findings': {
                'total': summary.get('total_findings', 0),
                'critical': summary.get('critical_findings', 0),
                'moderate': summary.get('moderate_findings', 0),
                'formal': summary.get('formal_findings', 0),
            } if execution.status == 'completed' else None,
            'benefits': benefits,
            'url': url_for('fap_review.revision_result', execution_id=execution.id),
        })

    return jsonify({'revisions': items})


@fap_review_bp.route('/petitions/<int:petition_id>/status', methods=['POST'])
@require_law_firm
def petition_update_status(petition_id: int):
    """Permite controle manual do status agregado da petição."""
    law_firm_id = get_current_law_firm_id()

    petition = FapReviewPetition.query.filter_by(
        id=petition_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    payload = request.get_json(silent=True) or {}
    new_status = str(payload.get('workflow_status') or '').strip()
    if new_status not in PETITION_WORKFLOW_STATUSES:
        return jsonify({'error': 'Status da petição inválido.'}), 400

    old_status = petition.workflow_status
    if new_status == old_status:
        return jsonify({'success': True, 'workflow_status': new_status})

    # Aprovar, devolver para ajustes e reabrir são exclusivos do admin (regra
    # espelhada dos botões da tela).
    if _svc.status_transition_requires_admin(old_status, new_status) and session.get('user_role') != 'admin':
        return jsonify({'error': 'Apenas administradores podem executar esta mudança de status.'}), 403

    try:
        petition.workflow_status = new_status
        petition.status_changed_at = datetime.now()
        petition.updated_at = datetime.now()
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao atualizar status da petição: {error}')
        return jsonify({'error': 'Não foi possível atualizar o status da petição.'}), 500

    _log_audit(
        law_firm_id,
        'petition_status_updated',
        'petition',
        petition.id,
        f'Status alterado de {PETITION_WORKFLOW_STATUSES.get(old_status, old_status)} para {PETITION_WORKFLOW_STATUSES.get(new_status, new_status)}',
        old_value=old_status,
        new_value=new_status,
    )

    return jsonify({'success': True, 'workflow_status': new_status})


@fap_review_bp.route('/lawyer-stats', methods=['GET'])
@require_law_firm
@require_admin_user
def lawyer_stats():
    """Exibe score e histórico de qualidade das revisões por advogado."""
    law_firm_id = get_current_law_firm_id()
    score_data = _build_lawyer_statistics(law_firm_id)

    return render_template(
        'fap_review/lawyer_stats.html',
        overview=score_data['overview'],
        lawyers=score_data['lawyers'],
    )


def _get_execution_triage_state(execution, law_firm_id: int) -> dict:
    """Estado consolidado da triagem de uma execução (fonte para tela e endpoints)."""
    payload = _load_execution_result_payload(execution)
    findings = payload.get('findings') or []
    total_findings = len(findings) if isinstance(findings, list) else 0

    checked_indices = {
        row.finding_index
        for row in FapReviewFindingCheck.query.filter_by(execution_id=execution.id).all()
    }

    ignored_indices: set[int] = set()
    if execution.law_firm_document_identifier and total_findings:
        ignored_fingerprints = _get_ignored_finding_fingerprints(
            law_firm_id=law_firm_id,
            law_firm_document_identifier=execution.law_firm_document_identifier,
        )
        ignored_indices = {
            index
            for index, finding in enumerate(findings, start=1)
            if _build_finding_fingerprint(finding) in ignored_fingerprints
        }

    return {
        'total_findings': total_findings,
        'checked_indices': checked_indices,
        'ignored_indices': ignored_indices,
        'complete': _svc.is_triage_complete(total_findings, checked_indices, ignored_indices),
    }


@fap_review_bp.route('/revision/<int:execution_id>/findings/<int:finding_index>/check', methods=['POST'])
@require_law_firm
def revision_finding_check(execution_id: int, finding_index: int):
    """Persiste o "Marcar como revisado" de um ponto de atenção (triagem por execução)."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    if _svc.is_execution_superseded(execution):
        return jsonify({'error': 'Esta revisão foi substituída por uma versão mais recente — triagem encerrada.'}), 409

    payload = _load_execution_result_payload(execution)
    findings = payload.get('findings') or []
    if finding_index < 1 or finding_index > len(findings):
        return jsonify({'error': 'Ponto de atenção não encontrado nesta revisão.'}), 404

    request_payload = request.get_json(silent=True) or {}
    checked = bool(request_payload.get('checked'))

    existing = FapReviewFindingCheck.query.filter_by(
        execution_id=execution.id,
        finding_index=finding_index,
    ).first()

    try:
        if checked and not existing:
            db.session.add(FapReviewFindingCheck(
                law_firm_id=law_firm_id,
                execution_id=execution.id,
                finding_index=finding_index,
                created_by_id=user_id,
            ))
        elif not checked and existing:
            db.session.delete(existing)

        # Triar achados significa que o usuário está revisando a petição
        _svc.mark_petition_in_user_review(execution.petition)

        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao persistir check do ponto de atenção: {error}')
        return jsonify({'error': 'Não foi possível salvar a marcação do ponto de atenção.'}), 500

    triage = _get_execution_triage_state(execution, law_firm_id)
    return jsonify({
        'success': True,
        'checked': checked,
        'triage_complete': triage['complete'],
        'petition_workflow_status': execution.petition.workflow_status if execution.petition else None,
    })


@fap_review_bp.route('/revision/<int:execution_id>/findings/check-all', methods=['POST'])
@require_law_firm
def revision_finding_check_all(execution_id: int):
    """Marca como revisados todos os pontos ainda não triados da execução."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    if _svc.is_execution_superseded(execution):
        return jsonify({'error': 'Esta revisão foi substituída por uma versão mais recente — triagem encerrada.'}), 409

    triage = _get_execution_triage_state(execution, law_firm_id)
    if not triage['total_findings']:
        return jsonify({'error': 'Esta revisão não tem pontos de atenção para triar.'}), 400

    to_check = [
        index for index in range(1, triage['total_findings'] + 1)
        if index not in triage['checked_indices'] and index not in triage['ignored_indices']
    ]

    try:
        for index in to_check:
            db.session.add(FapReviewFindingCheck(
                law_firm_id=law_firm_id,
                execution_id=execution.id,
                finding_index=index,
                created_by_id=user_id,
            ))

        _svc.mark_petition_in_user_review(execution.petition)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao marcar todos os pontos como revisados: {error}')
        return jsonify({'error': 'Não foi possível marcar todos os pontos como revisados.'}), 500

    if to_check:
        try:
            _log_audit(
                law_firm_id,
                'revision_findings_checked_all',
                'execution',
                execution.id,
                f'{len(to_check)} ponto(s) de atenção marcados como revisados em lote',
            )
        except Exception as audit_error:
            current_app.logger.warning(f'Marcação em lote salva, mas falha na auditoria: {audit_error}')

    triage = _get_execution_triage_state(execution, law_firm_id)
    return jsonify({
        'success': True,
        'checked_indices': sorted(triage['checked_indices']),
        'newly_checked': to_check,
        'triage_complete': triage['complete'],
        'petition_workflow_status': execution.petition.workflow_status if execution.petition else None,
    })


@fap_review_bp.route('/revision/<int:execution_id>/complete-triage', methods=['POST'])
@require_law_firm
def revision_complete_triage(execution_id: int):
    """Conclui a triagem: usuário decide entre nova versão ou versão final para aprovação."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    petition = execution.petition
    if not petition:
        return jsonify({'error': 'Esta revisão não está vinculada a uma petição.'}), 400

    if _svc.is_execution_superseded(execution):
        return jsonify({'error': 'Esta revisão foi substituída por uma versão mais recente — conclua a triagem na revisão atual.'}), 409

    request_payload = request.get_json(silent=True) or {}
    outcome = str(request_payload.get('outcome') or '').strip()
    new_status = _svc.TRIAGE_OUTCOME_STATUSES.get(outcome)
    if not new_status:
        return jsonify({'error': 'Desfecho de triagem inválido.'}), 400

    if petition.workflow_status in _svc.NEW_REVISION_BLOCKED_STATUSES:
        return jsonify({'error': 'Esta petição está travada para triagem. Um administrador pode reabri-la.'}), 403

    # Gate no servidor: não confia no estado renderizado na tela
    triage = _get_execution_triage_state(execution, law_firm_id)
    if not triage['complete']:
        pending = triage['total_findings'] - len(
            (triage['checked_indices'] | triage['ignored_indices'])
            & set(range(1, triage['total_findings'] + 1))
        )
        return jsonify({
            'error': f'Ainda há {pending} ponto(s) de atenção sem triagem. '
                     'Marque cada um como revisado ou não pertinente antes de concluir.'
        }), 400

    old_status = petition.workflow_status
    try:
        if petition.workflow_status != new_status:
            petition.workflow_status = new_status
            petition.status_changed_at = datetime.now()
            petition.updated_at = datetime.now()
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao concluir triagem da execução {execution_id}: {error}')
        return jsonify({'error': 'Não foi possível concluir a triagem.'}), 500

    outcome_labels = {
        'new_version': 'Triagem concluída: usuário vai enviar nova versão',
        'final_version': 'Triagem concluída: versão final aguardando aprovação do revisor',
    }
    _log_audit(
        law_firm_id,
        'revision_triage_completed',
        'petition',
        petition.id,
        outcome_labels[outcome],
        old_value=old_status,
        new_value=new_status,
    )

    redirect_url = None
    if outcome == 'new_version':
        redirect_url = url_for('fap_review.revision', petition_id=petition.id)

    return jsonify({
        'success': True,
        'workflow_status': new_status,
        'redirect_url': redirect_url,
    })


@fap_review_bp.route('/revision/<int:execution_id>/findings/<int:finding_index>/dismiss-feedback', methods=['POST'])
@require_law_firm
def revision_finding_feedback(execution_id: int, finding_index: int):
    """Persiste feedback de ponto marcado como não útil para futuras revisões do mesmo documento."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    if not execution.law_firm_document_identifier:
        return jsonify({'error': 'Esta revisão não possui identificador de documento para persistir feedback.'}), 400

    if _svc.is_execution_superseded(execution):
        return jsonify({'error': 'Esta revisão foi substituída por uma versão mais recente — use a revisão atual.'}), 409

    try:
        payload = json.loads(execution.result_json or '{}')
    except json.JSONDecodeError:
        return jsonify({'error': 'Resultado da revisão inválido para registrar feedback.'}), 400

    findings = payload.get('findings') or []
    if finding_index < 1 or finding_index > len(findings):
        return jsonify({'error': 'Ponto de atenção não encontrado nesta revisão.'}), 404

    finding = findings[finding_index - 1]
    finding_fingerprint = _build_finding_fingerprint(finding)
    if not finding_fingerprint:
        return jsonify({'error': 'Não foi possível identificar o ponto de atenção selecionado.'}), 400

    request_payload = request.get_json(silent=True) or {}
    dismissed = bool(request_payload.get('dismissed'))

    existing_feedback = FapReviewIgnoredFinding.query.filter_by(
        law_firm_id=law_firm_id,
        law_firm_document_identifier=execution.law_firm_document_identifier,
        finding_fingerprint=finding_fingerprint,
    ).first()

    description = str(finding.get('description') or '').strip()
    audit_action = None
    audit_description = None

    try:
        if dismissed:
            if not existing_feedback:
                db.session.add(FapReviewIgnoredFinding(
                    law_firm_id=law_firm_id,
                    law_firm_document_identifier=execution.law_firm_document_identifier,
                    source_execution_id=execution.id,
                    created_by_id=user_id,
                    finding_fingerprint=finding_fingerprint,
                    finding_description=description,
                ))
            audit_action = 'revision_finding_dismissed'
            audit_description = f'Ponto marcado como não útil: {description[:200]}'
        elif existing_feedback:
            db.session.delete(existing_feedback)
            audit_action = 'revision_finding_dismiss_undone'
            audit_description = f'Ponto voltou a ser considerado no histórico: {description[:200]}'

        # Triar achados significa que o usuário está revisando a petição
        petition_status_changed = _svc.mark_petition_in_user_review(execution.petition)

        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f'Erro ao persistir feedback do ponto de atenção: {error}')
        return jsonify({'error': 'Não foi possível salvar o feedback do ponto de atenção.'}), 500

    try:
        if audit_action and audit_description:
            _log_audit(
                law_firm_id,
                audit_action,
                'execution',
                execution.id,
                audit_description,
            )
        if petition_status_changed:
            _log_audit(
                law_firm_id,
                'petition_status_updated',
                'petition',
                execution.petition.id,
                'Status alterado para Em revisão ao triar pontos de atenção',
                new_value='in_review',
            )
    except Exception as audit_error:
        current_app.logger.warning(f'Feedback salvo, mas falha ao registrar auditoria: {audit_error}')

    return jsonify({
        'success': True,
        'dismissed': dismissed,
        'petition_workflow_status': execution.petition.workflow_status if execution.petition else None,
    })


@fap_review_bp.route('/revision/<int:execution_id>/status', methods=['GET'])
@require_law_firm
def revision_status(execution_id: int):
    """Status da execução para o acompanhamento no formulário (revisão em background)."""
    law_firm_id = get_current_law_firm_id()
    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()
    return jsonify({
        'status': execution.status,
        'error_message': execution.error_message,
    })


@fap_review_bp.route('/revision/<int:execution_id>/reprocess', methods=['POST'])
@require_law_firm
def reprocess_revision(execution_id: int):
    """Reexecuta uma revisão que falhou reaproveitando os arquivos já enviados.

    Grava na MESMA execução: `revision_number` é a versão da petição revisada,
    não a tentativa de processamento — uma falha técnica não é uma revisão nova.
    Os arquivos não são copiados; a execução já aponta para eles.
    """
    law_firm_id = get_current_law_firm_id()
    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    block_reason = _svc.describe_reprocess_block(execution)
    if block_reason:
        return jsonify({'error': block_reason}), 409

    petition_file_path = execution.main_document_path
    if not petition_file_path or not Path(petition_file_path).is_file():
        return jsonify({
            'error': 'O arquivo original desta revisão não está mais no servidor. '
                     'Envie a petição novamente pela tela de Nova Revisão.'
        }), 422

    # Anexo ou planilha ausente não impede a revisão — só o documento principal
    # é essencial. O agente lê os auxiliares da própria execução.
    compared_file_path = None
    if execution.comparative_analysis and execution.compared_document_path:
        if Path(execution.compared_document_path).is_file():
            compared_file_path = execution.compared_document_path
        else:
            logger.warning(
                'Reprocessamento da execução %s sem o documento comparado (arquivo ausente).',
                execution_id,
            )

    benefits_spreadsheet = _load_execution_benefits_spreadsheet(execution)
    if benefits_spreadsheet and not Path(str(benefits_spreadsheet['path'])).is_file():
        logger.warning(
            'Reprocessamento da execução %s sem a planilha de benefícios (arquivo ausente).',
            execution_id,
        )
        benefits_spreadsheet = None

    # Guardado antes do reset: a execução é sobrescrita e o erro se perderia.
    previous_error = (execution.error_message or 'sem mensagem registrada')[:200]

    _svc.reset_execution_for_reprocess(execution)
    # O agente carrega as referências ATIVAS, então o snapshot de rastreabilidade
    # tem de refletir as versões desta execução, não as da tentativa que falhou.
    execution.used_versions_json = json.dumps(
        _svc.collect_active_versions(law_firm_id), ensure_ascii=False)
    _sync_petition_after_revision(execution)
    db.session.commit()

    _log_audit(
        law_firm_id,
        'revision_reprocessed',
        'execution',
        execution.id,
        f'Reprocessamento solicitado. Erro anterior: {previous_error}',
        user_id=session.get('user_id'),
    )

    _start_review_in_background(
        execution.id,
        law_firm_id,
        petition_file_path,
        compared_file_path,
        benefits_spreadsheet=benefits_spreadsheet,
    )

    return jsonify({
        'success': True,
        'execution_id': execution.id,
        'message': 'Reprocessamento iniciado com os mesmos arquivos.',
    })


@fap_review_bp.route('/revision/<int:execution_id>/document/main', methods=['GET'])
@require_law_firm
def revision_main_document(execution_id: int):
    """Abre o documento principal salvo da execução de revisão."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    file_path = str(execution.main_document_path or '').strip()
    if not file_path:
        flash('Documento principal não disponível para esta execução.', 'warning')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        flash('Arquivo da revisão não foi encontrado no armazenamento.', 'error')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    return send_file(
        path,
        # ?baixar=1 força download; sem o parâmetro, o navegador renderiza inline
        # o que souber (PDF) e baixa o restante (DOCX)
        as_attachment=bool(request.args.get('baixar')),
        download_name=execution.main_document_filename or path.name,
    )


@fap_review_bp.route('/revision/<int:execution_id>/document/main/preview', methods=['GET'])
@require_law_firm
def revision_main_document_preview(execution_id: int):
    """Preview HTML do documento principal DOCX (o navegador não renderiza DOCX nativamente)."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    file_path = str(execution.main_document_path or '').strip()
    path = Path(file_path)
    if not file_path or not path.exists() or not path.is_file():
        flash('Documento principal não disponível para esta execução.', 'warning')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    if path.suffix.lower() != '.docx':
        return redirect(url_for('fap_review.revision_main_document', execution_id=execution_id))

    try:
        content_html = render_docx_preview_html(path)
    except ValueError as e:
        current_app.logger.warning('Falha no preview DOCX da execução %s: %s', execution_id, e)
        content_html = None

    return render_template(
        'fap_review/document_preview.html',
        content_html=content_html,
        document_filename=execution.main_document_filename or path.name,
        highlight_text=(request.args.get('destaque') or '').strip(),
        highlight_excerpt=(request.args.get('trecho') or '').strip(),
        download_url=url_for('fap_review.revision_main_document', execution_id=execution_id),
    )


def _send_execution_file(execution_id: int, file_path: str, download_name: str, missing_message: str):
    """Entrega um arquivo salvo de uma execução, com fallback amigável quando sumiu do disco."""
    normalized = str(file_path or '').strip()
    path = Path(normalized) if normalized else None
    if not path or not path.exists() or not path.is_file():
        flash(missing_message, 'error')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    return send_file(
        path,
        # ?baixar=1 força download; sem o parâmetro, o navegador renderiza inline o que souber
        as_attachment=bool(request.args.get('baixar')),
        download_name=download_name or path.name,
    )


@fap_review_bp.route('/revision/<int:execution_id>/document/aux/<int:doc_index>', methods=['GET'])
@require_law_firm
def revision_auxiliary_document(execution_id: int, doc_index: int):
    """Abre/baixa um documento auxiliar salvo da execução de revisão."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    try:
        aux_docs = json.loads(execution.auxiliary_documents_json or '[]')
    except (TypeError, json.JSONDecodeError):
        aux_docs = []

    doc = aux_docs[doc_index] if 0 <= doc_index < len(aux_docs) and isinstance(aux_docs[doc_index], dict) else {}
    if not doc.get('path'):
        flash('Documento auxiliar não encontrado nesta execução.', 'warning')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    return _send_execution_file(
        execution_id,
        str(doc['path']),
        str(doc.get('name') or ''),
        'Arquivo auxiliar não foi encontrado no armazenamento.',
    )


@fap_review_bp.route('/revision/<int:execution_id>/document/spreadsheet', methods=['GET'])
@require_law_firm
def revision_benefits_spreadsheet_file(execution_id: int):
    """Abre/baixa a planilha de benefícios usada na execução de revisão."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    spreadsheet = _load_execution_benefits_spreadsheet(execution)
    if not spreadsheet:
        flash('Planilha de benefícios não disponível para esta execução.', 'warning')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    return _send_execution_file(
        execution_id,
        str(spreadsheet['path']),
        str(spreadsheet.get('name') or ''),
        'Planilha de benefícios não foi encontrada no armazenamento.',
    )


@fap_review_bp.route('/revision/<int:execution_id>/document/compared', methods=['GET'])
@require_law_firm
def revision_compared_document(execution_id: int):
    """Abre/baixa a segunda versão (documento comparado) da execução de revisão."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    compared_path = str(execution.compared_document_path or '').strip()
    if not compared_path:
        flash('Documento comparado não disponível para esta execução.', 'warning')
        return redirect(url_for('fap_review.revision_result', execution_id=execution_id))

    return _send_execution_file(
        execution_id,
        compared_path,
        Path(compared_path).name,
        'Documento comparado não foi encontrado no armazenamento.',
    )


def _load_training_payload(execution) -> dict:
    """Payload da comparação de treinamento, tolerante a JSON corrompido."""
    if not execution.result_json:
        return {}
    try:
        return json.loads(execution.result_json)
    except (TypeError, json.JSONDecodeError):
        return {}


def _training_documents_label(execution, payload: dict | None = None) -> str:
    """Os dois arquivos comparados, como a listagem os identifica."""
    source_files = (payload or {}).get('source_files') or {}
    original = source_files.get('original_filename') or execution.main_document_filename or '—'
    revised = source_files.get('revised_filename') or ''
    return f'{original} → {revised}' if revised else original


def _validate_training_uploads(original_file, revised_file) -> str | None:
    """Motivo pelo qual os arquivos não servem; None quando servem."""
    if (not original_file or not original_file.filename
            or not revised_file or not revised_file.filename):
        return ('Envie os dois documentos: como o advogado enviou e como ficou '
                'depois da revisão.')

    for label, upload in (('enviado pelo advogado', original_file),
                          ('revisado', revised_file)):
        if _get_file_extension(upload.filename) == '.doc':
            return (f'O documento {label} está em .doc, que o Revisor não lê. '
                    'Envie em PDF ou DOCX.')
        if not allowed_file(upload.filename, ALLOWED_DOCUMENT_EXTENSIONS):
            return (f'O documento {label} tem extensão não permitida. '
                    'Envie em PDF ou DOCX.')

    return None


def _get_active_prompt_content(law_firm_id: int, prompt_type: str) -> str:
    """Conteúdo do prompt ativo de um tipo (vazio quando não configurado)."""
    prompt = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
        is_active=True,
    ).first()
    return prompt.content if prompt else ''


def _current_reference_versions(law_firm_id: int) -> dict[str, int]:
    """``version_number`` da referência ativa de cada destino do treinamento."""
    versions = {}
    for target in _svc.TRAINING_TARGETS:
        reference = _get_active_reference(law_firm_id, target['key'])
        versions[target['key']] = reference.version_number if reference else 0
    return versions


def _strip_pattern_indices(patterns: list[dict]) -> list[dict]:
    """Tira os índices antes de gravar: eles serviram à reconciliação e a tela
    não os usa. ``result_json`` é TEXT (64 KB no MySQL) e o payload já carrega
    os exemplos literais de cada padrão."""
    return [
        {chave: valor for chave, valor in pattern.items() if chave != 'indices'}
        for pattern in patterns
    ]


def _launch_training_comparison(execution_id: int, law_firm_id: int) -> None:
    """Roda a comparação fora da requisição.

    A chamada de LLM leva mais que o timeout padrão do gunicorn (30s) e antes
    rodava dentro do POST: estourar o teto matava o worker no meio do
    treinamento. Mesmo desenho da revisão.
    """
    app_obj = current_app._get_current_object()

    def _run_training_in_background():
        with app_obj.app_context():
            try:
                _execute_training_comparison(execution_id, law_firm_id)
            except Exception as agent_error:
                app_obj.logger.error(f"Erro na comparação de treinamento: {agent_error}")
                try:
                    background_execution = FapReviewExecution.query.get(execution_id)
                    if background_execution and background_execution.status == 'processing':
                        background_execution.status = 'failed'
                        background_execution.error_message = str(agent_error)
                        background_execution.completed_at = datetime.now()
                        db.session.commit()
                except Exception:
                    db.session.rollback()
            finally:
                db.session.remove()

    threading.Thread(
        target=_run_training_in_background,
        daemon=True,
        name=f'fap-training-{execution_id}',
    ).start()


def _execute_training_comparison(execution_id: int, law_firm_id: int) -> None:
    """Compara os documentos e deixa a execução aguardando confirmação humana."""
    execution = FapReviewExecution.query.get(execution_id)
    if not execution:
        raise ValueError(f"Execução {execution_id} não encontrada")

    setting = _get_fap_setting(law_firm_id)
    payload = _load_training_payload(execution)
    source_files = payload.get('source_files') or {}

    original_text = _extract_text_from_document(
        source_files.get('original_path') or execution.main_document_path)
    revised_text = _extract_text_from_document(
        source_files.get('revised_path') or execution.compared_document_path)

    # PDF digitalizado (imagem, sem camada de texto) não extrai nada. Sem esta
    # parada, a comparação seguia com string vazia e a prévia chegava com as
    # caixas em branco, sem dizer por quê — parecendo que a correção não tinha
    # nada a ensinar.
    if not original_text.strip() or not revised_text.strip():
        ilegiveis = ' e '.join(
            label for label, texto in (
                ('do documento enviado pelo advogado', original_text),
                ('do documento revisado', revised_text),
            ) if not texto.strip()
        )
        raise ValueError(
            f'Não foi possível ler o texto {ilegiveis}. '
            'Documento digitalizado (imagem) não serve para treinamento — '
            'envie o arquivo com texto selecionável.'
        )

    # Etapa 1 — as diferenças, sem IA. `difflib` compara duas versões do mesmo
    # documento de forma exata e em 87ms; o modelo, recebendo os documentos
    # inteiros, resumia como "padronização terminológica" e omitia o
    # placeholder "R$ XXX" que o advogado esqueceu de preencher.
    changes = _diff_svc.extract_changes(original_text, revised_text)
    changes_summary = _diff_svc.summarize_changes(changes)

    if not changes:
        raise ValueError(
            'Os dois documentos são idênticos — não há revisão para aprender. '
            'Confira se enviou a versão do advogado e a versão revisada.'
        )

    api_key = os.getenv('OPENAI_API_KEY')
    model = setting.training_model
    temperature = min(max(setting.training_temperature, 0.0), 1.0)

    # Agrupar é tarefa mecânica: temperatura zero, como no revisor. A
    # temperatura configurada vale para a etapa que escreve texto novo.
    grouper = FapTrainingDiffGrouperAgent(openai_api_key=api_key, model=model, temperature=0.0)
    proposer = FapTrainingApplySubAgent(openai_api_key=api_key, model=model, temperature=temperature)

    manual_reference = _get_active_reference(law_firm_id, 'manual_fap')
    cases_reference = _get_active_reference(law_firm_id, 'casos_referencia')

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Etapa 2a — o que se repete literalmente é agrupado SEM IA. O par
        # "removido → inserido" que aparece duas vezes já é padrão provado, e
        # o rótulo sai dele mesmo ("Trocar «no dia» por «em»"), o que torna
        # impossível o rótulo não bater com o exemplo.
        exact_patterns, remaining_indices = _diff_svc.cluster_repeated_changes(changes)

        # Etapa 2b — o modelo agrupa só o que sobrou (par único, aconteceu uma
        # vez). Ele apenas ATRIBUI índices; contagem, exemplos e relevância
        # continuam saindo do código.
        grouping = loop.run_until_complete(
            grouper.group_changes(
                changes_text=_diff_svc.format_for_prompt(
                    changes, only_indices=remaining_indices),
                changes_summary=changes_summary,
            )
        )

        patterns = _diff_svc.reconcile_patterns(
            [pattern.model_dump() for pattern in grouping.patterns],
            changes,
            already_claimed={
                index for pattern in exact_patterns for index in pattern['indices']
            },
        )

        grouping_payload = {
            'summary': grouping.summary,
            'exact_patterns': _strip_pattern_indices(exact_patterns),
            'patterns': _strip_pattern_indices(patterns),
            'unassigned': _diff_svc.unassigned_count(exact_patterns + patterns, changes),
        }

        # Etapa 3 — propor, com o manual e os casos INTEIROS à vista. Só cabe
        # porque os documentos ficaram para trás na etapa 1.
        extract = loop.run_until_complete(
            proposer.propose_updates(
                grouping=grouping_payload,
                manual_content=manual_reference.content if manual_reference else '',
                cases_content=cases_reference.content if cases_reference else '',
                reviewer_identity=_get_active_prompt_content(law_firm_id, 'revisor_identity'),
                reviewer_rules=_get_active_prompt_content(law_firm_id, 'revisor_rules'),
                training_identity=_get_active_prompt_content(law_firm_id, 'training_identity'),
                training_rules=_get_active_prompt_content(law_firm_id, 'training_rules'),
                training_prompt=_get_active_prompt_content(law_firm_id, 'training_prompt'),
            )
        )
    finally:
        loop.close()

    payload['stage'] = 'preview'
    payload['changes_summary'] = changes_summary
    payload['grouping'] = grouping_payload
    payload['extract'] = extract.model_dump()
    # As ~240 diferenças cruas NÃO entram no payload: `result_json` é TEXT
    # (64 KB no MySQL) e o diff sozinho passa de 36 KB. Os exemplos literais
    # que a tela mostra vêm dos padrões agrupados, que são pequenos.

    execution.result_json = json.dumps(payload, ensure_ascii=False)
    execution.status = 'pending'
    execution.updated_at = datetime.now()
    db.session.commit()

    _log_audit(
        law_firm_id,
        'training_preview_generated',
        'execution',
        execution.id,
        'Comparação gerada e aguardando confirmação humana',
        user_id=execution.user_id,
    )


@fap_review_bp.route('/training/comparar', methods=['POST'])
@require_law_firm
@require_admin_user
def training_compare():
    """Recebe os dois documentos e dispara a comparação."""
    law_firm_id = get_current_law_firm_id()
    setting = _get_fap_setting(law_firm_id)

    if True:
        if not setting.training_enabled:
            flash('O agente de treinamento está desligado nas Configurações.', 'warning')
            return redirect(url_for('fap_review.training'))

        original_file = request.files.get('original_document')
        revised_file = request.files.get('revised_document')

        upload_error = _validate_training_uploads(original_file, revised_file)
        if upload_error:
            flash(upload_error, 'warning')
            return redirect(url_for('fap_review.training'))

        try:
            upload_dir = _create_upload_directory(law_firm_id, 'training')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')

            original_path = upload_dir / (timestamp + 'original_' + secure_filename(original_file.filename))
            revised_path = upload_dir / (timestamp + 'revised_' + secure_filename(revised_file.filename))

            original_file.save(str(original_path))
            revised_file.save(str(revised_path))

            execution = FapReviewExecution(
                law_firm_id=law_firm_id,
                user_id=session.get('user_id'),
                execution_type='training',
                status='processing',
                model_name=_get_fap_setting(law_firm_id).training_model,
                main_document_path=str(original_path),
                main_document_filename=original_file.filename,
                comparative_analysis=True,
                compared_document_path=str(revised_path),
                result_json=json.dumps(
                    {
                        'stage': 'processing',
                        'source_files': {
                            'original_filename': original_file.filename,
                            'revised_filename': revised_file.filename,
                            'original_path': str(original_path),
                            'revised_path': str(revised_path),
                        },
                    },
                    ensure_ascii=False,
                ),
            )
            db.session.add(execution)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao registrar comparação de treinamento: {e}")
            flash(f'Erro ao enviar os documentos: {str(e)}', 'error')
            return redirect(url_for('fap_review.training'))

        _log_audit(
            law_firm_id,
            'training_comparison_started',
            'execution',
            execution.id,
            'Comparação de treinamento iniciada',
        )
        _launch_training_comparison(execution.id, law_firm_id)

        return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))


@fap_review_bp.route('/training')
@require_law_firm
@require_admin_user
def training():
    """Entrada do treinamento: a escolha do modo e a atividade recente."""
    law_firm_id = get_current_law_firm_id()
    setting = _get_fap_setting(law_firm_id)

    recent = FapReviewExecution.query.filter(
        FapReviewExecution.law_firm_id == law_firm_id,
        FapReviewExecution.execution_type.in_(_svc.TRAINING_EXECUTION_TYPES),
    ).order_by(FapReviewExecution.created_at.desc()).limit(12).all()

    rows = []
    for execution in recent:
        payload = _load_training_payload(execution)
        # RPI-03: a coerência entre lotes não precisa de mecanismo novo — o
        # versionamento com ativação já existe. Precisa ficar visível: com que
        # modelo cada lote rodou, e se é o mesmo que está valendo hoje.
        model_meta = {
            'model_label': _svc.describe_model_name(execution.model_name),
            'model_is_current': bool(
                execution.model_name and execution.model_name == setting.training_model),
        }
        if execution.execution_type == _svc.TRAINING_CHAT_TYPE:
            first = FapReviewTrainingMessage.query.filter_by(
                execution_id=execution.id, role='user',
            ).order_by(FapReviewTrainingMessage.id.asc()).first()
            subject = (first.content if first else '').strip().splitlines()[0][:90] if first and first.content.strip() else 'Conversa sem mensagens'
            rows.append({
                'execution': execution,
                'documents': subject,
                **model_meta,
                **_svc.summarize_chat_execution(execution.status, payload, subject),
            })
        else:
            rows.append({
                'execution': execution,
                'documents': _training_documents_label(execution, payload),
                'is_chat': False,
                **model_meta,
                **_svc.summarize_training_execution(execution.status, payload),
            })

    return render_template('fap_review/training.html', setting=setting, comparison_rows=rows)


# ---------------------------------------------------------------------------
# Treinamento interativo
# ---------------------------------------------------------------------------

def _chat_execution_or_404(execution_id: int, law_firm_id: int):
    return FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
        execution_type=_svc.TRAINING_CHAT_TYPE,
    ).first_or_404()


def _chat_messages(execution_id: int):
    return FapReviewTrainingMessage.query.filter_by(
        execution_id=execution_id,
    ).order_by(FapReviewTrainingMessage.id.asc()).all()


def _enrich_chat_edits(edits_by_id: dict, payload: dict, contents: dict) -> dict:
    """Confere cada edição contra o documento atual e anexa diff, selo e decisão."""
    enriched = {}
    for edit_id, edit in edits_by_id.items():
        content = contents.get(str(edit.get('target') or ''), '')
        checked = _svc.verify_reference_edit(edit, content)
        checked['id'] = edit_id
        checked['message_id'] = edit.get('message_id')
        checked['preview'] = _svc.build_edit_preview(content, edit)
        checked['effective_kind'] = _svc.effective_edit_kind(checked.get('kind'), checked['preview'])
        checked['decision'] = _svc.decision_for(payload, edit_id)
        enriched[edit_id] = checked
    return enriched


def _chat_tray(payload: dict, edits: dict, law_firm_id: int) -> list[dict]:
    """A bandeja: edições aceitas, por destino, com a versão que vão gerar."""
    versions = _current_reference_versions(law_firm_id)
    groups = []
    for target in _svc.TRAINING_TARGETS:
        items = [
            edits[edit_id] for edit_id in _svc.chat_state(payload)['accepted']
            if edit_id in edits and edits[edit_id].get('target') == target['key']
        ]
        if not items:
            continue
        current = versions.get(target['key'], 0)
        groups.append({
            'key': target['key'], 'label': target['label'],
            'current_version': current, 'next_version': current + 1,
            'edits': items,
        })
    return groups


def _chat_page_context(execution, law_firm_id: int) -> dict:
    payload = _load_training_payload(execution)
    messages = _chat_messages(execution.id)
    contents = _current_reference_contents(law_firm_id)
    edits = _enrich_chat_edits(_svc.edits_from_messages(messages), payload, contents)
    return {
        'execution': execution,
        'messages': messages,
        'edits': edits,
        'tray': _chat_tray(payload, edits, law_firm_id),
        'state': _svc.chat_state(payload),
        'versions': _current_reference_versions(law_firm_id),
    }


@fap_review_bp.route('/training/conversa', methods=['POST'])
@require_law_firm
@require_admin_user
def training_chat_start():
    """Abre uma conversa nova."""
    law_firm_id = get_current_law_firm_id()
    setting = _get_fap_setting(law_firm_id)

    if not setting.training_enabled:
        flash('O agente de treinamento está desligado nas Configurações.', 'warning')
        return redirect(url_for('fap_review.training'))

    execution = FapReviewExecution(
        law_firm_id=law_firm_id,
        user_id=session.get('user_id'),
        execution_type=_svc.TRAINING_CHAT_TYPE,
        status='pending',
        model_name=_get_fap_setting(law_firm_id).training_model,
        main_document_filename='Treinamento interativo',
        result_json=json.dumps({'stage': 'chat', 'accepted': [], 'refused': [], 'saved': []}),
    )
    db.session.add(execution)
    db.session.commit()

    _log_audit(law_firm_id, 'training_chat_started', 'execution', execution.id,
               'Conversa de treinamento iniciada')
    return redirect(url_for('fap_review.training_chat', execution_id=execution.id))


@fap_review_bp.route('/training/conversa/<int:execution_id>')
@require_law_firm
@require_admin_user
def training_chat(execution_id: int):
    """A conversa: mensagens, propostas e a bandeja de aceitas."""
    law_firm_id = get_current_law_firm_id()
    execution = _chat_execution_or_404(execution_id, law_firm_id)
    return render_template('fap_review/training_chat.html',
                           **_chat_page_context(execution, law_firm_id))


@fap_review_bp.route('/training/conversa/<int:execution_id>/mensagem', methods=['POST'])
@require_law_firm
@require_admin_user
def training_chat_message(execution_id: int):
    """Recebe uma mensagem, roda o agente e devolve a resposta renderizada.

    Roda na requisição, não em thread: resposta de chat de 10–20 s o usuário
    espera olhando, e o padrão thread + reload da comparação faria a conversa
    engasgar. O usuário e a resposta são gravados JUNTOS, depois que o agente
    responde — toda mensagem do usuário tem resposta.
    """
    law_firm_id = get_current_law_firm_id()
    execution = _chat_execution_or_404(execution_id, law_firm_id)

    if execution.status == 'completed':
        return jsonify({'error': 'Esta conversa foi encerrada.'}), 400

    data = request.get_json(silent=True) or {}
    text = str(data.get('message') or request.form.get('message') or '').strip()
    if not text:
        return jsonify({'error': 'Escreva uma mensagem.'}), 400

    setting = _get_fap_setting(law_firm_id)
    contents = _current_reference_contents(law_firm_id)
    history = [
        {'role': message.role, 'content': message.content}
        for message in _chat_messages(execution.id)
    ]

    agent = FapTrainingChatAgent(
        openai_api_key=os.getenv('OPENAI_API_KEY'),
        model=setting.training_model,
        temperature=min(max(setting.training_temperature, 0.0), 1.0),
    )

    try:
        turn = agent.respond(
            history=history,
            user_message=text,
            manual_content=contents.get('manual_fap', ''),
            cases_content=contents.get('casos_referencia', ''),
            reviewer_identity=_get_active_prompt_content(law_firm_id, 'revisor_identity'),
            reviewer_rules=_get_active_prompt_content(law_firm_id, 'revisor_rules'),
            training_identity=_get_active_prompt_content(law_firm_id, 'training_identity'),
            training_rules=_get_active_prompt_content(law_firm_id, 'training_rules'),
        )
    except Exception as error:
        current_app.logger.error(f"Erro no treinamento interativo: {error}")
        return jsonify({'error': f'A IA não respondeu: {error}'}), 502

    user_id = session.get('user_id')
    user_message = FapReviewTrainingMessage(
        law_firm_id=law_firm_id, execution_id=execution.id, user_id=user_id,
        role='user', content=text)
    assistant_message = FapReviewTrainingMessage(
        law_firm_id=law_firm_id, execution_id=execution.id, user_id=user_id,
        role='assistant', content=turn.reply,
        edits_json=json.dumps([edit.model_dump() for edit in turn.edits], ensure_ascii=False))
    db.session.add(user_message)
    db.session.add(assistant_message)
    execution.updated_at = datetime.now()
    db.session.commit()

    context = _chat_page_context(execution, law_firm_id)
    return jsonify({
        'user_html': render_template('fap_review/_training_chat_message.html',
                                     message=user_message, edits=context['edits'],
                                     execution=execution),
        'assistant_html': render_template('fap_review/_training_chat_message.html',
                                          message=assistant_message, edits=context['edits'],
                                          execution=execution),
        'tray_html': render_template('fap_review/_training_chat_tray.html', **context),
    })


@fap_review_bp.route('/training/conversa/<int:execution_id>/edicao/<edit_id>/<decision>', methods=['POST'])
@require_law_firm
@require_admin_user
def training_chat_decision(execution_id: int, edit_id: str, decision: str):
    """Aceitar, recusar ou desfazer uma proposta. Aceitar não grava: vai para a bandeja."""
    law_firm_id = get_current_law_firm_id()
    execution = _chat_execution_or_404(execution_id, law_firm_id)

    if decision not in _svc.CHAT_DECISIONS:
        return jsonify({'error': 'Decisão desconhecida.'}), 400

    edits = _svc.edits_from_messages(_chat_messages(execution.id))
    if edit_id not in edits:
        return jsonify({'error': 'Proposta não encontrada nesta conversa.'}), 404

    if decision == 'accept':
        content = _current_reference_contents(law_firm_id).get(edits[edit_id].get('target') or '', '')
        if _svc.verify_reference_edit(edits[edit_id], content)['status'] != 'ok':
            return jsonify({'error': 'Esta proposta não pode ser aceita: o trecho que ela altera '
                                     'não foi encontrado no documento.'}), 400

    payload = _svc.apply_chat_decision(_load_training_payload(execution), edit_id, decision)
    execution.result_json = json.dumps(payload, ensure_ascii=False)
    execution.updated_at = datetime.now()
    db.session.commit()

    context = _chat_page_context(execution, law_firm_id)
    return jsonify({
        'edit_html': render_template('fap_review/_training_edit_card.html',
                                     edit=context['edits'][edit_id], execution=execution),
        'tray_html': render_template('fap_review/_training_chat_tray.html', **context),
    })


@fap_review_bp.route('/training/conversa/<int:execution_id>/salvar', methods=['POST'])
@require_law_firm
@require_admin_user
def training_chat_save(execution_id: int):
    """Grava as aceitas como versão nova de cada destino e esvazia a bandeja."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    execution = _chat_execution_or_404(execution_id, law_firm_id)

    payload = _load_training_payload(execution)
    edits = _svc.edits_from_messages(_chat_messages(execution.id))
    selection = _svc.accepted_edits(payload, edits)

    if not selection:
        flash('Nenhuma alteração aceita — nada para gravar.', 'warning')
        return redirect(url_for('fap_review.training_chat', execution_id=execution.id))

    activate = request.form.get('mode') == 'activate'

    try:
        applied_targets, blocked = [], []
        for target in _svc.TRAINING_TARGETS:
            do_alvo = [item for item in selection if item.get('target') == target['key']]
            if not do_alvo:
                continue
            current_reference = _get_active_reference(law_firm_id, target['key'])
            content, resultado = _svc.apply_reference_edits(
                current_reference.content if current_reference else '', do_alvo)
            aplicadas = [item for item in resultado if item['status'] == 'applied']
            blocked.extend(item for item in resultado if item['status'] != 'applied')
            if not aplicadas:
                continue
            new_version = _append_reference_version(
                law_firm_id=law_firm_id, user_id=user_id, reference_type=target['key'],
                new_content=content, activate=activate)
            applied_targets.append({
                'key': target['key'], 'label': target['label'],
                'version_number': new_version.version_number,
                'previous_version': current_reference.version_number if current_reference else 0,
                'activated': activate, 'edits': len(aplicadas),
            })

        if not applied_targets:
            db.session.rollback()
            flash('Nenhuma alteração pôde ser aplicada — os trechos que elas alteram não foram '
                  'encontrados no documento atual.', 'warning')
            return redirect(url_for('fap_review.training_chat', execution_id=execution.id))

        payload = _svc.record_chat_save(
            payload, applied_targets, activate, now_sp().strftime('%d/%m/%Y %H:%M'))
        payload['blocked_last_save'] = len(blocked)
        execution.result_json = json.dumps(payload, ensure_ascii=False)
        execution.updated_at = datetime.now()
        db.session.commit()

    except Exception as error:
        db.session.rollback()
        current_app.logger.error(f"Erro ao gravar treinamento interativo: {error}")
        flash(f'Erro ao gravar: {error}', 'error')
        return redirect(url_for('fap_review.training_chat', execution_id=execution.id))

    written = ', '.join(
        f"{item['label']} v{item['version_number']} ({item['edits']} alterações)"
        for item in applied_targets)
    _log_audit(law_firm_id, 'training_applied', 'execution', execution.id,
               f"Treinamento interativo gravado ({'ativado' if activate else 'rascunho'}): {written}")
    flash(f'Gravado: {written}.' + ('' if activate else ' Salvo como rascunho — ainda não está valendo.'),
          'success')
    return redirect(url_for('fap_review.training_chat', execution_id=execution.id))


@fap_review_bp.route('/training/conversa/<int:execution_id>/encerrar', methods=['POST'])
@require_law_firm
@require_admin_user
def training_chat_close(execution_id: int):
    """Encerra a conversa; o que estava aceito e não salvo fica registrado como pendente."""
    law_firm_id = get_current_law_firm_id()
    execution = _chat_execution_or_404(execution_id, law_firm_id)
    execution.status = 'completed'
    execution.completed_at = datetime.now()
    db.session.commit()
    flash('Conversa encerrada.', 'success')
    return redirect(url_for('fap_review.training'))


@fap_review_bp.route('/training/<int:execution_id>')
@require_law_firm
@require_admin_user
def training_comparison(execution_id: int):
    """Uma comparação: a espera, a prévia do que será gravado, ou o que foi gravado."""
    law_firm_id = get_current_law_firm_id()

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
        execution_type='training',
    ).first_or_404()

    # Watchdog: a comparação roda em thread; sem isso, um reinício do processo
    # web deixaria a execução presa em "processando" para sempre.
    if _svc.is_execution_stuck(execution):
        execution.status = 'failed'
        execution.error_message = ('Processamento interrompido (tempo excedido — provável '
                                   'reinício do servidor). Envie os documentos novamente.')
        execution.completed_at = datetime.now()
        db.session.commit()

    payload = _load_training_payload(execution)

    extract = payload.get('extract') or {}

    return render_template(
        'fap_review/training_comparison.html',
        execution=execution,
        extract=extract,
        grouping=payload.get('grouping') or {},
        changes_summary=payload.get('changes_summary') or {},
        applied=payload.get('applied') or {},
        edit_groups=_svc.build_training_edit_groups(
            extract.get('edits') or [],
            _current_reference_versions(law_firm_id),
            _current_reference_contents(law_firm_id),
        ),
        documents=_training_documents_label(execution, payload),
    )


def _current_reference_contents(law_firm_id: int) -> dict[str, str]:
    """Conteúdo ativo de cada destino, contra o qual as âncoras são conferidas."""
    contents = {}
    for target in _svc.TRAINING_TARGETS:
        reference = _get_active_reference(law_firm_id, target['key'])
        contents[target['key']] = reference.content if reference else ''
    return contents


@fap_review_bp.route('/training/<int:execution_id>/aplicar', methods=['POST'])
@require_law_firm
@require_admin_user
def training_apply(execution_id: int):
    """Grava nas referências exatamente o texto confirmado na prévia.

    Sem chamada de IA aqui: o que a pessoa leu (e pôde editar) é o que entra.
    """
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id,
        execution_type='training',
    ).first_or_404()

    if execution.status != 'pending':
        flash('Esta comparação não está aguardando confirmação.', 'warning')
        return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))

    payload = _load_training_payload(execution)
    edits = (payload.get('extract') or {}).get('edits') or []

    selection = _svc.parse_training_edit_selection(
        request.form.getlist('edits'),
        edits,
        {chave[len('text_'):]: valor
         for chave, valor in request.form.items() if chave.startswith('text_')},
    )

    if not selection:
        flash('Nada foi marcado para gravar — nenhuma referência foi alterada.', 'warning')
        return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))

    activate = request.form.get('mode') == 'activate'

    try:
        applied_targets = []
        blocked = []

        for target in _svc.TRAINING_TARGETS:
            do_alvo = [item for item in selection if item.get('target') == target['key']]
            if not do_alvo:
                continue

            current_reference = _get_active_reference(law_firm_id, target['key'])
            content, resultado = _svc.apply_reference_edits(
                current_reference.content if current_reference else '', do_alvo)

            aplicadas = [item for item in resultado if item['status'] == 'applied']
            blocked.extend(item for item in resultado if item['status'] != 'applied')

            if not aplicadas:
                continue

            new_version = _append_reference_version(
                law_firm_id=law_firm_id,
                user_id=user_id,
                reference_type=target['key'],
                new_content=content,
                activate=activate,
            )
            applied_targets.append({
                'key': target['key'],
                'label': target['label'],
                'version_number': new_version.version_number,
                'previous_version': current_reference.version_number if current_reference else 0,
                'activated': activate,
                'edits': len(aplicadas),
            })

        if not applied_targets:
            db.session.rollback()
            flash('Nenhuma alteração pôde ser aplicada — os trechos que elas alteram '
                  'não foram encontrados no documento atual.', 'warning')
            return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))

        payload['stage'] = 'applied'
        payload['applied'] = {
            'activated': activate,
            'applied_at': now_sp().strftime('%d/%m/%Y %H:%M'),
            'targets': applied_targets,
            'blocked': len(blocked),
        }

        execution.result_json = json.dumps(payload, ensure_ascii=False)
        execution.status = 'completed'
        execution.completed_at = datetime.now()
        execution.updated_at = datetime.now()
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao gravar treinamento: {e}")
        flash(f'Erro ao gravar: {str(e)}', 'error')
        return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))

    written = ', '.join(
        f"{item['label']} v{item['version_number']} ({item['edits']} alterações)"
        for item in applied_targets
    )

    _log_audit(
        law_firm_id,
        'training_applied',
        'execution',
        execution.id,
        f"Treinamento gravado ({'ativado' if activate else 'rascunho'}): {written}",
    )

    flash(
        f'Gravado: {written}.'
        + ('' if activate else ' Salvo como rascunho — ainda não está valendo.'),
        'success',
    )
    return redirect(url_for('fap_review.training_comparison', execution_id=execution.id))


@fap_review_bp.route('/settings', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def settings():
    """Página de configurações do módulo"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    setting = _get_fap_setting(law_firm_id)
    
    if request.method == 'POST':
        try:
            data = request.json
            
            # Atualizar configurações
            setting.reviewer_model = data.get('reviewer_model', setting.reviewer_model)
            setting.training_model = data.get('training_model', setting.training_model)
            # Normalizar temperatura (converter vírgula para ponto se necessário)
            reviewer_temp_str = str(data.get('reviewer_temperature', setting.reviewer_temperature)).replace(',', '.')
            setting.reviewer_temperature = float(reviewer_temp_str)
            training_temp_str = str(data.get('training_temperature', setting.training_temperature)).replace(',', '.')
            setting.training_temperature = float(training_temp_str)
            setting.reviewer_enabled = data.get('reviewer_enabled', setting.reviewer_enabled)
            setting.training_enabled = data.get('training_enabled', setting.training_enabled)
            setting.updated_at = now_sp()
            
            db.session.commit()
            
            # Log de auditoria
            _log_audit(law_firm_id, 'settings_updated', 'setting', setting.id,
                      'Configurações do FAP Review atualizadas')
            
            return jsonify({'success': True, 'message': 'Configurações salvas com sucesso'})
        
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET - Exibir página
    available_models, model_options_error = fetch_openrouter_text_models_for_info(
        selected_model=setting.reviewer_model or '',
        fallback_model=setting.reviewer_model or '',
    )
    return render_template('fap_review/settings.html',
                           setting=setting,
                           available_models=available_models,
                           model_options_error=model_options_error)


@fap_review_bp.route('/settings/prompts/type/<string:prompt_type>/edit', methods=['GET'])
@require_law_firm
@require_admin_user
def edit_prompt_by_type(prompt_type: str):
    """Abre edição do prompt pela tipagem, criando versão inicial se necessário."""
    law_firm_id = get_current_law_firm_id()

    valid_types = {
        'revisor_identity',
        'revisor_rules',
        'revisor_output_format',
        'training_identity',
        'training_rules',
        'training_prompt',
        'training_update_policy',
    }

    if prompt_type not in valid_types:
        flash('Tipo de prompt inválido', 'error')
        return redirect(url_for('fap_review.settings'))

    prompt = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
        is_active=True,
    ).order_by(FapReviewPromptVersion.version_number.desc()).first()

    if not prompt:
        prompt = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
    ).order_by(FapReviewPromptVersion.version_number.desc()).first()

    if not prompt:
        prompt = FapReviewPromptVersion(
            law_firm_id=law_firm_id,
            version_number=1,
            prompt_type=prompt_type,
            content='',
            is_active=True,
            created_by_id=session.get('user_id'),
        )
        db.session.add(prompt)
        db.session.commit()

        _log_audit(
            law_firm_id,
            'prompt_created',
            'prompt',
            prompt.id,
            f'Prompt inicial criado para {prompt_type}'
        )

    return redirect(url_for('fap_review.edit_prompt', prompt_version_id=prompt.id))


@fap_review_bp.route('/settings/references/type/<string:reference_type>/edit', methods=['GET'])
@require_law_firm
@require_admin_user
def edit_reference_by_type(reference_type: str):
    """Abre edição da referência pela tipagem, criando versão inicial se necessário."""
    law_firm_id = get_current_law_firm_id()

    valid_types = {
        'manual_fap',
        'casos_referencia',
        'project_instructions',
    }

    if reference_type not in valid_types:
        flash('Tipo de referência inválido', 'error')
        return redirect(url_for('fap_review.settings'))

    reference = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
        is_active=True,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()

    if not reference:
        reference = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()

    if not reference:
        reference = FapReviewReferenceVersion(
            law_firm_id=law_firm_id,
            version_number=1,
            reference_type=reference_type,
            content='',
            is_active=True,
            created_by_id=session.get('user_id'),
        )
        db.session.add(reference)
        db.session.commit()

        _log_audit(
            law_firm_id,
            'reference_created',
            'reference',
            reference.id,
            f'Referência inicial criada para {reference_type}'
        )

    return redirect(url_for('fap_review.edit_reference', reference_version_id=reference.id))


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS DE PROMPTS E REFERENCIAS
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.route('/settings/prompts', methods=['GET'])
@require_law_firm
@require_admin_user
def list_prompts():
    """Lista prompts por tipo"""
    law_firm_id = get_current_law_firm_id()
    
    prompt_types = [
        'revisor_identity',
        'revisor_rules',
        'revisor_output_format',
        'training_identity',
        'training_rules',
        'training_prompt',
        'training_update_policy'
    ]
    
    prompts = {}
    for ptype in prompt_types:
        versions = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type=ptype
        ).order_by(FapReviewPromptVersion.version_number.desc()).all()
        prompts[ptype] = versions
    
    return jsonify({
        'prompts': {
            k: [{'version': v.version_number, 'is_active': v.is_active, 'created_at': v.created_at.isoformat()} for v in v]
            for k, v in prompts.items()
        }
    })


@fap_review_bp.route('/settings/prompts/<int:prompt_version_id>', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def edit_prompt(prompt_version_id: int):
    """Edita um prompt específico"""
    law_firm_id = get_current_law_firm_id()
    
    prompt = FapReviewPromptVersion.query.filter_by(
        id=prompt_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    # Carregar todas as versões deste tipo
    all_versions = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt.prompt_type
    ).order_by(FapReviewPromptVersion.version_number.desc()).all()

    is_read_only_prompt = prompt.prompt_type in READ_ONLY_PROMPT_TYPES

    if request.method == 'POST':
        if is_read_only_prompt:
            return jsonify({'error': 'Este prompt é somente leitura e não pode ser editado.'}), 403

        try:
            content = request.json.get('content', '')
            change_note = str(request.json.get('change_note') or '').strip()[:255] or None
            activate = bool(request.json.get('activate'))

            # max+1 do tipo: a versão da página pode não ser a mais recente,
            # e dois saves seguidos não podem gerar números duplicados.
            max_version = db.session.query(
                func.max(FapReviewPromptVersion.version_number)
            ).filter_by(
                law_firm_id=law_firm_id,
                prompt_type=prompt.prompt_type,
            ).scalar() or 0

            if activate:
                FapReviewPromptVersion.query.filter_by(
                    law_firm_id=law_firm_id,
                    prompt_type=prompt.prompt_type,
                    is_active=True,
                ).update({'is_active': False})

            new_version = FapReviewPromptVersion(
                law_firm_id=law_firm_id,
                version_number=max_version + 1,
                prompt_type=prompt.prompt_type,
                content=content,
                change_note=change_note,
                is_active=activate,
                created_by_id=session.get('user_id')
            )
            db.session.add(new_version)
            db.session.commit()

            note_suffix = f' — {change_note}' if change_note else ''
            _log_audit(law_firm_id, 'prompt_updated', 'prompt', new_version.id,
                      f'Nova versão criada: v{new_version.version_number}{note_suffix}')
            if activate:
                _log_audit(law_firm_id, 'prompt_activated', 'prompt', new_version.id,
                          f'Versão v{new_version.version_number} ativada')

            return jsonify({
                'success': True,
                'version_id': new_version.id,
                'redirect_url': url_for('fap_review.edit_prompt', prompt_version_id=new_version.id),
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET
    return render_template(
        'fap_review/edit_prompt.html',
        prompt=prompt,
        versions=all_versions,
        is_read_only_prompt=is_read_only_prompt,
    )


@fap_review_bp.route('/settings/prompts/<int:prompt_version_id>/activate', methods=['POST'])
@require_law_firm
@require_admin_user
def activate_prompt(prompt_version_id: int):
    """Ativa uma versão de prompt"""
    law_firm_id = get_current_law_firm_id()
    
    prompt = FapReviewPromptVersion.query.filter_by(
        id=prompt_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    if prompt.prompt_type in READ_ONLY_PROMPT_TYPES:
        return jsonify({'error': 'Este prompt é somente leitura e não permite ativação manual.'}), 403
    
    try:
        # Desativar outras versões do mesmo tipo
        FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type=prompt.prompt_type,
            is_active=True
        ).update({'is_active': False})
        
        # Ativar esta versão
        prompt.is_active = True
        db.session.commit()
        
        _log_audit(law_firm_id, 'prompt_activated', 'prompt', prompt.id,
                  f'Versão v{prompt.version_number} ativada')
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# Diff de referência pode ser grande; acima disso a resposta é um erro amigável.
_MAX_DIFF_CHARS = 2_000_000


def _build_version_diff(base, other):
    """Diff unificado entre duas versões (other → base), pronto para a UI."""
    if len(base.content or '') > _MAX_DIFF_CHARS or len(other.content or '') > _MAX_DIFF_CHARS:
        return None
    lines = list(difflib.unified_diff(
        (other.content or '').splitlines(),
        (base.content or '').splitlines(),
        lineterm='',
        n=3,
    ))[2:]  # descarta cabeçalhos ---/+++; os rótulos vão à parte
    return {
        'success': True,
        'from_label': f'v{other.version_number}',
        'to_label': f'v{base.version_number}',
        'lines': lines,
        'identical': not lines,
    }


@fap_review_bp.route('/settings/prompts/<int:prompt_version_id>/diff/<int:other_version_id>', methods=['GET'])
@require_law_firm
@require_admin_user
def prompt_version_diff(prompt_version_id: int, other_version_id: int):
    """Diff entre duas versões do mesmo tipo de prompt."""
    law_firm_id = get_current_law_firm_id()
    base = FapReviewPromptVersion.query.filter_by(
        id=prompt_version_id, law_firm_id=law_firm_id).first_or_404()
    other = FapReviewPromptVersion.query.filter_by(
        id=other_version_id, law_firm_id=law_firm_id,
        prompt_type=base.prompt_type).first_or_404()

    diff = _build_version_diff(base, other)
    if diff is None:
        return jsonify({'error': 'Conteúdo grande demais para comparar aqui.'}), 413
    return jsonify(diff)


@fap_review_bp.route('/settings/references/<int:reference_version_id>/diff/<int:other_version_id>', methods=['GET'])
@require_law_firm
@require_admin_user
def reference_version_diff(reference_version_id: int, other_version_id: int):
    """Diff entre duas versões do mesmo tipo de referência."""
    law_firm_id = get_current_law_firm_id()
    base = FapReviewReferenceVersion.query.filter_by(
        id=reference_version_id, law_firm_id=law_firm_id).first_or_404()
    other = FapReviewReferenceVersion.query.filter_by(
        id=other_version_id, law_firm_id=law_firm_id,
        reference_type=base.reference_type).first_or_404()

    diff = _build_version_diff(base, other)
    if diff is None:
        return jsonify({'error': 'Conteúdo grande demais para comparar aqui.'}), 413
    return jsonify(diff)


@fap_review_bp.route('/settings/references/import-file', methods=['POST'])
@require_law_firm
@require_admin_user
def reference_import_file():
    """Extrai texto de um arquivo (.md/.txt/.docx) para preencher o editor de referência.

    Não grava nada: o admin revisa o conteúdo no editor e salva como nova versão.
    """
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'Envie um arquivo.'}), 400

    extension = _get_file_extension(file.filename)
    if extension not in {'.md', '.txt', '.docx'}:
        return jsonify({'error': 'Formato não suportado. Envie .md, .txt ou .docx.'}), 400

    try:
        if extension in {'.md', '.txt'}:
            content = file.read().decode('utf-8', errors='replace')
        else:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name
            try:
                content = _extract_text_from_document(tmp_path)
            finally:
                os.unlink(tmp_path)
    except Exception as error:
        current_app.logger.error(f'Erro ao importar referência de arquivo: {error}')
        return jsonify({'error': 'Não foi possível extrair o texto do arquivo.'}), 500

    if not (content or '').strip():
        return jsonify({'error': 'O arquivo não contém texto extraível.'}), 400

    return jsonify({'success': True, 'content': content})


@fap_review_bp.route('/settings/references', methods=['GET'])
@require_law_firm
@require_admin_user
def list_references():
    """Lista documentos de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference_types = ['manual_fap', 'casos_referencia', 'project_instructions']
    
    references = {}
    for rtype in reference_types:
        versions = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type=rtype
        ).order_by(FapReviewReferenceVersion.version_number.desc()).all()
        references[rtype] = versions
    
    return jsonify({
        'references': {
            k: [{'version': v.version_number, 'is_active': v.is_active, 'created_at': v.created_at.isoformat()} for v in v]
            for k, v in references.items()
        }
    })


@fap_review_bp.route('/settings/references/<int:reference_version_id>', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def edit_reference(reference_version_id: int):
    """Edita um documento de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference = FapReviewReferenceVersion.query.filter_by(
        id=reference_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    # Carregar todas as versões deste tipo
    all_versions = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference.reference_type
    ).order_by(FapReviewReferenceVersion.version_number.desc()).all()

    is_read_only_reference = reference.reference_type in READ_ONLY_REFERENCE_TYPES

    if request.method == 'POST':
        if is_read_only_reference:
            return jsonify({'error': 'Esta referência é somente leitura e não pode ser editada.'}), 403

        try:
            content = request.json.get('content', '')
            change_note = str(request.json.get('change_note') or '').strip()[:255] or None
            activate = bool(request.json.get('activate'))

            # max+1 do tipo: a versão da página pode não ser a mais recente,
            # e dois saves seguidos não podem gerar números duplicados.
            max_version = db.session.query(
                func.max(FapReviewReferenceVersion.version_number)
            ).filter_by(
                law_firm_id=law_firm_id,
                reference_type=reference.reference_type,
            ).scalar() or 0

            if activate:
                FapReviewReferenceVersion.query.filter_by(
                    law_firm_id=law_firm_id,
                    reference_type=reference.reference_type,
                    is_active=True,
                ).update({'is_active': False})

            new_version = FapReviewReferenceVersion(
                law_firm_id=law_firm_id,
                version_number=max_version + 1,
                reference_type=reference.reference_type,
                content=content,
                change_note=change_note,
                is_active=activate,
                created_by_id=session.get('user_id')
            )
            db.session.add(new_version)
            db.session.commit()

            note_suffix = f' — {change_note}' if change_note else ''
            _log_audit(law_firm_id, 'reference_updated', 'reference', new_version.id,
                      f'Nova versão criada: v{new_version.version_number}{note_suffix}')
            if activate:
                _log_audit(law_firm_id, 'reference_activated', 'reference', new_version.id,
                          f'Versão v{new_version.version_number} ativada')

            return jsonify({
                'success': True,
                'version_id': new_version.id,
                'redirect_url': url_for('fap_review.edit_reference', reference_version_id=new_version.id),
            })

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET
    return render_template(
        'fap_review/edit_reference.html',
        reference=reference,
        versions=all_versions,
        is_read_only_reference=is_read_only_reference,
    )


@fap_review_bp.route('/settings/references/<int:reference_version_id>/activate', methods=['POST'])
@require_law_firm
@require_admin_user
def activate_reference(reference_version_id: int):
    """Ativa uma versão de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference = FapReviewReferenceVersion.query.filter_by(
        id=reference_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    if reference.reference_type in READ_ONLY_REFERENCE_TYPES:
        return jsonify({'error': 'Esta referência é somente leitura e não permite ativação manual.'}), 403
    
    try:
        # Desativar outras versões do mesmo tipo
        FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type=reference.reference_type,
            is_active=True
        ).update({'is_active': False})
        
        # Ativar esta versão
        reference.is_active = True
        db.session.commit()
        
        _log_audit(law_firm_id, 'reference_activated', 'reference', reference.id,
                  f'Versão v{reference.version_number} ativada')
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS DE AUDITORIA
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.route('/audit-logs', methods=['GET'])
@require_law_firm
@require_admin_user
def audit_logs():
    """Exibe logs de auditoria"""
    law_firm_id = get_current_law_firm_id()
    
    page = request.args.get('page', 1, type=int)
    logs = FapReviewAuditLog.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(FapReviewAuditLog.created_at.desc()).paginate(page=page, per_page=50)
    
    return render_template('fap_review/audit_logs.html', logs=logs)


@fap_review_bp.route('/api/audit-logs', methods=['GET'])
@require_law_firm
@require_admin_user
def api_audit_logs():
    """API para obter logs de auditoria"""
    law_firm_id = get_current_law_firm_id()
    
    action_filter = request.args.get('action', '')
    entity_filter = request.args.get('entity_type', '')
    limit = request.args.get('limit', 50, type=int)
    
    query = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id)
    
    if action_filter:
        query = query.filter_by(action=action_filter)
    if entity_filter:
        query = query.filter_by(entity_type=entity_filter)
    
    logs = query.order_by(FapReviewAuditLog.created_at.desc()).limit(limit).all()
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'action': log.action,
            'entity_type': log.entity_type,
            'user': log.user.name if log.user else 'System',
            'created_at': log.created_at.isoformat(),
            'description': log.change_description
        } for log in logs]
    })
