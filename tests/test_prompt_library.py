#!/usr/bin/env python3
"""
Biblioteca de IA: regras, tela /prompts e comandos/ferramentas do MCP.

- pessoal só o dono vê (nem admin); outro escritório nunca;
- editar: dono, ou admin no item do escritório; recomendar só admin;
- versões e restaurar; aviso de CPF/CNPJ ao compartilhar;
- importar skill (.zip com script ignorado) e baixar no formato do Claude;
- comandos do IntellexIA lidos por AST com {{argumento}};
- no MCP: meu_*/escritorio_* na lista de comandos, prompts/get renderiza,
  biblioteca_prompts, usar_prompt e salvar_prompt.

Escritórios descartáveis, removidos no fim.

    uv run python tests/test_prompt_library.py
"""

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError

from main import app
from app.models import (
    db, LawFirm, PromptLibraryFavorite, PromptLibraryItem, PromptLibraryVersion, User, UserMcpCall, UserPageVisit,
)
from app.services import prompt_library_service as svc

CNPJS = ('00000000002071', '00000000002152')
_falhas = []
CPF_VALIDO = '529.982.247-25'


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        PromptLibraryFavorite.query.filter_by(law_firm_id=firm.id).delete()
        PromptLibraryVersion.query.filter_by(law_firm_id=firm.id).delete()
        PromptLibraryItem.query.filter_by(law_firm_id=firm.id).delete()
        for u in User.query.filter_by(law_firm_id=firm.id).all():
            UserPageVisit.query.filter_by(user_id=u.id).delete()
            UserMcpCall.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    us = {}
    for i, cnpj in enumerate(CNPJS):
        firm = LawFirm(name=f'Escritório Teste Biblioteca {i}', cnpj=cnpj)
        db.session.add(firm)
        db.session.flush()
        for papel in ('admin', 'lawyer', 'lawyer2'):
            u = User(law_firm_id=firm.id, name=f'{papel} {i}', role='lawyer' if papel == 'lawyer2' else papel,
                     is_active=True, email=f'{papel}{i}__test_biblioteca@example.com')
            u.set_password('x')
            db.session.add(u)
            us[(i, papel)] = u
    db.session.commit()
    return us


def _logar(c, u):
    with c.session_transaction() as s:
        s.clear()
        s['user_id'] = u.id
        s['law_firm_id'] = u.law_firm_id
        s['user_role'] = u.role


def test_texto():
    print('\n1. Campos, preenchimento e dados pessoais')
    check('campos na ordem, sem repetir, com acento',
          svc.campos('{{empresa}} e {{ vigência }} e {{empresa}} {{1x}}') == ['empresa', 'vigência'])
    check('preencher troca os informados e deixa os outros',
          svc.preencher('A {{empresa}} em {{vigencia}}', {'empresa': 'Vale'}) == 'A Vale em {{vigencia}}')
    check('slug sem acento', svc.slugify('Análise de Sentença — FAP!') == 'analise_de_sentenca_fap')
    achados = svc.dados_pessoais(f'cpf {CPF_VALIDO} e cnpj 11.222.333/0001-81 e nb 1234567890')
    check('acha CPF e CNPJ válidos, mascarados', len(achados) == 2 and all('*' in a for a in achados), str(achados))
    check('número qualquer não é CPF', not svc.dados_pessoais('protocolo 12345678901 e 111.111.111-11'))


