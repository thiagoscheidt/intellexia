"""
Revisor de Petições FAP — regras de workflow compartilhadas.

Fonte única para a tela (``app/blueprints/fap_review.py``) e para o MCP: o status
agregado da petição, o título, a leitura do resultado e o registro de uma revisão
seguem a mesma regra nos dois caminhos — como já fazemos no ``fap_digest_service``
e nos exports em Excel.

``log_audit`` recebe ``user_id`` explicitamente porque o MCP não tem sessão Flask;
o blueprint mantém um wrapper que injeta o usuário da sessão.
"""
import difflib
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import func

from app.agents.fap_review.finding_sanitizer import fingerprint_achado
from app.models import (
    db, FapReviewAuditLog, FapReviewExecution, FapReviewFindingCheck, FapReviewIgnoredFinding,
    FapReviewPetition, FapReviewPromptVersion, FapReviewReferenceVersion,
)
from app.models import User as _Usuario

logger = logging.getLogger(__name__)

# Rótulos do status agregado da petição (o comment da coluna lista os códigos).
PETITION_WORKFLOW_STATUSES = {
    'new': 'Nova',
    'in_review': 'Em revisão',
    'awaiting_adjustments': 'Aguardando ajustes',
    'awaiting_approval': 'Aguardando aprovação',
    'ready_for_filing': 'Aprovada pelo revisor',
    'filed': 'Processo iniciado',
    'archived': 'Arquivada',
}

# Desfecho da triagem escolhido pelo usuário → status resultante.
TRIAGE_OUTCOME_STATUSES = {
    'new_version': 'awaiting_adjustments',   # "Revisada — enviar nova versão"
    'final_version': 'awaiting_approval',    # "Versão final — enviar para aprovação"
}

# Petição aguardando aprovação/aprovada/protocolada/arquivada não aceita novo
# ciclo de revisão (admin destrava com "Devolver para ajustes"/"Reabrir petição").
NEW_REVISION_BLOCKED_STATUSES = {'awaiting_approval', 'ready_for_filing', 'filed', 'archived'}

MAX_IDENTIFIER_LENGTH = 96

# Rótulo para execução sem modelo gravado. NUNCA substituir por um nome de
# modelo "provável": foi um literal chutado no template que produziu o RPI-18,
# com o debug anunciando gpt-4o-mini enquanto o Sonnet rodava. A configuração
# do escritório pode ter mudado desde a execução — só o que foi gravado vale.
MODEL_NOT_RECORDED = 'não registrado'

# Revisão feita no Claude: o Claude do usuário revisou na conversa, com as
# instruções do Revisor, e o IntellexIA só conferiu e gravou o resultado
# (fap_review_claude_service). O modelo é o que a pessoa escolheu no Claude,
# não o do escritório — por isso a revisão leva selo, fica fora da pontuação,
# não vira ponto de atenção da revisão seguinte e não envia para aprovação.
REVIEW_ORIGIN_CLAUDE = 'claude'
REVIEW_ORIGIN_CLAUDE_LABEL = 'Feita no Claude'
REVIEW_ORIGIN_INTELLEXIA_LABEL = 'IntellexIA'
CLAUDE_REVIEW_APPROVAL_BLOCK = (
    'A última revisão desta petição foi feita no Claude e não envia para aprovação. '
    'Faça uma revisão pela tela do Revisor antes.'
)
APPROVAL_STATUSES = {'awaiting_approval', 'ready_for_filing'}


def is_claude_review(execution) -> bool:
    return bool(execution) and execution.review_origin == REVIEW_ORIGIN_CLAUDE


def describe_review_origin(execution) -> str:
    return REVIEW_ORIGIN_CLAUDE_LABEL if is_claude_review(execution) else REVIEW_ORIGIN_INTELLEXIA_LABEL


def intellexia_reviews_only():
    """Filtro SQL: só revisões feitas pelo IntellexIA (origem vazia)."""
    return db.or_(FapReviewExecution.review_origin.is_(None),
                  FapReviewExecution.review_origin != REVIEW_ORIGIN_CLAUDE)


def latest_revision_is_claude(petition) -> bool:
    """A última revisão da petição foi feita no Claude (trava a ida à aprovação)."""
    if not petition or not petition.latest_revision_id:
        return False
    return is_claude_review(FapReviewExecution.query.get(petition.latest_revision_id))

_SO_DIGITOS = re.compile(r'[0-9]+')


def describe_model_name(value: str | None) -> str:
    """Modelo a exibir para uma execução; ausência é dita, não adivinhada."""
    return str(value or '').strip() or MODEL_NOT_RECORDED


def validate_wrike_identifier(raw: str | None) -> tuple[str, str | None]:
    """Valida o Id Wrike da petição (RPI-23).

    Só dígitos: texto livre quebra a busca por Id e impede relacionar os dados
    com o Wrike depois. Devolve ``(valor_normalizado, mensagem_de_erro | None)``.

    O valor é tratado como identificador, não como número — zero à esquerda é
    preservado, e por isso a normalização apara as pontas mas não converte.
    """
    valor = str(raw or '').strip()

    if not valor:
        return '', 'Informe o Id Wrike da petição.'
    if len(valor) > MAX_IDENTIFIER_LENGTH:
        return valor, f'O Id Wrike pode ter no máximo {MAX_IDENTIFIER_LENGTH} caracteres.'
    # `str.isdigit()` aceita '²' e '١٢٣'; ambos passariam e quebrariam
    # exatamente a busca por Id que este requisito existe para proteger.
    if not _SO_DIGITOS.fullmatch(valor):
        return valor, 'O Id Wrike deve conter apenas números.'

    return valor, None

# Só revisão que falhou pode ser reexecutada com os mesmos arquivos.
# 'completed' fica de fora para não sobrescrever achados já triados, e
# 'processing'/'pending' para não disparar duas execuções (cada clique custa uma
# chamada de modelo). Execução presa em 'processing' não precisa estar aqui: o
# watchdog de `revision_result` já a converte em 'failed'.
REPROCESSABLE_EXECUTION_STATUSES = frozenset({'failed'})

# Tempo além do qual uma execução em 'processing' é dada como interrompida.
# A revisão roda em thread daemon: se o processo web reiniciar no meio, ela
# ficaria presa em "processando" para sempre.
PROCESSING_TIMEOUT_SECONDS = 15 * 60


def is_execution_stuck(execution, now: datetime | None = None) -> bool:
    """Execução presa em 'processing' além do tempo limite.

    Mede desde `updated_at` — o início do processamento ATUAL —, não desde
    `created_at`. A diferença importa no reprocessamento: a execução é antiga
    por criação e recém-iniciada por processamento, e medir pela criação a
    marcaria como interrompida no instante seguinte ao clique, antes de o
    agente ter qualquer chance de responder.
    """
    if execution.status != 'processing':
        return False
    started = execution.updated_at or execution.created_at
    if not started:
        return False
    return ((now or datetime.now()) - started).total_seconds() > PROCESSING_TIMEOUT_SECONDS


def describe_reprocess_block(execution) -> str | None:
    """Motivo pelo qual a execução não pode ser reprocessada; None quando pode."""
    if execution.execution_type != 'revision':
        return 'Apenas revisões podem ser reprocessadas.'
    if execution.status not in REPROCESSABLE_EXECUTION_STATUSES:
        label = 'concluída' if execution.status == 'completed' else 'em processamento'
        return (
            f'Esta revisão está {label} e não pode ser reprocessada. '
            'O reprocessamento existe para revisões que falharam.'
        )
    return None


