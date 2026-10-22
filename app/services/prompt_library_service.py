"""
Biblioteca de IA — prompts, agentes e skills de cada pessoa e do escritório.

Fonte única da tela ``/prompts`` (``prompt_library``) e do servidor MCP
(comandos ``meu_*``/``escritorio_*`` e as ferramentas ``biblioteca_prompts``,
``usar_prompt`` e ``salvar_prompt``).

- **Um tipo só por baixo.** Prompt, agente e skill são etiquetas: todos têm
  texto, "quando usar", campos ``{{campo}}`` lidos do texto e anexos de texto.
- **Pessoal é só do dono**, nem o admin vê (como no Claude). Do escritório:
  todos veem; editar é do dono ou de admin. Recomendar é só de admin.
- **Compartilhar confere dado pessoal**: CPF ou CNPJ válido no texto pede
  confirmação antes de o item ir para o escritório.
- **Toda mudança de conteúdo vira versão**, e restaurar cria uma versão nova.
- **Skill do Claude** entra e sai no formato dele (pasta com ``SKILL.md``), só
  com arquivos de texto: script compartilhado rodaria na máquina dos colegas.
- Os comandos prontos do IntellexIA vêm do ``mcp_server/server.py`` por AST,
  sem subir o servidor, com cada argumento trocado por ``{{argumento}}``.
"""
from __future__ import annotations

import ast
import copy
import io
import json
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone

from app.models import (
    PromptLibraryFavorite, PromptLibraryItem, PromptLibraryVersion, User, UserMcpCall, db,
)
from app.utils.cnpj import cpf_valido

TIPOS = {'prompt': 'Prompt', 'agente': 'Agente', 'skill': 'Skill'}
TIPO_ICONE = {'prompt': 'bi-chat-left-text', 'agente': 'bi-robot', 'skill': 'bi-box-seam'}

# chave -> (rótulo, ícone, classe de cor da tela)
AREAS = {
    'fap': ('FAP', 'bi-shield-exclamation', 'fap'),
    'jurisprudencia': ('Jurisprudência', 'bi-bank', 'jur'),
    'processos': ('Processos', 'bi-folder2', 'proc'),
    'comunicacao': ('Comunicação', 'bi-envelope', 'com'),
    'base_conhecimento': ('Base de Conhecimento', 'bi-book', 'kb'),
    'dou': ('Diário Oficial', 'bi-newspaper', 'dou'),
    'geral': ('Geral', 'bi-stars', 'geral'),
}
VISIBILIDADES = {'pessoal': 'Só eu', 'escritorio': 'Escritório'}

PREFIXO_MEU = 'meu_'
PREFIXO_ESCRITORIO = 'escritorio_'

MAX_TITULO = 200
MAX_DESCRICAO = 1000
MAX_CORPO = 200_000
MAX_ANEXOS = 20
MAX_ANEXO = 200_000
MAX_ANEXOS_TOTAL = 1_000_000
MAX_SLUG = 60

# Importar skill: tamanho do arquivo enviado e do que está dentro do zip.
MAX_UPLOAD = 5 * 1024 * 1024
MAX_ARQUIVOS_ZIP = 50
EXTENSOES_TEXTO = {'.md', '.markdown', '.txt', '.csv', '.json', '.yaml', '.yml', '.html', '.htm', '.xml'}

_CAMPO = re.compile(r'\{\{\s*([^\W\d]\w{0,59})\s*\}\}')
_CPF = re.compile(r'(?<![\d./-])(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?![\d./-]*\d)')
_CNPJ = re.compile(r'(?<![\d./-])(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})(?![\d./-]*\d)')

_SERVER_MCP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           'mcp_server', 'server.py')


class ErroBiblioteca(ValueError):
    """Pedido que não serve — a mensagem vai para o usuário como está."""


class DadosPessoais(ErroBiblioteca):
    """O texto a compartilhar tem CPF ou CNPJ: precisa de confirmação."""

    def __init__(self, achados: list[str]):
        self.achados = achados
        super().__init__(
            'O texto tem o que parece ser dado de cliente ou segurado '
            f'({", ".join(achados[:5])}{"…" if len(achados) > 5 else ""}). '
            'Confira antes de compartilhar com o escritório.')


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── texto ────────────────────────────────────────────────────────────────────

def campos(texto: str | None) -> list[str]:
    """Campos ``{{campo}}`` do texto, na ordem em que aparecem, sem repetir."""
    vistos: list[str] = []
    for nome in _CAMPO.findall(texto or ''):
        if nome not in vistos:
            vistos.append(nome)
    return vistos


def preencher(texto: str, valores: dict | None) -> str:
    """Troca cada ``{{campo}}`` informado pelo valor; os não informados ficam como estão."""
    valores = {k: str(v) for k, v in (valores or {}).items() if v not in (None, '')}
    return _CAMPO.sub(lambda m: valores.get(m.group(1), m.group(0)), texto or '')


def slugify(titulo: str) -> str:
    base = unicodedata.normalize('NFKD', titulo or '').encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-z0-9]+', '_', base.lower()).strip('_')
    return (base[:MAX_SLUG].rstrip('_') or 'prompt')


