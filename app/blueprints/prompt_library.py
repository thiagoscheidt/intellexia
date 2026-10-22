"""
Biblioteca de IA (``/prompts``) — prompts, agentes e skills de cada pessoa
e do escritório, com cópia rápida e os mesmos itens como comando no Claude.

Qualquer usuário logado acessa (não é módulo: a biblioteca não expõe dado do
escritório). As regras ficam em ``prompt_library_service``; aqui só a tela.
"""
from __future__ import annotations

import json

from flask import (
    Blueprint, abort, flash, jsonify, make_response, redirect, render_template, request, session, url_for,
)

from app.models import User, db
from app.services import prompt_library_service as svc

prompt_library_bp = Blueprint('prompt_library', __name__, url_prefix='/prompts')


def _usuario() -> User:
    return db.session.get(User, session['user_id'])


def _item_ou_404(item_id: int, user: User):
    item = svc.obter(item_id, user)
    if item is None:
        abort(404)
    return item


def _voltar(aba: str | None = None):
    destino = request.form.get('voltar') or request.args.get('voltar')
    if destino and destino.startswith('/prompts') and not destino.startswith('//'):
        return redirect(destino)
    return redirect(url_for('prompt_library.index', aba=aba) if aba else url_for('prompt_library.index'))


@prompt_library_bp.route('/')
def index():
    user = _usuario()
    itens = svc.listar(user)
    sistema = svc.prompts_do_sistema_com_uso(user.law_firm_id)
    meus = [i for i in itens if i['meu']]
    escritorio = [i for i in itens if i['visibilidade'] == 'escritorio']
    return render_template(
        'prompt_library/index.html',
        itens=itens,
        sistema=sistema,
        contagem={
            'meus': len(meus),
            'escritorio': len(escritorio),
            'sistema': len(sistema),
            'favoritos': sum(1 for i in itens if i['favorito']),
            'usos': sum(i['usos'] for i in escritorio) + sum(i['usos'] for i in meus if i['visibilidade'] == 'pessoal'),
        },
        tipos=svc.TIPOS,
        tipo_icone=svc.TIPO_ICONE,
        areas=svc.AREAS,
        eh_admin=str(user.role or '').lower() == 'admin',
        ferramentas=svc.cards_ferramentas(user),
        aba=request.args.get('aba') or ('escritorio' if escritorio and not meus else 'meus'),
        # Texto de cada card para Copiar/Preencher, fora do HTML dos cards.
        dict_textos={str(i['id']): {'titulo': i['titulo'], 'texto': i['texto'], 'campos': i['campos'],
                                    'sistema': i['sistema'], 'comando': i['comando']}
                     for i in itens + sistema},
    )


# ── editor ───────────────────────────────────────────────────────────────────

def _dados_do_form() -> dict:
    nomes = request.form.getlist('anexo_nome')
    conteudos = request.form.getlist('anexo_conteudo')
    return {
        'titulo': request.form.get('titulo', ''),
        'comando': request.form.get('comando', ''),
        'descricao': request.form.get('descricao', ''),
        'corpo': request.form.get('corpo', ''),
        'tipo': request.form.get('tipo', 'prompt'),
        'area': request.form.get('area', 'geral'),
        'visibilidade': request.form.get('visibilidade', 'pessoal'),
        'usa_intellexia': request.form.get('usa_intellexia') == '1',
        'anexos': [{'nome': n, 'conteudo': c} for n, c in zip(nomes, conteudos)],
    }


def _editor(item=None, dados: dict | None = None, erro: str | None = None, achados=None, status: int = 200):
    if dados is None:
        dados = ({'titulo': item.titulo, 'comando': item.slug, 'descricao': item.descricao or '', 'corpo': item.corpo,
                  'tipo': item.tipo, 'area': item.area, 'visibilidade': item.visibilidade,
                  'usa_intellexia': item.usa_intellexia, 'anexos': svc.anexos(item)}
                 if item else {'titulo': '', 'comando': '', 'descricao': '', 'corpo': '', 'tipo': 'prompt', 'area': 'geral',
                               'visibilidade': 'pessoal', 'usa_intellexia': False, 'anexos': []})
    user = _usuario()
    ferramentas = svc.cards_ferramentas(user)
    return render_template(
        'prompt_library/editor.html', item=item, dados=dados, erro=erro, achados=achados or [],
        ferramentas=ferramentas,
        # nome -> o que o editor precisa para o aviso de módulo, sem a descrição inteira.
        mapa_ferramentas={i['nome']: {'modulo': i['modulo_rotulo'], 'so_admin': i['so_admin'], 'acesso': i['acesso']}
                          for i in ferramentas['itens']},
        tipos=svc.TIPOS, tipo_icone=svc.TIPO_ICONE, areas=svc.AREAS, visibilidades=svc.VISIBILIDADES,
        pode_compartilhar=item is None or item.owner_id == user.id,
        prefixo_comando=svc.prefixo_comando,
    ), status