def test_regras(us):
    print('\n2. Quem vê e quem edita')
    dono, colega, admin = us[(0, 'lawyer')], us[(0, 'lawyer2')], us[(0, 'admin')]
    outro = us[(1, 'admin')]
    p = svc.criar(dono, {'titulo': 'Resumo de sentença', 'corpo': 'Resuma a sentença da {{empresa}}.'})
    check('nasce pessoal, versão 1', p.visibilidade == 'pessoal' and p.versao == 1
          and PromptLibraryVersion.query.filter_by(item_id=p.id).count() == 1)
    check('pessoal: dono vê', svc.obter(p.id, dono) is not None)
    check('pessoal: colega não vê', svc.obter(p.id, colega) is None)
    check('pessoal: nem o admin vê', svc.obter(p.id, admin) is None)
    check('outro escritório nunca vê', svc.obter(p.id, outro) is None)
    check('comando pessoal = meu_<tipo>_<slug>', svc.nome_comando(p) == 'meu_prompt_resumo_de_sentenca')

    try:
        svc.alterar_visibilidade(p, colega, 'escritorio')
        check('só o dono compartilha', False)
    except PermissionError:
        check('só o dono compartilha', True)
    svc.alterar_visibilidade(p, dono, 'escritorio')
    check('compartilhado: colega vê', svc.obter(p.id, colega) is not None)
    check('comando do escritório = escritorio_<tipo>_<slug>', svc.nome_comando(p) == 'escritorio_prompt_resumo_de_sentenca')
    check('colega não edita', not svc.pode_editar(p, colega))
    check('admin edita item do escritório', svc.pode_editar(p, admin))

    try:
        svc.recomendar(p, dono, True)
        check('só admin recomenda', False)
    except PermissionError:
        check('só admin recomenda', True)
    svc.recomendar(p, admin, True)
    check('admin recomenda', p.recomendado and p.recomendado_por_id == admin.id)
    svc.alterar_visibilidade(p, dono, 'pessoal')
    check('tornar pessoal tira o selo', not p.recomendado)
    svc.alterar_visibilidade(p, dono, 'escritorio')

    print('\n3. Versões')
    svc.editar(p, admin, {'corpo': 'Resuma a sentença da {{empresa}} em tópicos.'})
    check('mudar o texto cria versão 2', p.versao == 2 and len(svc.versoes(p)) == 2)
    svc.editar(p, dono, {'area': 'jurisprudencia'})
    check('mudar só a área não cria versão', p.versao == 2 and p.area == 'jurisprudencia')
    svc.restaurar(p, dono, 1)
    check('restaurar a 1 vira a versão 3 com o texto antigo',
          p.versao == 3 and p.corpo == 'Resuma a sentença da {{empresa}}.')
    svc.editar(p, dono, {'titulo': 'Resumo de sentença FAP'})
    check('renomear o título não troca o comando', p.slug == 'resumo_de_sentenca')
    svc.editar(p, dono, {'comando': '/escritorio_prompt_Resumo Sentença FAP'})
    check('comando escolhido: prefixo e acento saem', p.slug == 'resumo_sentenca_fap', p.slug)
    try:
        svc.criar(dono, {'titulo': 'Outro', 'corpo': 'x', 'comando': 'resumo_sentenca_fap'})
        check('comando escolhido já em uso: erro', False)
    except svc.ErroBiblioteca as e:
        check('comando escolhido já em uso: erro', 'em uso' in str(e))
    curto = svc.criar(dono, {'titulo': 'Um título bem comprido para o comando', 'corpo': 'x', 'comando': 'rascunho'})
    check('comando escolhido na criação', svc.nome_comando(curto) == 'meu_prompt_rascunho')
    agente = svc.criar(dono, {'titulo': 'Analista', 'tipo': 'agente', 'corpo': 'x', 'visibilidade': 'escritorio'})
    check('agente do escritório = escritorio_agente_<nome>', svc.nome_comando(agente) == 'escritorio_agente_analista')
    check('o comando acha o item', svc.item_por_comando(colega, 'escritorio_agente_analista').id == agente.id)
    check('tipo errado no comando não acha', svc.item_por_comando(colega, 'escritorio_prompt_analista') is None)
    svc.arquivar(curto, dono)
    check('arquivar libera o nome do comando',
          svc.criar(dono, {'titulo': 'Novo', 'corpo': 'x', 'comando': 'rascunho'}).slug == 'rascunho')

    print('\n4. Compartilhar confere dado pessoal')
    try:
        svc.criar(dono, {'titulo': 'Caso', 'corpo': f'Segurado CPF {CPF_VALIDO}', 'visibilidade': 'escritorio'})
        check('CPF no texto pede confirmação', False)
    except svc.DadosPessoais as e:
        check('CPF no texto pede confirmação', bool(e.achados))
    q = svc.criar(dono, {'titulo': 'Caso', 'corpo': f'Segurado CPF {CPF_VALIDO}', 'visibilidade': 'escritorio'},
                  confirmar_dados=True)
    check('com confirmação, publica', q.visibilidade == 'escritorio')
    r = svc.criar(dono, {'titulo': 'Outro caso', 'corpo': f'CPF {CPF_VALIDO}'})
    try:
        svc.alterar_visibilidade(r, dono, 'escritorio')
        check('compartilhar depois também confere', False)
    except svc.DadosPessoais:
        check('compartilhar depois também confere', True)
    check('slug repetido ganha sufixo', svc.criar(dono, {'titulo': 'Caso', 'corpo': 'x'}).slug == 'caso_2')

    print('\n5. Favoritos, duplicar e arquivar')
    svc.favoritar(p, colega, True)
    check('favorito por usuário', p.id in svc.favoritos(colega) and p.id not in svc.favoritos(dono))
    copia = svc.duplicar(p, colega)
    check('duplicar = cópia pessoal do colega', copia.owner_id == colega.id and copia.visibilidade == 'pessoal'
          and copia.corpo == p.corpo)
    try:
        svc.arquivar(p, colega)
        check('colega não arquiva', False)
    except PermissionError:
        check('colega não arquiva', True)
    svc.arquivar(copia, colega)
    check('arquivado some', svc.obter(copia.id, colega) is None)
    return p


