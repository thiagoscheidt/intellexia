"""Blueprint: Base de Jurisprudência (submódulo do Painel de Processos).

Decisões FAP classificadas por tese e resultado — importadas da planilha do
escritório (Banco Mestre FAP) ou lidas de PDF pela IA — com pesquisa,
correspondência de teses com o catálogo do painel e uso na geração da
impugnação. Multi-tenant: tudo filtra por law_firm_id. Permissão = módulo
process_panel (ENDPOINT_MODULE_MAP).

Rotas:
    GET  /process-panel/jurisprudencia/                         pesquisa
    GET  /process-panel/jurisprudencia/decisao/<id>             decisão
    GET|POST .../decisao/<id>/editar                            corrigir dados
    GET  .../decisao/<id>/pdf                                   PDF inline
    POST .../decisao/<id>/anexar-pdf | reprocessar | excluir
    GET|POST .../importar          GET .../importar/<token>     conferência
    POST .../importar/<token>/confirmar
    GET|POST .../enviar            GET .../enviar/status        fila de PDFs
    POST .../enviar/<id>/tentar-de-novo | descartar | resolver
    GET  .../teses                 POST .../teses/<id>/<ação>   correspondência
    POST .../teses/sugerir         GET .../teses/sugestoes/status
    GET  .../api/buscar                                         busca do wizard
"""
from __future__ import annotations

import os
from functools import wraps

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)

from app.models import db, JudicialLegalThesis, JurisprudenceDecision, User
from app.services import jurisprudence_import_service as importacao
from app.services import jurisprudence_index_service as indice
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_search_service as busca
from app.services import jurisprudence_service as svc
from app.services import jurisprudence_thesis_service as teses_svc
from app.services import jurisprudence_upload_service as envios

jurisprudence_bp = Blueprint('jurisprudence', __name__, url_prefix='/process-panel/jurisprudencia')


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