def _comando(dados: dict, law_firm_id: int, titulo: str, atual=None) -> str:
    """O ``slug`` do item: o comando escolhido pela pessoa ou, sem escolha, o do título.

    Escolhido e ocupado é erro (a pessoa decidiu o nome); automático ganha sufixo.
    Sem escolha na edição, fica o atual: renomear o título não troca o comando
    que as pessoas já decoraram.
    """
    bruto = str(dados.get('comando') or '').strip().lstrip('/')
    # Quem cola o comando inteiro (/escritorio_prompt_x) escolheu só o "x".
    for prefixo in (PREFIXO_ESCRITORIO, PREFIXO_MEU):
        if bruto.lower().startswith(prefixo):
            bruto = bruto[len(prefixo):]
            break
    for tipo in TIPOS:
        if bruto.lower().startswith(tipo + '_'):
            bruto = bruto[len(tipo) + 1:]
            break
    if not bruto:
        return atual.slug if atual else _slug_unico(law_firm_id, titulo)
    slug = slugify(bruto)
    if atual is not None and slug == atual.slug:
        return slug
    ocupado = PromptLibraryItem.query.filter(
        PromptLibraryItem.law_firm_id == law_firm_id, PromptLibraryItem.slug == slug,
        PromptLibraryItem.id != (atual.id if atual else 0)).first()
    if ocupado:
        raise ErroBiblioteca(f'O comando "{slug}" já está em uso no escritório. Escolha outro nome.')
    return slug


def _slug_unico(law_firm_id: int, titulo: str, exceto_id: int | None = None) -> str:
    base = slugify(titulo)
    q = PromptLibraryItem.query.filter(PromptLibraryItem.law_firm_id == law_firm_id)
    if exceto_id:
        q = q.filter(PromptLibraryItem.id != exceto_id)
    usados = {s for (s,) in q.filter(PromptLibraryItem.slug.like(base + '%'))
              .with_entities(PromptLibraryItem.slug)}
    if base not in usados:
        return base
    n = 2
    while f'{base}_{n}' in usados:
        n += 1
    return f'{base}_{n}'


def dados_pessoais(*textos: str) -> list[str]:
    """CPFs e CNPJs válidos (DV) nos textos, mascarados para o aviso."""
    from app.services.dou_alert_service import cnpj_valido

    achados: list[str] = []
    for texto in textos:
        for m in _CNPJ.finditer(texto or ''):
            d = re.sub(r'\D', '', m.group(1))
            if cnpj_valido(d):
                achados.append(f'CNPJ {d[:2]}.***.***/{d[8:12]}-**')
        for m in _CPF.finditer(texto or ''):
            d = re.sub(r'\D', '', m.group(1))
            if cpf_valido(d):
                achados.append(f'CPF ***.{d[3:6]}.***-**')
    return list(dict.fromkeys(achados))


# ── anexos ───────────────────────────────────────────────────────────────────

def anexos(item) -> list[dict]:
    try:
        lista = json.loads(item.anexos_json or '[]')
    except (TypeError, ValueError):
        return []
    return [a for a in lista if isinstance(a, dict) and a.get('nome')]


def _limpar_anexos(brutos) -> list[dict]:
    limpos: list[dict] = []
    total = 0
    for a in brutos or []:
        nome = os.path.basename(str((a or {}).get('nome') or '').replace('\\', '/')).strip()[:200]
        conteudo = str((a or {}).get('conteudo') or '')
        if not nome and not conteudo.strip():
            continue
        if not nome:
            raise ErroBiblioteca('Dê um nome a cada anexo (ex.: checklist.md).')
        if len(conteudo) > MAX_ANEXO:
            raise ErroBiblioteca(f'O anexo "{nome}" passa de {MAX_ANEXO // 1000} mil caracteres.')
        if any(x['nome'] == nome for x in limpos):
            raise ErroBiblioteca(f'Há dois anexos chamados "{nome}".')
        total += len(conteudo)
        limpos.append({'nome': nome, 'conteudo': conteudo})
    if len(limpos) > MAX_ANEXOS:
        raise ErroBiblioteca(f'No máximo {MAX_ANEXOS} anexos por item.')
    if total > MAX_ANEXOS_TOTAL:
        raise ErroBiblioteca(f'Os anexos somam mais de {MAX_ANEXOS_TOTAL // 1_000_000} milhão de caracteres.')
    return limpos


# ── acesso ───────────────────────────────────────────────────────────────────

def _eh_admin(user: User) -> bool:
    return str(user.role or '').strip().lower() == 'admin'


def visiveis(user: User):
    """Query dos itens que o usuário vê: os dele e os do escritório, sem arquivados."""
    return PromptLibraryItem.query.filter(
        PromptLibraryItem.law_firm_id == user.law_firm_id,
        PromptLibraryItem.arquivado_em.is_(None),
        db.or_(PromptLibraryItem.visibilidade == 'escritorio', PromptLibraryItem.owner_id == user.id),
    )


