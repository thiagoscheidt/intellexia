"""
Blueprint: Painel FAP
Prefixo: /fap-panel

Rotas:
    GET  /fap-panel/sync            — Página de sincronização de contestações
    POST /fap-panel/sync/run-year   — AJAX: sincroniza uma empresa + ano específico
    GET  /fap-panel/import          — Redireciona para a página de importação automática existente
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.models import FapAutoImportedContestacao, FapCompany, FapWebContestacao, db
from app.services.fap_web_service import FapWebAuthPayload, FapWebService

fap_panel_bp = Blueprint('fap_panel', __name__, url_prefix='/fap-panel')

# ---------------------------------------------------------------------------
# Auth helpers (mesmos do disputes_center)
# ---------------------------------------------------------------------------

def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_law_firm_id():
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Anos de vigência disponíveis (mesmos da importação: 2010 até ano atual)
# ---------------------------------------------------------------------------

FAP_AVAILABLE_YEARS = list(range(datetime.now().year, 2009, -1))


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@fap_panel_bp.route('/')
@require_law_firm
def index():
    return redirect(url_for('fap_panel.sync_page'))


@fap_panel_bp.route('/import')
@require_law_firm
def import_page():
    """Redireciona para a importação automática existente no disputes_center."""
    return redirect(url_for('disputes_center.fap_auto_import'))


@fap_panel_bp.route('/sync')
@require_law_firm
def sync_page():
    law_firm_id = get_current_law_firm_id()
    companies = (
        FapCompany.query
        .filter_by(law_firm_id=law_firm_id)
        .order_by(FapCompany.nome)
        .all()
    )

    saved_auth = session.get('fap_auto_import_auth', '')

    # Resumo rápido de contestações já sincronizadas
    total_synced = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id).count()

    return render_template(
        'fap_panel/sync.html',
        companies=companies,
        years=FAP_AVAILABLE_YEARS,
        saved_auth=saved_auth,
        total_synced=total_synced,
    )


@fap_panel_bp.route('/sync/run-year', methods=['POST'])
@require_law_firm
def sync_run_year():
    """AJAX — Busca contestações de uma empresa em um ano e persiste no banco.

    Body JSON:
        { "cnpj": "12345678", "year": 2023 }

    Response JSON:
        {
            "ok": true,
            "year": 2023,
            "total": 10,
            "created": 7,
            "updated": 3
        }
    """
    law_firm_id = get_current_law_firm_id()

    data = request.get_json(silent=True) or {}
    cnpj_raiz = str(data.get('cnpj') or '').strip()
    year = data.get('year')

    if not cnpj_raiz or not year:
        return jsonify({'ok': False, 'message': 'Informe o CNPJ e o ano de vigência.'}), 400

    saved_auth = session.get('fap_auto_import_auth', '')
    if not saved_auth:
        return jsonify({
            'ok': False,
            'message': 'Dados de autenticação não encontrados. Salve a sessão FAP primeiro.',
        }), 400

    try:
        auth = FapWebAuthPayload.from_json(saved_auth)
    except Exception:
        return jsonify({'ok': False, 'message': 'Dados de autenticação inválidos na sessão.'}), 400

    # Busca na API FAP
    result = FapWebService(auth).fetch_contestacoes(cnpj=cnpj_raiz, year=year)
    if not result.ok:
        detail = (result.data or {}).get('detail', '') if result.data else ''
        payload = {'ok': False, 'message': result.message}
        if detail:
            payload['detail'] = detail
        return jsonify(payload), 502

    items = result.data
    year_int = int(year)

    # Resolve fap_company_id pelo cnpj_raiz (pode ser nulo se não sincronizou empresas ainda)
    fap_company = FapCompany.query.filter_by(law_firm_id=law_firm_id, cnpj=cnpj_raiz).first()
    fap_company_id = fap_company.id if fap_company else None

    created = 0
    updated = 0
    now = datetime.utcnow()

    try:
        for item in items:
            cid = item.get('id')
            if not cid:
                continue

            cnpj_full = str(item.get('cnpj') or '').strip()
            if not cnpj_full:
                cnpj_full = cnpj_raiz

            # Garante string com 14 dígitos
            cnpj_digits = ''.join(ch for ch in cnpj_full if ch.isdigit())
            cnpj_full_14 = cnpj_digits.zfill(14) if len(cnpj_digits) <= 14 else cnpj_digits

            instancia   = item.get('instancia') or {}
            situacao    = item.get('situacao') or {}

            # Normaliza data de transmissão
            raw_dt = item.get('dataTransmissao')
            data_transmissao = None
            if raw_dt:
                try:
                    # Formato ISO: "2024-11-13T00:00:00" ou com timezone
                    data_transmissao = datetime.fromisoformat(
                        raw_dt.replace('Z', '+00:00').split('+')[0]
                    )
                except Exception:
                    pass

            existing = FapWebContestacao.query.filter_by(
                law_firm_id=law_firm_id,
                contestacao_id=int(cid),
            ).first()

            if existing:
                existing.cnpj                = cnpj_full_14
                existing.cnpj_raiz           = cnpj_digits[:8]
                existing.ano_vigencia        = year_int
                existing.fap_company_id      = fap_company_id
                existing.instancia_codigo    = instancia.get('codigo')
                existing.instancia_descricao = instancia.get('descricao')
                existing.situacao_codigo     = situacao.get('codigo')
                existing.situacao_descricao  = situacao.get('descricao')
                existing.protocolo           = item.get('protocolo')
                existing.data_transmissao    = data_transmissao
                existing.raw_data            = json.dumps(item, ensure_ascii=False)
                existing.last_synced_at      = now
                updated += 1
            else:
                rec = FapWebContestacao(
                    law_firm_id         = law_firm_id,
                    fap_company_id      = fap_company_id,
                    contestacao_id      = int(cid),
                    cnpj                = cnpj_full_14,
                    cnpj_raiz           = cnpj_digits[:8],
                    ano_vigencia        = year_int,
                    instancia_codigo    = instancia.get('codigo'),
                    instancia_descricao = instancia.get('descricao'),
                    situacao_codigo     = situacao.get('codigo'),
                    situacao_descricao  = situacao.get('descricao'),
                    protocolo           = item.get('protocolo'),
                    data_transmissao    = data_transmissao,
                    raw_data            = json.dumps(item, ensure_ascii=False),
                    last_synced_at      = now,
                )
                db.session.add(rec)
                created += 1

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': f'Erro ao salvar no banco: {str(e)}'}), 500

    return jsonify({
        'ok': True,
        'year': year_int,
        'total': len(items),
        'created': created,
        'updated': updated,
    })


@fap_panel_bp.route('/contestacoes')
@require_law_firm
def contestacoes_page():
    """Página de visualização das contestações sincronizadas — estilo portal FAP."""
    from collections import defaultdict

    law_firm_id = get_current_law_firm_id()

    companies = (
        FapCompany.query
        .filter_by(law_firm_id=law_firm_id)
        .order_by(FapCompany.nome)
        .all()
    )

    # ── Filtros ──────────────────────────────────────────────────────────
    f_year      = request.args.get('ano_vigencia', '').strip()
    f_cnpj_raiz = request.args.get('cnpj_raiz', '').strip()
    f_instancia = request.args.get('instancia', '').strip()
    f_situacao  = request.args.get('situacao', '').strip()
    f_protocolo = request.args.get('protocolo', '').strip()
    f_prazo2    = request.args.get('prazo_2_instancia') == '1'

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)

    if f_year:
        query = query.filter(FapWebContestacao.ano_vigencia == int(f_year))
    if f_cnpj_raiz:
        query = query.filter(FapWebContestacao.cnpj_raiz == f_cnpj_raiz)
    if f_instancia:
        query = query.filter(FapWebContestacao.instancia_codigo == f_instancia)
    if f_situacao:
        query = query.filter(FapWebContestacao.situacao_codigo == f_situacao)
    if f_protocolo:
        query = query.filter(FapWebContestacao.protocolo.ilike(f'%{f_protocolo}%'))

    all_rows = query.order_by(
        FapWebContestacao.ano_vigencia.desc(),
        FapWebContestacao.cnpj.asc(),
    ).all()

    # ── Mapa de contestações já importadas (contestacao_id → report_id) ──
    contestacao_ids = [r.contestacao_id for r in all_rows]
    imported_map = {}
    if contestacao_ids:
        imported_rows = (
            FapAutoImportedContestacao.query
            .filter(
                FapAutoImportedContestacao.law_firm_id == law_firm_id,
                FapAutoImportedContestacao.contestacao_id.in_(contestacao_ids),
            )
            .all()
        )
        for imp in imported_rows:
            imported_map[imp.contestacao_id] = imp.report_id

    # ── Valores únicos para os filtros de instância e situação ───────────
    distinct = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    instancias = {(r.instancia_codigo, r.instancia_descricao)
                  for r in distinct.with_entities(
                      FapWebContestacao.instancia_codigo,
                      FapWebContestacao.instancia_descricao).distinct()
                  if r.instancia_codigo}
    situacoes = {(r.situacao_codigo, r.situacao_descricao)
                 for r in distinct.with_entities(
                     FapWebContestacao.situacao_codigo,
                     FapWebContestacao.situacao_descricao).distinct()
                 if r.situacao_codigo}

    # ── Agrupamento por (ano_vigencia, cnpj) para montar a tabela ────────
    # Cada célula contém a lista de contestações naquela categoria.
    # Classificação:
    #   instancia_codigo contém "SEGUNDA" → recurso (cols 5,6); senão → contestação (cols 3,4)
    #   "em andamento" = situacao que contém "ANDAMENTO" ou não contém "TRANSMIT"/"RESULT"/"DIVULG"
    def _is_segunda(cod):
        return cod and 'SEGUNDA' in cod.upper()

    def _is_em_andamento(cod, desc):
        s = ((cod or '') + ' ' + (desc or '')).upper()
        return ('ANDAMENTO' in s or 'PRAZO' in s) and 'TRANSMIT' not in s and 'RESULT' not in s and 'DIVULG' not in s

    grouped = defaultdict(lambda: {'c_and1': [], 'c_tra1': [], 'c_and2': [], 'c_tra2': []})

    for r in all_rows:
        key = (r.ano_vigencia, r.cnpj)
        is2 = _is_segunda(r.instancia_codigo)
        em_and = _is_em_andamento(r.situacao_codigo, r.situacao_descricao)
        if is2:
            grouped[key]['c_and2' if em_and else 'c_tra2'].append(r)
        else:
            grouped[key]['c_and1' if em_and else 'c_tra1'].append(r)

    # ── Formata CNPJ 14 dígitos para exibição ────────────────────────────
    def _fmt_cnpj(digits):
        s = (digits or '').zfill(14)
        if len(s) == 14:
            return f'{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}'
        return digits

    table_rows = []
    for (ano, cnpj_raw), cells in sorted(grouped.items(), key=lambda x: (-x[0][0], x[0][1])):
        table_rows.append({
            'ano_vigencia': ano,
            'cnpj_raw':     cnpj_raw,
            'cnpj_fmt':     _fmt_cnpj(cnpj_raw),
            'c_and1':       cells['c_and1'],
            'c_tra1':       cells['c_tra1'],
            'c_and2':       cells['c_and2'],
            'c_tra2':       cells['c_tra2'],
        })

    return render_template(
        'fap_panel/contestacoes.html',
        companies=companies,
        years=FAP_AVAILABLE_YEARS,
        table_rows=table_rows,
        total=len(all_rows),
        instancias=sorted(instancias),
        situacoes=sorted(situacoes),
        imported_map=imported_map,
        # filtros ativos (para repreencher o form)
        f_year=f_year,
        f_cnpj_raiz=f_cnpj_raiz,
        f_instancia=f_instancia,
        f_situacao=f_situacao,
        f_protocolo=f_protocolo,
        f_prazo2=f_prazo2,
    )


@fap_panel_bp.route('/sync/summary', methods=['GET'])
@require_law_firm
def sync_summary():
    """AJAX — Retorna um resumo das contestações sincronizadas por empresa/vigência."""
    law_firm_id = get_current_law_firm_id()
    cnpj_raiz = request.args.get('cnpj', '').strip()

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    if cnpj_raiz:
        query = query.filter_by(cnpj_raiz=cnpj_raiz)

    rows = query.order_by(
        FapWebContestacao.cnpj,
        FapWebContestacao.ano_vigencia.desc(),
    ).all()

    items = [
        {
            'id':                  r.id,
            'contestacao_id':      r.contestacao_id,
            'cnpj':                r.cnpj,
            'cnpj_raiz':           r.cnpj_raiz,
            'ano_vigencia':        r.ano_vigencia,
            'instancia_codigo':    r.instancia_codigo or '',
            'instancia_descricao': r.instancia_descricao or '',
            'situacao_codigo':     r.situacao_codigo or '',
            'situacao_descricao':  r.situacao_descricao or '',
            'protocolo':           r.protocolo or '',
            'data_transmissao':    r.data_transmissao.strftime('%d/%m/%Y') if r.data_transmissao else '',
            'report_id':           r.report_id,
            'last_synced_at':      r.last_synced_at.strftime('%d/%m/%Y %H:%M') if r.last_synced_at else '',
        }
        for r in rows
    ]

    return jsonify({'ok': True, 'items': items, 'total': len(items)})