def require_admin_user(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = User.query.get(session.get('user_id')) if session.get('user_id') else None
        if not user or user.role != 'admin':
            flash('Acesso negado: privilégio de administrador necessário.', 'danger')
            return redirect(url_for('jurisprudence.index'))
        return f(*args, **kwargs)
    return decorated_function


@jurisprudence_bp.app_template_filter('jur_resultado')
def _filtro_resultado(valor, curto=True):
    return (norm.RESULTADO_LABELS_CURTOS if curto else norm.RESULTADO_LABELS).get(valor or '', 'Sem resultado')


@jurisprudence_bp.app_template_filter('jur_tipo')
def _filtro_tipo(valor, curto=True):
    return (norm.TIPO_LABELS_CURTOS if curto else norm.TIPO_LABELS).get(valor or '', 'Decisão')


def _alternar(nome: str, valor) -> str:
    """URL da pesquisa com `valor` ligado/desligado no parâmetro `nome`."""
    args = request.args.to_dict(flat=False)
    args.pop('pagina', None)
    valores = [v for v in args.get(nome, []) if v != '']
    valor = str(valor)
    args[nome] = [v for v in valores if v != valor] if valor in valores else [*valores, valor]
    return url_for('jurisprudence.index', **{k: v for k, v in args.items() if v})


def _com(**trocas) -> str:
    """URL da pesquisa com os parâmetros trocados (None remove)."""
    args = request.args.to_dict(flat=False)
    if 'pagina' not in trocas:
        args.pop('pagina', None)
    for nome, valor in trocas.items():
        if valor is None or valor == '':
            args.pop(nome, None)
        else:
            args[nome] = [str(valor)]
    return url_for('jurisprudence.index', **{k: v for k, v in args.items() if v})


def _decisao(decision_id: int) -> JurisprudenceDecision:
    decisao = JurisprudenceDecision.query.filter_by(
        id=decision_id, law_firm_id=get_current_law_firm_id()).first()
    if decisao is None:
        abort(404)
    return decisao


# ── Pesquisa ──────────────────────────────────────────────────────────

@jurisprudence_bp.route('/')
@require_law_firm
def index():
    law_firm_id = get_current_law_firm_id()
    filtros = busca.Filtros.do_request(request.args)
    resultado = busca.buscar(law_firm_id, filtros)
    modo_inteiro = request.args.get('modo') == 'inteiro' and bool(filtros.q)
    return render_template(
        'jurisprudence/index.html',
        filtros=filtros,
        r=resultado,
        modo_inteiro=modo_inteiro,
        inteiro=_busca_no_inteiro_teor(law_firm_id, filtros) if modo_inteiro else None,
        totais=svc.totais(law_firm_id),
        pendentes=svc.contar_teses_pendentes(law_firm_id),
        ordens=busca.ORDENS,
        resultado_labels=norm.RESULTADO_LABELS_CURTOS,
        tipo_labels=norm.TIPO_LABELS,
        envios_ativos=envios.painel(law_firm_id, limite=50)['ativos'],
        alternar=_alternar,
        com=_com,
        mostrar_livres=request.args.get('livres') == '1',
        reset=svc.o_que_o_reset_apaga(law_firm_id) if session.get('user_role') == 'admin' else None,
        palavra_reset=PALAVRA_RESET,
    )


PALAVRA_RESET = 'RESETAR'


@jurisprudence_bp.route('/resetar', methods=['POST'])
@require_law_firm
@require_admin_user
def resetar():
    """Apaga a Base de Jurisprudência inteira do escritório (admin, com confirmação digitada)."""
    if (request.form.get('confirmacao') or '').strip().upper() != PALAVRA_RESET:
        flash(f'Confirmação incorreta — digite "{PALAVRA_RESET}" para apagar a base.', 'warning')
        return redirect(url_for('jurisprudence.index'))
    try:
        r = svc.resetar_base(get_current_law_firm_id())
    except ValueError as erro:
        flash(str(erro), 'warning')
        return redirect(url_for('jurisprudence.index'))
    except Exception as erro:
        flash(f'Falha ao apagar a base: {erro}', 'danger')
        return redirect(url_for('jurisprudence.index'))
    resumo = f"{r['decisoes']} decisão(ões), {r['teses']} tese(s) e {r['pdfs']} PDF(s)"
    if r['avisos']:
        flash(f"Base apagada ({resumo}), mas houve falha ao limpar: {', '.join(r['avisos'])}. "
              'Rode o reset de novo para tentar outra vez.', 'warning')
    else:
        flash(f'Base de Jurisprudência apagada por completo — {resumo}. Pode importar do zero.', 'success')
    return redirect(url_for('jurisprudence.index'))


def _busca_no_inteiro_teor(law_firm_id: int, filtros) -> dict:
    """Resultado do modo "inteiro teor": uma linha por decisão, com o trecho da
    página onde o termo aparece. `indisponivel` quando o índice não responde."""
    achados = indice.buscar_inteiro_teor(law_firm_id, filtros.q, tribunais=filtros.tribunais,
                                         resultados=filtros.resultados, tipos=filtros.tipos)
    if achados is None:
        return {'indisponivel': True, 'linhas': []}
    decisoes = {d.id: d for d in JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id,
        JurisprudenceDecision.id.in_({a['decision_id'] for a in achados})).all()} if achados else {}
    linhas = [{**a, 'decisao': decisoes[a['decision_id']]} for a in achados if a['decision_id'] in decisoes]
    cobertura = envios.cobertura(law_firm_id)
    return {'indisponivel': False, 'linhas': linhas, 'cobertura': cobertura}


@jurisprudence_bp.route('/api/buscar')
@require_law_firm
def api_buscar():
    consulta = (request.args.get('q') or '').strip()
    if len(consulta) < 2:
        return jsonify({'decisoes': []})
    return jsonify({'decisoes': busca.buscar_para_geracao(get_current_law_firm_id(), consulta)})


# ── Decisão ───────────────────────────────────────────────────────────

