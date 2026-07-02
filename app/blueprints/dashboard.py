from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from app.models import db, User
from datetime import datetime
from functools import wraps
import logging

from app.services.token_analytics_service import TokenAnalyticsService

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('law_firm_id'):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_law_firm_id():
    return session.get('law_firm_id')


# Rótulos amigáveis dos campos rastreados no histórico de mudanças
# (usado na aba "Atualizadas" para mostrar o que mudou na última alteração).
_FAP_CHANGE_FIELD_LABELS = {
    'situacao_codigo': 'Situação',
    'situacao_descricao': 'Situação',
    'instancia_codigo': 'Instância',
    'instancia_descricao': 'Instância',
    'protocolo': 'Protocolo',
    'data_transmissao': 'Transmissão',
    'data_dou_date': 'Publicação D.O.U.',
    'cnpj': 'CNPJ',
    'cnpj_raiz': 'CNPJ',
    'ano_vigencia': 'Vigência',
    'fap_company_id': 'Empresa',
}


def _fmt_cnpj_digits(digits):
    s = (digits or '').zfill(14)
    if len(s) == 14:
        return f'{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}'
    return digits or ''


def _fap_company_name_map(law_firm_id):
    """Mapa CNPJ → nome da empresa (para exibir junto às contestações)."""
    from app.models import FapCompany
    return {
        c.cnpj: c.nome
        for c in FapCompany.query.filter_by(law_firm_id=law_firm_id)
        .with_entities(FapCompany.cnpj, FapCompany.nome).all()
        if c.cnpj
    }


def _changed_field_labels(changed_fields_json):
    """Converte o JSON de changed_fields em rótulos amigáveis, sem repetição."""
    import json
    if not changed_fields_json:
        return []
    try:
        fields = json.loads(changed_fields_json)
    except (ValueError, TypeError):
        return []
    labels = []
    for f in fields:
        lbl = _FAP_CHANGE_FIELD_LABELS.get(f, f)
        if lbl not in labels:
            labels.append(lbl)
    return labels


def _contestacao_item(r, company_map, data_str, extra=None):
    """Monta o dict de exibição de uma contestação (comum às três abas)."""
    nome = (
        company_map.get(r.cnpj)
        or company_map.get(r.cnpj_raiz)
        or company_map.get((r.cnpj or '')[:8])
        or ''
    )
    item = {
        'id': r.id,
        'contestacao_id': r.contestacao_id,
        'cnpj_raiz': r.cnpj_raiz,
        'cnpj_fmt': _fmt_cnpj_digits(r.cnpj),
        'empresa': nome,
        'ano_vigencia': r.ano_vigencia,
        'protocolo': r.protocolo or '—',
        'situacao': r.situacao_descricao or '',
        'instancia': r.instancia_descricao or '',
        'data': data_str,
    }
    if extra:
        item.update(extra)
    return item


def _build_latest_dou_contestacoes(law_firm_id, limit=10):
    """Contestações mais recentemente publicadas no D.O.U. (por ``data_dou_date``)."""
    from app.models import FapWebContestacao

    rows = (
        FapWebContestacao.query
        .filter_by(law_firm_id=law_firm_id)
        .filter(FapWebContestacao.data_dou_date.isnot(None))
        .order_by(FapWebContestacao.data_dou_date.desc())
        .limit(limit)
        .all()
    )
    cmap = _fap_company_name_map(law_firm_id)
    return [
        _contestacao_item(r, cmap, r.data_dou_date.strftime('%d/%m/%Y'))
        for r in rows
    ]


def _build_latest_cadastro_contestacoes(law_firm_id, limit=10):
    """Contestações trazidas mais recentemente (por ``created_at``)."""
    from app.models import FapWebContestacao

    rows = (
        FapWebContestacao.query
        .filter_by(law_firm_id=law_firm_id)
        .order_by(FapWebContestacao.created_at.desc(), FapWebContestacao.id.desc())
        .limit(limit)
        .all()
    )
    cmap = _fap_company_name_map(law_firm_id)
    return [
        _contestacao_item(r, cmap, r.created_at.strftime('%d/%m/%Y') if r.created_at else '—')
        for r in rows
    ]


