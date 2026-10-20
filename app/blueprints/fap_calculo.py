"""Blueprint: Benefícios do cálculo FAP (submenu do Painel FAP).

Lista todo benefício (B91–B94) e CAT que o portal usou nos cálculos FAP
sincronizados. Permissão = módulo ``fap_panel`` (ENDPOINT_MODULE_MAP).
Multi-tenant: tudo filtra por law_firm_id.
"""
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from app.models import FapCalculoEstabelecimento, FapCalculoItem, FapCompany, db
from app.services import fap_calculo_query_service as consulta
from app.services import fap_group_service
from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CNPJ_RAIZ, apenas_digitos, completar_zeros, formatar_cnpj

fap_calculo_bp = Blueprint('fap_calculo', __name__, url_prefix='/fap-panel/calculo')

PER_PAGE = 50


def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Você precisa estar associado a um escritório.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@fap_calculo_bp.route('/')
@require_law_firm
def beneficios_page():
    law_firm_id = get_current_law_firm_id()
    args = request.args

    vigencia = args.get('vigencia', '').strip()
    vigencia = int(vigencia) if vigencia.isdigit() else None
    raiz = args.get('raiz', '').strip()
    grupo = args.get('grupo', '').strip()
    cnpj = args.get('cnpj', '').strip()
    if len(apenas_digitos(cnpj)) > TAMANHO_CNPJ_RAIZ:
        # O campo é um select de CNPJ só dígitos; link antigo com pontuação continua valendo.
        cnpj = completar_zeros(cnpj, TAMANHO_CNPJ)
    q = args.get('q', '').strip()
    tipos = [t for t in args.getlist('tipo') if t in consulta.TIPOS]
    situacao = args.get('situacao', '').strip()
    if situacao not in consulta.SITUACOES:
        situacao = ''
    contestado_arg = args.get('contestado', '').strip()
    contestado = {'sim': True, 'nao': False}.get(contestado_arg)
    if contestado is None:
        contestado_arg = ''
    try:
        page = max(1, int(args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    query = consulta.filtrar(
        law_firm_id, vigencia=vigencia, raizes=[raiz] if raiz else None,
        grupo=grupo or None, cnpj=cnpj or None, identificador=q or None,
        tipos=tipos or None, situacao=situacao or None, contestado=contestado)
    contadores = consulta.contadores(query, law_firm_id=law_firm_id)
    total = contadores['total']
    total_pages = max(1, -(-total // PER_PAGE))
    page = min(page, total_pages)
    itens, total = consulta.pagina(query, page, PER_PAGE, law_firm_id=law_firm_id)

    vigencias = [a for (a,) in db.session.query(FapCalculoEstabelecimento.ano_vigencia)
                 .filter(FapCalculoEstabelecimento.law_firm_id == law_firm_id)
                 .distinct().order_by(FapCalculoEstabelecimento.ano_vigencia.desc()).all()]
    empresas = (FapCompany.query.filter_by(law_firm_id=law_firm_id)
                .order_by(FapCompany.nome).all())

    filtros = {k: v for k, v in {
        'vigencia': vigencia, 'raiz': raiz, 'grupo': grupo, 'cnpj': cnpj, 'q': q,
        'situacao': situacao, 'contestado': contestado_arg,
    }.items() if v not in (None, '')}
    if tipos:
        filtros['tipo'] = tipos

    return render_template(
        'fap_calculo/beneficios.html',
        itens=itens, total=total, page=page, total_pages=total_pages,
        per_page=PER_PAGE, contadores=contadores, tipos_disponiveis=consulta.TIPOS,
        vigencias=vigencias, empresas=empresas,
        grupos=fap_group_service.select_options(law_firm_id),
        f=dict(vigencia=vigencia, raiz=raiz, grupo=grupo, cnpj=cnpj, q=q, tipos=tipos,
               situacao=situacao, contestado=contestado_arg),
        filtros=filtros,
    )


@fap_calculo_bp.route('/estabelecimentos.json')
@require_law_firm
def estabelecimentos_json():
    """Estabelecimentos de uma empresa (raiz) para o campo com busca da tela.

    Vem da sincronização (``fap_calculo_estabelecimentos``), com a quantidade de
    itens de cada um — o Santander tem 3 mil estabelecimentos, e por isso a
    lista é pedida só depois de escolher a empresa, em vez de ir inteira na página.
    """
    law_firm_id = get_current_law_firm_id()
    raiz = completar_zeros(request.args.get('raiz', ''), TAMANHO_CNPJ_RAIZ)
    if not raiz or len(raiz) != TAMANHO_CNPJ_RAIZ:
        return jsonify({'itens': []})
    qtd = dict(
        db.session.query(FapCalculoItem.cnpj, func.count(FapCalculoItem.id))
        .filter(FapCalculoItem.law_firm_id == law_firm_id, FapCalculoItem.cnpj_raiz == raiz)
        .group_by(FapCalculoItem.cnpj).all()
    )
    cnpjs = {c for (c,) in db.session.query(FapCalculoEstabelecimento.cnpj).filter(
        FapCalculoEstabelecimento.law_firm_id == law_firm_id,
        FapCalculoEstabelecimento.cnpj_raiz == raiz).distinct()} | set(qtd)
    ordenados = sorted(cnpjs, key=lambda c: (-qtd.get(c, 0), c))
    return jsonify({'itens': [
        {'cnpj': c, 'texto': f"{formatar_cnpj(c)} · {qtd.get(c, 0)} item(ns)"} for c in ordenados
    ]})
