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
from app.services import segurado_nome_service
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


def _filtros_da_requisicao(args):
    """Filtros da tela a partir da URL — os mesmos para a lista e para a planilha."""
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
    return dict(vigencia=vigencia, raiz=raiz, grupo=grupo, cnpj=cnpj, q=q, tipos=tipos,
                situacao=situacao, contestado=contestado, contestado_arg=contestado_arg)


def _consulta_filtrada(law_firm_id, f):
    return consulta.filtrar(
        law_firm_id, vigencia=f['vigencia'], raizes=[f['raiz']] if f['raiz'] else None,
        grupo=f['grupo'] or None, cnpj=f['cnpj'] or None, identificador=f['q'] or None,
        tipos=f['tipos'] or None, situacao=f['situacao'] or None, contestado=f['contestado'])


@fap_calculo_bp.route('/')
@require_law_firm
def beneficios_page():
    law_firm_id = get_current_law_firm_id()
    args = request.args
    fr = _filtros_da_requisicao(args)
    vigencia, raiz, grupo, cnpj, q, tipos, situacao, contestado_arg = (
        fr['vigencia'], fr['raiz'], fr['grupo'], fr['cnpj'], fr['q'], fr['tipos'],
        fr['situacao'], fr['contestado_arg'])
    try:
        page = max(1, int(args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    query = _consulta_filtrada(law_firm_id, fr)
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
        revelar_nome_disponivel=segurado_nome_service.disponivel(),
    )


@fap_calculo_bp.route('/exportar.xlsx')
@require_law_firm
def exportar_excel():
    """Planilha do que está filtrado na tela — mesmos filtros, mesma ordem."""
    from io import BytesIO
    from datetime import datetime

    from flask import send_file

    from app.services import fap_calculo_export_service

    law_firm_id = get_current_law_firm_id()
    fr = _filtros_da_requisicao(request.args)
    query = _consulta_filtrada(law_firm_id, fr)
    contadores = consulta.contadores(query, law_firm_id=law_firm_id)

    rotulos = fap_calculo_export_service.rotulos_dos_filtros(law_firm_id, fr)
    workbook = fap_calculo_export_service.montar_planilha(
        consulta.todos(query, law_firm_id=law_firm_id), rotulos, contadores)

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return send_file(
        stream, as_attachment=True,
        download_name=f'beneficios_calculo_fap_{datetime.now():%Y%m%d_%H%M%S}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@fap_calculo_bp.route('/segurado/revelar-nome', methods=['POST'])
@require_law_firm
def revelar_nome_segurado():
    """Botão "Revelar nome" — mesma consulta e mesma base da Central."""
    from app.services import segurado_nome_service

    payload = request.get_json(silent=True) or {}
    corpo, status = segurado_nome_service.resposta_revelar(
        get_current_law_firm_id(), payload.get('cpf'), session.get('user_id'))
    return jsonify(corpo), status


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