def test_skill(us):
    print('\n6. Importar e baixar skill')
    dono = us[(0, 'lawyer')]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('revisao-impugnacao/SKILL.md',
                    '---\nname: revisao-impugnacao\ndescription: Checklist antes do protocolo\n---\n\n# Revisão\n\nConfira a {{secao}}.')
        zf.writestr('revisao-impugnacao/checklist.md', '- tabela de benefícios\n- teses')
        zf.writestr('revisao-impugnacao/scripts/conferir.py', 'print("oi")')
        zf.writestr('__MACOSX/._SKILL.md', 'lixo')
    item, ignorados = svc.importar_skill(dono, 'revisao.zip', buf.getvalue())
    check('frontmatter vira título e "quando usar"',
          item.titulo == 'Revisao impugnacao' and item.descricao == 'Checklist antes do protocolo')
    check('tipo skill, pessoal', item.tipo == 'skill' and item.visibilidade == 'pessoal')
    check('texto do SKILL.md sem o frontmatter', item.corpo.startswith('# Revisão') and 'name:' not in item.corpo)
    check('anexo de texto entra', [a['nome'] for a in svc.anexos(item)] == ['checklist.md'])
    check('script fica de fora e é avisado', ignorados == ['scripts/conferir.py'], str(ignorados))
    try:
        svc.importar_skill(dono, 'x.zip', b'PK\x03\x04quebrado')
        check('zip inválido recusado', False)
    except svc.ErroBiblioteca:
        check('zip inválido recusado', True)

    nome, dados = svc.exportar_skill(item)
    zf = zipfile.ZipFile(io.BytesIO(dados))
    nomes = sorted(zf.namelist())
    check('baixar: pasta/SKILL.md + anexos',
          nomes == ['revisao-impugnacao/SKILL.md', 'revisao-impugnacao/checklist.md'], str(nomes))
    md = zf.read('revisao-impugnacao/SKILL.md').decode()
    check('SKILL.md com name/description no formato do Claude',
          md.startswith('---\nname: revisao-impugnacao\ndescription: Checklist antes do protocolo\n---'), md[:120])
    meta, _ = svc._frontmatter(md)
    reimportado, _ = svc.ler_skill('x.md', md.encode())
    check('o que sai entra de volta', meta.get('name') == 'revisao-impugnacao' and '{{secao}}' in reimportado['corpo'])


