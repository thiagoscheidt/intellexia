#!/usr/bin/env python3
"""
ler_arquivo_base_conhecimento (MCP) e a rota /knowledge-base/<id>/view.

A ferramenta devolve o arquivo inteiro: Markdown/texto do arquivo original,
os demais tipos remontados dos trechos indexados (aqui simulados — o teste
confere o contrato, não o Meilisearch/Qdrant). A rota é o destino do
'url_abrir' do MCP e entregava qualquer arquivo como PDF.

Roda contra SQLite descartável.

Uso: uv run python tests/test_mcp_ler_arquivo_kb.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_mcp_ler_arquivo_kb.db')
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

from mcp_server.tools import knowledge  # noqa: E402

PASTA = tempfile.mkdtemp(prefix='mcp_ler_arquivo_kb_')
APP_URL = 'https://app.exemplo'
FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra and not condicao else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def _arquivo(nome, conteudo: bytes) -> str:
    caminho = os.path.join(PASTA, nome)
    with open(caminho, 'wb') as f:
        f.write(conteudo)
    return caminho


def _preparar():
    from app.models import KnowledgeBase, LawFirm, User
    db.create_all()
    db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
    db.session.add(LawFirm(id=2, name='Outro', cnpj='00000000000272'))
    db.session.add(User(id=1, law_firm_id=1, name='Admin', email='a@b.c', password_hash='x', role='admin'))

    resumo = '# Resumo do caso\n\n## Pedidos\n\nExclusão do B91 de trajeto.\n\n' + ('Fundamento longo. ' * 4000)
    arquivos = [
        (10, 1, 'resumo.md', 'MD', _arquivo('resumo.md', resumo.encode('utf-8')), 'completed', True),
        (11, 1, 'nota.txt', 'TXT', _arquivo('nota.txt', 'Ação de revisão — vigência 2021.'.encode('cp1252')), 'completed', True),
        (12, 1, 'sentenca.pdf', 'PDF', _arquivo('sentenca.pdf', b'%PDF-1.4 x'), 'completed', True),
        (13, 1, 'antigo.pdf', 'PDF', _arquivo('antigo.pdf', b'%PDF-1.4 y'), 'completed', True),
        (14, 1, 'pendente.pdf', 'PDF', _arquivo('pendente.pdf', b'%PDF-1.4 z'), 'pending', True),
        (15, 1, 'apagado.md', 'MD', _arquivo('apagado.md', b'# x'), 'completed', False),
        (16, 2, 'outro.md', 'MD', _arquivo('outro.md', b'# segredo do outro'), 'completed', True),
        (17, 1, 'peticao.docx', 'DOCX', _arquivo('peticao.docx', b'PK\x03\x04'), 'completed', True),
        (18, 1, 'planilha.odt', 'ODT', _arquivo('planilha.odt', b'PK\x03\x04'), 'completed', True),
    ]
    for id_, firma, nome, tipo, caminho, status, ativo in arquivos:
        db.session.add(KnowledgeBase(id=id_, user_id=1, law_firm_id=firma, original_filename=nome,
                                     file_path=caminho, file_type=tipo, processing_status=status, is_active=ativo))
    db.session.commit()


INDICE_FALSO = {
    # Pedaços com página, fora de ordem: a remontagem segue o chunk_index.
    12: [{'text': 'Julgo procedente.', 'page': 2, 'chunk_index': 1},
         {'text': 'Vistos. A empresa pede a exclusão.', 'page': 1, 'chunk_index': 0}],
    # Corte antigo sem página: 20 caracteres repetidos entre um pedaço e o seguinte.
    13: [{'text': 'O laudo afastou o nexo causal do evento.', 'chunk_index': 0},
         {'text': 'nexo causal do evento. Recurso provido.', 'chunk_index': 1}],
}


def test_ferramenta():
    print('\n1. ler_arquivo_base_conhecimento')
    knowledge._pedacos_do_indice = lambda file_id: INDICE_FALSO.get(file_id, [])

    r = knowledge.read_kb_file_handler(10, 1, app_public_url=APP_URL)
    check('.md vem do arquivo original', r['origem_texto'] == 'arquivo_original'
          and r['texto'].startswith('# Resumo do caso'), r.get('origem_texto'))
    check('documento grande vem em partes', r['tem_mais'] and r['retornados'] <= knowledge.MAX_CARACTERES_LEITURA
          and r['proximo_deslocamento'] == r['retornados'], (r['retornados'], r.get('proximo_deslocamento')))
    check('link para abrir no sistema', r['url_abrir'] == f'{APP_URL}/knowledge-base/10/view')
    lido, desloc = r['texto'], r['proximo_deslocamento']
    while desloc is not None:
        parte = knowledge.read_kb_file_handler(10, 1, deslocamento=desloc)
        lido += parte['texto']
        desloc = parte.get('proximo_deslocamento')
    check('as partes juntas dão o arquivo inteiro, sem buraco nem repetição',
          lido == open(os.path.join(PASTA, 'resumo.md'), encoding='utf-8').read().strip())

    r = knowledge.read_kb_file_handler(11, 1)
    check('.txt em cp1252 é lido com acento', r['texto'] == 'Ação de revisão — vigência 2021.', r['texto'])

    r = knowledge.read_kb_file_handler(12, 1)
    check('PDF é remontado do índice, na ordem, com a página marcada',
          r['origem_texto'] == 'indice_de_busca'
          and r['texto'] == '[Página 1]\n\nVistos. A empresa pede a exclusão.\n\n[Página 2]\n\nJulgo procedente.',
          r['texto'])
    check('avisa que o texto foi remontado', 'remontado' in r.get('observacao', ''))

    r = knowledge.read_kb_file_handler(13, 1)
    check('sobreposição do corte antigo não se repete',
          r['texto'] == 'O laudo afastou o nexo causal do evento.\n\nRecurso provido.', r['texto'])

    r = knowledge.read_kb_file_handler(14, 1)
    check('arquivo ainda não processado avisa em vez de devolver vazio calado',
          r['texto'] == '' and 'ainda não foi processado' in r['aviso'], r)

    for arquivo_id, firma, rotulo in ((16, 1, 'arquivo de outro escritório'), (15, 1, 'arquivo excluído'),
                                     (999, 1, 'arquivo inexistente')):
        try:
            knowledge.read_kb_file_handler(arquivo_id, firma)
            check(f'{rotulo} → ToolError', False)
        except ToolError as erro:
            check(f'{rotulo} → ToolError', 'não encontrado' in str(erro))

    def _quebrado(_file_id):
        raise ConnectionError('meili e qdrant fora')
    knowledge._pedacos_do_indice = _quebrado
    try:
        knowledge.read_kb_file_handler(12, 1)
        check('índices fora → ToolError com motivo', False)
    except ToolError as erro:
        check('índices fora → ToolError com motivo', 'indisponíveis' in str(erro))
    r = knowledge.read_kb_file_handler(10, 1)
    check('.md não depende dos índices', r['texto'].startswith('# Resumo do caso'))


def test_rota_view():
    print('\n2. /knowledge-base/<id>/view (destino do url_abrir)')
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(user_id=1, law_firm_id=1, user_role='admin')

    r = cliente.get('/knowledge-base/10/view')
    check('.md sai como texto puro', r.status_code == 200 and r.mimetype == 'text/plain'
          and r.headers.get('X-Content-Type-Options') == 'nosniff', (r.status_code, r.mimetype))
    r = cliente.get('/knowledge-base/11/view')
    check('.txt em cp1252 sai em UTF-8 legível', 'Ação de revisão' in r.get_data(as_text=True))
    r = cliente.get('/knowledge-base/12/view')
    check('PDF continua inline como PDF', r.mimetype == 'application/pdf'
          and 'attachment' not in r.headers.get('Content-Disposition', ''), r.mimetype)
    r.close()
    r = cliente.get('/knowledge-base/17/view')
    check('DOCX vai para a visualização de DOCX', r.status_code == 302 and '/view-docx' in r.headers['Location'])
    r = cliente.get('/knowledge-base/18/view')
    check('outro tipo vira download isolado', 'attachment' in r.headers.get('Content-Disposition', '')
          and 'sandbox' in r.headers.get('Content-Security-Policy', ''), dict(r.headers))
    r.close()
    r = cliente.get('/knowledge-base/16/view')
    check('arquivo de outro escritório não abre', r.status_code == 302 and '/view' not in r.headers['Location'])


def main():
    print('=' * 60)
    print('MCP: LER ARQUIVO DA BASE DE CONHECIMENTO')
    print('=' * 60)
    with app.app_context():
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        _preparar()
        test_ferramenta()
        test_rota_view()
    print('\n' + '=' * 60)
    if FALHAS:
        print(f'❌ {len(FALHAS)} falha(s): {", ".join(FALHAS)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        import shutil
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        shutil.rmtree(PASTA, ignore_errors=True)