def reset_execution_for_reprocess(execution) -> None:
    """Devolve a execução ao estado inicial de processamento.

    Preserva `revision_number` — a numeração representa a versão da petição
    revisada, não a tentativa de processamento — e preserva `result_json`, que
    pode conter resultado aproveitável de uma execução que falhou só na etapa de
    contabilidade de custo, depois de o modelo já ter respondido.
    """
    execution.status = 'processing'
    execution.error_message = None
    execution.completed_at = None
    # Marca o início DESTE processamento: é o relógio que `is_execution_stuck`
    # lê. Explícito em vez de confiar no `onupdate` do ORM, porque disso depende
    # o watchdog não matar o reprocessamento no instante seguinte ao clique.
    execution.updated_at = datetime.now()


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


REVIEWER_PROMPT_TYPES = ('revisor_identity', 'revisor_rules', 'revisor_output_format')
REVIEWER_REFERENCE_TYPES = ('manual_fap', 'casos_referencia', 'project_instructions')


def collect_active_versions(law_firm_id: int, prompt_types: tuple = REVIEWER_PROMPT_TYPES) -> dict:
    """Snapshot das versões ativas de prompt/referência do revisor.

    Gravado em ``FapReviewExecution.used_versions_json`` para responder, depois,
    "com qual prompt esta revisão rodou?" — tela e MCP usam o mesmo helper. O
    treinamento passa os prompts que ele usa (``training_prompt_types``).
    """
    versions: dict[str, dict] = {}
    for prompt_type in prompt_types:
        version = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id, prompt_type=prompt_type, is_active=True,
        ).first()
        if version:
            versions[prompt_type] = {'id': version.id, 'version': version.version_number}
    for reference_type in REVIEWER_REFERENCE_TYPES:
        version = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id, reference_type=reference_type, is_active=True,
        ).first()
        if version:
            versions[reference_type] = {'id': version.id, 'version': version.version_number}
    return versions


def derive_petition_workflow_status(execution_status: str) -> str:
    """Traduz o status da revisão para o status agregado da petição.

    Revisão concluída fica 'in_review' (usuário ainda vai triar os achados);
    'awaiting_adjustments' é decisão humana ao concluir a triagem — exceto em
    falha, que exige novo envio.
    """
    if execution_status in {'pending', 'processing', 'completed'}:
        return 'in_review'
    if execution_status == 'failed':
        return 'awaiting_adjustments'
    return 'new'


def status_transition_requires_admin(old_status: str, new_status: str) -> bool:
    """Transições reservadas ao admin: aprovar, devolver para ajustes e reabrir.

    Regra simétrica de tela × endpoint: entrar em 'ready_for_filing' ou sair de
    'awaiting_approval'/'ready_for_filing' exige usuário admin.
    """
    if new_status == 'ready_for_filing':
        return True
    return old_status in {'awaiting_approval', 'ready_for_filing'}


class StatusChangeRefused(ValueError):
    """Mudança de status recusada, com a mensagem para o usuário e o status HTTP."""

    def __init__(self, message: str, status_http: int = 400):
        super().__init__(message)
        self.status_http = status_http


def change_petition_status(petition: FapReviewPetition, new_status: str, *, user_id: int | None,
                           user_role: str | None, via: str = '') -> str:
    """Muda o status agregado da petição com as regras da tela. Devolve o status anterior.

    Fonte única do seletor de status, do arrastar do kanban e da ferramenta
    `mudar_status_peticao` do MCP — o Claude não pode ser porta lateral:
    aprovar, devolver para ajustes e reabrir são do admin
    (`status_transition_requires_admin`), e quem não é admin não manda para
    aprovação a petição cuja última revisão foi feita no Claude. ``via`` vai
    para a auditoria (ex.: "via Claude"). Levanta StatusChangeRefused.
    """
    new_status = str(new_status or '').strip()
    if new_status not in PETITION_WORKFLOW_STATUSES:
        raise StatusChangeRefused('Status da petição inválido.', 400)
    old_status = petition.workflow_status
    if new_status == old_status:
        return old_status
    is_admin = user_role == 'admin'
    if status_transition_requires_admin(old_status, new_status) and not is_admin:
        raise StatusChangeRefused('Apenas administradores podem executar esta mudança de status.', 403)
    # O advogado não leva à aprovação o que o modelo do escritório não revisou.
    if new_status in APPROVAL_STATUSES and not is_admin and latest_revision_is_claude(petition):
        raise StatusChangeRefused(CLAUDE_REVIEW_APPROVAL_BLOCK, 403)

    now = datetime.now()
    petition.workflow_status = new_status
    petition.status_changed_at = now
    petition.updated_at = now
    db.session.commit()

    description = (f'Status alterado de {PETITION_WORKFLOW_STATUSES.get(old_status, old_status)} '
                   f'para {PETITION_WORKFLOW_STATUSES.get(new_status, new_status)}')
    if via:
        description += f' ({via})'
    log_audit(petition.law_firm_id, user_id, 'petition_status_updated', 'petition', petition.id,
              description, old_value=old_status, new_value=new_status)
    return old_status


def is_triage_complete(total_findings: int, checked_indices: set[int],
                       ignored_indices: set[int]) -> bool:
    """Triagem completa: todo ponto (1..N) está checado como revisado ou descartado."""
    if total_findings <= 0:
        return True
    triaged = {i for i in (checked_indices | ignored_indices) if 1 <= i <= total_findings}
    return len(triaged) >= total_findings


# ── Triagem dos achados ─────────────────────────────────────────────
# Fonte única dos botões "Marcar como revisado", "Não pertinente" e "Concluir
# triagem" da tela de resultado e da ferramenta `triar_achados_revisao` do MCP.
# "Revisado" vale só para a execução; "não pertinente" vale para o documento
# (Id Wrike): o achado com a mesma impressão digital não volta nas próximas revisões.

TRIAGE_SUPERSEDED = ('Esta revisão foi substituída por uma versão mais recente — '
                     'a triagem é feita na revisão atual.')
TRIAGE_OUTCOME_LABELS = {
    'new_version': 'Triagem concluída: usuário vai enviar nova versão',
    'final_version': 'Triagem concluída: versão final aguardando aprovação do revisor',
}


class TriageRefused(StatusChangeRefused):
    """Triagem recusada, com a mensagem para o usuário e o status HTTP."""


def ignored_finding_fingerprints(law_firm_id: int, law_firm_document_identifier: str) -> set[str]:
    """Impressões digitais dos achados marcados como não pertinentes no documento."""
    if not law_firm_document_identifier:
        return set()
    rows = FapReviewIgnoredFinding.query.filter_by(
        law_firm_id=law_firm_id,
        law_firm_document_identifier=law_firm_document_identifier,
    ).with_entities(FapReviewIgnoredFinding.finding_fingerprint).all()
    return {str(row[0]) for row in rows if row and row[0]}


def _triage_findings_list(execution: FapReviewExecution) -> list:
    findings = load_execution_result_payload(execution).get('findings') or []
    return findings if isinstance(findings, list) else []


