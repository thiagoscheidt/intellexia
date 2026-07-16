"""
Revisor de Petições FAP — regras de workflow compartilhadas.

Fonte única para a tela (``app/blueprints/fap_review.py``) e para o MCP: o status
agregado da petição, o título, a leitura do resultado e o registro de uma revisão
seguem a mesma regra nos dois caminhos — como já fazemos no ``fap_digest_service``
e nos exports em Excel.

``log_audit`` recebe ``user_id`` explicitamente porque o MCP não tem sessão Flask;
o blueprint mantém um wrapper que injeta o usuário da sessão.
"""
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
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
                       title: str = '', comparative: bool = False) -> dict:
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
        comparative_analysis=comparative,
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


# ── Estatísticas por advogado ────────────────────────────────────────────────
# Extraídas do blueprint: a tela (admin) e a tool MCP mostram o mesmo número.


def normalize_finding_field(value: object) -> str:
    """Normaliza campo textual de achado para fingerprint estável."""
    return ' '.join(str(value or '').strip().split()).lower()



def build_finding_fingerprint(finding: dict | None) -> str:
    """Gera fingerprint estável de um achado para persistir feedback do usuário."""
    if not isinstance(finding, dict):
        return ''

    payload = {
        'category': normalize_finding_field(finding.get('category')),
        'severity': normalize_finding_field(finding.get('severity')),
        'description': normalize_finding_field(finding.get('description')),
        'location': normalize_finding_field(finding.get('location')),
        'correction': normalize_finding_field(finding.get('correction')),
        'manual_reference': normalize_finding_field(finding.get('manual_reference')),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()



def calculate_lawyer_score(total_findings: int, completed_revisions: int, rework_ratio: float, recurrence_rate: float) -> int:
    """Gera score heurístico simples para incentivar redução de retrabalho e reincidência."""
    if completed_revisions <= 0:
        return 100

    avg_findings = total_findings / completed_revisions
    finding_penalty = min(45.0, avg_findings * 6.0)
    rework_penalty = min(30.0, rework_ratio * 30.0)
    recurrence_penalty = min(25.0, recurrence_rate * 25.0)

    score = 100.0 - finding_penalty - rework_penalty - recurrence_penalty
    return max(0, min(100, int(round(score))))



def translate_user_role(role: str | None) -> str:
    """Traduz o papel do usuário para exibição em português."""
    role_map = {
        'admin': 'administrador',
        'lawyer': 'advogado',
        'assistant': 'assistente',
        'user': 'usuário',
    }
    normalized_role = str(role or '').strip().lower()
    return role_map.get(normalized_role, normalized_role or 'usuário')



def normalize_finding_severity(severity: str | None) -> str:
    """Normaliza a severidade do achado para um conjunto conhecido em português."""
    normalized_severity = str(severity or '').strip().upper()
    severity_map = {
        'CRITICAL': 'CRÍTICO',
        'CRITICO': 'CRÍTICO',
        'CRÍTICO': 'CRÍTICO',
        'MODERATE': 'MODERADO',
        'MODERADO': 'MODERADO',
        'FORMAL': 'FORMAL',
    }
    return severity_map.get(normalized_severity, normalized_severity or 'FORMAL')



def translate_finding_category(category: str | None) -> str:
    """Traduz categorias de achados para exibição em português."""
    normalized_category = str(category or '').strip().upper()
    category_map = {
        'CRITICAL': 'Crítico',
        'CRITICO': 'Crítico',
        'CRÍTICO': 'Crítico',
        'MODERATE': 'Moderado',
        'MODERADO': 'Moderado',
        'FORMAL': 'Formal',
        'SEM_CATEGORIA': 'Sem categoria',
    }
    if normalized_category in category_map:
        return category_map[normalized_category]

    cat_match = re.fullmatch(r'CAT[-_\s]?(\d+)', normalized_category)
    if cat_match:
        return f"Categoria {cat_match.group(1)}"

    return str(category or 'Sem categoria').strip() or 'Sem categoria'



def build_lawyer_statistics(law_firm_id: int) -> dict:
    """Consolida score e métricas dos advogados a partir do histórico de revisões."""
    revisions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        execution_type='revision',
    ).order_by(
        FapReviewExecution.created_at.asc(),
        FapReviewExecution.id.asc(),
    ).all()

    lawyer_stats: dict[int, dict] = {}
    petition_user_groups: dict[tuple[int, int], list[FapReviewExecution]] = defaultdict(list)

    for execution in revisions:
        if not execution.user_id or not execution.user:
            continue

        stats = lawyer_stats.setdefault(execution.user_id, {
            'user': execution.user,
            'total_revisions': 0,
            'completed_revisions': 0,
            'petitions': set(),
            'petition_history': {},
            'total_findings': 0,
            'critical_findings': 0,
            'moderate_findings': 0,
            'formal_findings': 0,
            'repeated_findings': 0,
            'categories': Counter(),
            'monthly': defaultdict(lambda: {'revisions': 0, 'findings': 0, 'repeated_findings': 0}),
        })

        stats['total_revisions'] += 1
        if execution.petition_id:
            stats['petitions'].add(execution.petition_id)
            petition_user_groups[(execution.user_id, execution.petition_id)].append(execution)

        month_key = (execution.created_at or execution.updated_at or datetime.now()).strftime('%Y-%m')
        stats['monthly'][month_key]['revisions'] += 1

        payload = load_execution_result_payload(execution)
        findings = payload.get('findings') or []
        if execution.status == 'completed':
            stats['completed_revisions'] += 1

        petition_key = execution.petition_id or execution.id
        petition_title = execution.petition.title if execution.petition else (execution.main_document_filename or 'Petição')
        petition_identifier = (
            execution.petition.office_document_identifier
            if execution.petition and execution.petition.office_document_identifier
            else (execution.law_firm_document_identifier or '-')
        )
        petition_history = stats['petition_history'].setdefault(petition_key, {
            'petition_id': execution.petition_id,
            'title': petition_title,
            'identifier': petition_identifier,
            'revision_count': 0,
            'latest_revision_number': 0,
            'latest_status': execution.status,
            'latest_at': execution.created_at or execution.updated_at,
            'total_findings': 0,
            'repeated_findings': 0,
            'categories': Counter(),
        })
        petition_history['revision_count'] += 1
        petition_history['latest_revision_number'] = max(
            petition_history['latest_revision_number'],
            execution.revision_number or petition_history['revision_count'],
        )
        petition_history['latest_status'] = execution.status
        petition_history['latest_at'] = execution.created_at or execution.updated_at

        for finding in findings:
            severity = normalize_finding_severity(finding.get('severity'))
            category = translate_finding_category(finding.get('category') or 'SEM_CATEGORIA')

            stats['total_findings'] += 1
            petition_history['total_findings'] += 1
            stats['categories'][category] += 1
            petition_history['categories'][category] += 1
            stats['monthly'][month_key]['findings'] += 1

            if severity == 'CRÍTICO':
                stats['critical_findings'] += 1
            elif severity == 'MODERADO':
                stats['moderate_findings'] += 1
            else:
                stats['formal_findings'] += 1

    for (user_id, petition_id), grouped_revisions in petition_user_groups.items():
        if petition_id is None:
            continue

        seen_fingerprints: set[str] = set()
        for execution in sorted(grouped_revisions, key=lambda item: ((item.revision_number or 0), item.created_at or datetime.now(), item.id)):
            payload = load_execution_result_payload(execution)
            findings = payload.get('findings') or []
            month_key = (execution.created_at or execution.updated_at or datetime.now()).strftime('%Y-%m')
            petition_key = execution.petition_id or execution.id
            petition_history = lawyer_stats[user_id]['petition_history'].get(petition_key)

            for finding in findings:
                fingerprint = build_finding_fingerprint(finding)
                if not fingerprint:
                    continue
                if fingerprint in seen_fingerprints:
                    lawyer_stats[user_id]['repeated_findings'] += 1
                    lawyer_stats[user_id]['monthly'][month_key]['repeated_findings'] += 1
                    if petition_history:
                        petition_history['repeated_findings'] += 1
                seen_fingerprints.add(fingerprint)

    lawyers: list[dict] = []
    total_findings_overall = 0
    total_repeated_overall = 0

    for stats in lawyer_stats.values():
        petitions_count = len(stats['petitions'])
        rework_petitions = sum(
            1 for petition_data in stats['petition_history'].values()
            if petition_data['revision_count'] > 1
        )
        completed_revisions = stats['completed_revisions'] or 0
        total_findings = stats['total_findings'] or 0
        repeated_findings = stats['repeated_findings'] or 0
        recurrence_rate = (repeated_findings / total_findings) if total_findings else 0.0
        rework_ratio = (rework_petitions / petitions_count) if petitions_count else 0.0
        avg_findings_per_revision = (total_findings / completed_revisions) if completed_revisions else 0.0

        monthly_trend = []
        for month_key in sorted(stats['monthly'].keys())[-6:]:
            month_metrics = stats['monthly'][month_key]
            monthly_trend.append({
                'month_key': month_key,
                'label': f"{month_key[5:7]}/{month_key[0:4]}",
                'revisions': month_metrics['revisions'],
                'findings': month_metrics['findings'],
                'repeated_findings': month_metrics['repeated_findings'],
            })

        petition_history_rows = []
        for petition_data in stats['petition_history'].values():
            top_category = petition_data['categories'].most_common(1)
            petition_history_rows.append({
                **petition_data,
                'top_category': top_category[0][0] if top_category else '-',
            })

        petition_history_rows.sort(
            key=lambda item: (item['revision_count'], item['latest_at'] or datetime.now()),
            reverse=True,
        )

        total_findings_overall += total_findings
        total_repeated_overall += repeated_findings

        lawyers.append({
            'user_id': stats['user'].id,
            'name': stats['user'].name,
            'role': translate_user_role(stats['user'].role),
            'score': calculate_lawyer_score(total_findings, completed_revisions, rework_ratio, recurrence_rate),
            'total_revisions': stats['total_revisions'],
            'completed_revisions': completed_revisions,
            'petitions_count': petitions_count,
            'rework_petitions': rework_petitions,
            'rework_ratio': rework_ratio,
            'total_findings': total_findings,
            'critical_findings': stats['critical_findings'],
            'moderate_findings': stats['moderate_findings'],
            'formal_findings': stats['formal_findings'],
            'repeated_findings': repeated_findings,
            'recurrence_rate': recurrence_rate,
            'avg_findings_per_revision': avg_findings_per_revision,
            'top_categories': stats['categories'].most_common(5),
            'petition_history': petition_history_rows,
            'monthly_trend': monthly_trend,
        })

    lawyers.sort(
        key=lambda item: (-item['score'], item['recurrence_rate'], item['avg_findings_per_revision'], item['name'].lower()),
    )

    for index, lawyer in enumerate(lawyers, start=1):
        lawyer['rank'] = index

    overview = {
        'total_lawyers': len(lawyers),
        'total_revisions': len(revisions),
        'total_findings': total_findings_overall,
        'repeated_findings': total_repeated_overall,
        'recurrence_rate': (total_repeated_overall / total_findings_overall) if total_findings_overall else 0.0,
    }

    return {
        'overview': overview,
        'lawyers': lawyers,
    }