def test_sistema():
    print('\n7. Comandos do IntellexIA')
    import ast

    arvore = ast.parse(open(svc._SERVER_MCP, encoding='utf-8').read())
    esperados = sum(1 for n in arvore.body if isinstance(n, ast.FunctionDef)
                    and any('prompt' in ast.unparse(d) for d in n.decorator_list))
    itens = svc.prompts_do_sistema()
    check('todos os @mcp.prompt lidos com texto', len(itens) == esperados and all(i['corpo'] for i in itens),
          f'{len(itens)} de {esperados}')
    analise = svc.prompt_do_sistema('analise_empresa')
    check('argumento vira {{campo}}', analise and analise['campos'] == ['nome_empresa'])


def test_ferramentas(us):
    print('\n7b. Ferramentas do conector')
    colega, admin = us[(0, 'lawyer2')], us[(0, 'admin')]
    grupos = svc.ferramentas_do_conector(colega)
    todas = {i['nome']: i for g in grupos for i in g['itens']}
    import mcp_server  # noqa: F401  (só garante o pacote no path)
    import ast as _ast
    arvore = _ast.parse(open(svc._SERVER_MCP, encoding='utf-8').read())
    registradas = sum(1 for n in _ast.walk(arvore) if isinstance(n, _ast.FunctionDef)
                      and any(_ast.unparse(d).startswith('mcp.tool') for d in n.decorator_list))
    check('todas as ferramentas do servidor na lista, por área', len(todas) == registradas and len(grupos) > 5,
          f'{len(todas)} de {registradas}')
    check('módulo de cada uma lido do server.py', todas['listar_beneficios_fap']['modulo'] == 'fap_panel'
          and todas['consultar_cnpj']['modulo'] is None)
    sem_dou = 'dou' not in colega.get_module_permissions()
    check('sem o módulo: sem acesso, com o motivo',
          not sem_dou or (not todas['pesquisar_dou']['acesso'] and 'Diario Oficial' in todas['pesquisar_dou']['motivo']))
    check('ferramenta só de admin: advogado sem acesso', not todas['estatisticas_revisor']['acesso'])
    adm = {i['nome']: i for g in svc.ferramentas_do_conector(admin) for i in g['itens']}
    check('admin tem acesso a todas', all(i['acesso'] for i in adm.values()))
    cards = svc.cards_ferramentas(colega)
    acessos = [i['acesso'] for i in cards['itens']]
    check('cards: com acesso primeiro, bloqueadas no fim', acessos == sorted(acessos, reverse=True)
          and cards['bloqueadas'] == acessos.count(False))
    check('cards: todo card com nome curto do manual', all(i['titulo'] and i['titulo'] != i['nome'] for i in cards['itens']))
    check('cards: Painel FAP num filtro só', sum(1 for c, _, _ in cards['filtros'] if c == 'fap') == 1
          and dict((c, n) for c, _, n in cards['filtros'])['fap'] == sum(1 for i in cards['itens'] if i['area'] == 'fap'))
    check('citadas no texto, na ordem, palavra inteira',
          svc.ferramentas_citadas('Chame resumo_fap e listar_beneficios_fap; resumo_fapx não') ==
          ['resumo_fap', 'listar_beneficios_fap'])
    a = svc.criar(colega, {'titulo': 'Agente cita ferramenta', 'corpo': 'Chame resumo_fap para a {{empresa}}.'})
    check('citar ferramenta marca "usa dados do IntellexIA"', a.usa_intellexia)
    check('card traz as ferramentas citadas', svc.serializar(a, colega)['ferramentas'] == ['resumo_fap'])
    check('comandos do IntellexIA também mostram as ferramentas',
          'resumo_fap' in svc.prompt_do_sistema('analise_empresa')['ferramentas'])