def _build_latest_atualizacao_contestacoes(law_firm_id, limit=10):
    """Contestações com mudança real de conteúdo mais recente.

    Usa ``FapWebContestacaoChangeHistory`` (change_type='updated'): a data
    exibida é a da última mudança e os rótulos indicam o que mudou nela.
    """
    from sqlalchemy import func
    from app.models import FapWebContestacao, FapWebContestacaoChangeHistory

    # Última mudança real por contestação → top N por essa data.
    subq = (
        db.session.query(
            FapWebContestacaoChangeHistory.contestacao_db_id.label('cid'),
            func.max(FapWebContestacaoChangeHistory.synced_at).label('last_change'),
        )
        .filter(
            FapWebContestacaoChangeHistory.law_firm_id == law_firm_id,
            FapWebContestacaoChangeHistory.change_type == 'updated',
        )
        .group_by(FapWebContestacaoChangeHistory.contestacao_db_id)
        .subquery()
    )
    rows = (
        db.session.query(FapWebContestacao, subq.c.last_change)
        .join(subq, FapWebContestacao.id == subq.c.cid)
        .order_by(subq.c.last_change.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []

    cmap = _fap_company_name_map(law_firm_id)
    items = []
    for r, last_change in rows:
        # Entrada específica da última mudança (para saber o que mudou).
        last_entry = (
            FapWebContestacaoChangeHistory.query
            .filter_by(law_firm_id=law_firm_id, contestacao_db_id=r.id, change_type='updated')
            .order_by(FapWebContestacaoChangeHistory.synced_at.desc(),
                      FapWebContestacaoChangeHistory.id.desc())
            .first()
        )
        items.append(_contestacao_item(
            r, cmap,
            last_change.strftime('%d/%m/%Y') if last_change else '—',
            extra={'changed': _changed_field_labels(last_entry.changed_fields if last_entry else None)},
        ))
    return items


def _build_deferimento_distribution(law_firm_id):
    """Distribuição de contestações por status de deferimento.

    O deferimento vive em raw_data['deferimento']['descricao'] (não é coluna),
    então parseamos o JSON em Python. Contestações sem deferimento entram na
    categoria 'Sem julgamento'.

    Retorna (overall, por_empresa):
      - overall:     {descricao: total} agregando todas as empresas
      - por_empresa: {cnpj_raiz: {descricao: total}} para filtro no frontend
    """
    import json as _json
    from app.models import FapWebContestacao

    rows = (
        FapWebContestacao.query
        .filter_by(law_firm_id=law_firm_id)
        .with_entities(FapWebContestacao.cnpj_raiz, FapWebContestacao.raw_data)
        .all()
    )

    overall = {}
    por_empresa = {}
    for raiz, raw_data in rows:
        desc = ''
        if raw_data:
            try:
                raw = _json.loads(raw_data)
                deferimento = raw.get('deferimento') or {}
                desc = (deferimento.get('descricao') or '').strip()
            except Exception:
                desc = ''
        key = desc or 'Sem julgamento'
        overall[key] = overall.get(key, 0) + 1
        bucket = por_empresa.setdefault(raiz or '—', {})
        bucket[key] = bucket.get(key, 0) + 1

    return overall, por_empresa


@dashboard_bp.route('/')
def index():
    """Redireciona para o dashboard principal"""
    user = User.query.get(session.get('user_id'))
    law_firm = user.law_firm if user else None
    
    message = request.args.get('message')
    if message:
        from flask import flash
        flash(message)
    return redirect(url_for('dashboard.dashboard'))

@dashboard_bp.route('/dashboard')
@require_law_firm
def dashboard():
    """Dashboard principal com estatísticas do sistema"""
    try:
        user = User.query.get(session.get('user_id'))
        law_firm = user.law_firm if user else None
        law_firm_id = get_current_law_firm_id()

        from app.models import (
            Lawyer, KnowledgeBase, KnowledgeCategory,
            JudicialProcess, Benefit, FapWebContestacao, FapCompany,
            FapContestationCat, FapContestationPayrollMass,
            FapContestationEmploymentLink, FapContestationTurnoverRate,
        )

        # ── Painel de Processos ───────────────────────────────────────
        total_processes = JudicialProcess.query.filter_by(law_firm_id=law_firm_id).count()
        active_processes = JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='ativo').count()
        suspended_processes = JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='suspenso').count()
        closed_processes = JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='encerrado').count()

        # ── Painel FAP — FapWebContestacao ───────────────────────────
        total_contestacoes = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id).count()
        contestacoes_com_pdf = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id).filter(
            FapWebContestacao.file_path.isnot(None)
        ).count()

        contestacoes_por_situacao_result = db.session.query(
            FapWebContestacao.situacao_descricao,
            db.func.count(FapWebContestacao.id).label('count')
        ).filter(
            FapWebContestacao.law_firm_id == law_firm_id
        ).group_by(FapWebContestacao.situacao_descricao).all()
        contestacoes_por_situacao = {
            (s or 'Indefinida'): c for s, c in contestacoes_por_situacao_result
        }

        contestacoes_por_ano_result = db.session.query(
            FapWebContestacao.ano_vigencia,
            db.func.count(FapWebContestacao.id).label('count')
        ).filter(
            FapWebContestacao.law_firm_id == law_firm_id
        ).group_by(FapWebContestacao.ano_vigencia).order_by(FapWebContestacao.ano_vigencia.desc()).limit(5).all()
        contestacoes_por_ano = {str(a): c for a, c in contestacoes_por_ano_result}

        # ── Contestações por situação, agrupadas por empresa ─────────
        # Permite no frontend filtrar o gráfico de situação por empresa.
        situacao_por_empresa_result = db.session.query(
            FapWebContestacao.cnpj_raiz,
            FapWebContestacao.situacao_descricao,
            db.func.count(FapWebContestacao.id).label('count'),
        ).filter(
            FapWebContestacao.law_firm_id == law_firm_id
        ).group_by(
            FapWebContestacao.cnpj_raiz,
            FapWebContestacao.situacao_descricao,
        ).all()

        company_names = {
            c.cnpj: (c.nome or '')
            for c in FapCompany.query.filter_by(law_firm_id=law_firm_id)
            .with_entities(FapCompany.cnpj, FapCompany.nome).all()
            if c.cnpj
        }

        contestacoes_situacao_por_empresa = {}
        for raiz, sit, cnt in situacao_por_empresa_result:
            key = raiz or '—'
            bucket = contestacoes_situacao_por_empresa.setdefault(key, {})
            bucket[(sit or 'Indefinida')] = cnt

        # Lista de empresas (com contestações) para o seletor do gráfico
        contestacoes_empresas = [
            {
                'cnpj_raiz': raiz,
                'nome': company_names.get(raiz) or company_names.get((raiz or '')[:8]) or raiz,
            }
            for raiz in contestacoes_situacao_por_empresa
        ]
        contestacoes_empresas.sort(key=lambda e: (e['nome'] or '').lower())

        # ── Contestações por status de deferimento ───────────────────
        contestacoes_por_deferimento, contestacoes_deferimento_por_empresa = \
            _build_deferimento_distribution(law_firm_id)

        # ── Contestações recentes (abas: D.O.U. / Cadastro / Atualização) ──
        latest_dou_contestacoes = _build_latest_dou_contestacoes(law_firm_id, limit=20)
        latest_cadastro_contestacoes = _build_latest_cadastro_contestacoes(law_firm_id, limit=20)
        latest_atualizacao_contestacoes = _build_latest_atualizacao_contestacoes(law_firm_id, limit=20)

        # ── Disputes Center — Benefit ─────────────────────────────────
        total_benefits_dc = Benefit.query.filter_by(law_firm_id=law_firm_id).count()
        benefits_classified = Benefit.query.filter_by(law_firm_id=law_firm_id).filter(
            Benefit.fap_contestation_topics_json.isnot(None)
        ).count()
        benefits_deferidos = Benefit.query.filter_by(law_firm_id=law_firm_id, first_instance_status='deferido').count()
        benefits_indeferidos = Benefit.query.filter_by(law_firm_id=law_firm_id, first_instance_status='indeferido').count()

        # ── Distribuição por categoria FAP (categoria principal) ──────
        topic_rows = db.session.query(
            Benefit.fap_contestation_topic,
            db.func.count(Benefit.id),
        ).filter(
            Benefit.law_firm_id == law_firm_id
        ).group_by(Benefit.fap_contestation_topic).all()
        topic_bucket = {}
        for topic, cnt in topic_rows:
            label = (topic or '').strip() or 'Não classificado'
            topic_bucket[label] = topic_bucket.get(label, 0) + cnt
        benefits_topic_distribution = [
            {'label': label, 'count': cnt}
            for label, cnt in sorted(topic_bucket.items(), key=lambda kv: kv[1], reverse=True)
        ]

        # ── Status por instância (Deferido/Indeferido/Em análise/Pendente) ──
        def _status_by_instance(column):
            rows = db.session.query(column, db.func.count(Benefit.id)).filter(
                Benefit.law_firm_id == law_firm_id
            ).group_by(column).all()
            buckets = {'deferido': 0, 'indeferido': 0, 'analyzing': 0, 'pending': 0}
            alias = {
                'deferido': 'deferido', 'approved': 'deferido',
                'indeferido': 'indeferido', 'rejected': 'indeferido',
                'analyzing': 'analyzing', 'in_review': 'analyzing',
                'em análise': 'analyzing', 'em analise': 'analyzing',
                'pending': 'pending', 'pendente': 'pending',
            }
            for value, cnt in rows:
                key = alias.get(str(value or '').strip().lower())
                if key:
                    buckets[key] += cnt
            return buckets

        benefits_status_first = _status_by_instance(Benefit.first_instance_status)
        benefits_status_second = _status_by_instance(Benefit.second_instance_status)

        # ── Contadores das demais categorias de contestação ───────────
        count_cats = FapContestationCat.query.filter_by(law_firm_id=law_firm_id).count()
        count_payroll_masses = FapContestationPayrollMass.query.filter_by(law_firm_id=law_firm_id).count()
        count_employment_links = FapContestationEmploymentLink.query.filter_by(law_firm_id=law_firm_id).count()
        count_turnover_rates = FapContestationTurnoverRate.query.filter_by(law_firm_id=law_firm_id).count()

        # ── Base de Conhecimento ──────────────────────────────────────
        knowledge_count = KnowledgeBase.query.filter_by(law_firm_id=law_firm_id, is_active=True).count()
        knowledge_categories_count = KnowledgeCategory.query.filter_by(law_firm_id=law_firm_id, is_active=True).count()
        all_tags = KnowledgeBase.query.with_entities(KnowledgeBase.tags).filter_by(
            law_firm_id=law_firm_id, is_active=True
        ).all()
        tag_set = set()
        for (tags_str,) in all_tags:
            if tags_str:
                tag_set.update(t.strip() for t in tags_str.split(',') if t.strip())
        knowledge_tags_count = len(tag_set)

        # ── Equipe ────────────────────────────────────────────────────
        total_lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).count()
        total_users = User.query.filter_by(law_firm_id=law_firm_id).count()

        return render_template('dashboard.html',
            total_processes=total_processes,
            active_processes=active_processes,
            suspended_processes=suspended_processes,
            closed_processes=closed_processes,
            total_contestacoes=total_contestacoes,
            contestacoes_com_pdf=contestacoes_com_pdf,
            contestacoes_por_situacao=contestacoes_por_situacao,
            contestacoes_por_ano=contestacoes_por_ano,
            contestacoes_situacao_por_empresa=contestacoes_situacao_por_empresa,
            contestacoes_empresas=contestacoes_empresas,
            contestacoes_por_deferimento=contestacoes_por_deferimento,
            contestacoes_deferimento_por_empresa=contestacoes_deferimento_por_empresa,
            latest_dou_contestacoes=latest_dou_contestacoes,
            latest_cadastro_contestacoes=latest_cadastro_contestacoes,
            latest_atualizacao_contestacoes=latest_atualizacao_contestacoes,
            total_benefits_dc=total_benefits_dc,
            benefits_classified=benefits_classified,
            benefits_deferidos=benefits_deferidos,
            benefits_indeferidos=benefits_indeferidos,
            benefits_topic_distribution=benefits_topic_distribution,
            benefits_status_first=benefits_status_first,
            benefits_status_second=benefits_status_second,
            count_cats=count_cats,
            count_payroll_masses=count_payroll_masses,
            count_employment_links=count_employment_links,
            count_turnover_rates=count_turnover_rates,
            knowledge_count=knowledge_count,
            knowledge_categories_count=knowledge_categories_count,
            knowledge_tags_count=knowledge_tags_count,
            total_lawyers=total_lawyers,
            total_users=total_users,
            user=user,
            law_firm=law_firm,
        )
    except Exception as e:
        print(f"Erro no dashboard: {str(e)}")
        from flask import flash
        flash(f'Erro ao carregar dashboard: {str(e)}', 'danger')
        return render_template('dashboard.html',
            total_processes=0,
            active_processes=0,
            suspended_processes=0,
            closed_processes=0,
            total_contestacoes=0,
            contestacoes_com_pdf=0,
            contestacoes_por_situacao={},
            contestacoes_por_ano={},
            contestacoes_situacao_por_empresa={},
            contestacoes_empresas=[],
            contestacoes_por_deferimento={},
            contestacoes_deferimento_por_empresa={},
            latest_dou_contestacoes=[],
            latest_cadastro_contestacoes=[],
            latest_atualizacao_contestacoes=[],
            total_benefits_dc=0,
            benefits_classified=0,
            benefits_deferidos=0,
            benefits_indeferidos=0,
            benefits_topic_distribution=[],
            benefits_status_first={'deferido': 0, 'indeferido': 0, 'analyzing': 0, 'pending': 0},
            benefits_status_second={'deferido': 0, 'indeferido': 0, 'analyzing': 0, 'pending': 0},
            count_cats=0,
            count_payroll_masses=0,
            count_employment_links=0,
            count_turnover_rates=0,
            knowledge_count=0,
            knowledge_categories_count=0,
            knowledge_tags_count=0,
            total_lawyers=0,
            total_users=0,
            user=user if 'user' in locals() else None,
            law_firm=law_firm if 'law_firm' in locals() else None,
        )

