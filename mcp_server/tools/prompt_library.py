"""Biblioteca de IA no MCP — ferramentas e os comandos ``meu_*``/``escritorio_*``.

Tudo passa por ``prompt_library_service``, o mesmo da tela ``/prompts``: o que
cada usuário vê, os campos ``{{campo}}`` e o texto entregue ao Claude.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

from app.models import User, db
from app.services import prompt_library_service as svc


def _usuario(law_firm_id: int, user_id: int) -> User:
    user = db.session.get(User, user_id)
    if not user or user.law_firm_id != law_firm_id or not user.is_active:
        raise ToolError('Usuário não encontrado. Reconecte o cliente MCP.')
    return user


def _resumo(i: dict) -> dict:
    return {
        'nome': i['comando'],
        'titulo': i['titulo'],
        'quando_usar': i['descricao'] or None,
        'tipo': i['tipo'],
        'area': i['area_rotulo'],
        'campos': i['campos'],
        'ferramentas': i.get('ferramentas') or [],
        'anexos': i['anexos'],
        'de': ('IntellexIA' if i['sistema'] else ('você' if i['meu'] else i['autor'])),
        'visibilidade': {'pessoal': 'só você', 'escritorio': 'escritório'}.get(i['visibilidade'], 'IntellexIA'),
        'recomendado_pelo_escritorio': i['recomendado'],
        'usos': i['usos'],
    }


def biblioteca_prompts_handler(law_firm_id: int, user_id: int, busca: str | None = None,
                               incluir_sistema: bool = False) -> dict:
    user = _usuario(law_firm_id, user_id)
    itens = svc.listar(user)
    if incluir_sistema:
        itens += svc.prompts_do_sistema_com_uso(law_firm_id)
    if busca:
        termos = svc.slugify(busca).split('_')
        def casa(i):
            alvo = svc.slugify(' '.join([i['titulo'], i['descricao'], i['corpo'], i['area_rotulo'], i['comando']]))
            return all(t in alvo for t in termos)
        itens = [i for i in itens if casa(i)]
    itens.sort(key=lambda i: (not i['recomendado'], -i['usos'], i['titulo'].lower()))
    return {
        'total': len(itens),
        'itens': [_resumo(i) for i in itens],
        'dica': ('Para usar um item, chame usar_prompt com o "nome" e os "campos". Também aparecem como '
                 'comandos prontos do conector (pode ser preciso reconectar para a lista atualizar).'),
    }


def usar_prompt_handler(law_firm_id: int, user_id: int, nome: str, campos: dict | None = None) -> dict:
    user = _usuario(law_firm_id, user_id)
    item = svc.item_por_comando(user, nome)
    if item is None:
        sistema = svc.prompt_do_sistema(nome)
        if sistema is None:
            raise ToolError(f'Não achei "{nome}" na biblioteca. Veja os nomes em biblioteca_prompts.')
        texto = svc.preencher(sistema['corpo'], campos)
        faltando = svc.campos(texto)
        if faltando:
            texto += ('\n\nAntes de seguir, pergunte ao usuário o valor de: ' + ', '.join(faltando) + '.')
        return {'nome': nome, 'titulo': sistema['titulo'], 'texto': texto,
                'instrucao': 'Siga o texto acima como se o usuário o tivesse escrito.'}
    svc.registrar_uso(item)
    return {'nome': nome, 'titulo': item.titulo, 'texto': svc.texto_para_ia(item, campos),
            'instrucao': 'Siga o texto acima como se o usuário o tivesse escrito.'}


def salvar_prompt_handler(law_firm_id: int, user_id: int, app_public_url: str, titulo: str, texto: str,
                          quando_usar: str | None = None, tipo: str = 'prompt', area: str = 'geral',
                          compartilhar: bool = False, usa_intellexia: bool = False,
                          comando: str | None = None) -> dict:
    user = _usuario(law_firm_id, user_id)
    try:
        item = svc.criar(user, {
            'titulo': titulo, 'comando': comando, 'corpo': texto, 'descricao': quando_usar, 'tipo': tipo, 'area': area,
            'visibilidade': 'escritorio' if compartilhar else 'pessoal', 'usa_intellexia': usa_intellexia,
        })
    except svc.DadosPessoais as e:
        raise ToolError(str(e) + ' Salve sem compartilhar (compartilhar=false), tire os dados do texto, '
                        'ou compartilhe depois pela tela da Biblioteca de IA, que pede confirmação.') from e
    except svc.ErroBiblioteca as e:
        raise ToolError(str(e)) from e
    return {
        'salvo': True,
        'nome': svc.nome_comando(item),
        'titulo': item.titulo,
        'visibilidade': 'escritório' if item.visibilidade == 'escritorio' else 'só você',
        'campos': svc.campos(item.corpo),
        'link': f'{app_public_url.rstrip("/")}/prompts/{item.id}/editar',
    }