def triage_state(execution: FapReviewExecution) -> dict:
    """Estado da triagem de uma execução: revisados, não pertinentes e se está completa."""
    findings = _triage_findings_list(execution)
    total = len(findings)
    checked = {row.finding_index for row in FapReviewFindingCheck.query.filter_by(execution_id=execution.id)}
    ignored: set[int] = set()
    if execution.law_firm_document_identifier and total:
        fingerprints = ignored_finding_fingerprints(execution.law_firm_id, execution.law_firm_document_identifier)
        ignored = {i for i, finding in enumerate(findings, start=1)
                   if build_finding_fingerprint(finding) in fingerprints}
    return {
        'total_findings': total,
        'checked_indices': checked,
        'ignored_indices': ignored,
        'complete': is_triage_complete(total, checked, ignored),
    }


def _triage_open(execution: FapReviewExecution) -> list:
    if is_execution_superseded(execution):
        raise TriageRefused(TRIAGE_SUPERSEDED, 409)
    return _triage_findings_list(execution)


def _finding_at(findings: list, finding_index: int) -> dict:
    if finding_index < 1 or finding_index > len(findings):
        raise TriageRefused('Ponto de atenção não encontrado nesta revisão.', 404)
    return findings[finding_index - 1]


def _set_checked(execution, finding_index: int, checked: bool, user_id: int | None) -> None:
    existing = FapReviewFindingCheck.query.filter_by(execution_id=execution.id, finding_index=finding_index).first()
    if checked and not existing:
        db.session.add(FapReviewFindingCheck(law_firm_id=execution.law_firm_id, execution_id=execution.id,
                                             finding_index=finding_index, created_by_id=user_id))
    elif not checked and existing:
        db.session.delete(existing)


def _set_dismissed(execution, finding: dict, dismissed: bool, user_id: int | None) -> str | None:
    """Grava ou desfaz o "não pertinente". Devolve a ação de auditoria, ou None se nada mudou."""
    fingerprint = build_finding_fingerprint(finding)
    if not fingerprint:
        raise TriageRefused('Não foi possível identificar o ponto de atenção selecionado.', 400)
    existing = FapReviewIgnoredFinding.query.filter_by(
        law_firm_id=execution.law_firm_id,
        law_firm_document_identifier=execution.law_firm_document_identifier,
        finding_fingerprint=fingerprint,
    ).first()
    if dismissed:
        if not existing:
            db.session.add(FapReviewIgnoredFinding(
                law_firm_id=execution.law_firm_id,
                law_firm_document_identifier=execution.law_firm_document_identifier,
                source_execution_id=execution.id,
                created_by_id=user_id,
                finding_fingerprint=fingerprint,
                finding_description=str(finding.get('description') or '').strip(),
            ))
        return 'revision_finding_dismissed'
    if existing:
        db.session.delete(existing)
        return 'revision_finding_dismiss_undone'
    return None


def _audit_triage(execution, user_id: int | None, dismiss_audits: list[tuple[str, dict]],
                  petition_status_changed: bool, via: str = '') -> None:
    """Auditoria depois do commit: falhar aqui não desfaz a triagem já gravada."""
    sufixo = f' ({via})' if via else ''
    try:
        for action, finding in dismiss_audits:
            description = str(finding.get('description') or '').strip()[:200]
            texto = (f'Ponto marcado como não útil: {description}' if action == 'revision_finding_dismissed'
                     else f'Ponto voltou a ser considerado no histórico: {description}')
            log_audit(execution.law_firm_id, user_id, action, 'execution', execution.id, texto + sufixo)
        if petition_status_changed:
            log_audit(execution.law_firm_id, user_id, 'petition_status_updated', 'petition', execution.petition.id,
                      'Status alterado para Em revisão ao triar pontos de atenção' + sufixo, new_value='in_review')
    except Exception as error:  # noqa: BLE001
        db.session.rollback()
        logger.warning('Triagem salva, mas falha ao registrar auditoria: %s', error)


def set_finding_checked(execution: FapReviewExecution, finding_index: int, checked: bool, *,
                        user_id: int | None) -> None:
    """"Marcar como revisado" de um achado (e desfazer). Levanta TriageRefused."""
    _finding_at(_triage_open(execution), finding_index)
    _set_checked(execution, finding_index, checked, user_id)
    # Triar achados significa que o usuário está revisando a petição
    mark_petition_in_user_review(execution.petition)
    db.session.commit()


def set_finding_dismissed(execution: FapReviewExecution, finding_index: int, dismissed: bool, *,
                          user_id: int | None, via: str = '') -> None:
    """"Não pertinente" de um achado (e desfazer), para as próximas revisões do documento."""
    if not execution.law_firm_document_identifier:
        raise TriageRefused('Esta revisão não possui identificador de documento para persistir feedback.', 400)
    finding = _finding_at(_triage_open(execution), finding_index)
    action = _set_dismissed(execution, finding, dismissed, user_id)
    status_changed = mark_petition_in_user_review(execution.petition)
    db.session.commit()
    _audit_triage(execution, user_id, [(action, finding)] if action else [], status_changed, via)


def _numeros_da_triagem(valores, total: int) -> set[int]:
    numeros = set()
    for valor in valores or []:
        try:
            numero = int(str(valor).strip())
        except (TypeError, ValueError):
            raise TriageRefused(f'"{valor}" não é número de achado.', 400) from None
        if numero < 1 or numero > total:
            raise TriageRefused(f'Não existe o achado {numero}: esta revisão tem {total} achado(s).', 400)
        numeros.add(numero)
    return numeros


def triage_findings(execution: FapReviewExecution, *, pertinentes=None, nao_pertinentes=None,
                    demais_pertinentes: bool = False, user_id: int | None, via: str = '') -> dict:
    """Triagem em lote: pertinente = "revisado"; não pertinente = não volta nas próximas revisões.

    Confere tudo antes de gravar — um número errado não deixa a triagem pela
    metade. ``demais_pertinentes`` marca como revisado o que ainda não foi
    triado ("o resto está ok"). Devolve o estado da triagem depois de gravar.
    """
    findings = _triage_open(execution)
    total = len(findings)
    if not total:
        raise TriageRefused('Esta revisão não tem pontos de atenção para triar.', 400)
    sim = _numeros_da_triagem(pertinentes, total)
    nao = _numeros_da_triagem(nao_pertinentes, total)
    if sim & nao:
        repetidos = ', '.join(map(str, sorted(sim & nao)))
        raise TriageRefused(f'O achado {repetidos} está como pertinente e como não pertinente: escolha um.', 400)
    if not (sim or nao or demais_pertinentes):
        raise TriageRefused('Diga quais achados foram pertinentes e quais não foram.', 400)
    if nao and not execution.law_firm_document_identifier:
        raise TriageRefused('Esta revisão não tem Id Wrike: o "não pertinente" não tem onde ser guardado.', 400)

    if demais_pertinentes:
        state = triage_state(execution)
        triados = state['checked_indices'] | state['ignored_indices'] | sim | nao
        sim |= set(range(1, total + 1)) - triados

    dismiss_audits = []
    for numero in sorted(nao):
        action = _set_dismissed(execution, findings[numero - 1], True, user_id)
        _set_checked(execution, numero, False, user_id)
        dismiss_audits.append((action, findings[numero - 1]))
    db.session.flush()
    for numero in sorted(sim):
        action = _set_dismissed(execution, findings[numero - 1], False, user_id)
        _set_checked(execution, numero, True, user_id)
        if action:
            dismiss_audits.append((action, findings[numero - 1]))
    status_changed = mark_petition_in_user_review(execution.petition)
    db.session.commit()
    _audit_triage(execution, user_id, dismiss_audits, status_changed, via)
    if sim:
        try:
            log_audit(execution.law_firm_id, user_id, 'revision_findings_checked', 'execution', execution.id,
                      f'{len(sim)} ponto(s) de atenção marcados como revisados' + (f' ({via})' if via else ''))
        except Exception as error:  # noqa: BLE001
            db.session.rollback()
            logger.warning('Triagem salva, mas falha ao registrar auditoria: %s', error)
    return triage_state(execution)


