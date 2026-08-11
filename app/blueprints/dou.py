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
from io import BytesIO
from pathlib import Path

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, abort, session, current_app)
from sqlalchemy import func

from app.models import db, DouEdition, DouArticle, DouSyncRun, Client

from app.services import dou_ingestion_service as ingestion
from app.services import dou_search_service as busca_service
from app.services.dou_xml_parser import grifar_html, sanitizar_html

dou_bp = Blueprint('dou', __name__, url_prefix='/dou')

PER_PAGE_EDICOES = 30
PER_PAGE_MATERIAS = 50
PER_PAGE_BUSCA = 20

# Rótulos de data em português: strftime depende de locale instalado no
# servidor, o que não se pode assumir.
DIAS_SEMANA = ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom')
MESES = ('jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul',
         'ago', 'set', 'out', 'nov', 'dez')


ORDENS = {
    'pagina': 'Página do Diário',
    'orgao': 'Órgão',
    'tipo': 'Tipo de ato',
}


def _parse_data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


def _ordenacao(ordem):
    """Critérios de ORDER BY, sempre terminando em ``id``.

    Página é o padrão porque é a ordem de leitura do jornal impresso. Sem isso a
    listagem saía na ordem em que os arquivos vinham do ZIP — arbitrária, com a
    página pulando 117, 26, 116, 26.

    ``pagina_num.is_(None)`` como primeiro critério joga as páginas nulas para o
    fim: MySQL não aceita NULLS LAST, e o booleano ordena False antes de True
    nos dois bancos. O ``id`` no fim garante ordem estável na paginação — sem
    ele, empates fazem LIMIT/OFFSET repetir e pular linhas.
    """
    pagina = (DouArticle.pagina_num.is_(None), DouArticle.pagina_num)
    if ordem == 'orgao':
        return (DouArticle.orgao_hierarquia, *pagina, DouArticle.id)
    if ordem == 'tipo':
        return (DouArticle.art_type, *pagina, DouArticle.id)
    return (*pagina, DouArticle.id)


