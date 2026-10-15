#!/usr/bin/env python3
"""
buscar_por_numero_processo (MCP): um número, todas as bases do escritório.

Trava o que a busca promete: com ou sem pontuação dá o mesmo resultado; número
completo é igualdade e parcial é "contém" (mínimo 7 dígitos); campo da Base de
Conhecimento com dois números ainda casa pelo número completo; cada base só
aparece com o módulo da tela; outro escritório nunca aparece.

Roda contra SQLite descartável.

Uso: uv run python tests/test_mcp_numero_processo.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_mcp_numero_processo.db')
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'

from app.models import db  # noqa: E402

app.extensions.pop('sqlalchemy', None)
try:
    db._app_engines.pop(app, None)
except Exception:
    pass
db.init_app(app)

from fastmcp.exceptions import ToolError  # noqa: E402

from mcp_server.tools.numero_processo import search_by_process_number_handler as buscar  # noqa: E402

APP_URL = 'https://app.exemplo'
TODOS = ['knowledge_base', 'process_panel']
NUMERO = '5001181-56.2023.4.03.6100'
DIGITOS = '50011815620234036100'
FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra and not condicao else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def _preparar():
    from app.models import (ImpugnacaoReferenceModel, JudicialProcess, JurisprudenceDecision, KnowledgeBase,
                            LawFirm, User)
    db.create_all()
    db.session.add_all([LawFirm(id=1, name='Escritório', cnpj='00000000000191'),
                        LawFirm(id=2, name='Outro', cnpj='00000000000272')])
    db.session.add_all([User(id=1, law_firm_id=1, name='A', email='a@b.c', password_hash='x', role='admin'),
                        User(id=2, law_firm_id=2, name='B', email='b@b.c', password_hash='x', role='admin')])
    kb = dict(user_id=1, law_firm_id=1, file_path='/x.md', file_type='MD', processing_status='completed')
    db.session.add_all([
        KnowledgeBase(id=1, original_filename='impugnacao.md', lawsuit_number=NUMERO,
                      source_url='https://drive.google.com/file/d/abc/view', **kb),
        # dois números no mesmo campo, como a tela de detalhes já prevê
        KnowledgeBase(id=2, original_filename='apelacao.md', lawsuit_number=f'5009999-11.2020.4.04.7000, {NUMERO}', **kb),
        KnowledgeBase(id=3, original_filename='outro.md', lawsuit_number='5002222-33.2021.4.04.7100', **kb),
        KnowledgeBase(id=4, original_filename='excluido.md', lawsuit_number=NUMERO, is_active=False, **kb),
        KnowledgeBase(id=5, user_id=2, law_firm_id=2, original_filename='alheio.md', lawsuit_number=NUMERO,
                      file_path='/y.md', file_type='MD'),
    ])
    db.session.add_all([
        JurisprudenceDecision(id=1, law_firm_id=1, processo=NUMERO, processo_digits=DIGITOS,
                              tipo_documento='sentenca', data_julgamento=date(2023, 10, 4), resultado='favoravel',
                              drive_link='https://drive.google.com/file/d/dec/view'),
        JurisprudenceDecision(id=2, law_firm_id=2, processo=NUMERO, processo_digits=DIGITOS),
    ])
    db.session.add_all([
        ImpugnacaoReferenceModel(id=1, law_firm_id=1, title='Santos Brasil — Impugnação', process_number=NUMERO,
                                 source_drive_file_id='1NxLd'),
        ImpugnacaoReferenceModel(id=2, law_firm_id=2, title='Alheia', process_number=NUMERO),
    ])
    db.session.add_all([
        JudicialProcess(id=1, law_firm_id=1, user_id=1, process_number=NUMERO, title='Santos Brasil x União'),
        JudicialProcess(id=2, law_firm_id=2, user_id=2, process_number=NUMERO, title='Alheio'),
    ])
    db.session.commit()


def _ids(resultado, base):
    return [i['id'] for i in resultado['bases'][base]['itens']]


def main():
    with app.app_context():
        _preparar()

        print('\nFormato do número')
        com = buscar(1, TODOS, NUMERO, app_public_url=APP_URL)
        sem = buscar(1, TODOS, DIGITOS, app_public_url=APP_URL)
        check('com e sem pontuação acham o mesmo', com['bases'] == sem['bases'])
        check('número completo é comparação exata', com['comparacao'].startswith('número completo'))
        check('acha nas quatro bases', [len(com['bases'][b]['itens']) for b in
                                        ('base_conhecimento', 'jurisprudencia', 'pecas_modelo', 'processos')]
              == [2, 1, 1, 1], {b: len(g['itens']) for b, g in com['bases'].items()})
        check('Base: campo com dois números casa pelo número completo', 2 in _ids(com, 'base_conhecimento'))
        check('Base: arquivo excluído não aparece', 4 not in _ids(com, 'base_conhecimento'))
        check('nunca outro escritório', all(i['id'] not in (5,) for i in com['bases']['base_conhecimento']['itens'])
              and _ids(com, 'jurisprudencia') == [1] and _ids(com, 'pecas_modelo') == [1] and _ids(com, 'processos') == [1])

        parcial = buscar(1, TODOS, '5001181', app_public_url=APP_URL)
        check('parte do número (7 dígitos) procura por conteúdo', parcial['comparacao'].startswith('parte')
              and _ids(parcial, 'base_conhecimento') == _ids(com, 'base_conhecimento'))
        meio = buscar(1, TODOS, '56.2023.4.03', app_public_url=APP_URL)
        check('pedaço do meio, com pontuação, também acha', _ids(meio, 'processos') == [1], meio['digitos'])
        try:
            buscar(1, TODOS, '55123')
            check('menos de 7 dígitos é recusado', False)
        except ToolError as erro:
            check('menos de 7 dígitos é recusado, com o porquê', '7 dígitos' in str(erro))

        print('\nO que volta em cada item')
        kb = com['bases']['base_conhecimento']['itens'][0]
        check('Base: link para abrir e original no Drive',
              kb['url_abrir'] == f'{APP_URL}/knowledge-base/{kb["id"]}/view' and 'url_original' in
              next(i for i in com['bases']['base_conhecimento']['itens'] if i['id'] == 1))
        dec = com['bases']['jurisprudencia']['itens'][0]
        check('Jurisprudência: instância, resultado e link',
              (dec['instancia'], dec['url']) == ('Sentença', f'{APP_URL}/process-panel/jurisprudencia/decisao/1')
              and dec['url_original'].startswith('https://drive'), dec)
        peca = com['bases']['pecas_modelo']['itens'][0]
        check('Peça-modelo: link do Drive montado do id',
              peca['url_original'] == 'https://drive.google.com/file/d/1NxLd/view', peca)
        check('cada grupo diz qual tool lê o item', all(g.get('proximo_passo') for g in com['bases'].values()))

        print('\nPermissões e filtros')
        so_kb = buscar(1, ['knowledge_base'], NUMERO)
        check('sem process_panel: só a Base, e o resto em sem_permissao',
              list(so_kb['bases']) == ['base_conhecimento'] and len(so_kb['sem_permissao']) == 3, so_kb.get('sem_permissao'))
        try:
            buscar(1, ['fap_panel'], NUMERO)
            check('sem nenhum módulo das bases é recusado', False)
        except ToolError:
            check('sem nenhum módulo das bases é recusado', True)
        uma = buscar(1, TODOS, NUMERO, bases=['jurisprudencia'])
        check('bases=[...] restringe a consulta', list(uma['bases']) == ['jurisprudencia'])
        try:
            buscar(1, TODOS, NUMERO, bases=['planilha'])
            check('base desconhecida é recusada', False)
        except ToolError as erro:
            check('base desconhecida é recusada, listando as válidas', 'base_conhecimento' in str(erro))

        print('\nPaginação')
        pagina = buscar(1, TODOS, NUMERO, bases=['base_conhecimento'], limite=1)
        grupo = pagina['bases']['base_conhecimento']
        check('limite por base com tem_mais e dica de continuação',
              grupo['retornados'] == 1 and grupo['tem_mais'] and "bases=['base_conhecimento']" in grupo['dica'], grupo)
        seguinte = buscar(1, TODOS, NUMERO, bases=['base_conhecimento'], limite=1,
                          deslocamento=grupo['proximo_deslocamento'])
        check('a página seguinte traz o outro arquivo, sem repetir',
              set(_ids(pagina, 'base_conhecimento')) | set(_ids(seguinte, 'base_conhecimento')) == {1, 2})

        vazio = buscar(1, TODOS, '9999999-99.2099.4.04.7000')
        check('nada encontrado vem com aviso', vazio['total_encontrado'] == 0 and vazio.get('aviso'))

    if FALHAS:
        print(f'\n❌ {len(FALHAS)} falha(s): {FALHAS}')
        return 1
    print('\n✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