@jurisprudence_bp.route('/decisao/<int:decision_id>')
@require_law_firm
def decisao(decision_id):
    d = _decisao(decision_id)
    em_leitura = next((u for u in envios.painel(d.law_firm_id, limite=200)['linhas']
                       if u['upload'].decision_id == d.id and u['estado'] in ('queued', 'processing')), None)
    return render_template(
        'jurisprudence/decision.html',
        d=d,
        trilha=svc.decisoes_do_processo(d),
        precedentes=svc.precedentes_com_link(d),
        citacao=norm.citacao(d),
        catalogo=sorted({c for t in d.theses for c in t.catalog_theses}, key=lambda c: c.name),
        pdf_disponivel=bool(d.pdf_path and os.path.exists(d.pdf_path)),
        em_leitura=em_leitura,
    )


@jurisprudence_bp.route('/decisao/<int:decision_id>/parecidas')
@require_law_firm
def parecidas(decision_id):
    """Decisões semanticamente próximas — carregado pela página da decisão."""
    d = _decisao(decision_id)
    achados = indice.parecidas(d)
    if achados is None:
        return jsonify({'disponivel': False, 'decisoes': []})
    decisoes = {x.id: x for x in JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == d.law_firm_id,
        JurisprudenceDecision.id.in_([a['decision_id'] for a in achados])).all()} if achados else {}
    return jsonify({'disponivel': True, 'decisoes': [
        {**busca.resumo_para_geracao(decisoes[a['decision_id']]),
         'url': url_for('jurisprudence.decisao', decision_id=a['decision_id'])}
        for a in achados if a['decision_id'] in decisoes
    ]})


@jurisprudence_bp.route('/decisao/<int:decision_id>/pdf')
@require_law_firm
def decisao_pdf(decision_id):
    d = _decisao(decision_id)
    if not d.pdf_path or not os.path.exists(d.pdf_path):
        abort(404)
    resposta = send_file(os.path.abspath(d.pdf_path), mimetype='application/pdf',
                         as_attachment=False, download_name=d.original_filename or 'decisao.pdf')
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    return resposta


def _lista_do_form(nome: str) -> list[str]:
    return [linha.strip(' •-\t') for linha in (request.form.get(nome) or '').splitlines() if linha.strip(' •-\t')]


@jurisprudence_bp.route('/decisao/<int:decision_id>/editar', methods=['GET', 'POST'])
@require_law_firm
def editar(decision_id):
    d = _decisao(decision_id)
    if request.method == 'GET':
        return render_template('jurisprudence/edit.html', d=d,
                               resultado_labels=norm.RESULTADO_LABELS, tipo_labels=norm.TIPO_LABELS)
    bruto = {
        'processo': request.form.get('processo'),
        'tribunal': request.form.get('tribunal'),
        'orgao_julgador': request.form.get('orgao_julgador'),
        'uf': request.form.get('uf'),
        'relator': request.form.get('relator'),
        'data_julgamento': request.form.get('data_julgamento'),
        'tipo_documento': norm.TIPO_LABELS.get(request.form.get('tipo_documento'), request.form.get('tipo_documento')),
        'classe_processual': request.form.get('classe_processual'),
        'resultado': norm.RESULTADO_LABELS.get(request.form.get('resultado'), request.form.get('resultado')),
        'motivo_resultado': request.form.get('motivo_resultado'),
        'parte_autora': request.form.get('parte_autora'),
        'vigencia_fap': request.form.get('vigencia_fap'),
        'ementa': request.form.get('ementa'),
        'resumo_executivo': request.form.get('resumo_executivo'),
        'teses': _lista_do_form('teses'),
        'fundamentos': _lista_do_form('fundamentos'),
        'precedentes': _lista_do_form('precedentes'),
        'argumentos_acolhidos': _lista_do_form('argumentos_acolhidos'),
        'argumentos_rejeitados': _lista_do_form('argumentos_rejeitados'),
    }
    mudaram = svc.corrigir_manualmente(d, bruto, svc.ResolvedorDeTeses(d.law_firm_id))
    db.session.commit()
    if mudaram:
        indice.agendar(d.law_firm_id, [d.id])
    flash(f'{len(mudaram)} campo(s) corrigido(s). O reprocessamento pela IA não sobrescreve o que foi corrigido à mão.'
          if mudaram else 'Nada mudou.', 'success' if mudaram else 'info')
    return redirect(url_for('jurisprudence.decisao', decision_id=d.id))