def obter(item_id: int, user: User):
    """O item, se o usuário o vê; senão ``None`` (de outro escritório, pessoal alheio ou arquivado)."""
    return visiveis(user).filter(PromptLibraryItem.id == item_id).first()


def pode_editar(item, user: User) -> bool:
    if item.law_firm_id != user.law_firm_id:
        return False
    if item.owner_id == user.id:
        return True
    return item.visibilidade == 'escritorio' and _eh_admin(user)


def _exigir_edicao(item, user: User) -> None:
    if not pode_editar(item, user):
        raise PermissionError('Só quem criou o item (ou um administrador, se for do escritório) pode alterá-lo.')


def prefixo_comando(visibilidade: str, tipo: str) -> str:
    """``escritorio_agente_`` / ``meu_prompt_``: de quem é e o que é, antes do nome."""
    escopo = PREFIXO_ESCRITORIO if visibilidade == 'escritorio' else PREFIXO_MEU
    return f'{escopo}{tipo if tipo in TIPOS else "prompt"}_'


def nome_comando(item) -> str:
    return prefixo_comando(item.visibilidade, item.tipo) + item.slug


def item_por_comando(user: User, nome: str):
    """O item que o usuário vê com esse nome de comando, ou ``None``."""
    nome = (nome or '').strip()
    for vis in ('escritorio', 'pessoal'):
        for tipo in TIPOS:
            prefixo = prefixo_comando(vis, tipo)
            if not nome.startswith(prefixo):
                continue
            q = visiveis(user).filter(PromptLibraryItem.slug == nome[len(prefixo):],
                                      PromptLibraryItem.visibilidade == vis, PromptLibraryItem.tipo == tipo)
            if vis == 'pessoal':
                q = q.filter(PromptLibraryItem.owner_id == user.id)
            return q.first()
    return None


# ── gravação ─────────────────────────────────────────────────────────────────

def _validar(dados: dict, atual=None) -> dict:
    def texto(chave, padrao=''):
        valor = dados.get(chave, getattr(atual, chave, padrao) if atual else padrao)
        return str(valor if valor is not None else '').strip()

    titulo = texto('titulo')
    corpo = str(dados.get('corpo', atual.corpo if atual else '') or '')
    if not titulo:
        raise ErroBiblioteca('Dê um título.')
    if len(titulo) > MAX_TITULO:
        raise ErroBiblioteca(f'O título passa de {MAX_TITULO} caracteres.')
    if not corpo.strip():
        raise ErroBiblioteca('O texto está vazio.')
    if len(corpo) > MAX_CORPO:
        raise ErroBiblioteca(f'O texto passa de {MAX_CORPO // 1000} mil caracteres.')
    descricao = texto('descricao')
    if len(descricao) > MAX_DESCRICAO:
        raise ErroBiblioteca(f'O "quando usar" passa de {MAX_DESCRICAO} caracteres.')
    tipo = texto('tipo', 'prompt') or 'prompt'
    if tipo not in TIPOS:
        raise ErroBiblioteca('Tipo inválido: use prompt, agente ou skill.')
    area = texto('area', 'geral') or 'geral'
    if area not in AREAS:
        raise ErroBiblioteca(f'Área inválida. Use: {", ".join(AREAS)}.')
    visibilidade = texto('visibilidade', 'pessoal') or 'pessoal'
    if visibilidade not in VISIBILIDADES:
        raise ErroBiblioteca('Visibilidade inválida: use pessoal ou escritorio.')
    usa = dados.get('usa_intellexia', atual.usa_intellexia if atual else False)
    if isinstance(usa, str):
        usa = usa.strip().lower() in ('1', 'true', 'on', 'sim')
    if 'anexos' in dados:
        lista_anexos = _limpar_anexos(dados.get('anexos'))
    else:
        lista_anexos = anexos(atual) if atual else []
    # Citar uma ferramenta do conector já é usar os dados do IntellexIA.
    usa = bool(usa) or bool(ferramentas_citadas(corpo + ' ' + ' '.join(a['conteudo'] for a in lista_anexos)))
    return {'titulo': titulo, 'corpo': corpo, 'descricao': descricao or None, 'tipo': tipo, 'area': area,
            'visibilidade': visibilidade, 'usa_intellexia': usa, 'anexos': lista_anexos}


def _validar_com_comando(dados: dict, law_firm_id: int, atual=None) -> dict:
    v = _validar(dados, atual)
    v['slug'] = _comando(dados, law_firm_id, v['titulo'], atual)
    return v


def _conferir_dados(v: dict, confirmar_dados: bool) -> None:
    if v['visibilidade'] != 'escritorio' or confirmar_dados:
        return
    achados = dados_pessoais(v['titulo'], v['descricao'] or '', v['corpo'],
                             *[a['conteudo'] for a in v['anexos']])
    if achados:
        raise DadosPessoais(achados)


def _anexos_json(lista: list[dict]) -> str | None:
    return json.dumps(lista, ensure_ascii=False) if lista else None