@dou_bp.app_context_processor
def inject_dou_health():
    """Chip do Diário Oficial na header (barato: dois COUNT com índice).

    Conta **saúde da captura**, não volume. O DOU não tem fila de trabalho:
    ninguém "resolve" o Diário, e um contador de matérias só cresceria — ao
    lado de badges que significam "faça algo", isso ensinaria a ignorar a área
    inteira. O que pede ação é a captura ter falhado ou parado.

    Sem filtro por escritório, diferente dos outros chips: o acervo é global e
    a saúde da captura é a mesma para todos.
    """
    try:
        return {'dou_health': ingestion.health_counters()}
    except Exception:  # noqa: BLE001 — chip nunca derruba a header
        return {'dou_health': None}


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

    linhas = []
    for data in datas:
        publicadas = [e for e in por_data.get(data, [])
                      if e.status == DouEdition.STATUS_PARSED]
        linhas.append({
            'data': data,
            'dia': data.day,
            'semana': DIAS_SEMANA[data.weekday()],
            'mes_ano': f'{MESES[data.month - 1]} {data.year}',
            'edicoes': publicadas,
            'total_materias': sum(e.qtd_materias or 0 for e in publicadas),
        })

    # Escala das barras: o maior caderno visível na página. Comparar contra o
    # maior da página (e não contra o do próprio dia) mantém as barras
    # comparáveis entre dias diferentes.
    maior_caderno = max(
        (e.qtd_materias or 0 for linha in linhas for e in linha['edicoes']),
        default=0,
    ) or 1

    periodo = db.session.query(
        func.min(DouEdition.data_publicacao), func.max(DouEdition.data_publicacao)
    ).filter(DouEdition.status == DouEdition.STATUS_PARSED).first()

    return render_template('dou/edicoes.html', linhas=linhas, paginacao=paginacao,
                           maior_caderno=maior_caderno,
                           periodo_inicio=periodo[0] if periodo else None,
                           periodo_fim=periodo[1] if periodo else None,
                           total_edicoes=paginacao.total,
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
    ordem = request.args.get('ordem') if request.args.get('ordem') in ORDENS else 'pagina'
    page = request.args.get('page', 1, type=int)

    materias = None
    tipos = []
    if ativa is not None:
        query = DouArticle.query.filter(DouArticle.edition_id == ativa.id)
        if orgao:
            query = query.filter(DouArticle.orgao_hierarquia.ilike(f'%{orgao}%'))
        if tipo:
            query = query.filter(DouArticle.art_type == tipo)

        materias = (query.order_by(*_ordenacao(ordem))
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
                           materias=materias, tipos=tipos, ordens=ORDENS,
                           f_orgao=orgao, f_tipo=tipo, f_ordem=ordem)


# ----------------------------------------------------------------- busca

@dou_bp.route('/busca')
def busca():
    """Busca por termo em todo o acervo.

    O acervo é global, mas a lista de clientes do atalho é do escritório — é o
    único ponto desta tela que enxerga tenant.
    """
    termo = (request.args.get('q') or '').strip()
    ordem = 'data' if request.args.get('ordem') == 'data' else 'relevancia'
    pagina = max(request.args.get('page', 1, type=int) or 1, 1)

    filtros = {
        'pub_name': request.args.getlist('secao'),
        'orgao_raiz': request.args.getlist('orgao'),
        'art_type': request.args.getlist('tipo'),
        'de': _parse_data(request.args.get('de')),
        'ate': _parse_data(request.args.get('ate')),
    }

    resultado = None
    if termo:
        resultado = busca_service.search(
            termo, filtros=filtros, ordem=ordem,
            pagina=pagina, por_pagina=PER_PAGE_BUSCA)

    law_firm_id = session.get('law_firm_id')
    clientes = (Client.query.filter_by(law_firm_id=law_firm_id)
                .order_by(Client.name).all()) if law_firm_id else []

    return render_template(
        'dou/busca.html',
        termo=termo, resultado=resultado, filtros=filtros, ordem=ordem,
        pagina=pagina, por_pagina=PER_PAGE_BUSCA, clientes=clientes,
        disponivel=busca_service.is_available(),
        section_labels=DouEdition.SECTION_LABELS,
    )


# ------------------------------------------------------- nível 3: a matéria

@dou_bp.route('/materia/<int:article_id>')
def materia(article_id):
    artigo = DouArticle.query.get_or_404(article_id)
    edicao_obj = artigo.edition

    # A página impressa corresponde 1:1 à página do PDF assinado — conferido em
    # 216 matérias de todas as seções, 96% batendo. Só oferecemos a aba quando
    # há PDF em disco e a matéria diz em que página está.
    pagina_no_pdf = (artigo.pagina_num
                     if edicao_obj and edicao_obj.pdf_disponivel and artigo.pagina_num
                     else None)

    termo_busca = (request.args.get('q') or '').strip()

    # Onde a matéria fica dentro do recorte de três páginas: a primeira, quando
    # ela abre a seção e não há anterior; a segunda no resto dos casos.
    pagina_no_recorte = 1 if (artigo.pagina_num or 1) <= 1 else 2

    # Vindo da busca, abrir onde o termo está — que nem sempre é a página
    # registrada na matéria. No edital 11908 o título está na 109 e o CNPJ
    # procurado, na 110: abrir na 109 mostraria a página certa e o achado
    # nenhum.
    if termo_busca and pagina_no_pdf:
        encontrada = _pagina_do_termo(artigo, termo_busca)
        if encontrada:
            pagina_no_recorte = encontrada

    return render_template(
        'dou/materia.html',
        artigo=artigo,
        edicao=edicao_obj,
        pagina_no_recorte=pagina_no_recorte,
        termo_busca=termo_busca,
        # A ordem importa: sanitizar primeiro, grifar depois. Grifar antes
        # faria a faxina descartar o <mark> que acabamos de inserir.
        texto_formatado=grifar_html(
            sanitizar_html(artigo.texto_html),
            busca_service.termos_para_grifo(termo_busca),
        ),
        pagina_pdf=pagina_no_pdf,
    )


def _janela_do_recorte(artigo, total_paginas):
    """(início, fim) em índice zero das páginas que entram no recorte."""
    indice = artigo.pagina_num - 1
    return max(0, indice - 1), min(total_paginas - 1, indice + 1)


def _pagina_do_termo(artigo, consulta):
    """Em qual página do recorte o termo aparece (1-based). 0 se não achar.

    Custa uma abertura do PDF (~10 ms) e só roda quando se veio da busca.
    """
    termos = busca_service.termos_para_pdf(consulta)
    if not termos:
        return 0
    try:
        import fitz
        with fitz.open(Path(artigo.edition.pdf_path)) as documento:
            inicio, fim = _janela_do_recorte(artigo, documento.page_count)
            for numero in range(inicio, fim + 1):
                if any(documento[numero].search_for(t) for t in termos):
                    return numero - inicio + 1
    except Exception:  # noqa: BLE001 — é conveniência; falhar volta ao padrão
        current_app.logger.warning(
            'DOU: não foi possível localizar %r no PDF da matéria %s',
            consulta, artigo.id)
    return 0


def _grifar(recorte, termos) -> int:
    """Marca as ocorrências dos termos no recorte. Devolve a 1ª página com grifo.

    Devolve 0 quando não achou nada — quem chama decide para onde abrir.
    """
    primeira = 0
    for numero in range(recorte.page_count):
        pagina = recorte[numero]
        for termo in termos:
            for retangulo in pagina.search_for(termo):
                pagina.add_highlight_annot(retangulo)
                primeira = primeira or (numero + 1)
    return primeira


@dou_bp.route('/materia/<int:article_id>/pagina.pdf')
def pagina_pdf(article_id):
    """A página da matéria e as vizinhas, recortadas do PDF assinado da seção.

    Mandar o PDF inteiro para mostrar uma página é inviável: a Seção 3 tem
    60 MB. O recorte custa poucos milissegundos e o tamanho não depende do
    arquivo de origem. Mantém o texto selecionável, o que uma imagem perderia.

    Vêm a anterior e a seguinte porque matéria não respeita limite de página:
    um edital começa numa e termina na outra, e mostrar só a página registrada
    entregaria o ato cortado.
    """
    artigo = DouArticle.query.get_or_404(article_id)
    edicao_obj = artigo.edition

    if not (edicao_obj and edicao_obj.pdf_disponivel and artigo.pagina_num):
        abort(404)

    caminho = Path(edicao_obj.pdf_path)
    if not caminho.exists():
        abort(404)

    termos = busca_service.termos_para_pdf(request.args.get('q') or '')

    try:
        import fitz  # PyMuPDF — import tardio: só esta rota precisa
        with fitz.open(caminho) as documento:
            indice = artigo.pagina_num - 1
            if not 0 <= indice < documento.page_count:
                abort(404)
            inicio, fim = _janela_do_recorte(artigo, documento.page_count)
            with fitz.open() as recorte:
                recorte.insert_pdf(documento, from_page=inicio, to_page=fim)

                # Rótulos com a numeração original: sem isso o visualizador
                # mostraria "1, 2, 3" e o leitor perderia a referência da
                # página do Diário, que é como o ato é citado.
                recorte.set_page_labels([{'startpage': 0, 'prefix': '',
                                          'style': 'D', 'firstpagenum': inicio + 1}])

                if termos:
                    _grifar(recorte, termos)

                conteudo = recorte.tobytes()
    except Exception:  # noqa: BLE001 — PDF corrompido não pode virar 500
        current_app.logger.exception(
            'DOU: falha ao extrair a página %s da matéria %s',
            artigo.pagina_num, article_id)
        abort(404)

    return send_file(
        BytesIO(conteudo), mimetype='application/pdf', as_attachment=False,
        download_name=f'DOU-{artigo.pub_date:%Y-%m-%d}-{artigo.pub_name}-p{artigo.pagina}.pdf',
    )


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