def complete_triage(execution: FapReviewExecution, outcome: str, *, user_id: int | None,
                    via: str = '') -> str:
    """Conclui a triagem: nova versão ou versão final para aprovação. Devolve o status anterior.

    Mesmas travas da tela: revisão atual, desfecho válido, revisão feita no
    Claude não vai para aprovação, petição travada não muda e todo achado tem
    de estar triado. Levanta TriageRefused.
    """
    petition = execution.petition
    if not petition:
        raise TriageRefused('Esta revisão não está vinculada a uma petição.', 400)
    _triage_open(execution)
    new_status = TRIAGE_OUTCOME_STATUSES.get(str(outcome or '').strip())
    if not new_status:
        raise TriageRefused('Desfecho de triagem inválido.', 400)
    if new_status in APPROVAL_STATUSES and is_claude_review(execution):
        raise TriageRefused(CLAUDE_REVIEW_APPROVAL_BLOCK, 403)
    if petition.workflow_status in NEW_REVISION_BLOCKED_STATUSES:
        raise TriageRefused('Esta petição está travada para triagem. Um administrador pode reabri-la.', 403)

    state = triage_state(execution)
    if not state['complete']:
        pendentes = (set(range(1, state['total_findings'] + 1))
                     - state['checked_indices'] - state['ignored_indices'])
        raise TriageRefused(
            f'Ainda há {len(pendentes)} ponto(s) de atenção sem triagem '
            f'({", ".join(map(str, sorted(pendentes)))}). '
            'Marque cada um como revisado ou não pertinente antes de concluir.', 400)

    old_status = petition.workflow_status
    if old_status != new_status:
        petition.workflow_status = new_status
        petition.status_changed_at = datetime.now()
        petition.updated_at = datetime.now()
    db.session.commit()
    log_audit(execution.law_firm_id, user_id, 'revision_triage_completed', 'petition', petition.id,
              TRIAGE_OUTCOME_LABELS[str(outcome).strip()] + (f' ({via})' if via else ''),
              old_value=old_status, new_value=new_status)
    return old_status


def count_pending_review_queues(law_firm_id: int) -> dict:
    """Filas ativas do Revisor para o painel de notificações — um count agrupado, com índice.

    'in_review' agrega novas + em revisão (mesmo agrupamento do card do painel);
    'awaiting_adjustments' é ação do advogado (enviar nova versão);
    'awaiting_approval' é ação do revisor (admin).
    """
    counts = dict(
        db.session.query(FapReviewPetition.workflow_status, func.count(FapReviewPetition.id))
        .filter(
            FapReviewPetition.law_firm_id == law_firm_id,
            FapReviewPetition.workflow_status.in_(
                ['new', 'in_review', 'awaiting_adjustments', 'awaiting_approval']),
        )
        .group_by(FapReviewPetition.workflow_status)
        .all()
    )
    return {
        'in_review': counts.get('new', 0) + counts.get('in_review', 0),
        'awaiting_adjustments': counts.get('awaiting_adjustments', 0),
        'awaiting_approval': counts.get('awaiting_approval', 0),
    }


SEM_REVISOR = 'Sem revisor'

# Petição sem status gravado não é arquivada — e `!= 'archived'` sozinho, em
# SQL, deixaria o NULL de fora da conta.
PETITION_NOT_ARCHIVED = db.or_(
    FapReviewPetition.workflow_status.is_(None),
    FapReviewPetition.workflow_status != 'archived',
)


def agrupar_peticoes_por_advogado(linhas) -> list[dict]:
    """Linhas ``(user_id, nome, status, quantidade)`` viram um grupo por advogado.

    Separado da query de propósito: a forma do agrupamento — total somado,
    quebra por status, ordenação — é o que a tela consome, e testá-la não pode
    depender de banco.

    Ordena por volume, porque é a fila maior que interessa primeiro; empate cai
    na ordem alfabética, senão a lista dançaria a cada recarga. Petição ainda
    sem revisão vira um grupo próprio, sempre por último: não é advogado, é a
    ausência de um, e esconder essas petições faria o contador não fechar com a
    listagem.
    """
    grupos: dict = {}
    for user_id, nome, status, quantidade in linhas:
        if not quantidade:
            continue
        grupo = grupos.setdefault(user_id, {
            'user_id': user_id,
            'name': (nome or '').strip() or SEM_REVISOR,
            'total': 0,
            'por_status': {},
        })
        grupo['total'] += quantidade
        grupo['por_status'][status] = grupo['por_status'].get(status, 0) + quantidade

    return sorted(
        grupos.values(),
        key=lambda g: (g['user_id'] is None, -g['total'], g['name'].lower()),
    )


def lawyer_petition_counts(law_firm_id: int) -> list[dict]:
    """Petições por advogado e por situação — o contador do RPI-04.

    O advogado é quem enviou a **última** revisão da petição, que é o nome já
    exibido na linha da listagem. Arquivadas ficam fora: a listagem também as
    esconde por padrão, e contador que não bate com o que se vê na tela mente.
    """
    linhas = (
        db.session.query(
            FapReviewExecution.user_id,
            _Usuario.name,
            FapReviewPetition.workflow_status,
            func.count(FapReviewPetition.id),
        )
        .select_from(FapReviewPetition)
        .outerjoin(FapReviewExecution,
                   FapReviewExecution.id == FapReviewPetition.latest_revision_id)
        .outerjoin(_Usuario, _Usuario.id == FapReviewExecution.user_id)
        .filter(
            FapReviewPetition.law_firm_id == law_firm_id,
            FapReviewPetition.workflow_status != 'archived',
        )
        .group_by(FapReviewExecution.user_id, _Usuario.name,
                  FapReviewPetition.workflow_status)
        .all()
    )
    return agrupar_peticoes_por_advogado(linhas)


def mark_petition_in_user_review(petition: FapReviewPetition | None) -> bool:
    """Marca a petição como 'Em revisão' quando o usuário começa a triar os achados.

    Disparado pelos botões "Não pertinente" e "Marcar como revisado" da tela de
    resultado. Só promove a partir de estados pré-triagem; nunca rebaixa petição
    aprovada, protocolada ou arquivada. Não faz commit — responsabilidade do chamador.
    """
    if not petition or petition.workflow_status not in {'new', 'awaiting_adjustments'}:
        return False

    petition.workflow_status = 'in_review'
    petition.status_changed_at = datetime.now()
    petition.updated_at = datetime.now()
    return True


