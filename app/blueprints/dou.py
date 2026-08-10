"""
Diário Oficial — acervo do DOU capturado do INLABS.

Duas frentes: o **acervo** (navegar por data e seção, filtrar por órgão e tipo
de ato, ler a matéria, baixar o PDF assinado) e a **captura** (saúde da
ingestão, com reprocesso de data).

Esta tela nunca baixa nada de forma síncrona numa requisição de usuário: o
download é responsabilidade do cron (scripts/sync_dou.py). O botão
"reprocessar" é a única exceção e roda uma data por vez.

As tabelas do DOU não têm law_firm_id — é um catálogo público compartilhado
(ver docstring de DouEdition). Por isso este blueprint não filtra por tenant;
a proteção é a permissão de módulo, aplicada pelo middleware.
"""

from datetime import datetime
from pathlib import Path

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, abort)
from sqlalchemy import func

from app.models import db, DouEdition, DouArticle, DouSyncRun
from app.services import dou_ingestion_service as ingestion

dou_bp = Blueprint('dou', __name__, url_prefix='/dou')

PER_PAGE = 30


def _parse_data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


@dou_bp.route('/')
def index():
    return redirect(url_for('dou.acervo'))


@dou_bp.route('/acervo')
def acervo():
    """Navegação por data e seção, com filtro por órgão e tipo de ato."""
    data = _parse_data(request.args.get('data'))
    secao = (request.args.get('secao') or '').strip().upper()
    orgao = (request.args.get('orgao') or '').strip()
    tipo = (request.args.get('tipo') or '').strip()
    page = request.args.get('page', 1, type=int)

    # Datas disponíveis, da mais recente para a mais antiga
    datas = [
        d[0] for d in db.session.query(DouEdition.data_publicacao)
        .filter(DouEdition.status == DouEdition.STATUS_PARSED)
        .distinct().order_by(DouEdition.data_publicacao.desc()).limit(180).all()
    ]

    if data is None and datas:
        data = datas[0]

    edicoes = []
    materias = None
    if data:
        edicoes = (DouEdition.query
                   .filter_by(data_publicacao=data)
                   .order_by(DouEdition.secao).all())

        query = DouArticle.query.filter(DouArticle.pub_date == data)
        if secao:
            query = query.filter(DouArticle.pub_name == secao)
        if orgao:
            query = query.filter(DouArticle.orgao_hierarquia.ilike(f'%{orgao}%'))
        if tipo:
            query = query.filter(DouArticle.art_type == tipo)

        materias = (query.order_by(DouArticle.pub_name, DouArticle.id)
                    .paginate(page=page, per_page=PER_PAGE, error_out=False))

    tipos = [
        t[0] for t in db.session.query(DouArticle.art_type)
        .filter(DouArticle.pub_date == data, DouArticle.art_type.isnot(None))
        .distinct().order_by(DouArticle.art_type).all()
    ] if data else []

    return render_template(
        'dou/acervo.html',
        datas=datas, data_selecionada=data, edicoes=edicoes,
        materias=materias, tipos=tipos,
        f_secao=secao, f_orgao=orgao, f_tipo=tipo,
        secoes=DouEdition.XML_SECTIONS, section_labels=DouEdition.SECTION_LABELS,
    )


@dou_bp.route('/materia/<int:article_id>')
def materia(article_id):
    artigo = DouArticle.query.get_or_404(article_id)
    return render_template('dou/materia.html', artigo=artigo, edicao=artigo.edition)


@dou_bp.route('/edicao/<int:edition_id>/pdf')
def baixar_pdf(edition_id):
    """Entrega o PDF assinado da edição, se ainda existir em disco."""
    edicao = DouEdition.query.get_or_404(edition_id)
    if not edicao.pdf_disponivel:
        flash('O PDF assinado desta edição não está disponível.', 'warning')
        return redirect(url_for('dou.acervo', data=edicao.data_publicacao.isoformat()))

    caminho = Path(edicao.pdf_path)
    if not caminho.exists():
        abort(404)
    return send_file(caminho.resolve(), as_attachment=True, download_name=caminho.name)


@dou_bp.route('/captura')
def captura():
    """Saúde da ingestão: execuções recentes e cobertura por dia."""
    execucoes = (DouSyncRun.query
                 .order_by(DouSyncRun.iniciado_em.desc()).limit(20).all())

    cobertura = (db.session.query(
        DouEdition.data_publicacao,
        func.count(DouEdition.id).label('secoes'),
        func.sum(DouEdition.qtd_materias).label('materias'),
    ).group_by(DouEdition.data_publicacao)
     .order_by(DouEdition.data_publicacao.desc()).limit(60).all())

    com_erro = (DouEdition.query
                .filter(DouEdition.status == DouEdition.STATUS_ERROR)
                .order_by(DouEdition.data_publicacao.desc()).limit(50).all())

    return render_template('dou/captura.html', execucoes=execucoes,
                           cobertura=cobertura, com_erro=com_erro,
                           total_materias=DouArticle.query.count())


@dou_bp.route('/captura/reprocessar', methods=['POST'])
def reprocessar():
    """Reprocessa uma data. Único ponto em que a tela dispara download."""
    data = _parse_data(request.form.get('data'))
    if not data:
        flash('Informe uma data válida (AAAA-MM-DD).', 'danger')
        return redirect(url_for('dou.captura'))

    try:
        run = ingestion.ingest_single_date(data)
    except Exception as exc:  # noqa: BLE001 — erro vira mensagem, não 500
        flash(f'Falha ao reprocessar {data:%d/%m/%Y}: {exc}', 'danger')
        return redirect(url_for('dou.captura'))

    flash(
        f'{data:%d/%m/%Y}: {run.materias_inseridas} matéria(s) nova(s), '
        f'{run.materias_atualizadas} atualizada(s), {run.erros} erro(s).',
        'success' if run.erros == 0 else 'warning',
    )
    return redirect(url_for('dou.captura'))