def _gravar_versao(item, user_id: int | None) -> None:
    db.session.add(PromptLibraryVersion(
        item_id=item.id, law_firm_id=item.law_firm_id, versao=item.versao, titulo=item.titulo,
        descricao=item.descricao, corpo=item.corpo, anexos_json=item.anexos_json,
        editado_por_id=user_id, created_at=_agora()))


def criar(user: User, dados: dict, confirmar_dados: bool = False) -> PromptLibraryItem:
    v = _validar_com_comando(dados, user.law_firm_id)
    _conferir_dados(v, confirmar_dados)
    agora = _agora()
    item = PromptLibraryItem(
        law_firm_id=user.law_firm_id, owner_id=user.id, tipo=v['tipo'], titulo=v['titulo'],
        slug=v['slug'], descricao=v['descricao'], corpo=v['corpo'],
        anexos_json=_anexos_json(v['anexos']), area=v['area'], usa_intellexia=v['usa_intellexia'],
        visibilidade=v['visibilidade'], versao=1, usos=0, created_at=agora, updated_at=agora)
    db.session.add(item)
    db.session.flush()
    _gravar_versao(item, user.id)
    db.session.commit()
    return item


def editar(item, user: User, dados: dict, confirmar_dados: bool = False) -> PromptLibraryItem:
    _exigir_edicao(item, user)
    v = _validar_com_comando(dados, item.law_firm_id, atual=item)
    mudou = _conteudo_mudou(item, v)
    # Já estava no escritório e o conteúdo não mudou: nada novo a conferir.
    _conferir_dados(v, confirmar_dados or (item.visibilidade == 'escritorio' and not mudou))
    item.slug = v['slug']
    item.titulo, item.descricao, item.corpo = v['titulo'], v['descricao'], v['corpo']
    item.anexos_json = _anexos_json(v['anexos'])
    item.tipo, item.area, item.usa_intellexia = v['tipo'], v['area'], v['usa_intellexia']
    _mudar_visibilidade(item, v['visibilidade'])
    item.updated_at = _agora()
    if mudou:
        item.versao = (item.versao or 1) + 1
        _gravar_versao(item, user.id)
    db.session.commit()
    return item


def _conteudo_mudou(item, v: dict) -> bool:
    return (v['titulo'] != item.titulo or (v['descricao'] or None) != (item.descricao or None)
            or v['corpo'] != item.corpo or v['anexos'] != anexos(item))


def _mudar_visibilidade(item, visibilidade: str) -> None:
    item.visibilidade = visibilidade
    if visibilidade != 'escritorio':
        # Recomendação é do escritório: item pessoal não carrega o selo.
        item.recomendado = False
        item.recomendado_por_id = None


def alterar_visibilidade(item, user: User, visibilidade: str, confirmar_dados: bool = False):
    if item.owner_id != user.id:
        raise PermissionError('Só quem criou o item pode compartilhá-lo ou torná-lo pessoal.')
    if visibilidade not in VISIBILIDADES:
        raise ErroBiblioteca('Visibilidade inválida: use pessoal ou escritorio.')
    if visibilidade == 'escritorio' and not confirmar_dados:
        achados = dados_pessoais(item.titulo, item.descricao or '', item.corpo,
                                 *[a['conteudo'] for a in anexos(item)])
        if achados:
            raise DadosPessoais(achados)
    _mudar_visibilidade(item, visibilidade)
    item.updated_at = _agora()
    db.session.commit()
    return item


def recomendar(item, user: User, valor: bool):
    if not _eh_admin(user) or item.law_firm_id != user.law_firm_id:
        raise PermissionError('Só administradores marcam um item como recomendado pelo escritório.')
    if valor and item.visibilidade != 'escritorio':
        raise ErroBiblioteca('Só itens compartilhados com o escritório podem ser recomendados.')
    item.recomendado = bool(valor)
    item.recomendado_por_id = user.id if valor else None
    db.session.commit()
    return item


def arquivar(item, user: User):
    _exigir_edicao(item, user)
    item.arquivado_em = _agora()
    item.recomendado = False
    # Libera o nome do comando para outro item (o slug é único no escritório).
    item.slug = f'{item.slug}__arquivado_{item.id}'[:80]
    db.session.query(PromptLibraryFavorite).filter_by(item_id=item.id).delete()
    db.session.commit()
    return item


def duplicar(item, user: User) -> PromptLibraryItem:
    """Cópia pessoal de um item que o usuário vê (ou de um comando do IntellexIA, como dict)."""
    if isinstance(item, dict):
        dados = {k: item[k] for k in ('titulo', 'descricao', 'corpo', 'tipo', 'area', 'usa_intellexia')}
    else:
        dados = {'titulo': item.titulo, 'descricao': item.descricao, 'corpo': item.corpo, 'tipo': item.tipo,
                 'area': item.area, 'usa_intellexia': item.usa_intellexia, 'anexos': anexos(item)}
    dados['titulo'] = (dados['titulo'] + ' (cópia)')[:MAX_TITULO]
    dados['visibilidade'] = 'pessoal'
    return criar(user, dados)