def test_tela(us, p):
    print('\n8. Tela /prompts')
    c = app.test_client()
    dono, colega, admin = us[(0, 'lawyer')], us[(0, 'lawyer2')], us[(0, 'admin')]
    pessoal = svc.criar(dono, {'titulo': 'Meu rascunho secreto', 'corpo': 'texto <b>secreto</b>'})
    _logar(c, colega)
    html = c.get('/prompts/').get_data(as_text=True)
    check('abre para quem não é admin', 'Biblioteca de IA' in html)
    check('mostra o item do escritório', 'Resumo de sentença FAP' in html)
    check('não mostra pessoal de outro', 'Meu rascunho secreto' not in html)
    check('aba do IntellexIA com os comandos', 'analise_empresa' in html)
    check('botão e modal "Ferramentas do IntellexIA" com os cards', 'data-bs-target="#plbFerramentas"' in html
          and 'id="plbFerramentas"' in html and '/prompts/novo?ferramenta=listar_beneficios_fap' in html)
    check('card com o nome curto do manual', 'Benefícios do cálculo FAP' in html)
    check('"+ Novo" com Prompt, Agente, Skill e importar', all(x in html for x in (
        '/prompts/novo?tipo=prompt', '/prompts/novo?tipo=agente', '/prompts/novo?tipo=skill', 'Importar skill do Claude')))
    check('comando no card', '/escritorio_prompt_resumo_sentenca_fap' in html)
    _logar(c, dono)
    html = c.get('/prompts/').get_data(as_text=True)
    check('texto escapado no card', '&lt;b&gt;secreto&lt;/b&gt;' in html and '<b>secreto</b>' not in html)
    check('texto no JSON também escapado para o HTML', '\\u003cb\\u003e' in html)

    _logar(c, colega)
    check('colega não abre o editor de item alheio',
          c.get(f'/prompts/{p.id}/editar').status_code == 302)
    check('pessoal alheio = 404', c.get(f'/prompts/{pessoal.id}/editar').status_code == 404)
    r = c.post('/prompts/novo', data={'titulo': 'E-mail ao cliente', 'corpo': 'Escreva ao {{cliente}}.',
                                      'tipo': 'prompt', 'area': 'comunicacao', 'visibilidade': 'pessoal',
                                      'anexo_nome': ['modelo.md'], 'anexo_conteudo': ['Prezado...']})
    novo = PromptLibraryItem.query.filter_by(owner_id=colega.id, titulo='E-mail ao cliente').first()
    check('criar pela tela', r.status_code == 302 and novo and svc.anexos(novo)[0]['nome'] == 'modelo.md')
    r = c.post('/prompts/novo', data={'titulo': 'Com CPF', 'corpo': f'CPF {CPF_VALIDO}', 'visibilidade': 'escritorio'})
    check('CPF ao compartilhar: volta ao editor com aviso', r.status_code == 422
          and 'Conferi' in r.get_data(as_text=True))
    r = c.post('/prompts/novo', data={'titulo': 'Com CPF', 'corpo': f'CPF {CPF_VALIDO}', 'visibilidade': 'escritorio',
                                      'confirmar_dados': '1'})
    check('com a confirmação, salva', r.status_code == 302)
    html = c.get('/prompts/novo').get_data(as_text=True)
    check('editor tem o campo do comando no Claude', 'name="comando"' in html and '/meu_prompt_' in html)
    html = c.get('/prompts/novo?ferramenta=listar_beneficios_fap').get_data(as_text=True)
    check('"Usar num agente": editor de agente com a ferramenta no texto',
          'Novo agente' in html and 'Chame a ferramenta listar_beneficios_fap do IntellexIA para' in html)
    check('editor tem o "Inserir ferramenta"', 'Inserir ferramenta do IntellexIA' in html and 'data-fm-inserir="resumo_fap"' in html)
    html = c.get('/prompts/novo?ferramenta=nao_existe').get_data(as_text=True)
    check('ferramenta desconhecida é ignorada', 'nao_existe' not in html)
    html = c.get('/prompts/novo?tipo=agente').get_data(as_text=True)
    check('"+ Novo → Agente" abre o editor com o tipo marcado',
          'Novo agente' in html and 'value="agente" checked' in html and '/meu_agente_' in html)
    r = c.post('/prompts/novo', data={'titulo': 'Checklist do protocolo', 'comando': 'checklist', 'corpo': 'x'})
    check('comando escolhido pela tela', r.status_code == 302 and
          PromptLibraryItem.query.filter_by(owner_id=colega.id, slug='checklist').count() == 1)
    r = c.post('/prompts/novo', data={'titulo': 'Outro checklist', 'comando': 'checklist', 'corpo': 'x'})
    check('comando repetido: volta ao editor com o aviso', r.status_code == 400 and 'em uso' in r.get_data(as_text=True))
    r = c.post('/prompts/novo', data={'titulo': '', 'corpo': 'x'})
    check('sem título: 400 com mensagem', r.status_code == 400 and 'título' in r.get_data(as_text=True))

    antes = p.usos or 0
    c.post(f'/prompts/{p.id}/uso.json')
    db.session.refresh(p)
    check('copiar conta uso', p.usos == antes + 1)
    r = c.post(f'/prompts/{p.id}/favorito.json', json={'favorito': True})
    check('favoritar por JSON', r.get_json() == {'favorito': True})
    j = c.get(f'/prompts/{p.id}/versoes.json').get_json()
    check('versões em JSON, mais nova primeiro', j['versoes'][0]['versao'] == p.versao and not j['pode_restaurar'])
    r = c.get(f'/prompts/{p.id}/skill.zip')
    check('baixar skill', r.status_code == 200 and r.headers['Content-Type'] == 'application/zip')
    r = c.post('/prompts/sistema/analise_empresa/duplicar')
    copia = PromptLibraryItem.query.filter_by(owner_id=colega.id).filter(
        PromptLibraryItem.titulo.like('Analise empresa%')).first()
    check('duplicar comando do IntellexIA', r.status_code == 302 and copia and '{{nome_empresa}}' in copia.corpo)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('x/SKILL.md', '---\nname: minha-skill\ndescription: teste\n---\nFaça.')
        zf.writestr('x/run.sh', 'echo')
    r = c.post('/prompts/importar', data={'arquivo': (io.BytesIO(buf.getvalue()), 'skill.zip')},
               content_type='multipart/form-data')
    check('importar pela tela', r.status_code == 302 and
          PromptLibraryItem.query.filter_by(owner_id=colega.id, tipo='skill').count() == 1)

    html = c.get('/prompts/').get_data(as_text=True)
    check('header: botão Biblioteca e a janela rápida', 'data-bs-target="#bibliotecaRapida"' in html
          and 'id="bibliotecaRapida"' in html and 'js/biblioteca_rapida.js?v=' in html)
    j = c.get('/prompts/rapido.json').get_json()
    titulos = {i['titulo'] for i in j['itens']}
    check('janela rápida: itens do usuário, do escritório e do IntellexIA',
          'Resumo de sentença FAP' in titulos and 'E-mail ao cliente' in titulos
          and any(i['sistema'] for i in j['itens']))
    check('janela rápida: pessoal de outro não vem', 'Meu rascunho secreto' not in titulos)
    check('janela rápida: favorito marcado', any(i['favorito'] and i['id'] == p.id for i in j['itens']))

    _logar(c, admin)
    r = c.post(f'/prompts/{p.id}/recomendar', data={'valor': '1'})
    db.session.refresh(p)
    check('admin recomenda pela tela', p.recomendado)
    _logar(c, us[(1, 'admin')])
    check('outro escritório: 404', c.get(f'/prompts/{p.id}/versoes.json').status_code == 404)