@dashboard_bp.route('/dashboard/tokens')
@require_law_firm
def dashboard_tokens():
    """Dashboard de monitoramento de uso de tokens dos agentes."""
    try:
        user = User.query.get(session.get('user_id'))
        law_firm = user.law_firm if user else None
        law_firm_id = get_current_law_firm_id()

        days_raw = request.args.get('days', '30')
        selected_agent = (request.args.get('agent') or '').strip()
        selected_action = (request.args.get('action') or '').strip()
        selected_model = (request.args.get('model') or '').strip()

        try:
            days = int(days_raw)
        except Exception:
            days = 30
        days = max(1, min(days, 365))

        analytics_service = TokenAnalyticsService()
        metrics = analytics_service.build_dashboard_data(
            law_firm_id=law_firm_id,
            days=days,
            agent_name=selected_agent or None,
            action_name=selected_action or None,
            model_name=selected_model or None,
        )

        return render_template(
            'dashboard_tokens.html',
            user=user,
            law_firm=law_firm,
            days=days,
            **metrics,
        )
    except Exception as e:
        print(f"Erro no dashboard de tokens: {str(e)}")
        from flask import flash
        flash(f'Erro ao carregar dashboard de tokens: {str(e)}', 'danger')
        return render_template(
            'dashboard_tokens.html',
            user=None,
            law_firm=None,
            days=30,
            period_days=30,
            period_start=None,
            period_end=None,
            total_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_cost_usd=0,
            avg_tokens_per_call=0,
            avg_cost_per_call=0,
            success_count=0,
            error_count=0,
            date_labels=[],
            date_tokens=[],
            date_calls=[],
            date_costs=[],
            top_agents=[],
            top_actions=[],
            model_distribution=[],
            recent_entries=[],
            all_agents=[],
            all_actions=[],
            all_models=[],
            selected_agent='',
            selected_action='',
            selected_model='',
        )