def is_execution_superseded(execution: FapReviewExecution) -> bool:
    """Revisão concluída que deixou de ser a corrente da petição (chegou versão mais nova).

    Derivado de ``petition.latest_revision_id`` — o ``status`` da execução não é
    mutado, pois alimenta histórico, score de advogados e revisão focada.
    """
    petition = execution.petition
    return bool(
        execution.execution_type == 'revision'
        and execution.status == 'completed'
        and petition
        and petition.latest_revision_id
        and petition.latest_revision_id != execution.id
    )


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
        new_status = derive_petition_workflow_status(execution.status)
        if new_status != petition.workflow_status:
            petition.workflow_status = new_status
            petition.status_changed_at = datetime.now()

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


def describe_new_revision_block(petition) -> str | None:
    """Motivo pelo qual a petição não aceita revisão nova; None quando aceita."""
    if not petition or petition.workflow_status not in NEW_REVISION_BLOCKED_STATUSES:
        return None
    status_label = PETITION_WORKFLOW_STATUSES.get(petition.workflow_status, petition.workflow_status)
    unlock_hint = (
        'Um administrador deve aprová-la ou devolvê-la para ajustes.'
        if petition.workflow_status == 'awaiting_approval'
        else 'Um administrador pode reabri-la para ajustes.'
    )
    return f'Esta petição está "{status_label}" e não aceita nova revisão. {unlock_hint}'


def check_new_revision_allowed(law_firm_id: int, identifier: str) -> tuple:
    """Confere se o Id Wrike aceita revisão nova, como a tela.

    Devolve ``(petição existente ou None, identificador normalizado)``. Levanta
    ValueError com a mensagem para o usuário: Id inválido para petição nova ou
    petição bloqueada (aguardando aprovação, aprovada, protocolada, arquivada).
    """
    identifier = str(identifier or '').strip()
    petition = None
    if identifier:
        petition = FapReviewPetition.query.filter_by(
            law_firm_id=law_firm_id,
            office_document_identifier=identifier,
        ).first()
    if not petition:
        # Só petição nova passa pela validação, como na tela: a existente pode
        # ter Id anterior ao RPI-23 e continua aceitando revisão.
        identifier, identifier_error = validate_wrike_identifier(identifier)
        if identifier_error:
            raise ValueError(identifier_error)

    block = describe_new_revision_block(petition)
    if block:
        raise ValueError(block)
    return petition, identifier


def running_revision(petition) -> FapReviewExecution | None:
    """Revisão da petição ainda em processamento (não presa), se houver."""
    if not petition:
        return None
    running = FapReviewExecution.query.filter_by(
        petition_id=petition.id,
        execution_type='revision',
        status='processing',
    ).order_by(FapReviewExecution.id.desc()).first()
    if running and not is_execution_stuck(running):
        return running
    return None


def _next_revision_number(petition) -> int:
    if not petition:
        return 1
    return FapReviewExecution.query.filter_by(
        petition_id=petition.id,
        execution_type='revision',
    ).count() + 1


STUCK_EXECUTION_MESSAGE = ('Processamento interrompido (tempo excedido — provável reinício '
                           'do servidor). Envie a revisão novamente.')


def fail_if_stuck(execution) -> bool:
    """Marca como falha a revisão presa em 'processing'; True se marcou."""
    if not is_execution_stuck(execution):
        return False
    execution.status = 'failed'
    execution.error_message = STUCK_EXECUTION_MESSAGE
    execution.completed_at = datetime.now()
    sync_petition_after_revision(execution)
    db.session.commit()
    return True


def revision_result_url(execution_id: int) -> str:
    """Endereço absoluto da tela da revisão, também fora de requisição (MCP, thread)."""
    from flask import current_app, url_for
    from app.utils.urls import app_public_url

    with current_app.test_request_context(base_url=app_public_url()):
        return url_for('fap_review.revision_result', execution_id=execution_id, _external=True)


# ── Estatísticas por advogado ────────────────────────────────────────────────
# Extraídas do blueprint: a tela (admin) e a tool MCP mostram o mesmo número.


def normalize_finding_field(value: object) -> str:
    """Normaliza campo textual de achado para fingerprint estável."""
    return ' '.join(str(value or '').strip().split()).lower()


def build_finding_fingerprint(finding: dict | None) -> str:
    """Gera fingerprint estável de um achado para persistir feedback do usuário.

    Delega ao saneador (função pura, sem Flask) para que a identidade usada na
    deduplicação dentro de uma revisão e a usada para reconhecer achado
    descartado entre revisões sejam literalmente a mesma. Divergindo, um achado
    marcado "não pertinente" voltaria a aparecer na revisão seguinte.
    """
    return fingerprint_achado(finding)


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


# Nível de prioridade -> (rótulo exibido, cor Bootstrap). O primeiro alias que
# casar vence, então os mais longos vêm antes dentro de cada grupo.
_CORRECTION_PRIORITY_LEVELS = (
    (('altíssima', 'altissima', 'alta', 'urgente', 'high'), 'Alta', 'danger'),
    (('média', 'media', 'moderada', 'medium', 'moderate'), 'Média', 'warning'),
    (('baixa', 'low'), 'Baixa', 'success'),
    (('sem achados', 'nenhuma', 'n/a'), 'Sem achados', 'secondary'),
    (('erro na análise', 'erro na analise'), 'Erro na análise', 'secondary'),
)

# Pontuação que separa o nível do texto que vem depois ("Alta — corrigir...").
_CORRECTION_PRIORITY_SEPARATOR = re.compile(r'^[\s\-—–:;,.]+')


