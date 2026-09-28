"""
Base de Conhecimento do Painel de Processos: Visão geral, cobertura por tese,
busca nas duas bases e as abas nas telas de jurisprudência e peças-modelo.

Roda contra SQLite descartável. A busca de trechos das peças é forçada a cair
na reserva (Meilisearch "fora do ar"), para o teste não depender do índice nem
ler o índice de dev de outro escritório.

Executar:
    uv run python tests/test_base_conhecimento.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_base_conhecimento.db')
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

from app.services import impugnacao_reference_search  # noqa: E402
from app.services import jurisprudence_import_service as _imp  # noqa: E402

PASTA_TMP = tempfile.mkdtemp(prefix='base_conhecimento_teste_')
_imp.UPLOAD_BASE_DIR = PASTA_TMP
# Meilisearch "fora do ar": a busca de peças tem de cair no LIKE dos trechos.
impugnacao_reference_search.search_chunks = lambda *a, **k: None

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def _preparar():
    """Catálogo com 5 teses, 2 peças-modelo e 7 decisões ligadas por tese.

    Monta o cenário de cada situação da cobertura:
      TRAJETO - B91   peça + decisões favoráveis     → coberta
      ROTATIVIDADE    decisões favoráveis, sem peça  → sem peça-modelo
      CNAE            peça, sem decisão              → sem decisão
      LIMINAR         4 decisões, 3 contra           → maioria contra
      ESTABELECIMENTO nada                           → descoberta
    """
    from datetime import date
    from app.models import (LawFirm, User, JudicialLegalThesis, ImpugnacaoReferenceModel,
                            ImpugnacaoReferenceChunk, JurisprudenceDecision, JurisprudenceThesis)
    db.create_all()
    db.session.add_all([LawFirm(id=1, name='Escritório', cnpj='00000000000191'),
                        LawFirm(id=2, name='Outro', cnpj='00000000000272')])
    db.session.add_all([User(id=1, law_firm_id=1, name='Admin', email='a@b.c', password_hash='x', role='admin'),
                        User(id=2, law_firm_id=2, name='Outra', email='o@b.c', password_hash='x', role='admin')])
    catalogo = {}
    for i, (key, nome) in enumerate([('trajeto_b91', 'TRAJETO - B91'), ('rotatividade', 'ROTATIVIDADE'),
                                     ('correcao_do_cnae', 'CORRECAO DO CNAE'),
                                     ('revogacao_liminar', 'REVOGACAO DA LIMINAR'),
                                     ('individualizacao', 'INDIVIDUALIZACAO POR ESTABELECIMENTO')], start=1):
        catalogo[key] = JudicialLegalThesis(id=i, law_firm_id=1, key=key, name=nome, is_active=True)
        db.session.add(catalogo[key])
    db.session.flush()

    p1 = ImpugnacaoReferenceModel(law_firm_id=1, title='Impugnação Metalúrgica Vale', trf_region='TRF4',
                                  orgao_julgador='2ª Vara Federal de Joinville', status='active',
                                  ingestion_status='completed', chunks_count=30,
                                  thesis_catalog_ids=['trajeto_b91', 'correcao_do_cnae'])
    p2 = ImpugnacaoReferenceModel(law_firm_id=1, title='Impugnação Têxtil Serra', trf_region='TRF3',
                                  status='active', ingestion_status='failed', chunks_count=0,
                                  thesis_catalog_ids=['revogacao_liminar'])
    arquivada = ImpugnacaoReferenceModel(law_firm_id=1, title='Arquivada', trf_region='TRF1', status='archived',
                                         thesis_catalog_ids=['rotatividade'])
    alheia = ImpugnacaoReferenceModel(law_firm_id=2, title='Peça de outro escritório', trf_region='TRF4',
                                      status='active', thesis_catalog_ids=['rotatividade'])
    db.session.add_all([p1, p2, arquivada, alheia])
    db.session.flush()
    db.session.add(ImpugnacaoReferenceChunk(reference_id=p1.id, law_firm_id=1, section_kind='merit_by_thesis',
                                            secao_origem='MÉRITO', full_text='A taxa média de rotatividade foi inferior a 75% <b>',
                                            preview_text='A taxa média de rotatividade foi inferior a 75% <b>'))
    db.session.add(ImpugnacaoReferenceChunk(reference_id=alheia.id, law_firm_id=2, section_kind='merit_by_thesis',
                                            full_text='rotatividade de outro escritório', preview_text='x'))

    def tese(nome, ligada_a):
        t = JurisprudenceThesis(law_firm_id=1, key=nome, name=nome, status='ligada' if ligada_a else 'pendente')
        t.catalog_theses = [catalogo[k] for k in ligada_a]
        db.session.add(t)
        return t
    t_trajeto = tese('ACIDENTE DE TRAJETO', ['trajeto_b91'])
    t_rot = tese('TAXA DE ROTATIVIDADE', ['rotatividade'])
    t_lim = tese('LIMINAR REVOGADA', ['revogacao_liminar'])
    t_sem = tese('TESE SEM LIGACAO', [])

    def decisao(n, resultado, teses, texto='decisão'):
        d = JurisprudenceDecision(law_firm_id=1, processo=f'50000{n:02d}-00.2024.4.04.7200',
                                  processo_digits=f'50000{n:02d}0020244047200',
                                  tribunal='TRF4', tipo_documento='sentenca', resultado=resultado,
                                  data_julgamento=date(2025, 1, n), source='planilha',
                                  motivo_resultado=texto, search_text=texto.lower())
        d.theses = teses
        db.session.add(d)
    decisao(1, 'favoravel', [t_trajeto, t_sem], 'exclusão do trajeto')
    decisao(2, 'parcial', [t_trajeto, t_rot], 'trajeto e rotatividade')
    decisao(3, 'favoravel', [t_rot], 'afastado o bloqueio por rotatividade')
    decisao(4, 'desfavoravel', [t_lim])
    decisao(5, 'desfavoravel', [t_lim])
    decisao(6, 'desfavoravel', [t_lim])
    decisao(7, 'favoravel', [t_lim])
    db.session.commit()


def test_servico():
    print('\n1. Visão geral e cobertura por tese')
    from app.services import process_knowledge_service as base
    v = base.visao_geral(1)
    check('contagens das abas só do escritório e só peças ativas',
          base.contagens(1) == {'decisoes': 7, 'pecas': 2}, base.contagens(1))
    check('jurisprudência: 4 de 7 a favor = 57%', v['jurisprudencia']['pct_a_favor'] == 57, v['jurisprudencia']['pct_a_favor'])
    check('peças: TRFs cobertos e os sem peça',
          v['pecas']['por_trf'] == [('TRF3', 1), ('TRF4', 1)] and 'TRF1' in v['pecas']['trfs_sem_peca'], v['pecas'])
    situacao = {l['tese'].key: l['situacao'] for l in v['cobertura']}
    check('peça + decisão favorável = coberta', situacao['trajeto_b91'] == base.COBERTA)
    check('decisões sem peça = sem peça-modelo (a arquivada e a de outro escritório não contam)',
          situacao['rotatividade'] == base.SEM_PECA)
    check('peça sem decisão = sem decisão', situacao['correcao_do_cnae'] == base.SEM_DECISAO)
    check('3 de 4 contra = maioria contra', situacao['revogacao_liminar'] == base.MAIORIA_CONTRA)
    check('nada = descoberta', situacao['individualizacao'] == base.DESCOBERTA)
    check('o que pede ação vem primeiro', v['cobertura'][0]['situacao'] == base.DESCOBERTA
          and v['cobertura'][-1]['situacao'] == base.COBERTA)
    trajeto = next(l for l in v['cobertura'] if l['tese'].key == 'trajeto_b91')
    check('decisão com duas teses conta em cada uma', trajeto['decisoes'] == 2 and trajeto['pecas'] == 1)
    pend = {p['chave']: p['n'] for p in v['pendencias']}
    check('pendências juntam as duas bases',
          pend.get('teses') == 1 and pend.get('sem_peca') == 2 and pend.get('pecas_falha') == 1, pend)
    check('pendência zerada não aparece', 'pdf_falha' not in pend and 'pecas_processando' not in pend)
    check('escritório sem nada: visão geral vazia, sem erro',
          base.visao_geral(2)['jurisprudencia']['decisoes'] == 0 and base.visao_geral(2)['cobertura'] == [])


def test_busca():
    print('\n2. Busca nas duas bases')
    from app.services import process_knowledge_service as base
    r = base.buscar(1, 'rotatividade')
    check('jurisprudência acha as 2 decisões', r['jurisprudencia']['total'] == 2, r['jurisprudencia']['total'])
    check('peças: cai no LIKE com o índice fora e avisa', r['pecas']['indisponivel'] and r['pecas']['total_pecas'] == 1)
    trecho = r['pecas']['grupos'][0]['trechos'][0]['html']
    check('trecho de peça grifado e escapado', '<mark>rotatividade</mark>' in trecho and '&lt;b&gt;' in trecho, trecho)
    check('peça de outro escritório nunca aparece',
          all(g['peca'].law_firm_id == 1 for g in r['pecas']['grupos']))
    so_jur = base.buscar(1, 'rotatividade', 'jurisprudencia')
    check('escopo "jurisprudência" não busca peças', so_jur['pecas'] is None and so_jur['jurisprudencia'])
    check('consulta vazia não busca nada', base.buscar(1, '  ')['jurisprudencia'] is None)


def test_rotas():
    print('\n3. Rotas, abas e menu')
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(user_id=1, law_firm_id=1, user_role='admin')

    resp = cliente.get('/process-panel/base-conhecimento/')
    html = resp.get_data(as_text=True)
    check('visão geral abre', resp.status_code == 200, resp.status_code)
    check('abas com as contagens', 'Jurisprudência <span class="badge text-bg-light border">7</span>' in html
          and 'Peças-modelo <span class="badge text-bg-light border">2</span>' in html)
    check('cobertura mostra "maioria contra"', 'maioria contra' in html)
    check('menu tem o item Base de Conhecimento ativo',
          '/process-panel/base-conhecimento/' in html and 'Base de Jurisprudência</p>' not in html)
    check('filtro "todas" da cobertura abre', cliente.get('/process-panel/base-conhecimento/?cobertura=todas').status_code == 200)

    resp = cliente.get('/process-panel/base-conhecimento/buscar?q=rotatividade')
    html = resp.get_data(as_text=True)
    check('busca abre com as duas colunas', resp.status_code == 200 and 'Peças-modelo ·' in html and 'Jurisprudência ·' in html)
    check('busca vazia abre sem erro', cliente.get('/process-panel/base-conhecimento/buscar').status_code == 200)

    html = cliente.get('/process-panel/jurisprudencia/').get_data(as_text=True)
    check('aba Jurisprudência ativa na pesquisa', 'kb-abas' in html and 'nav-link active" href="/process-panel/jurisprudencia/"' in html)
    resp = cliente.get('/referencias-impugnacao/')
    html = resp.get_data(as_text=True)
    check('aba Peças-modelo ativa na lista de peças',
          resp.status_code == 200 and 'nav-link active" href="/referencias-impugnacao/"' in html, resp.status_code)
    check('menu marcado também dentro das peças', 'Base de Conhecimento</p>' in html)

    outro = app.test_client()
    with outro.session_transaction() as sessao:
        sessao.update(user_id=2, law_firm_id=2, user_role='admin')
    html = outro.get('/process-panel/base-conhecimento/').get_data(as_text=True)
    check('outro escritório vê só a sua peça', 'Peças-modelo <span class="badge text-bg-light border">1</span>' in html
          and 'Jurisprudência <span class="badge text-bg-light border">0</span>' in html)


def main():
    print('=' * 60)
    print('BASE DE CONHECIMENTO DO PAINEL DE PROCESSOS')
    print('=' * 60)
    with app.app_context():
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        _preparar()
        test_servico()
        test_busca()
        test_rotas()
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
        shutil.rmtree(PASTA_TMP, ignore_errors=True)