def _salvar(item=None):
    user = _usuario()
    dados = _dados_do_form()
    if item is not None and item.owner_id != user.id:
        dados['visibilidade'] = item.visibilidade  # admin edita, mas não muda quem vê
    confirmar = request.form.get('confirmar_dados') == '1'
    try:
        salvo = svc.editar(item, user, dados, confirmar) if item else svc.criar(user, dados, confirmar)
    except svc.DadosPessoais as e:
        return _editor(item, dados, str(e), e.achados, 422)
    except svc.ErroBiblioteca as e:
        return _editor(item, dados, str(e), status=400)
    flash(f'“{salvo.titulo}” salvo na biblioteca.', 'success')
    return redirect(url_for('prompt_library.index', aba='escritorio' if salvo.visibilidade == 'escritorio' else 'meus',
                            _anchor=f'item-{salvo.id}'))


@prompt_library_bp.route('/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        return _salvar()
    tipo = request.args.get('tipo')
    ferramenta = request.args.get('ferramenta', '')
    if ferramenta not in svc._modulos_das_ferramentas():
        ferramenta = ''
    if ferramenta:
        tipo = 'agente'  # "Usar num agente", da lista de ferramentas
    if tipo in svc.TIPOS:
        # O "+ Novo" da tela já diz o tipo: o editor abre com ele marcado.
        return _editor(dados={'titulo': '', 'comando': '', 'descricao': '', 'tipo': tipo,
                              'corpo': svc.linha_da_ferramenta(ferramenta) if ferramenta else '',
                              'area': 'geral', 'visibilidade': 'pessoal', 'usa_intellexia': tipo == 'agente',
                              'anexos': []})
    return _editor()


@prompt_library_bp.route('/<int:item_id>/editar', methods=['GET', 'POST'])
def editar(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    if not svc.pode_editar(item, user):
        flash('Só quem criou o item (ou um administrador, se for do escritório) pode editá-lo.', 'danger')
        return redirect(url_for('prompt_library.index'))
    if request.method == 'POST':
        return _salvar(item)
    return _editor(item)


# ── ações dos cards ──────────────────────────────────────────────────────────

@prompt_library_bp.route('/<int:item_id>/duplicar', methods=['POST'])
def duplicar(item_id: int):
    user = _usuario()
    copia = svc.duplicar(_item_ou_404(item_id, user), user)
    flash('Cópia criada em “Meus”. Ajuste à vontade.', 'success')
    return redirect(url_for('prompt_library.editar', item_id=copia.id))


@prompt_library_bp.route('/sistema/<nome>/duplicar', methods=['POST'])
def duplicar_sistema(nome: str):
    origem = svc.prompt_do_sistema(nome)
    if origem is None:
        abort(404)
    copia = svc.duplicar(origem, _usuario())
    flash('Cópia criada em “Meus”. Ajuste à vontade.', 'success')
    return redirect(url_for('prompt_library.editar', item_id=copia.id))


@prompt_library_bp.route('/<int:item_id>/arquivar', methods=['POST'])
def arquivar(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    try:
        svc.arquivar(item, user)
        flash(f'“{item.titulo}” saiu da biblioteca.', 'success')
    except PermissionError as e:
        flash(str(e), 'danger')
    return _voltar()


@prompt_library_bp.route('/<int:item_id>/visibilidade', methods=['POST'])
def visibilidade(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    destino = request.form.get('visibilidade', '')
    try:
        svc.alterar_visibilidade(item, user, destino, request.form.get('confirmar_dados') == '1')
    except svc.DadosPessoais as e:
        flash(str(e) + ' Abra o item, revise o texto e salve marcando a confirmação.', 'warning')
        return redirect(url_for('prompt_library.editar', item_id=item.id))
    except (PermissionError, svc.ErroBiblioteca) as e:
        flash(str(e), 'danger')
        return _voltar()
    flash('Compartilhado com o escritório.' if destino == 'escritorio' else 'Agora só você vê este item.', 'success')
    return _voltar('escritorio' if destino == 'escritorio' else 'meus')


@prompt_library_bp.route('/<int:item_id>/recomendar', methods=['POST'])
def recomendar(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    valor = request.form.get('valor') == '1'
    try:
        svc.recomendar(item, user, valor)
        flash('Marcado como recomendado pelo escritório.' if valor else 'Selo de recomendado retirado.', 'success')
    except (PermissionError, svc.ErroBiblioteca) as e:
        flash(str(e), 'danger')
    return _voltar('escritorio')


@prompt_library_bp.route('/<int:item_id>/skill.zip')
def baixar_skill(item_id: int):
    item = _item_ou_404(item_id, _usuario())
    nome, conteudo = svc.exportar_skill(item)
    resp = make_response(conteudo)
    resp.headers['Content-Type'] = 'application/zip'
    resp.headers['Content-Disposition'] = f'attachment; filename="{nome}"'
    return resp


@prompt_library_bp.route('/importar', methods=['POST'])
def importar():
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        flash('Escolha o .zip da skill ou o arquivo SKILL.md.', 'danger')
        return redirect(url_for('prompt_library.index'))
    try:
        item, ignorados = svc.importar_skill(_usuario(), arquivo.filename, arquivo.read(svc.MAX_UPLOAD + 1))
    except svc.ErroBiblioteca as e:
        flash(str(e), 'danger')
        return redirect(url_for('prompt_library.index'))
    msg = f'Skill “{item.titulo}” importada para “Meus”. Confira e salve.'
    if ignorados:
        msg += (' Ficaram de fora (só arquivos de texto entram na biblioteca): '
                + ', '.join(ignorados[:8]) + ('…' if len(ignorados) > 8 else '') + '.')
    flash(msg, 'warning' if ignorados else 'success')
    return redirect(url_for('prompt_library.editar', item_id=item.id))


# ── JSON (cards) ─────────────────────────────────────────────────────────────

@prompt_library_bp.route('/rapido.json')
def rapido_json():
    """Itens da janela rápida da header (botão Biblioteca / Ctrl+K), lidos só quando ela abre."""
    user = _usuario()
    campos = ('id', 'titulo', 'descricao', 'tipo_rotulo', 'tipo_icone', 'area_rotulo', 'area_cor', 'comando',
              'texto', 'campos', 'favorito', 'recomendado', 'usos', 'visibilidade', 'meu', 'sistema')
    itens = svc.listar(user) + svc.prompts_do_sistema_com_uso(user.law_firm_id)
    resp = jsonify({'itens': [{k: i[k] for k in campos} for i in itens]})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@prompt_library_bp.route('/<int:item_id>/favorito.json', methods=['POST'])
def favorito_json(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    valor = bool((request.get_json(silent=True) or {}).get('favorito'))
    return jsonify({'favorito': svc.favoritar(item, user, valor)})


@prompt_library_bp.route('/<int:item_id>/uso.json', methods=['POST'])
def uso_json(item_id: int):
    item = _item_ou_404(item_id, _usuario())
    svc.registrar_uso(item)
    return jsonify({'usos': (item.usos or 0)})


@prompt_library_bp.route('/<int:item_id>/versoes.json')
def versoes_json(item_id: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    autores = {u.id: u.name for u in User.query.filter_by(law_firm_id=user.law_firm_id)}
    return jsonify({
        'atual': item.versao,
        'pode_restaurar': svc.pode_editar(item, user),
        'versoes': [{
            'versao': v.versao, 'titulo': v.titulo, 'descricao': v.descricao or '', 'corpo': v.corpo,
            'anexos': [a.get('nome') for a in json.loads(v.anexos_json or '[]') if isinstance(a, dict)],
            'autor': autores.get(v.editado_por_id, '—'),
            'em': v.created_at.isoformat() + 'Z',
        } for v in svc.versoes(item)],
    })


@prompt_library_bp.route('/<int:item_id>/versoes/<int:versao>/restaurar', methods=['POST'])
def restaurar(item_id: int, versao: int):
    user = _usuario()
    item = _item_ou_404(item_id, user)
    try:
        svc.restaurar(item, user, versao)
        flash(f'Versão {versao} restaurada (virou a versão {item.versao}).', 'success')
    except (PermissionError, svc.ErroBiblioteca) as e:
        flash(str(e), 'danger')
    return _voltar()


@prompt_library_bp.app_template_filter('plb_previa')
def _previa(texto: str, limite: int = 420):
    """Começo do texto, escapado, com os ``{{campos}}`` marcados."""
    from markupsafe import Markup, escape

    trecho = (texto or '')[:limite]
    seguro = str(escape(trecho))
    return Markup(svc._CAMPO.sub(lambda m: f'<span class="plb-campo">{m.group(0)}</span>', seguro))


@prompt_library_bp.app_template_global('static_versionado')
def _static_versionado(arquivo: str) -> str:
    """URL do estático com ``?v=<mtime>``: arquivo mudou, endereço muda, e o
    navegador não fica com o CSS/JS antigo (o modal novo chegou sem estilo assim)."""
    import os

    from flask import current_app

    try:
        versao = int(os.path.getmtime(os.path.join(current_app.static_folder, arquivo)))
    except OSError:
        versao = 0
    return url_for('static', filename=arquivo, v=versao)