@jurisprudence_bp.route('/decisao/<int:decision_id>/anexar-pdf', methods=['POST'])
@require_law_firm
def anexar_pdf(decision_id):
    d = _decisao(decision_id)
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        flash('Escolha o PDF da decisão.', 'warning')
    else:
        try:
            envios.anexar_pdf(d.law_firm_id, d, arquivo)
            flash('PDF anexado. Agora a decisão pode ser reprocessada pela IA.', 'success')
        except envios.ArquivoRecusado as erro:
            flash(str(erro), 'warning')
    return redirect(url_for('jurisprudence.decisao', decision_id=d.id))


@jurisprudence_bp.route('/decisao/<int:decision_id>/reprocessar', methods=['POST'])
@require_law_firm
def reprocessar(decision_id):
    d = _decisao(decision_id)
    try:
        envios.reprocessar_decisao(d.law_firm_id, d, session.get('user_id'))
        flash('Leitura iniciada. O que foi corrigido à mão será preservado.', 'info')
    except ValueError as erro:
        flash(str(erro), 'warning')
    return redirect(url_for('jurisprudence.decisao', decision_id=d.id))


@jurisprudence_bp.route('/decisao/<int:decision_id>/excluir', methods=['POST'])
@require_law_firm
@require_admin_user
def excluir(decision_id):
    d = _decisao(decision_id)
    indice.remover(d.law_firm_id, d.id)
    svc.excluir_decisao(d)
    db.session.commit()
    flash('Decisão excluída da base.', 'success')
    return redirect(url_for('jurisprudence.index'))


# ── Importar planilha ─────────────────────────────────────────────────

@jurisprudence_bp.route('/importar', methods=['GET', 'POST'])
@require_law_firm
def importar():
    law_firm_id = get_current_law_firm_id()
    if request.method == 'GET':
        return render_template('jurisprudence/import.html', conferencia=None, token=None)
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename or not arquivo.filename.lower().endswith('.xlsx'):
        flash('Envie a planilha em .xlsx.', 'warning')
        return redirect(url_for('jurisprudence.importar'))
    token = importacao.guardar_arquivo(law_firm_id, arquivo)
    nomes = session.get('jurisprudence_imports') or {}
    nomes[token] = arquivo.filename[:200]
    session['jurisprudence_imports'] = dict(list(nomes.items())[-5:])
    return redirect(url_for('jurisprudence.conferir', token=token))


@jurisprudence_bp.route('/importar/<token>')
@require_law_firm
def conferir(token):
    law_firm_id = get_current_law_firm_id()
    nome = (session.get('jurisprudence_imports') or {}).get(token)
    try:
        caminho = importacao.caminho_da_importacao(law_firm_id, token)
        if not os.path.exists(caminho):
            raise importacao.PlanilhaInvalida('Importação não encontrada. Envie a planilha de novo.')
        conferencia = importacao.conferir(law_firm_id, caminho, nome)
    except importacao.PlanilhaInvalida as erro:
        flash(str(erro), 'warning')
        return redirect(url_for('jurisprudence.importar'))
    return render_template('jurisprudence/import.html', conferencia=conferencia, token=token,
                           tipo_labels=norm.TIPO_LABELS)


@jurisprudence_bp.route('/importar/<token>/confirmar', methods=['POST'])
@require_law_firm
def confirmar_importacao(token):
    law_firm_id = get_current_law_firm_id()
    nome = (session.get('jurisprudence_imports') or {}).get(token)
    try:
        caminho = importacao.caminho_da_importacao(law_firm_id, token)
        if not os.path.exists(caminho):
            raise importacao.PlanilhaInvalida('Importação não encontrada. Envie a planilha de novo.')
        resultado = importacao.importar(law_firm_id, caminho, user_id=session.get('user_id'), nome_arquivo=nome)
        indice.agendar(law_firm_id, resultado['ids'])
    except importacao.PlanilhaInvalida as erro:
        flash(str(erro), 'warning')
        return redirect(url_for('jurisprudence.importar'))
    flash(f"{resultado['criadas']} decisão(ões) importada(s); {resultado['puladas']} já estavam na base. "
          f"{resultado['teses_criadas']} tese(s) nova(s), {resultado['teses_ligadas_sozinhas']} ligada(s) "
          'ao catálogo automaticamente.', 'success')
    pendentes = svc.contar_teses_pendentes(law_firm_id)
    if pendentes:
        return redirect(url_for('jurisprudence.teses'))
    return redirect(url_for('jurisprudence.index'))