def favoritar(item, user: User, valor: bool) -> bool:
    atual = db.session.get(PromptLibraryFavorite, (user.id, item.id))
    if valor and not atual:
        db.session.add(PromptLibraryFavorite(user_id=user.id, item_id=item.id, law_firm_id=user.law_firm_id,
                                             created_at=_agora()))
    elif not valor and atual:
        db.session.delete(atual)
    db.session.commit()
    return bool(valor)


def favoritos(user: User) -> set[int]:
    return {i for (i,) in db.session.query(PromptLibraryFavorite.item_id).filter_by(user_id=user.id)}


def registrar_uso(item) -> None:
    PromptLibraryItem.query.filter_by(id=item.id).update(
        {PromptLibraryItem.usos: PromptLibraryItem.usos + 1}, synchronize_session=False)
    db.session.commit()


def versoes(item) -> list[PromptLibraryVersion]:
    return (PromptLibraryVersion.query.filter_by(item_id=item.id)
            .order_by(PromptLibraryVersion.versao.desc(), PromptLibraryVersion.id.desc()).all())


def restaurar(item, user: User, versao: int) -> PromptLibraryItem:
    _exigir_edicao(item, user)
    v = PromptLibraryVersion.query.filter_by(item_id=item.id, versao=versao).first()
    if not v:
        raise ErroBiblioteca(f'Versão {versao} não encontrada.')
    try:
        lista = json.loads(v.anexos_json or '[]')
    except (TypeError, ValueError):
        lista = []
    return editar(item, user, {'titulo': v.titulo, 'descricao': v.descricao, 'corpo': v.corpo, 'anexos': lista},
                  confirmar_dados=True)


# ── leitura ──────────────────────────────────────────────────────────────────

def texto_para_copiar(corpo: str, lista_anexos: list[dict]) -> str:
    """O texto do botão Copiar: o corpo e, em seguida, os anexos."""
    partes = [corpo.strip()] + [f'--- Anexo: {a["nome"]} ---\n{a["conteudo"].strip()}' for a in lista_anexos]
    return '\n\n'.join(p for p in partes if p)


def texto_para_ia(item, valores: dict | None = None) -> str:
    """O texto que vai para o Claude: campos preenchidos, anexos e o que falta perguntar."""
    corpo = preencher(item.corpo, valores)
    partes = [texto_para_copiar(corpo, anexos(item))]
    faltando = campos(corpo)
    if faltando:
        partes.append('Antes de seguir, pergunte ao usuário o valor de: '
                      + ', '.join(faltando) + ' (aparecem no texto acima como {{campo}}).')
    return '\n\n'.join(p for p in partes if p)


def serializar(item, user: User, favs: set[int] | None = None, autores: dict | None = None) -> dict:
    autor = (autores or {}).get(item.owner_id) if autores is not None else item.owner
    rotulo, icone, cor = AREAS.get(item.area, AREAS['geral'])
    lista_anexos = anexos(item)
    return {
        'id': item.id,
        'tipo': item.tipo,
        'tipo_rotulo': TIPOS.get(item.tipo, 'Prompt'),
        'tipo_icone': TIPO_ICONE.get(item.tipo, 'bi-chat-left-text'),
        'titulo': item.titulo,
        'descricao': item.descricao or '',
        'corpo': item.corpo,
        'texto': texto_para_copiar(item.corpo, lista_anexos),
        'campos': campos(item.corpo),
        'ferramentas': ferramentas_citadas(item.corpo + ' ' + ' '.join(a['conteudo'] for a in lista_anexos)),
        'anexos': [a['nome'] for a in lista_anexos],
        'area': item.area,
        'area_rotulo': rotulo,
        'area_icone': icone,
        'area_cor': cor,
        'usa_intellexia': bool(item.usa_intellexia),
        'visibilidade': item.visibilidade,
        'recomendado': bool(item.recomendado),
        'versao': item.versao or 1,
        'usos': item.usos or 0,
        'comando': nome_comando(item),
        'meu': item.owner_id == user.id,
        'pode_editar': pode_editar(item, user),
        'favorito': item.id in (favs or set()),
        'autor': autor.name if autor else 'Ex-integrante do escritório',
        'autor_id': autor.id if autor else None,
        'autor_foto': getattr(autor, 'google_picture_url', None) if autor else None,
        'atualizado_em': item.updated_at.isoformat() + 'Z' if item.updated_at else None,
        'sistema': False,
    }


def listar(user: User) -> list[dict]:
    itens = visiveis(user).order_by(PromptLibraryItem.usos.desc(), PromptLibraryItem.id).all()
    ids_autores = {i.owner_id for i in itens if i.owner_id}
    autores = {u.id: u for u in User.query.filter(User.id.in_(ids_autores))} if ids_autores else {}
    favs = favoritos(user)
    return [serializar(i, user, favs, autores) for i in itens]


# ── comandos do IntellexIA (servidor MCP) ────────────────────────────────────

_cache_sistema: dict = {'mtime': None, 'itens': []}


