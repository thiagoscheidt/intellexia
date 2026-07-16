"""
Revisor de Petições FAP — regras de workflow compartilhadas.

Fonte única para a tela (``app/blueprints/fap_review.py``) e para o MCP: o status
agregado da petição, o título, a leitura do resultado e o registro de uma revisão
seguem a mesma regra nos dois caminhos — como já fazemos no ``fap_digest_service``
e nos exports em Excel.

``log_audit`` recebe ``user_id`` explicitamente porque o MCP não tem sessão Flask;
o blueprint mantém um wrapper que injeta o usuário da sessão.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from app.models import db, FapReviewAuditLog, FapReviewExecution, FapReviewPetition

logger = logging.getLogger(__name__)

# Rótulos do status agregado da petição (o comment da coluna lista os códigos).
PETITION_WORKFLOW_STATUSES = {
    'new': 'Nova',
    'in_review': 'Em revisão',
    'awaiting_adjustments': 'Aguardando ajustes',
    'ready_for_filing': 'Aprovada pelo revisor',
    'filed': 'Processo iniciado',
    'archived': 'Arquivada',
}

MAX_IDENTIFIER_LENGTH = 96


def build_petition_title(raw_title: str, fallback_filename: str = '',
                         fallback_identifier: str = '') -> str:
    """Monta um título amigável para a petição."""
    title = ' '.join(str(raw_title or '').strip().split())
    if title:
        return title

    filename = Path(str(fallback_filename or '')).stem.strip()
    if filename:
        return filename

    identifier = str(fallback_identifier or '').strip()
    return identifier or 'Petição sem título'


def derive_petition_workflow_status(execution_status: str) -> str:
    """Traduz o status da revisão para o status agregado da petição."""
    if execution_status in {'pending', 'processing'}:
        return 'in_review'
    if execution_status == 'completed':
        return 'awaiting_adjustments'
    if execution_status == 'failed':
        return 'awaiting_adjustments'
    return 'new'


def sync_petition_after_revision(execution: FapReviewExecution) -> None:
    """Atualiza a visão agregada da petição depois de uma revisão."""
    petition = execution.petition
    if not petition or execution.execution_type != 'revision':
        return

    if execution.revision_number is None:
        execution.revision_number = FapReviewExecution.query.filter_by(
            petition_id=petition.id,
            execution_type='revision',
        ).count()

    petition.latest_revision_id = execution.id
    petition.revision_count = max(petition.revision_count or 0, execution.revision_number or 0)
    petition.last_reviewed_at = execution.completed_at or execution.updated_at or execution.created_at

    if petition.workflow_status not in {'filed', 'archived'}:
        petition.workflow_status = derive_petition_workflow_status(execution.status)

    petition.updated_at = datetime.now()


def load_execution_result_payload(execution: FapReviewExecution) -> dict:
    """Lê o payload JSON da revisão com fallback seguro."""
    if not execution.result_json:
        return {}

    try:
        payload = json.loads(execution.result_json)
    except (TypeError, json.JSONDecodeError):
        logger.warning('Falha ao interpretar result_json da execução %s', execution.id)
        return {}

    return payload if isinstance(payload, dict) else {}


def log_audit(law_firm_id: int, user_id: int | None, action: str, entity_type: str,
              entity_id: int = None, description: str = "",
              old_value: str = "", new_value: str = "") -> None:
    """Registra ação de auditoria do módulo Revisor."""
    db.session.add(FapReviewAuditLog(
        law_firm_id=law_firm_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        change_description=description,
        old_value=old_value,
        new_value=new_value,
    ))
    db.session.commit()


def upload_directory(law_firm_id: int, subdir: str = "") -> Path:
    """Diretório de uploads do módulo, criado se necessário."""
    base_dir = Path('uploads/fap_review') / str(law_firm_id)
    if subdir:
        base_dir = base_dir / subdir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _safe_slug(value: str, max_len: int = 40) -> str:
    slug = re.sub(r'[^A-Za-z0-9_-]+', '_', str(value or '').strip())
    return slug.strip('_')[:max_len] or 'peticao'


def record_text_review(law_firm_id: int, user_id: int | None, identifier: str,
                       petition_text: str, result_payload: dict,
                       title: str = '') -> dict:
    """Registra no módulo uma revisão feita a partir de texto (via MCP).

    Segue o mesmo caminho da tela: reaproveita/cria a petição pelo identificador do
    escritório, guarda o texto revisado em disco (para a tela conseguir abrir o
    documento) e grava a execução já concluída, sincronizando o status da petição.

    Retorna ``{"peticao_id", "revisao_id", "numero_revisao", "status_peticao",
    "peticao_criada"}``.
    """
    identifier = str(identifier or '').strip()
    if not identifier:
        raise ValueError('Identificador do documento é obrigatório para registrar a revisão.')
    if len(identifier) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f'O identificador do documento deve ter no máximo {MAX_IDENTIFIER_LENGTH} caracteres.'
        )

    petition = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
        office_document_identifier=identifier,
    ).first()

    petition_created = False
    if not petition:
        petition = FapReviewPetition(
            law_firm_id=law_firm_id,
            created_by_id=user_id,
            office_document_identifier=identifier,
            title=build_petition_title(title, fallback_identifier=identifier),
            workflow_status='in_review',
        )
        db.session.add(petition)
        db.session.flush()
        petition_created = True

    revision_number = FapReviewExecution.query.filter_by(
        petition_id=petition.id,
        execution_type='revision',
    ).count() + 1

    # O texto revisado vira arquivo: a tela abre o documento da execução e a revisão
    # precisa ser auditável — sem isso ficaria um registro sem o que foi revisado.
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{stamp}_mcp_{_safe_slug(identifier)}_rev{revision_number}.md'
    filepath = upload_directory(law_firm_id, 'revisions') / filename
    filepath.write_text(petition_text or '', encoding='utf-8')

    now = datetime.now()
    execution = FapReviewExecution(
        law_firm_id=law_firm_id,
        user_id=user_id,
        petition_id=petition.id,
        execution_type='revision',
        status='completed',
        revision_number=revision_number,
        main_document_path=str(filepath),
        main_document_filename=filename,
        law_firm_document_identifier=identifier,
        auxiliary_documents_count=0,
        auxiliary_documents_json=json.dumps([]),
        comparative_analysis=False,
        result_json=json.dumps(result_payload, ensure_ascii=False, indent=2),
        completed_at=now,
    )

    tokens_used = result_payload.get('tokens_used')
    if tokens_used is not None:
        execution.tokens_used = tokens_used
    cost_usd = result_payload.get('cost_usd')
    if cost_usd is not None:
        from decimal import Decimal
        execution.cost_usd = Decimal(str(cost_usd))

    db.session.add(execution)
    db.session.flush()

    sync_petition_after_revision(execution)
    db.session.commit()

    if petition_created:
        log_audit(law_firm_id, user_id, 'petition_created', 'petition', petition.id,
                  f'Petição criada via MCP: {petition.title}')
    log_audit(law_firm_id, user_id, 'revision_completed', 'execution', execution.id,
              f'Revisão via MCP (Claude) concluída: {identifier}')

    return {
        'peticao_id': petition.id,
        'revisao_id': execution.id,
        'numero_revisao': revision_number,
        'status_peticao': petition.workflow_status,
        'peticao_criada': petition_created,
    }