# ── Enviar decisões (PDF) ─────────────────────────────────────────────

@jurisprudence_bp.route('/enviar', methods=['GET', 'POST'])
@require_law_firm
def enviar():
    law_firm_id = get_current_law_firm_id()
    if request.method == 'POST':
        ids, recusas = envios.receber(law_firm_id, request.files.getlist('arquivos'), session.get('user_id'))
        for recusa in recusas:
            flash(recusa, 'warning')
        if ids:
            flash(f'{len(ids)} arquivo(s) na fila. A leitura roda em segundo plano — pode fechar esta tela.', 'info')
        return redirect(url_for('jurisprudence.enviar'))
    from app.services import ai_model_settings_service
    return render_template('jurisprudence/upload.html', p=envios.painel(law_firm_id),
                           cobertura=envios.cobertura(law_firm_id),
                           modelo=ai_model_settings_service.get_model(law_firm_id, 'jurisprudence_extractor'))


@jurisprudence_bp.route('/enviar/anexar-lote', methods=['POST'])
@require_law_firm
def anexar_lote():
    """PDFs das decisões importadas da planilha, casados pelo nome do arquivo."""
    r = envios.anexar_em_lote(get_current_law_firm_id(), request.files.getlist('arquivos'))
    for recusa in r['recusas']:
        flash(recusa, 'warning')
    if r['anexadas']:
        flash(f"{r['anexadas']} PDF(s) anexado(s) às decisões. O inteiro teor é extraído e indexado em segundo plano.",
              'success')
    if r['sem_par']:
        amostra = ', '.join(r['sem_par'][:5]) + ('…' if len(r['sem_par']) > 5 else '')
        flash(f"{len(r['sem_par'])} arquivo(s) sem decisão correspondente pelo nome ({amostra}). "
              'Se forem decisões novas, envie-os na área de cima para a IA ler.', 'warning')
    return redirect(url_for('jurisprudence.enviar'))


@jurisprudence_bp.route('/enviar/drive', methods=['POST'])
@require_law_firm
def buscar_no_drive():
    n = envios.buscar_no_drive(get_current_law_firm_id())
    flash(f'Buscando {n} PDF(s) no Drive em segundo plano.' if n
          else 'Nada a buscar agora (já em andamento, ou todas as decisões com link já têm PDF).', 'info')
    return redirect(url_for('jurisprudence.enviar'))


@jurisprudence_bp.route('/enviar/status')
@require_law_firm
def enviar_status():
    painel = envios.painel(get_current_law_firm_id())
    return jsonify({'contagem': painel['contagem'], 'ativos': painel['ativos'],
                    'assinatura': [(l['upload'].id, l['estado']) for l in painel['linhas']]})


def _acao_do_envio(funcao, upload_id, *args):
    try:
        return funcao(get_current_law_firm_id(), upload_id, *args)
    except (LookupError, ValueError) as erro:
        flash(str(erro), 'warning')
        return None


@jurisprudence_bp.route('/enviar/<int:upload_id>/tentar-de-novo', methods=['POST'])
@require_law_firm
def tentar_de_novo(upload_id):
    _acao_do_envio(envios.tentar_de_novo, upload_id, session.get('user_id'))
    return redirect(url_for('jurisprudence.enviar'))


@jurisprudence_bp.route('/enviar/<int:upload_id>/descartar', methods=['POST'])
@require_law_firm
def descartar_envio(upload_id):
    _acao_do_envio(envios.descartar, upload_id)
    return redirect(url_for('jurisprudence.enviar'))