def _area_do_comando(nome: str) -> str:
    if 'dou' in nome or 'regulatorio' in nome:
        return 'dou'
    if any(p in nome for p in ('peticao', 'protocolo', 'devolutiva')):
        return 'processos'
    if 'decisao' in nome:
        return 'jurisprudencia'
    if 'email' in nome:
        return 'comunicacao'
    if any(p in nome for p in ('cnpj', 'socios', 'ficha')):
        return 'geral'
    return 'fap'


def prompts_do_sistema() -> list[dict]:
    """Comandos prontos do servidor MCP com o texto real, lidos por AST.

    Cada função ``@mcp.prompt`` é executada isolada (só monta texto) com os
    argumentos trocados por ``{{argumento}}``. Cache pelo mtime do arquivo.
    """
    try:
        mtime = os.path.getmtime(_SERVER_MCP)
    except OSError:
        return []
    if _cache_sistema['mtime'] == mtime:
        return _cache_sistema['itens']
    with open(_SERVER_MCP, encoding='utf-8') as f:
        arvore = ast.parse(f.read())
    itens = []
    for no in arvore.body:
        if not isinstance(no, ast.FunctionDef):
            continue
        dec = next((d for d in no.decorator_list if isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute) and d.func.attr == 'prompt'), None)
        if dec is None:
            continue
        kw = {k.arg: k.value.value for k in dec.keywords if isinstance(k.value, ast.Constant)}
        nome = kw.get('name') or no.name
        args = [a.arg for a in no.args.args]
        sem_decorador = copy.copy(no)
        sem_decorador.decorator_list = []
        sem_decorador.returns = None
        funcao = ast.Module(body=[sem_decorador], type_ignores=[])
        espaco: dict = {}
        try:
            exec(compile(funcao, _SERVER_MCP, 'exec'), {'__builtins__': {'str': str}}, espaco)
            corpo = espaco[no.name](**{a: '{{' + a + '}}' for a in args})
        except Exception:
            continue
        area = _area_do_comando(nome)
        rotulo, icone, cor = AREAS[area]
        itens.append({
            'id': 'sistema:' + nome, 'sistema': True, 'tipo': 'agente', 'tipo_rotulo': 'Agente',
            'tipo_icone': TIPO_ICONE['agente'], 'titulo': nome.replace('_', ' ').capitalize(),
            'descricao': kw.get('description') or '', 'corpo': corpo, 'texto': corpo, 'campos': campos(corpo),
            'ferramentas': ferramentas_citadas(corpo),
            'anexos': [], 'area': area, 'area_rotulo': rotulo, 'area_icone': icone, 'area_cor': cor,
            'usa_intellexia': True, 'visibilidade': 'sistema', 'recomendado': False, 'versao': 1, 'usos': 0,
            'comando': nome, 'meu': False, 'pode_editar': False, 'favorito': False, 'autor': 'IntellexIA',
            'autor_id': None, 'autor_foto': None, 'atualizado_em': None,
        })
    _cache_sistema.update(mtime=mtime, itens=itens)
    return itens


def prompts_do_sistema_com_uso(law_firm_id: int) -> list[dict]:
    """Os comandos do IntellexIA com o uso pelo conector no escritório."""
    itens = [dict(i) for i in prompts_do_sistema()]
    nomes = [i['comando'] for i in itens]
    if nomes:
        linhas = (db.session.query(UserMcpCall.name, db.func.sum(UserMcpCall.calls))
                  .filter(UserMcpCall.law_firm_id == law_firm_id, UserMcpCall.kind == UserMcpCall.KIND_PROMPT,
                          UserMcpCall.name.in_(nomes))
                  .group_by(UserMcpCall.name).all())
        usos = {n: int(c or 0) for n, c in linhas}
        for i in itens:
            i['usos'] = usos.get(i['comando'], 0)
    return itens


def prompt_do_sistema(nome: str) -> dict | None:
    return next((i for i in prompts_do_sistema() if i['comando'] == nome), None)


# ── ferramentas do conector (o que o Claude consegue consultar) ──────────────

_cache_modulos: dict = {'mtime': None, 'mapa': {}}


def _modulos_das_ferramentas() -> dict[str, tuple[str | None, bool]]:
    """``{ferramenta: (módulo, só_admin)}`` lido do ``require_module``/``require_admin`` de cada tool.

    Por AST, como os comandos: o módulo de cada ferramenta já está escrito no
    ``server.py``, e uma lista paralela aqui ficaria para trás. ``get_identity``
    (só exige login) vira ``(None, False)``.
    """
    try:
        mtime = os.path.getmtime(_SERVER_MCP)
    except OSError:
        return {}
    if _cache_modulos['mtime'] == mtime:
        return _cache_modulos['mapa']
    with open(_SERVER_MCP, encoding='utf-8') as f:
        arvore = ast.parse(f.read())
    mapa: dict[str, tuple[str | None, bool]] = {}
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in no.decorator_list:
            texto = ast.unparse(dec)
            if not texto.startswith('mcp.tool'):
                continue
            m = re.search(r"name=['\"](\w+)", texto)
            nome = m.group(1) if m else no.name
            modulo, admin = None, False
            for c in ast.walk(no):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and c.func.id in ('require_module', 'require_admin')
                        and c.args and isinstance(c.args[0], ast.Constant)):
                    modulo, admin = c.args[0].value, c.func.id == 'require_admin'
                    break
            mapa[nome] = (modulo, admin)
    _cache_modulos.update(mtime=mtime, mapa=mapa)
    return mapa


