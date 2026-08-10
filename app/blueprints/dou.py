"""
Diário Oficial — acervo do DOU capturado do INLABS.

Navegação em três níveis, do familiar ao específico:

  1. ``/dou``                  edições por data, como a listagem do INLABS —
                               quem só quer o PDF assinado do dia resolve aqui
  2. ``/dou/edicao/<data>``    a edição do dia, com uma aba por seção e a lista
                               de matérias daquela seção (filtro por órgão/tipo)
  3. ``/dou/materia/<id>``     o inteiro teor da matéria

Mais a aba **Captura** (``/dou/captura``), com a saúde da ingestão.

As matérias são filtradas por ``edition_id``, nunca por ``pub_name``: o
atributo ``pubName`` vem do XML e não se sabe o que a Imprensa Nacional grava
nele dentro de um ZIP de edição extra. ``edition_id`` é exato nos dois casos.

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

PER_PAGE_EDICOES = 30
PER_PAGE_MATERIAS = 50


def _parse_data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


# ------------------------------------------------------- nível 1: as edições

@dou_bp.route('/')
def edicoes():
    """Lista as edições por data, da mais recente para a mais antiga.

    É a porta de entrada e espelha a listagem do INLABS: uma linha por dia,
    com as seções capturadas e o PDF assinado de cada uma. Só aparecem datas
    com ao menos uma seção processada — fim de semana e feriado, em que nada é
    publicado, não viram linha vazia.
    """
    page = request.args.get('page', 1, type=int)

    paginacao = (db.session.query(DouEdition.data_publicacao)
                 .filter(DouEdition.status == DouEdition.STATUS_PARSED)
                 .distinct()
                 .order_by(DouEdition.data_publicacao.desc())
                 .paginate(page=page, per_page=PER_PAGE_EDICOES, error_out=False))

    datas = [linha[0] for linha in paginacao.items]

    por_data = {}
    if datas:
        for edicao in (DouEdition.query
                       .filter(DouEdition.data_publicacao.in_(datas))
                       .order_by(DouEdition.secao).all()):
            por_data.setdefault(edicao.data_publicacao, []).append(edicao)

    linhas = [
        {
            'data': data,
            'edicoes': [e for e in por_data.get(data, [])
                        if e.status == DouEdition.STATUS_PARSED],
            'total_materias': sum(e.qtd_materias or 0 for e in por_data.get(data, [])),
        }
        for data in datas
    ]

    return render_template('dou/edicoes.html', linhas=linhas, paginacao=paginacao,
                           total_materias=DouArticle.query.count())


# ---------------------------------------------------- nível 2: a edição do dia

@dou_bp.route('/edicao/<data_str>')
def edicao(data_str):
    """A edição de um dia: abas por seção e as matérias da seção escolhida."""
    data = _parse_data(data_str)
    if data is None:
        abort(404)

    todas = (DouEdition.query
             .filter_by(data_publicacao=data)
             .order_by(DouEdition.secao).all())
    if not todas:
        abort(404)

    # Só viram aba as seções que de fato têm matérias
    abas = [e for e in todas if e.status == DouEdition.STATUS_PARSED and e.qtd_materias]

    secao = (request.args.get('secao') or '').strip().upper()
    ativa = next((e for e in abas if e.secao == secao), None) or (abas[0] if abas else None)

    orgao = (request.args.get('orgao') or '').strip()
    tipo = (request.args.get('tipo') or '').strip()
    page = request.args.get('page', 1, type=int)

    materias = None
    tipos = []
    if ativa is not None:
        query = DouArticle.query.filter(DouArticle.edition_id == ativa.id)
        if orgao:
            query = query.filter(DouArticle.orgao_hierarquia.ilike(f'%{orgao}%'))
        if tipo:
            query = query.filter(DouArticle.art_type == tipo)

        materias = (query.order_by(DouArticle.id)
                    .paginate(page=page, per_page=PER_PAGE_MATERIAS, error_out=False))

        tipos = [
            t[0] for t in db.session.query(DouArticle.art_type)
            .filter(DouArticle.edition_id == ativa.id,
                    DouArticle.art_type.isnot(None))
            .distinct().order_by(DouArticle.art_type).all()
        ]

    return render_template('dou/edicao.html', data=data, abas=abas, ativa=ativa,
                           nao_publicadas=[e for e in todas
                                           if e.status == DouEdition.STATUS_NOT_PUBLISHED],
                           com_erro=[e for e in todas
                                     if e.status == DouEdition.STATUS_ERROR],
                           materias=materias, tipos=tipos,
                           f_orgao=orgao, f_tipo=tipo)


# ------------------------------------------------------- nível 3: a matéria

@dou_bp.route('/materia/<int:article_id>')
def materia(article_id):
    artigo = DouArticle.query.get_or_404(article_id)
    return render_template('dou/materia.html', artigo=artigo, edicao=artigo.edition)


@dou_bp.route('/edicao/<int:edition_id>/pdf')
def baixar_pdf(edition_id):
    """Entrega o PDF assinado da edição, se ainda existir em disco.

    ``as_attachment=False`` faz o navegador **abrir** o PDF no visualizador
    embutido em vez de baixá-lo — os links apontam para uma aba nova. O
    ``download_name`` continua definido: é o nome que aparece quando o usuário
    decide salvar a partir do visualizador.
    """
    edicao_obj = DouEdition.query.get_or_404(edition_id)
    if not edicao_obj.pdf_disponivel:
        flash('O PDF assinado desta edição não está disponível.', 'warning')
        return redirect(url_for('dou.edicao',
                                data_str=edicao_obj.data_publicacao.isoformat()))

    caminho = Path(edicao_obj.pdf_path)
    if not caminho.exists():
        abort(404)
    return send_file(caminho.resolve(), as_attachment=False,
                     download_name=caminho.name, mimetype='application/pdf')


# ----------------------------------------------------------------- captura

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