@jurisprudence_bp.route('/enviar/<int:upload_id>/resolver', methods=['POST'])
@require_law_firm
def resolver_envio(upload_id):
    decisao_id = _acao_do_envio(envios.resolver_duplicata, upload_id,
                                request.form.get('acao', ''), session.get('user_id'))
    if decisao_id:
        flash('Pronto.', 'success')
    return redirect(url_for('jurisprudence.enviar'))


# ── Correspondência de teses ──────────────────────────────────────────

@jurisprudence_bp.route('/teses')
@require_law_firm
def teses():
    filtro = request.args.get('filtro') if request.args.get('filtro') in teses_svc.FILTROS else 'pendentes'
    dados = teses_svc.listar(get_current_law_firm_id(), filtro, request.args.get('q') or '')
    return render_template('jurisprudence/theses.html', dados=dados, filtro=filtro,
                           q=request.args.get('q') or '', is_admin=session.get('user_role') == 'admin')


def _voltar_para_teses():
    # Só caminho interno: `voltar` vem do formulário e não pode virar
    # redirecionamento para outro domínio.
    voltar = request.form.get('voltar') or ''
    if not voltar.startswith('/') or voltar.startswith('//') or '\\' in voltar:
        voltar = url_for('jurisprudence.teses')
    return redirect(voltar)


@jurisprudence_bp.route('/teses/<int:thesis_id>/<acao>', methods=['POST'])
@require_law_firm
def tese_acao(thesis_id, acao):
    law_firm_id = get_current_law_firm_id()
    try:
        if acao == 'ligar':
            teses_svc.ligar(law_firm_id, thesis_id, request.form.getlist('catalogo'))
        elif acao == 'sem-equivalente':
            teses_svc.marcar_sem_equivalente(law_firm_id, thesis_id)
        elif acao == 'reabrir':
            teses_svc.reabrir(law_firm_id, thesis_id)
        elif acao == 'mesclar':
            teses_svc.mesclar(law_firm_id, thesis_id, int(request.form.get('canonica') or 0))
        elif acao == 'desfazer-mescla':
            teses_svc.desfazer_mescla(law_firm_id, thesis_id)
        elif acao == 'aceitar':
            teses_svc.aceitar_sugestao(law_firm_id, thesis_id)
        elif acao == 'descartar-sugestao':
            teses_svc.descartar_sugestao(law_firm_id, thesis_id)
        elif acao == 'criar-no-catalogo':
            if session.get('user_role') != 'admin':
                flash('Só administradores criam teses no catálogo.', 'danger')
                return _voltar_para_teses()
            nova = teses_svc.criar_no_catalogo(law_firm_id, thesis_id)
            flash(f'Tese "{nova.name}" criada no catálogo e ligada.', 'success')
        else:
            abort(404)
    except (LookupError, ValueError) as erro:
        db.session.rollback()
        flash(str(erro), 'warning')
    return _voltar_para_teses()


@jurisprudence_bp.route('/teses/sugerir', methods=['POST'])
@require_law_firm
def teses_sugerir():
    law_firm_id = get_current_law_firm_id()
    if not JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, is_active=True).first():
        flash('O catálogo de teses do painel está vazio — cadastre as teses antes de pedir sugestões.', 'warning')
    elif teses_svc.sugestoes_em_andamento(law_firm_id):
        flash('A IA já está analisando as teses. A página atualiza sozinha.', 'info')
    else:
        n = teses_svc.pedir_sugestoes(law_firm_id, session.get('user_id'))
        flash(f'A IA está analisando {n} tese(s). As sugestões aparecem aqui quando terminar.' if n
              else 'Todas as teses pendentes já têm sugestão.', 'info')
    return redirect(url_for('jurisprudence.teses', filtro='sugeridas'))


@jurisprudence_bp.route('/teses/sugestoes/status')
@require_law_firm
def teses_sugestoes_status():
    return jsonify({'em_andamento': teses_svc.sugestoes_em_andamento(get_current_law_firm_id())})