def ferramentas_do_conector(user: User | None = None) -> list[dict]:
    """As ferramentas do MCP por área (do manual do MCP), com o acesso do usuário a cada uma."""
    from app.services.mcp_catalog_service import catalogo
    from app.utils.permissions import MODULE_PERMISSIONS

    mapa = _modulos_das_ferramentas()
    modulos = set(user.get_module_permissions()) if user else set()
    admin = bool(user) and _eh_admin(user)
    grupos = []
    for g in catalogo()['grupos']:
        itens = []
        for i in g['itens']:
            modulo, so_admin = mapa.get(i['nome'], (None, False))
            rotulo = MODULE_PERMISSIONS.get(modulo, modulo or '') if modulo else ''
            motivo = ''
            if user is not None and modulo and modulo not in modulos:
                motivo = f'Seu usuário não tem o módulo "{rotulo}". Peça acesso a um administrador.'
            elif user is not None and so_admin and not admin:
                motivo = 'Só administradores do escritório usam esta ferramenta (mesma regra da tela).'
            itens.append({**i, 'modulo': modulo, 'modulo_rotulo': rotulo, 'so_admin': so_admin,
                          'acesso': not motivo, 'motivo': motivo})
        grupos.append({'titulo': g['titulo'], 'icone': g['icone'], 'itens': itens})
    return grupos


# Grupo do manual do MCP -> (chave do filtro, rótulo do filtro, cor da tela). Os
# dois grupos do Painel FAP viram um filtro só; grupo novo cai em "Outras".
_AREA_DO_GRUPO = {
    'Painel FAP — consultas': ('fap', 'Painel FAP', 'fap'),
    'Painel FAP — análises e acompanhamento': ('fap', 'Painel FAP', 'fap'),
    'Base de Jurisprudência': ('jurisprudencia', 'Jurisprudência', 'jur'),
    'Diário Oficial da União': ('dou', 'Diário Oficial', 'dou'),
    'Processos Judiciais': ('processos', 'Processos', 'proc'),
    'Monitoramento de Processos': ('monitoramento', 'Monitoramento', 'mon'),
    'Base de Conhecimento': ('base', 'Base de Conhecimento', 'kb'),
    'Painel de Contestações': ('contestacoes', 'Contestações', 'cont'),
    'Relatórios em Excel': ('excel', 'Excel', 'com'),
    'Revisão de Petições': ('revisao', 'Revisão', 'cont'),
}
_AREA_OUTRAS = ('outras', 'Outras', 'geral')


def cards_ferramentas(user: User) -> dict:
    """As ferramentas em lista única para os cards: com acesso primeiro, filtros por área."""
    itens, areas = [], {}
    for g in ferramentas_do_conector(user):
        chave, rotulo, cor = _AREA_DO_GRUPO.get(g['titulo'], _AREA_OUTRAS)
        for i in g['itens']:
            itens.append({**i, 'grupo': g['titulo'], 'icone': g['icone'], 'area': chave, 'cor': cor,
                          'titulo': i.get('titulo') or i['nome'].replace('_', ' ').capitalize()})
            areas.setdefault(chave, [rotulo, 0])[1] += 1
    itens.sort(key=lambda i: not i['acesso'])  # estável: dentro de cada lado, a ordem do manual
    ordem = [c for c, _, _ in _AREA_DO_GRUPO.values()] + [_AREA_OUTRAS[0]]
    filtros = [(c, areas[c][0], areas[c][1]) for c in dict.fromkeys(ordem) if c in areas]
    return {'itens': itens, 'filtros': filtros, 'total': len(itens),
            'bloqueadas': sum(1 for i in itens if not i['acesso'])}


def linha_da_ferramenta(nome: str) -> str:
    """A linha que o editor insere: o jeito dos comandos do IntellexIA ("Chame resumo_fap ...")."""
    return f'Chame a ferramenta {nome} do IntellexIA para '


def ferramentas_citadas(texto: str | None) -> list[str]:
    """Ferramentas do conector citadas no texto, na ordem em que aparecem.

    Todo nome de ferramenta tem "_" (``listar_beneficios_fap``): casado como
    palavra inteira, não confunde com o português do roteiro.
    """
    texto = texto or ''
    achadas = []
    for nome in _modulos_das_ferramentas():
        m = re.search(r'(?<![\w])' + re.escape(nome) + r'(?![\w])', texto)
        if m:
            achadas.append((m.start(), nome))
    return [n for _, n in sorted(achadas)]


# ── skill do Claude (SKILL.md) ───────────────────────────────────────────────