@dashboard_bp.route('/execution-history/<int:execution_id>')
@require_law_firm
def view_execution_history(execution_id: int):
    """Visualiza histórico completo de execução de um agente."""
    try:
        from app.models import AgentExecutionHistory
        from app.services.agent_execution_history_service import AgentExecutionHistoryService

        user = User.query.get(session.get('user_id'))
        law_firm = user.law_firm if user else None
        law_firm_id = get_current_law_firm_id()

        execution = AgentExecutionHistoryService.get_execution_history_by_id(execution_id)

        if not execution or (execution.law_firm_id and execution.law_firm_id != law_firm_id):
            from flask import flash
            flash('Histórico de execução não encontrado', 'danger')
            return redirect(url_for('dashboard.dashboard_tokens'))

        return render_template(
            'execution_history_detail.html',
            user=user,
            law_firm=law_firm,
            execution=execution,
        )

    except Exception as e:
        logger.exception(f"Erro ao visualizar histórico de execução: {str(e)}")
        from flask import flash
        flash(f'Erro ao visualizar histórico: {str(e)}', 'danger')
        return redirect(url_for('dashboard.dashboard_tokens'))


@dashboard_bp.route('/api/token-usage/<int:token_usage_id>/execution-history', methods=['GET'])
@require_law_firm
def get_execution_history_for_token_usage(token_usage_id: int):
    """API para recuperar históricos de execução relacionados a um token usage."""
    try:
        from app.models import AgentTokenUsage, AgentExecutionHistory
        from app.services.agent_execution_history_service import AgentExecutionHistoryService

        law_firm_id = get_current_law_firm_id()

        # Verificar permissão
        token_usage = AgentTokenUsage.query.filter_by(id=token_usage_id).first()
        if not token_usage or (token_usage.law_firm_id and token_usage.law_firm_id != law_firm_id):
            return jsonify({"error": "Unauthorized"}), 403

        executions = AgentExecutionHistoryService.get_executions_by_token_usage_id(token_usage_id)

        return jsonify({
            "executions": [
                {
                    "id": e.id,
                    "agent_name": e.agent_name,
                    "action_name": e.action_name,
                    "agent_type": e.agent_type,
                    "status": e.status,
                    "model_name": e.model_name,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in executions
            ]
        })

    except Exception as e:
        logger.exception(f"Erro ao recuperar históricos: {str(e)}")
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200