def test_mcp(us, p):
    print('\n9. MCP')
    from mcp_server import prompt_library as mw
    from mcp_server.tools import prompt_library as tools
    import mcp_server.server as server

    colega = us[(0, 'lawyer2')]
    claims = {'user_id': colega.id, 'law_firm_id': colega.law_firm_id, 'modules': [], 'role': 'lawyer'}
    original = mw.get_access_token
    mw.get_access_token = lambda: SimpleNamespace(claims=claims)
    try:
        nomes = {pr.name: pr for pr in asyncio.run(server.mcp.list_prompts())}
        check('comandos do sistema continuam', 'analise_empresa' in nomes)
        check('item do escritório vira comando', 'escritorio_prompt_resumo_sentenca_fap' in nomes)
        check('item pessoal do usuário vira meu_*', 'meu_prompt_e_mail_ao_cliente' in nomes)
        check('pessoal de outro não aparece', not any('rascunho' in n for n in nomes))
        arg = [a.name for a in (nomes['escritorio_prompt_resumo_sentenca_fap'].arguments or [])]
        check('campos viram argumentos', arg == ['empresa'], str(arg))
        res = asyncio.run(server.mcp.render_prompt('escritorio_prompt_resumo_sentenca_fap', {'empresa': 'Vale'}))
        texto = res.messages[0].content.text
        check('prompts/get renderiza com o campo', 'da Vale' in texto, texto[:120])
        res = asyncio.run(server.mcp.render_prompt('meu_prompt_e_mail_ao_cliente', {}))
        texto = res.messages[0].content.text
        check('campo faltando vira pergunta + anexo junto',
              'pergunte ao usuário' in texto and 'Anexo: modelo.md' in texto, texto[:200])
        mw.get_access_token = lambda: SimpleNamespace(claims={**claims, 'user_id': us[(1, 'admin')].id,
                                                              'law_firm_id': us[(1, 'admin')].law_firm_id})
        nomes_outro = {pr.name for pr in asyncio.run(server.mcp.list_prompts())}
        check('outro escritório não recebe os comandos', 'escritorio_prompt_resumo_sentenca_fap' not in nomes_outro)
    finally:
        mw.get_access_token = original

    fid, uid = colega.law_firm_id, colega.id
    lista = tools.biblioteca_prompts_handler(fid, uid)
    check('biblioteca_prompts: recomendado primeiro', lista['itens'][0]['nome'] == 'escritorio_prompt_resumo_sentenca_fap')
    check('biblioteca_prompts: busca', tools.biblioteca_prompts_handler(fid, uid, 'e-mail')['total'] == 1)
    check('biblioteca_prompts: com o sistema',
          any(i['nome'] == 'analise_empresa' for i in tools.biblioteca_prompts_handler(fid, uid, None, True)['itens']))
    u = tools.usar_prompt_handler(fid, uid, 'escritorio_prompt_resumo_sentenca_fap', {'empresa': 'Vale'})
    check('usar_prompt devolve o texto pronto', 'da Vale' in u['texto'])
    u = tools.usar_prompt_handler(fid, uid, 'analise_empresa', {'nome_empresa': 'Vale'})
    check('usar_prompt aceita comando do IntellexIA', '"Vale"' in u['texto'])
    try:
        tools.usar_prompt_handler(fid, uid, 'escritorio_nao_existe')
        check('nome inexistente: erro claro', False)
    except ToolError as e:
        check('nome inexistente: erro claro', 'biblioteca_prompts' in str(e))
    s = tools.salvar_prompt_handler(fid, uid, 'http://x', 'Prazo de recurso', 'Calcule o prazo da {{decisao}}.')
    check('salvar_prompt: pessoal por padrão', s['nome'] == 'meu_prompt_prazo_de_recurso' and s['campos'] == ['decisao'])
    s = tools.salvar_prompt_handler(fid, uid, 'http://x', 'Prazo de embargos', 'x', comando='embargos')
    check('salvar_prompt: com comando escolhido', s['nome'] == 'meu_prompt_embargos')
    try:
        tools.salvar_prompt_handler(fid, uid, 'http://x', 'Caso', f'CPF {CPF_VALIDO}', compartilhar=True)
        check('salvar_prompt compartilhado com CPF: recusa', False)
    except ToolError as e:
        check('salvar_prompt compartilhado com CPF: recusa', 'compartilhar=false' in str(e))


def main() -> int:
    with app.app_context():
        db.create_all()
        us = _setup()
        try:
            test_texto()
            p = test_regras(us)
            test_skill(us)
            test_sistema()
            test_ferramentas(us)
            test_tela(us, p)
            test_mcp(us, p)
        finally:
            db.session.rollback()
            _cleanup()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