def _frontmatter(texto: str) -> tuple[dict, str]:
    texto = texto.lstrip('﻿')
    m = re.match(r'^---\s*\n(.*?)\n---\s*(?:\n|$)', texto, re.S)
    if not m:
        return {}, texto
    import yaml

    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), texto[m.end():]


def _decodificar(dados: bytes) -> str | None:
    for codificacao in ('utf-8-sig', 'cp1252'):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return None


def ler_skill(nome_arquivo: str, conteudo: bytes) -> tuple[dict, list[str]]:
    """``.zip`` de skill ou ``SKILL.md`` → dados de um item (tipo skill) + o que foi ignorado."""
    if len(conteudo) > MAX_UPLOAD:
        raise ErroBiblioteca(f'Arquivo maior que {MAX_UPLOAD // (1024 * 1024)} MB.')
    ignorados: list[str] = []
    nome_arquivo = (nome_arquivo or '').lower()
    if nome_arquivo.endswith('.zip') or conteudo[:2] == b'PK':
        try:
            zf = zipfile.ZipFile(io.BytesIO(conteudo))
        except zipfile.BadZipFile:
            raise ErroBiblioteca('O arquivo não é um .zip válido.')
        arquivos = [i for i in zf.infolist() if not i.is_dir()
                    and '__MACOSX' not in i.filename and not os.path.basename(i.filename).startswith('.')]
        if len(arquivos) > MAX_ARQUIVOS_ZIP:
            raise ErroBiblioteca(f'O .zip tem mais de {MAX_ARQUIVOS_ZIP} arquivos.')
        if sum(i.file_size for i in arquivos) > MAX_ANEXOS_TOTAL + MAX_CORPO:
            raise ErroBiblioteca('O conteúdo do .zip é grande demais para a biblioteca.')
        principal = min((i for i in arquivos if os.path.basename(i.filename).lower() == 'skill.md'),
                        key=lambda i: i.filename.count('/'), default=None)
        if principal is None:
            raise ErroBiblioteca('O .zip não tem SKILL.md — é o arquivo principal de uma skill do Claude.')
        pasta = principal.filename.rsplit('/', 1)[0] + '/' if '/' in principal.filename else ''
        texto = _decodificar(zf.read(principal))
        if texto is None:
            raise ErroBiblioteca('Não consegui ler o SKILL.md como texto.')
        lista_anexos = []
        for i in arquivos:
            if i is principal:
                continue
            relativo = i.filename[len(pasta):] if i.filename.startswith(pasta) else i.filename
            if os.path.splitext(i.filename)[1].lower() not in EXTENSOES_TEXTO:
                ignorados.append(relativo)
                continue
            dados = _decodificar(zf.read(i))
            if dados is None or len(dados) > MAX_ANEXO:
                ignorados.append(relativo)
                continue
            lista_anexos.append({'nome': relativo.replace('/', '_')[:200], 'conteudo': dados})
    else:
        texto = _decodificar(conteudo)
        if texto is None:
            raise ErroBiblioteca('Não consegui ler o arquivo como texto. Envie o .zip da skill ou o SKILL.md.')
        lista_anexos = []
    meta, corpo = _frontmatter(texto)
    nome = str(meta.get('name') or '').strip()
    titulo = (nome.replace('-', ' ').replace('_', ' ').strip().capitalize() if nome else '') or 'Skill importada'
    return {'tipo': 'skill', 'titulo': titulo[:MAX_TITULO],
            'descricao': str(meta.get('description') or '').strip()[:MAX_DESCRICAO] or None,
            'corpo': corpo.strip(), 'area': 'geral', 'visibilidade': 'pessoal',
            'anexos': lista_anexos}, ignorados


def importar_skill(user: User, nome_arquivo: str, conteudo: bytes) -> tuple[PromptLibraryItem, list[str]]:
    dados, ignorados = ler_skill(nome_arquivo, conteudo)
    return criar(user, dados), ignorados


def _nome_skill(item) -> str:
    """Nome no formato do Claude: minúsculas, números e hífens, até 64."""
    return (item.slug.replace('_', '-')[:64].strip('-')) or 'skill'


def exportar_skill(item) -> tuple[str, bytes]:
    """``.zip`` com ``<nome>/SKILL.md`` e os anexos, pronto para subir no Claude."""
    nome = _nome_skill(item)
    descricao = (item.descricao or item.titulo).replace('\n', ' ').strip()[:1024]
    import yaml

    frontmatter = yaml.safe_dump({'name': nome, 'description': descricao}, allow_unicode=True,
                                 sort_keys=False, width=10_000).strip()
    skill_md = f'---\n{frontmatter}\n---\n\n# {item.titulo}\n\n{item.corpo.strip()}\n'
    lista = anexos(item)
    if lista:
        skill_md += '\n## Arquivos de apoio\n\n' + '\n'.join(f'- `{a["nome"]}`' for a in lista) + '\n'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{nome}/SKILL.md', skill_md)
        for a in lista:
            zf.writestr(f'{nome}/{a["nome"]}', a['conteudo'])
    return f'{nome}.zip', buf.getvalue()