def split_correction_priority(value: object) -> dict:
    """Separa o nível de prioridade do plano de ação escrito junto.

    O contrato do agente pede ALTA|MÉDIA|BAIXA, mas o modelo costuma devolver
    "Alta — corrigir prioritariamente os 7 achados críticos (...) antes do
    protocolo". Um parágrafo não cabe numa pílula (`.badge` é `nowrap`, e a
    linha empurrava a tela inteira para a rolagem horizontal): o nível vira o
    selo colorido e o resto vira texto corrido.

    Nível desconhecido não vira selo — o texto inteiro vai para `detail`, que
    quebra linha normalmente.
    """
    raw = ' '.join(str(value or '').split())
    if not raw:
        return {'raw': '', 'level': '', 'level_style': 'secondary', 'detail': ''}

    lowered = raw.lower()
    for aliases, label, style in _CORRECTION_PRIORITY_LEVELS:
        for alias in aliases:
            if not lowered.startswith(alias):
                continue

            rest = raw[len(alias):]
            # "Altamente recomendável" não é o nível "Alta": depois do alias
            # tem de vir pontuação ou o fim da string.
            if rest and not _CORRECTION_PRIORITY_SEPARATOR.match(rest):
                continue

            detail = _CORRECTION_PRIORITY_SEPARATOR.sub('', rest).strip()
            if detail:
                detail = detail[0].upper() + detail[1:]
            return {'raw': raw, 'level': label, 'level_style': style, 'detail': detail}

    return {'raw': raw, 'level': '', 'level_style': 'secondary', 'detail': raw}


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
    """Consolida score e métricas dos advogados a partir do histórico de revisões.

    Revisão de petição arquivada fica de fora (RPI-09): arquivar é como se tira
    da conta um caso de teste ou um projeto duplicado por erro de Id Wrike, e
    eles não podem pesar no desempenho de ninguém. Revisão sem petição
    vinculada continua contando.
    """
    revisions = FapReviewExecution.query.outerjoin(
        FapReviewPetition, FapReviewPetition.id == FapReviewExecution.petition_id,
    ).filter(
        FapReviewExecution.law_firm_id == law_firm_id,
        FapReviewExecution.execution_type == 'revision',
        db.or_(FapReviewPetition.id.is_(None), PETITION_NOT_ARCHIVED),
        # Revisão feita no Claude é de outro revisor (o modelo que a pessoa
        # escolheu): não mede o advogado.
        intellexia_reviews_only(),
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


# ---------------------------------------------------------------------------
# Treinamento — o que a comparação escreveu e o que o usuário mandou gravar
# ---------------------------------------------------------------------------

# Destinos que o treinamento pode gravar, na ordem em que aparecem na tela.
TRAINING_TARGETS = (
    {'key': 'manual_fap', 'label': 'Manual de revisão FAP'},
    {'key': 'casos_referencia', 'label': 'Casos de referência'},
)

TRAINING_TARGET_LABELS = {target['key']: target['label'] for target in TRAINING_TARGETS}

# Situação da comparação, do ponto de vista de quem está olhando a lista.
# 'pending' é a comparação que já rodou e espera confirmação — antes ela ficava
# nesse estado para sempre, sem nenhuma tela que a reabrisse.
TRAINING_EXECUTION_STATUSES = {
    'processing': {'label': 'Processando', 'style': 'warning', 'icon': 'bi bi-hourglass-split'},
    'pending': {'label': 'Aguardando sua confirmação', 'style': 'warning', 'icon': 'bi bi-hourglass-split'},
    'completed': {'label': 'Concluída', 'style': 'success', 'icon': 'bi bi-check-circle'},
    'failed': {'label': 'Erro', 'style': 'danger', 'icon': 'bi bi-x-circle'},
}


def build_training_edit_groups(
    edits: list[dict],
    current_versions: dict[str, int] | None = None,
    contents: dict[str, str] | None = None,
) -> list[dict]:
    """Um bloco por destino, com as edições propostas para ele já conferidas.

    Cada edição recebe ``id`` (a posição na lista original, que é o que o
    formulário devolve), ``status`` e ``preview`` — o diff pronto para a tela.
    Um destino sem edição nenhuma não vira bloco.
    """
    edits = edits or []
    current_versions = current_versions or {}
    contents = contents or {}

    grouped: list[dict] = []
    for target in TRAINING_TARGETS:
        content = contents.get(target['key'], '')
        do_alvo = []

        for edit_id, edit in enumerate(edits):
            if str(edit.get('target') or '') != target['key']:
                continue
            conferida = verify_reference_edit(edit, content)
            conferida['id'] = edit_id
            conferida['preview'] = build_edit_preview(content, edit)
            conferida['effective_kind'] = effective_edit_kind(
                conferida.get('kind'), conferida['preview'])
            do_alvo.append(conferida)

        if not do_alvo:
            continue

        current = int(current_versions.get(target['key']) or 0)
        grouped.append({
            'key': target['key'],
            'label': target['label'],
            'current_version': current,
            'next_version': current + 1,
            'edits': do_alvo,
            'applicable': sum(1 for e in do_alvo if e['status'] == 'ok'),
        })

    return grouped


def effective_edit_kind(declared_kind: str | None, preview: dict | None) -> str:
    """O tipo que o diff realmente mostra, que nem sempre é o que o modelo disse.

    O modelo às vezes monta o texto novo como "âncora + regra nova". Mecanicamente
    isso é uma adição — nada sai do documento —, mas ele declara ``substitution``.
    A tela mostraria o selo "substituição · a regra vai ser trocada" ao lado de um
    diff sem nenhuma linha vermelha, que é exatamente o descasamento entre rótulo
    e evidência que este módulo passou a evitar. O selo passa a sair do diff.
    """
    linhas = (preview or {}).get('lines') or []
    saiu = any(linha.get('kind') == 'del' for linha in linhas)
    entrou = any(linha.get('kind') == 'ins' for linha in linhas)

    if saiu and entrou:
        # Refinamento e substituição têm a mesma mecânica; o que separa é a
        # intenção, e essa só o modelo sabe.
        return 'refinement' if declared_kind == 'refinement' else 'substitution'
    if entrou and not saiu:
        return 'addition'
    return str(declared_kind or '')


def parse_training_edit_selection(
    selected_ids,
    edits: list[dict],
    texts: dict | None = None,
) -> list[dict]:
    """As edições marcadas, com o texto que estava na caixa quando salvou.

    Edição bloqueada não entra nem se vier marcada: o formulário é do
    navegador e o servidor não confia nele. Caixa esvaziada também não grava —
    o silêncio nesse caminho já foi o bug que fazia a tela anunciar sucesso
    tendo escrito zero.
    """
    edits = edits or []
    texts = texts or {}

    escolhidos = set()
    for raw_id in (selected_ids or []):
        try:
            escolhidos.add(int(raw_id))
        except (TypeError, ValueError):
            continue

    selecao = []
    for edit_id, edit in enumerate(edits):
        if edit_id not in escolhidos:
            continue

        edit = dict(edit)
        override = texts.get(str(edit_id), texts.get(edit_id))
        if override is not None:
            edit['new_text'] = str(override)

        if not str(edit.get('new_text') or '').strip():
            continue

        edit['id'] = edit_id
        selecao.append(edit)

    return selecao


def append_to_reference_content(current_content: str | None, patch: str) -> str:
    """Conteúdo da nova versão: o texto atual com o trecho novo no fim."""
    current = (current_content or '').strip()
    patch = (patch or '').strip()
    if not current:
        return patch
    return f'{current}\n\n{patch}'


def summarize_training_execution(status: str | None, payload: dict | None) -> dict:
    """Situação e destinos gravados de uma comparação, para a listagem.

    Lê os destinos de ``applied.targets``. O template antigo procurava
    ``manual_updates_generated`` na raiz do JSON, mas a gravação sempre pôs
    esse dado sob ``training_result`` — as colunas Manual e Casos mostravam
    "Não" em toda linha, inclusive nas que tinham gravado. O formato antigo
    continua sendo lido para as execuções que já estão no banco.
    """
    payload = payload or {}
    status_key = str(status or '').strip()
    situation = TRAINING_EXECUTION_STATUSES.get(
        status_key,
        {'label': status_key or 'Desconhecida', 'style': 'secondary', 'icon': 'bi bi-question-circle'},
    )

    applied = payload.get('applied') or {}
    targets = []
    for item in applied.get('targets') or []:
        key = str(item.get('key') or '')
        targets.append({
            'key': key,
            'label': item.get('label') or TRAINING_TARGET_LABELS.get(key, key),
            'version_number': item.get('version_number'),
            'activated': bool(item.get('activated')),
        })

    if not targets:
        targets = _legacy_training_targets(payload)

    return {
        'situation': situation,
        'targets': targets,
        'is_pending': status_key == 'pending',
        'is_processing': status_key == 'processing',
    }


def _legacy_training_targets(payload: dict) -> list[dict]:
    """Destinos das execuções gravadas antes do formato ``applied``."""
    legacy = payload.get('training_result') or {}
    versions = legacy.get('reference_versions') or {}

    targets = []
    for key in ('manual_fap', 'casos_referencia'):
        version_number = versions.get(key)
        if not version_number:
            continue
        targets.append({
            'key': key,
            'label': TRAINING_TARGET_LABELS.get(key, key),
            'version_number': version_number,
            'activated': True,
        })
    return targets


# ---------------------------------------------------------------------------
# Treinamento — edições ancoradas no texto da referência
# ---------------------------------------------------------------------------

# Como cada edição se combina com o texto atual da referência.
#   addition      — acrescenta depois da âncora (ou no fim, se não houver âncora)
#   substitution  — troca a âncora pelo texto novo (a regra existia e ficou errada)
#   refinement    — igual à substituição na mecânica; separado porque a intenção
#                   é outra na tela: a regra está certa e ganha precisão
REFERENCE_EDIT_KINDS = ('addition', 'substitution', 'refinement')
_REPLACING_KINDS = ('substitution', 'refinement')

# Por que uma edição não pode ser aplicada.
EDIT_BLOCKED_REASONS = {
    'no_text': 'A edição não traz texto novo.',
    'bad_kind': 'Tipo de edição desconhecido.',
    'no_anchor': 'A edição não diz que trecho do documento ela altera.',
    'not_found': 'O trecho que esta edição diz alterar não existe no documento.',
    'ambiguous': 'O trecho que esta edição diz alterar aparece mais de uma vez no documento.',
}


def verify_reference_edit(edit: dict, content: str) -> dict:
    """Confere uma edição contra o texto atual da referência.

    Devolve a edição com ``status`` (``ok`` ou o motivo do bloqueio). A âncora
    tem de existir **literalmente e uma única vez**: um modelo que escreve o
    trecho de memória produz uma aproximação, e aplicar aproximação no texto
    errado corrompe o manual em silêncio. Melhor recusar e deixar a pessoa
    resolver à mão.
    """
    edit = dict(edit or {})
    content = content or ''

    kind = str(edit.get('kind') or '').strip()
    anchor = str(edit.get('anchor') or '').strip()
    new_text = str(edit.get('new_text') or '').strip()

    if kind not in REFERENCE_EDIT_KINDS:
        edit['status'] = 'bad_kind'
    elif not new_text:
        edit['status'] = 'no_text'
    elif kind in _REPLACING_KINDS and not anchor:
        # Substituir sem dizer o que: viraria acréscimo mudo no fim do arquivo.
        edit['status'] = 'no_anchor'
    elif anchor:
        occurrences = content.count(anchor)
        if occurrences == 0:
            edit['status'] = 'not_found'
        elif occurrences > 1:
            edit['status'] = 'ambiguous'
        else:
            edit['status'] = 'ok'
    else:
        # Adição sem âncora é acréscimo no fim — sempre aplicável.
        edit['status'] = 'ok'

    edit['blocked_reason'] = (
        None if edit['status'] == 'ok' else EDIT_BLOCKED_REASONS.get(edit['status'])
    )
    return edit


def verify_reference_edits(edits: list[dict], contents: dict[str, str]) -> list[dict]:
    """Confere todas as edições contra o conteúdo da referência de cada destino."""
    contents = contents or {}
    return [
        verify_reference_edit(edit, contents.get(str(edit.get('target') or ''), ''))
        for edit in (edits or [])
    ]


def apply_reference_edit(content: str, edit: dict) -> str:
    """Aplica uma edição já verificada e devolve o novo conteúdo."""
    content = content or ''
    kind = str(edit.get('kind') or '')
    anchor = str(edit.get('anchor') or '').strip()
    new_text = str(edit.get('new_text') or '').strip()

    if kind in _REPLACING_KINDS:
        return content.replace(anchor, new_text, 1)

    if anchor:
        return content.replace(anchor, f'{anchor}\n{new_text}', 1)

    return append_to_reference_content(content, new_text)


def apply_reference_edits(content: str, edits: list[dict]) -> tuple[str, list[dict]]:
    """Aplica as edições aceitas, uma a uma, e devolve ``(conteúdo, aplicadas)``.

    Cada edição é reconferida contra o conteúdo **já modificado** pelas
    anteriores: uma edição pode apagar o trecho que a seguinte usava como
    âncora, e aí a seguinte deixa de ser aplicável. Reconferir a cada passo é
    o que impede a segunda de cair no lugar errado.
    """
    content = content or ''
    applied: list[dict] = []

    for edit in edits or []:
        checked = verify_reference_edit(edit, content)
        if checked['status'] != 'ok':
            applied.append(checked)
            continue

        content = apply_reference_edit(content, checked)
        checked['status'] = 'applied'
        applied.append(checked)

    return content, applied


def build_edit_preview(content: str, edit: dict, context_lines: int = 3) -> dict:
    """Monta o diff de uma edição, no formato que a tela desenha.

    Numeração como no ``git``: as linhas de contexto e as removidas trazem o
    número no documento atual; as inseridas, o número que terão depois.
    """
    content = content or ''
    checked = verify_reference_edit(edit, content)

    if checked['status'] != 'ok':
        # Sem âncora válida não há onde ancorar o diff; a tela mostra só o que
        # entraria e o motivo do bloqueio.
        return {
            'status': checked['status'],
            'blocked_reason': checked['blocked_reason'],
            'header': 'trecho não localizado',
            'lines': (
                [{'kind': 'del', 'number': '?', 'text': linha}
                 for linha in str(edit.get('anchor') or '').splitlines()]
                + [{'kind': 'ins', 'number': '?', 'text': linha}
                   for linha in str(edit.get('new_text') or '').splitlines()]
            ),
        }

    old_lines = content.splitlines()
    new_lines = apply_reference_edit(content, checked).splitlines()
    opcodes = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes()

    lines: list[dict] = []
    first_old_line = None

    for position, (tag, start_a, end_a, start_b, end_b) in enumerate(opcodes):
        if tag == 'equal':
            bloco = list(range(start_a, end_a))
            # Contexto só encostado na mudança: as primeiras linhas quando o
            # bloco vem DEPOIS de uma alteração, as últimas quando vem ANTES.
            vizinhas: list[int] = []
            if position > 0 and opcodes[position - 1][0] != 'equal':
                vizinhas += bloco[:context_lines]
            if position + 1 < len(opcodes) and opcodes[position + 1][0] != 'equal':
                vizinhas += bloco[-context_lines:]

            for index in sorted(set(vizinhas)):
                lines.append({'kind': 'ctx', 'number': index + 1, 'text': old_lines[index]})
            continue

        if first_old_line is None:
            first_old_line = start_a + 1

        for index in range(start_a, end_a):
            lines.append({'kind': 'del', 'number': index + 1, 'text': old_lines[index]})
        for index in range(start_b, end_b):
            lines.append({'kind': 'ins', 'number': index + 1, 'text': new_lines[index]})

    return {
        'status': 'ok',
        'blocked_reason': None,
        'header': f'linha {first_old_line}' if first_old_line else 'fim do documento',
        'lines': lines,
    }


# ---------------------------------------------------------------------------
# Treinamento interativo — estado da conversa
# ---------------------------------------------------------------------------
#
# A sessão é uma FapReviewExecution(execution_type='training_chat'). No
# result_json dela ficam só decisões — ids aceitos, ids recusados, o que já foi
# gravado. As edições em si vivem em `fap_review_training_messages.edits_json`,
# cada uma com id estável "<message_id>-<posição>". Manter o payload pequeno é
# deliberado: TEXT tem 64 KB no MySQL, e uma conversa longa não caberia.

TRAINING_CHAT_TYPE = 'training_chat'
TRAINING_EXECUTION_TYPES = ('training', TRAINING_CHAT_TYPE)

# RPI-02: os prompts que cada modo de treinamento lê — a conversa não usa o
# TRAINING_PROMPT. Só esses entram na comparação com o vigente: a referência
# (manual, casos) também fica no snapshot, mas é o próprio treinamento que a
# muda, então todo lote que gravou algo apareceria como "outro".
_TRAINING_PROMPT_TYPES = {
    'training': ('revisor_identity', 'revisor_rules', 'training_identity',
                 'training_rules', 'training_prompt'),
    TRAINING_CHAT_TYPE: ('revisor_identity', 'revisor_rules', 'training_identity',
                         'training_rules'),
}

PROMPT_VERSION_LABELS = {
    'revisor_identity': 'Revisor · identidade',
    'revisor_rules': 'Revisor · regras',
    'training_identity': 'Treino · identidade',
    'training_rules': 'Treino · regras',
    'training_prompt': 'Treino · instrução',
}


def training_prompt_types(execution_type: str) -> tuple:
    return _TRAINING_PROMPT_TYPES.get(execution_type, _TRAINING_PROMPT_TYPES['training'])


def compare_prompt_versions(used: dict | None, current: dict, prompt_types: tuple) -> dict:
    """Versões de prompt com que o lote rodou, lado a lado com as vigentes.

    ``state``: 'unrecorded' (lote anterior ao registro — não se adivinha),
    'current' (mesmos prompts de hoje, comparável com um lote novo) ou 'changed'.
    A igualdade é pelo id da versão, não pelo número exibido.
    """
    if not used:
        return {'state': 'unrecorded', 'versions': [], 'changed': []}
    versions, changed = [], []
    for prompt_type in prompt_types:
        run = used.get(prompt_type) or {}
        now = current.get(prompt_type) or {}
        item = {
            'label': PROMPT_VERSION_LABELS.get(prompt_type, prompt_type),
            'version': run.get('version'),
            'current_version': now.get('version'),
        }
        versions.append(item)
        if run.get('id') != now.get('id'):
            changed.append(item)
    return {'state': 'changed' if changed else 'current', 'versions': versions, 'changed': changed}

CHAT_DECISIONS = ('accept', 'refuse', 'undo')


def edit_id_for(message_id: int, position: int) -> str:
    """Id estável de uma edição proposta numa mensagem."""
    return f'{int(message_id)}-{int(position)}'


def edits_from_messages(messages) -> dict[str, dict]:
    """Todas as edições propostas na conversa, por id, com o id gravado dentro."""
    by_id: dict[str, dict] = {}
    for message in messages or []:
        if getattr(message, 'role', None) != 'assistant' or not getattr(message, 'edits_json', None):
            continue
        try:
            proposed = json.loads(message.edits_json) or []
        except (TypeError, json.JSONDecodeError):
            continue
        for position, edit in enumerate(proposed):
            edit = dict(edit or {})
            edit['id'] = edit_id_for(message.id, position)
            edit['message_id'] = message.id
            by_id[edit['id']] = edit
    return by_id


def chat_state(payload: dict | None) -> dict:
    """Decisões da conversa, com os campos sempre presentes."""
    payload = payload or {}
    return {
        'accepted': [str(item) for item in (payload.get('accepted') or [])],
        'refused': [str(item) for item in (payload.get('refused') or [])],
        'saved': list(payload.get('saved') or []),
    }


def apply_chat_decision(payload: dict | None, edit_id: str, decision: str) -> dict:
    """Aplica aceitar / recusar / desfazer a uma edição e devolve o payload novo.

    Aceitar tira de recusadas; recusar tira de aceitas; desfazer tira das duas.
    Nada aqui grava referência: aceitar só coloca na bandeja.
    """
    if decision not in CHAT_DECISIONS:
        raise ValueError(f'Decisão desconhecida: {decision!r}')

    payload = dict(payload or {})
    state = chat_state(payload)
    edit_id = str(edit_id)

    accepted = [item for item in state['accepted'] if item != edit_id]
    refused = [item for item in state['refused'] if item != edit_id]

    if decision == 'accept':
        accepted.append(edit_id)
    elif decision == 'refuse':
        refused.append(edit_id)

    payload['stage'] = 'chat'
    payload['accepted'] = accepted
    payload['refused'] = refused
    payload.setdefault('saved', state['saved'])
    return payload


def accepted_edits(payload: dict | None, edits_by_id: dict[str, dict]) -> list[dict]:
    """As edições aceitas, na ordem em que foram aceitas, prontas para gravar."""
    return [
        dict(edits_by_id[edit_id])
        for edit_id in chat_state(payload)['accepted']
        if edit_id in (edits_by_id or {})
    ]


def decision_for(payload: dict | None, edit_id: str) -> str:
    """'accepted', 'refused' ou 'open' — o estado de uma edição na conversa."""
    state = chat_state(payload)
    edit_id = str(edit_id)
    if edit_id in state['accepted']:
        return 'accepted'
    if edit_id in state['refused']:
        return 'refused'
    return 'open'


def record_chat_save(payload: dict | None, targets: list[dict], activated: bool, applied_at: str) -> dict:
    """Registra uma gravação e esvazia a bandeja; a conversa segue da versão nova."""
    payload = dict(payload or {})
    state = chat_state(payload)
    saved = list(state['saved'])
    saved.append({
        'applied_at': applied_at,
        'activated': bool(activated),
        'targets': list(targets or []),
        'edit_ids': list(state['accepted']),
    })
    payload['stage'] = 'chat'
    payload['saved'] = saved
    payload['accepted'] = []
    payload['refused'] = state['refused']
    return payload


def summarize_chat_execution(status: str | None, payload: dict | None, subject: str = '') -> dict:
    """Situação e versões gravadas de uma conversa, para a lista unificada."""
    state = chat_state(payload)
    status_key = str(status or '').strip()

    if status_key == 'completed':
        situation = TRAINING_EXECUTION_STATUSES['completed']
    else:
        situation = {'label': 'Em andamento', 'style': 'warning', 'icon': 'bi bi-chat-dots'}

    targets: list[dict] = []
    for save in state['saved']:
        for item in save.get('targets') or []:
            targets.append({
                'key': item.get('key'),
                'label': item.get('label') or TRAINING_TARGET_LABELS.get(item.get('key'), item.get('key')),
                'version_number': item.get('version_number'),
                'activated': bool(item.get('activated')),
            })

    pending = len(state['accepted'])
    return {
        'situation': situation,
        'targets': targets,
        'is_pending': status_key != 'completed',
        'is_processing': False,
        'is_chat': True,
        'subject': subject,
        'pending_note': f'{pending} aceita{"s" if pending != 1 else ""}, não salva{"s" if pending != 1 else ""}' if pending else '',
    }
