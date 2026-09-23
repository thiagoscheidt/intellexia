"""
Base de Jurisprudência: normalização, importação, teses, busca, fila de PDFs,
agente de leitura, geração e rotas.

Cada verificação tranca uma descoberta feita no Banco Mestre FAP real (515
decisões), não uma linha de código. Roda contra SQLite descartável; o agente
de leitura usa LLM falso, sem rede.

Executar:
    uv run python tests/test_jurisprudencia.py
"""

import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_jurisprudencia.db')
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

from app.services import jurisprudence_normalizer as norm  # noqa: E402
from app.services import jurisprudence_import_service as _imp  # noqa: E402
from app.services import jurisprudence_upload_service as _up  # noqa: E402
import tempfile  # noqa: E402

# Arquivos do teste numa pasta própria — nunca em uploads/, que em dev tem dado real.
PASTA_TMP = tempfile.mkdtemp(prefix='jurisprudencia_teste_')
_imp.UPLOAD_BASE_DIR = PASTA_TMP
_up.UPLOAD_BASE_DIR = PASTA_TMP

FALHAS = []
PLANILHA_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'BANCO_MESTRE_FAP.xlsx')


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


CABECALHO = ['documento_id', 'nome_arquivo', 'link_drive', 'processo', 'tribunal', 'orgao_julgador', 'relator',
             'data_julgamento', 'tipo_documento', 'resultado', 'motivo_resultado', 'teses', 'ementa',
             'fundamentos', 'precedentes', 'resumo_executivo', 'palavras_chave', 'data_indexacao',
             'parte_autora', 'vigencia_fap', 'classe_processual']


def linha(processo, tribunal, orgao, data_j, tipo, resultado, teses, motivo='', vigencia='2019 a 2021',
          parte='METALURGICA VALE LTDA', ementa='', precedentes=''):
    return ['DOC1', f'{tipo}.pdf', 'https://drive.google.com/x', processo, tribunal, orgao, 'DESEMBARGADORA FEDERAL ANA',
            data_j, tipo, resultado, motivo, teses, ementa, 'Fundamento A; Fundamento B', precedentes,
            f'Resumo do caso {processo}', 'FAP', None, parte, vigencia, 'Apelação Cível']


LINHAS = [
    # processo com virada: sentença perdida, acórdão parcial
    linha('5012345-67.2021.4.04.7205', 'TRF4 - 2a Vara Federal de Blumenau', '2a Vara Federal de Blumenau',
          '2024-03-14', 'SENTENÇA', 'DESFAVORÁVEL', 'ACIDENTE DE TRAJETO; ERRO NA FREQUÊNCIA',
          motivo='Juízo entendeu que o percurso casa-trabalho integra o risco.'),
    linha('5012345-67.2021.4.04.7205', 'TRF4', '2a Turma', '2026-05-12', 'ACORDAO', 'PARCIALMENTE FAVORAVEL',
          'ACIDENTE DE TRAJETO; PRORROGAÇÃO DE BENEFÍCIO',
          motivo='Turma excluiu o acidente de trajeto e manteve a prorrogação.',
          ementa='TRIBUTÁRIO. FAP. ACIDENTE DE TRAJETO. 1. Exclusão.',
          precedentes='TRF4 AC 5003321-10.2023.4.04.7207; STJ REsp 1.999.888'),
    # a mesma decisão processada duas vezes com grafia diferente (medido: 6 casos na planilha real)
    linha('5012345-67.2021.4.04.7205', 'TRF4', '2a Turma', '2026-05-12', 'ACÓRDÃO', 'PARCIALMENTE FAVORAVEL',
          'ACIDENTE DE TRAJETO'),
    linha('5003321-10.2023.4.04.7207', 'TRF4 - 1a Vara Federal de Tubarão', None, '2025-02-02', 'SENTENCA',
          'FAVORAVEL', 'ACIDENTE DE TRAJETO; PRORROGACAO DE BENEFICIO; TAXA DE ROTATIVIDADE',
          motivo='Exclusão dos eventos de trajeto.', vigencia=2018.0),
    linha('5006749-11.2023.4.03.6114', 'TRF3 - 7a Vara Civel Federal de Sao Paulo', None, '2024-10-10',
          'EMBARGOS DE DECLARAÇÃO', 'DESFAVORAVEL', 'BIS IN IDEM; HONORARIOS ADVOCATICIOS', vigencia='teste',
          parte=None),
]


def planilha_xlsx(linhas, abas_extras=('ERROS_LOG', 'TESES')):
    from openpyxl import Workbook
    wb = Workbook()
    aba = wb.active
    aba.title = 'DOCUMENTOS'
    aba.append(CABECALHO)
    for l in linhas:
        aba.append(l)
    for nome in abas_extras:
        wb.create_sheet(nome).append(['x'])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def test_normalizacao():
    print('\n1. Normalização (as grafias da planilha real)')
    check('"TRF4 - 2a Vara…" vira sigla + órgão com ordinal',
          norm.separar_tribunal('TRF4 - 2a Vara Federal de Blumenau', None) == ('TRF4', '2ª Vara Federal de Blumenau'))
    check('órgão explícito vence o que vem no texto do tribunal',
          norm.separar_tribunal('TRF4', '2a Turma') == ('TRF4', '2ª Turma'))
    check('grafia sem acento é corrigida ("Civel", "Sao Paulo")',
          norm.separar_tribunal('TRF3 - 7a Vara Civel Federal de Sao Paulo')[1] == '7ª Vara Cível Federal de São Paulo')
    check('UF pelo número CNJ (72 = SC no TRF4)', norm.uf_do_processo('5003321-10.2023.4.04.7207') == 'SC')
    check('UF pelo sufixo "/RS"', norm.uf_do_processo('5083928-14.2021.4.04.7100/RS') == 'RS')
    check('UF pela seção judiciária no órgão', norm.uf_do_processo('x', '4a Vara Federal Civel da SJGO') == 'GO')
    check('vigência 2018.0 (float do Excel) vira 2018', norm.vigencia(2018.0) == ('2018', 2018, 2018))
    check('vigência "teste" não vira vigência', norm.vigencia('teste') == (None, None, None))
    check('SENTENÇA e SENTENCA são a mesma instância',
          norm.tipo_documento('SENTENÇA') == norm.tipo_documento('SENTENCA') == norm.TIPO_SENTENCA)
    check('EMBARGOS DE DECLARAÇÃO → embargos', norm.tipo_documento('EMBARGOS DE DECLARAÇÃO') == norm.TIPO_EMBARGOS)
    check('instância rara vira "outra"', norm.tipo_documento('DECISÃO DE ADMISSIBILIDADE DE RECURSO ESPECIAL') == norm.TIPO_OUTRA)
    check('PARCIALMENTE FAVORÁVEL → parcial', norm.resultado('PARCIALMENTE FAVORÁVEL') == norm.RESULTADO_PARCIAL)
    termos = norm.termos_da_consulta('in itinere prorrogação')
    check('"in itinere" é um termo só, não "in" + "itinere"', len(termos) == 2 and 'in itinere' in termos[0], termos)
    check('sinônimo: trajeto acha percurso', 'percurso' in norm.expandir_termo('trajeto'))
    check('aspas juntam a expressão', norm.termos_da_consulta('"erro no custo"')[0][0] == 'erro no custo')
    cit = norm.citacao({'tribunal': 'TRF4', 'orgao_julgador': '2ª Turma', 'processo': '5083928-14.2021.4.04.7100/RS',
                        'tipo_documento': 'acordao', 'classe_processual': 'Apelação Cível',
                        'relator': 'DESEMBARGADORA FEDERAL MARIA DE FÁTIMA', 'data_julgamento': date(2026, 5, 12)})
    check('citação de acórdão com classe abreviada e relator legível',
          cit == '(TRF4, AC 5083928-14.2021.4.04.7100, 2ª Turma, Rel. Desembargadora Federal Maria de Fátima, julgado em 12/05/2026)', cit)
    cit = norm.citacao({'tribunal': 'TRF4', 'orgao_julgador': '2ª Vara Federal de Blumenau', 'processo': '5012345-67.2021.4.04.7205',
                        'tipo_documento': 'sentenca', 'data_julgamento': date(2024, 3, 14)})
    check('citação de sentença no formato de primeiro grau', 'sentença proferida em 14/03/2024' in cit and 'Vara' in cit, cit)


def _preparar_base():
    from app.models import LawFirm, User, JudicialLegalThesis
    db.create_all()
    db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
    db.session.add(LawFirm(id=2, name='Outro', cnpj='00000000000272'))
    db.session.add(User(id=1, law_firm_id=1, name='Admin', email='a@b.c', password_hash='x', role='admin'))
    db.session.add(User(id=2, law_firm_id=2, name='Outra', email='o@b.c', password_hash='x', role='admin'))
    for i, nome in enumerate(['TRAJETO - B91', 'TRAJETO - B94', 'TAXA DE ROTATIVIDADE', 'CONCESSAO DUPLICADA DE BENEFICIO'], start=1):
        db.session.add(JudicialLegalThesis(id=i, law_firm_id=1, key=nome.lower().replace(' ', '_'), name=nome))
    db.session.commit()


def test_importacao():
    print('\n2. Importação da planilha')
    from app.services import jurisprudence_import_service as imp
    from app.services import jurisprudence_service as svc
    caminho = os.path.join(os.path.dirname(DB_FILE), '_tmp_jurisprudencia.xlsx')
    with open(caminho, 'wb') as f:
        f.write(planilha_xlsx(LINHAS).read())
    try:
        c = imp.conferir(1, caminho, 'BANCO.xlsx')
        check('lê a aba DOCUMENTOS', c['aba'] == 'DOCUMENTOS')
        check('5 lidas, 4 novas, 1 repetida na própria planilha',
              (c['lidas'], c['novas'], c['repetidas_na_planilha']) == (5, 4, 1), (c['lidas'], c['novas'], c['repetidas_na_planilha']))
        check('abas de log ficam de fora', c['outras_abas'] == ['ERROS_LOG', 'TESES'])
        check('grafias de tese unificadas por acento', c['padronizacao']['teses'] < c['padronizacao']['teses_brutas'],
              c['padronizacao'])
        check('"TAXA DE ROTATIVIDADE" ligaria sozinha (nome idêntico ao catálogo)', c['teses']['ligadas'] == 1, c['teses'])
        check('conferir não grava nada', svc.totais(1)['decisoes'] == 0)

        r = imp.importar(1, caminho, user_id=1, nome_arquivo='BANCO.xlsx')
        check('importa 4 e pula a repetida', (r['criadas'], r['puladas']) == (4, 1), r)
        r2 = imp.importar(1, caminho, user_id=1)
        check('reimportar não duplica nada', (r2['criadas'], r2['puladas']) == (0, 5), r2)
        check('processos distintos contados', svc.totais(1) == {'decisoes': 4, 'processos': 3}, svc.totais(1))
    finally:
        os.remove(caminho)

    from app.models import JurisprudenceDecision as D
    acordao = D.query.filter_by(law_firm_id=1, tipo_documento='acordao').first()
    check('órgão com ordinal e UF do CNJ gravados', (acordao.orgao_julgador, acordao.uf) == ('2ª Turma', 'SC'),
          (acordao.orgao_julgador, acordao.uf))
    check('data vira Date', acordao.data_julgamento == date(2026, 5, 12))
    check('teses gravadas como vieram', acordao.teses_brutas_json == ['ACIDENTE DE TRAJETO', 'PRORROGAÇÃO DE BENEFÍCIO'])
    embargos = D.query.filter_by(law_firm_id=1, tipo_documento='embargos').first()
    check('vigência inválida fica vazia e o resto entra', embargos.vigencia_texto is None and embargos.tribunal == 'TRF3')


def test_teses():
    print('\n3. Correspondência de teses')
    from app.models import JurisprudenceThesis as T, JurisprudenceDecision as D
    from app.services import jurisprudence_thesis_service as ts
    from app.services import jurisprudence_service as svc

    rot = T.query.filter_by(law_firm_id=1, key='TAXA DE ROTATIVIDADE').first()
    check('tese com nome do catálogo já nasce ligada', rot.status == 'ligada' and [c.id for c in rot.catalog_theses] == [3])
    prorrog_acento = T.query.filter_by(law_firm_id=1, key='PRORROGACAO DE BENEFICIO').first()
    check('PRORROGAÇÃO e PRORROGACAO são uma tese só',
          prorrog_acento is not None and T.query.filter_by(law_firm_id=1).filter(T.key.like('PRORROG%')).count() == 1)

    trajeto = T.query.filter_by(law_firm_id=1, key='ACIDENTE DE TRAJETO').first()
    ts.ligar(1, trajeto.id, [1, 2])
    check('ligar a várias teses do catálogo (trajeto ↔ B91 e B94)', sorted(c.id for c in trajeto.catalog_theses) == [1, 2])

    pendentes_antes = svc.contar_teses_pendentes(1)
    bis = T.query.filter_by(law_firm_id=1, key='BIS IN IDEM').first()
    hon = T.query.filter_by(law_firm_id=1, key='HONORARIOS ADVOCATICIOS').first()
    ts.marcar_sem_equivalente(1, hon.id)
    check('"sem equivalente" tira da fila', svc.contar_teses_pendentes(1) == pendentes_antes - 1)

    # mesclar: BIS IN IDEM passa a ser grafia de PRORROGACAO (só para exercitar)
    ts.mesclar(1, bis.id, prorrog_acento.id)
    embargos = D.query.filter_by(law_firm_id=1, tipo_documento='embargos').first()
    check('mesclar move as decisões para a canônica',
          [t.key for t in embargos.theses] == ['HONORARIOS ADVOCATICIOS', 'PRORROGACAO DE BENEFICIO'],
          [t.key for t in embargos.theses])
    check('a variante aponta para a canônica', db.session.get(T, bis.id).merged_into_id == prorrog_acento.id)
    from app.services.jurisprudence_service import ResolvedorDeTeses
    check('a grafia mesclada resolve para a canônica na próxima importação',
          ResolvedorDeTeses(1).resolver('Bis in idem').id == prorrog_acento.id)
    ts.desfazer_mescla(1, bis.id)
    embargos = db.session.get(D, embargos.id)
    check('desfazer devolve a decisão à variante pela tese bruta',
          sorted(t.key for t in embargos.theses) == ['BIS IN IDEM', 'HONORARIOS ADVOCATICIOS'],
          [t.key for t in embargos.theses])

    bis.suggestion_json = {'catalog_ids': [4], 'merge_into_id': None, 'sem_equivalente': False, 'motivo': 'x'}
    db.session.commit()
    ts.aceitar_sugestao(1, bis.id)
    check('aceitar sugestão liga ao catálogo', db.session.get(T, bis.id).status == 'ligada')
    try:
        ts.ligar(2, trajeto.id, [1])
        check('outro escritório não mexe na tese', False)
    except LookupError:
        check('outro escritório não mexe na tese', True)


def test_busca():
    print('\n4. Busca')
    from app.services import jurisprudence_search_service as s
    from werkzeug.datastructures import MultiDict

    def buscar(**kw):
        return s.buscar(1, s.Filtros.do_request(MultiDict(kw)))

    r = buscar(q='percurso')
    check('sinônimo: "percurso" acha as decisões de trajeto', r['total'] >= 3, r['total'])
    r = buscar(q='trajeto rotatividade')
    check('todos os termos (E): trajeto + rotatividade = 1', r['total'] == 1, r['total'])
    r = buscar(q='50123456720214047205')
    check('número sem pontuação acha o processo', r['total'] == 2 and r['processos'] == 1)
    r = buscar(q='5012345-67.2021.4.04.7205')
    check('número com pontuação também', r['total'] == 2)
    r = buscar(tese='1')
    check('filtro pela tese do catálogo (B91 via trajeto)', r['total'] == 3, r['total'])
    r = buscar(tribunal='TRF4')
    check('faceta disjuntiva: marcar TRF4 não zera TRF3', r['facetas']['tribunal'].get('TRF3') == 1, r['facetas']['tribunal'])
    check('barra de êxito soma o total', sum(e['n'] for e in r['exito']) == r['total'])
    r = buscar(vigencia='2020')
    check('vigência "2019 a 2021" vale para 2020', r['total'] == 2, r['total'])
    r = buscar(q='trajeto')
    cartao = next(c for c in r['cartoes'] if c['processo'].startswith('5012345'))
    check('um cartão por processo, com a trilha inteira', len(cartao['trilha']) == 2)
    check('sentença perdida + acórdão melhor = "virou no acórdão"', cartao['virada'] is True)
    check('instância que falta aparece como lacuna', cartao['faltando'] == ['Embargos'], cartao['faltando'])
    check('trecho vem com <mark> e escapado', '<mark>' in (cartao['trecho'] or ''), cartao['trecho'])
    r = buscar(q='trajeto', agrupar='decisao')
    check('por decisão: um cartão por decisão', len(r['cartoes']) == r['total'])
    check('trecho escapa HTML do texto', '&lt;b&gt;' in s.trecho('x <b> trajeto', [['trajeto']]))


def test_correcao_manual():
    print('\n5. Correção manual sobrevive ao reprocessamento')
    from app.models import JurisprudenceDecision as D
    from app.services import jurisprudence_service as svc
    d = D.query.filter_by(law_firm_id=1, tipo_documento='acordao').first()
    resolvedor = svc.ResolvedorDeTeses(1)
    mudou = svc.corrigir_manualmente(d, {**_bruto_de(d), 'relator': 'Des. Fed. Corrigido'}, resolvedor)
    check('só o campo alterado entra como manual', mudou == ['relator'], mudou)
    svc.atualizar_da_ia(d, {**_bruto_de(d), 'relator': 'ERRADO PELA IA', 'motivo_resultado': 'novo motivo'}, resolvedor)
    check('IA não sobrescreve o corrigido', d.relator == 'Des. Fed. Corrigido')
    check('IA atualiza o resto', d.motivo_resultado == 'novo motivo')
    db.session.commit()


def _bruto_de(d):
    return {
        'processo': d.processo, 'tribunal': d.tribunal, 'orgao_julgador': d.orgao_julgador, 'uf': d.uf,
        'relator': d.relator, 'data_julgamento': d.data_julgamento, 'tipo_documento': d.tipo_documento,
        'classe_processual': d.classe_processual, 'resultado': d.resultado, 'motivo_resultado': d.motivo_resultado,
        'parte_autora': d.parte_autora, 'vigencia_fap': d.vigencia_texto, 'ementa': d.ementa,
        'resumo_executivo': d.resumo_executivo, 'teses': d.teses_brutas_json, 'fundamentos': d.fundamentos_json,
        'precedentes': d.precedentes_json, 'argumentos_acolhidos': d.argumentos_acolhidos_json,
        'argumentos_rejeitados': d.argumentos_rejeitados_json,
    }


class _FakeRaw:
    def __init__(self, finish='stop'):
        self.response_metadata = {'finish_reason': finish}
        self.usage_metadata = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
        self.content = ''
        self.id = 'x'


class _FakeLLM:
    """Primeira chamada vem cortada; a segunda (sem raciocínio) responde."""
    def __init__(self, dados, cortar_primeira=True):
        self.dados, self.cortar, self.chamadas = dados, cortar_primeira, []

    def fabrica(self, com_raciocinio):
        chamadas, dados, cortar = self.chamadas, self.dados, self.cortar

        class _R:
            def invoke(self_inner, mensagens):
                chamadas.append((com_raciocinio, mensagens[0]['content']))
                if cortar and len(chamadas) == 1:
                    return {'raw': _FakeRaw('length'), 'parsed': None, 'parsing_error': 'cortado'}
                from app.agents.jurisprudence.decision_extractor_agent import DecisaoExtraida
                return {'raw': _FakeRaw(), 'parsed': DecisaoExtraida(**dados), 'parsing_error': None}
        return _R()


DADOS_PDF = {
    'processo': '5099999-11.2024.4.04.7200', 'tribunal': 'TRF4', 'orgao_julgador': '1ª Turma', 'uf': '',
    'relator': 'Des. X', 'data_julgamento': '21/03/2026', 'tipo_documento': 'ACORDAO',
    'classe_processual': 'Apelação Cível', 'resultado': 'FAVORAVEL', 'motivo_resultado': 'Excluiu o trajeto.',
    'parte_autora': 'EMPRESA NOVA S.A.', 'vigencia_fap': '2020', 'teses': ['ACIDENTE DE TRAJETO'],
    'ementa': 'Resumo da ementa.', 'fundamentos': ['F1'], 'precedentes': [], 'argumentos_acolhidos': ['A1'],
    'argumentos_rejeitados': [], 'resumo_executivo': 'História.', 'palavras_chave': ['FAP'],
}


def _pdf(nome='decisao.pdf'):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(b'%PDF-1.4 teste ' + os.urandom(8)), filename=nome, content_type='application/pdf')


def test_agente():
    print('\n6. Agente de leitura: retomada quando a resposta vem cortada')
    from app.agents.jurisprudence.decision_extractor_agent import JurisprudenceDecisionExtractorAgent, ExtracaoFalhou
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(b'%PDF-1.4 x')
        caminho = f.name
    try:
        fake = _FakeLLM(DADOS_PDF)
        agente = JurisprudenceDecisionExtractorAgent(model_name='fake', llm_factory=fake.fabrica)
        lido = agente.extrair(caminho, teses_referencia=['ACIDENTE DE TRAJETO'], law_firm_id=1)
        check('duas chamadas: a cortada e a retomada', len(fake.chamadas) == 2)
        check('a retomada vai sem raciocínio', fake.chamadas[1][0] is False and fake.chamadas[0][0] is True)
        check('a retomada pede a ementa resumida', 'NÃO transcreva a ementa' in fake.chamadas[1][1])
        check('a lista do escritório vai no prompt', 'ACIDENTE DE TRAJETO' in fake.chamadas[0][1])
        check('ementa da retomada é marcada como resumo', lido['ementa_modo'] == 'resumo')
        vazio = _FakeLLM({**DADOS_PDF, 'processo': '', 'resumo_executivo': ''}, cortar_primeira=False)
        try:
            JurisprudenceDecisionExtractorAgent(model_name='fake', llm_factory=vazio.fabrica).extrair(caminho)
            check('leitura sem processo nem conteúdo falha com motivo', False)
        except ExtracaoFalhou as erro:
            check('leitura sem processo nem conteúdo falha com motivo', 'imagem sem texto' in str(erro))
    finally:
        os.remove(caminho)


def test_fila():
    print('\n7. Fila de PDFs')
    from app.models import JurisprudenceUpload as U, JurisprudenceDecision as D
    from app.services import jurisprudence_upload_service as up
    from app.agents.jurisprudence.decision_extractor_agent import JurisprudenceDecisionExtractorAgent

    def agente(dados):
        return JurisprudenceDecisionExtractorAgent(model_name='fake', llm_factory=_FakeLLM(dados, False).fabrica)

    with app.test_request_context():
        up.disparar = lambda *a, **k: None          # sem thread no teste
        ids, recusas = up.receber(1, [_pdf('nova.pdf'), _pdf('duplicada.pdf')], user_id=1)
        from werkzeug.datastructures import FileStorage
        _, recusas2 = up.receber(1, [FileStorage(stream=io.BytesIO(b'nao e pdf'), filename='x.pdf')], user_id=1)
    check('dois PDFs na fila', len(ids) == 2 and not recusas)
    check('arquivo que não começa com %PDF é recusado', len(recusas2) == 1)

    u = up.processar(1, ids[0], agente=agente(DADOS_PDF))
    check('leitura nova vira decisão', u.status == 'done' and u.decision is not None and u.decision.source == 'pdf')
    check('resultado da IA normalizado', u.decision.resultado == 'favoravel' and u.decision.data_julgamento == date(2026, 3, 21))

    u2 = up.processar(1, ids[1], agente=agente({**DADOS_PDF, 'data_julgamento': '22/03/2026', 'resultado': 'DESFAVORAVEL'}))
    check('mesmo processo e instância vai para "revisar"', u2.status == 'review' and u2.duplicate_of_id == u.decision_id)
    up.resolver_duplicata(1, u2.id, 'guardar_ambas', 1)
    check('"guardar as duas" cria a segunda', D.query.filter_by(law_firm_id=1, processo_digits='50999991120244047200').count() == 2)

    class _Quebra:
        model_name = 'fake'
        def extrair(self, *a, **k):
            from app.agents.jurisprudence.decision_extractor_agent import ExtracaoFalhou
            raise ExtracaoFalhou('O PDF é imagem sem texto.')
    with app.test_request_context():
        ids3, _ = up.receber(1, [_pdf('ruim.pdf')], user_id=1)
    u3 = up.processar(1, ids3[0], agente=_Quebra())
    check('falha fica na linha com o motivo', u3.status == 'failed' and 'imagem sem texto' in u3.error_message)
    painel = up.painel(1)
    check('painel conta por situação', painel['contagem']['failed'] == 1 and painel['contagem']['done'] == 2, painel['contagem'])
    check('fila é por escritório', up.painel(2)['linhas'] == [])


def test_geracao():
    print('\n8. Geração da impugnação')
    from app.services import jurisprudence_generation_service as g

    class _Processo:
        process_number = '5009876-12.2025.4.04.7205'
        tribunal_name = 'TRF4'
        section = ''
        origin_unit = '2ª Vara Federal de Blumenau'
        judge_name = ''
    sugestoes = g.sugestoes_por_tese(1, _Processo(), [1])
    check('uma entrada por tese do catálogo', [s['tese'] for s in sugestoes] == ['TRAJETO - B91'])
    decisoes = sugestoes[0]['decisoes']
    check('favorável vem antes de parcial', decisoes[0]['resultado'] == 'favoravel', [d['resultado'] for d in decisoes])
    check('desfavorável aparece, marcada como contrária e desmarcada',
          any(d['contraria'] and not d['marcada'] for d in decisoes), decisoes)
    pares = g.pares_do_formulario([f"{decisoes[0]['id']}:1", f"{decisoes[-1]['id']}:1", 'lixo', f"{decisoes[0]['id']}:1"])
    check('pares do formulário sem repetição e sem lixo', len(pares) == 2, pares)
    bloco = g.bloco_do_prompt(1, pares)
    check('bloco traz a tese e a citação pronta', '[Tese: TRAJETO - B91]' in bloco and '(TRF4' in bloco, bloco[:300])
    check('decisão desfavorável vai rotulada CONTRÁRIA', 'CONTRÁRIA' in bloco)
    check('bloco de outro escritório vem vazio', g.bloco_do_prompt(2, pares) == '')
    check('pares_confirmados lê o JSON da versão', g.pares_confirmados({'jurisprudence': pares}) == pares)


def test_rotas():
    print('\n9. Rotas')
    from app.models import JurisprudenceDecision as D
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(user_id=1, law_firm_id=1, user_role='admin')

    def get(url):
        return cliente.get(url, follow_redirects=False)

    for url in ('/process-panel/jurisprudencia/', '/process-panel/jurisprudencia/?q=trajeto&tribunal=TRF4',
                '/process-panel/jurisprudencia/?agrupar=decisao&livres=1', '/process-panel/jurisprudencia/teses',
                '/process-panel/jurisprudencia/teses?filtro=todas', '/process-panel/jurisprudencia/enviar',
                '/process-panel/jurisprudencia/importar'):
        resp = get(url)
        check(f'GET {url} → 200', resp.status_code == 200, resp.status_code)
    d = D.query.filter_by(law_firm_id=1, tipo_documento='acordao').first()
    resp = get(f'/process-panel/jurisprudencia/decisao/{d.id}')
    check('página da decisão abre', resp.status_code == 200 and 'Citação pronta' in resp.get_data(as_text=True))
    check('edição abre', get(f'/process-panel/jurisprudencia/decisao/{d.id}/editar').status_code == 200)
    resp = cliente.post(f'/process-panel/jurisprudencia/decisao/{d.id}/editar',
                        data={'processo': d.processo, 'tribunal': d.tribunal, 'orgao_julgador': d.orgao_julgador,
                              'tipo_documento': 'acordao', 'resultado': 'favoravel', 'uf': d.uf,
                              'relator': d.relator, 'data_julgamento': d.data_julgamento.isoformat(),
                              'classe_processual': d.classe_processual, 'parte_autora': d.parte_autora,
                              'vigencia_fap': d.vigencia_texto, 'motivo_resultado': d.motivo_resultado,
                              'resumo_executivo': d.resumo_executivo, 'ementa': d.ementa,
                              'teses': '\n'.join(d.teses_brutas_json), 'fundamentos': '\n'.join(d.fundamentos_json),
                              'precedentes': '\n'.join(d.precedentes_json),
                              'argumentos_acolhidos': '', 'argumentos_rejeitados': ''})
    d = db.session.get(D, d.id)
    check('POST de correção grava e marca o campo', resp.status_code == 302 and d.resultado == 'favoravel'
          and 'resultado' in (d.manual_fields_json or []), d.manual_fields_json)
    check('API do wizard devolve JSON', get('/process-panel/jurisprudencia/api/buscar?q=trajeto').is_json)

    resp = cliente.post('/process-panel/jurisprudencia/importar',
                        data={'arquivo': (planilha_xlsx(LINHAS), 'BANCO.xlsx')}, content_type='multipart/form-data')
    check('upload da planilha leva à conferência', resp.status_code == 302 and '/importar/' in resp.headers['Location'])
    resp = get(resp.headers['Location'])
    check('conferência mostra que nada é novo', resp.status_code == 200 and 'Nada novo para importar' in resp.get_data(as_text=True))

    resp = cliente.post('/process-panel/jurisprudencia/teses/1/descartar-sugestao', data={'voltar': 'https://malicioso.example/'})
    check('"voltar" externo é ignorado', resp.status_code == 302 and 'malicioso' not in resp.headers['Location'])

    outro = app.test_client()
    with outro.session_transaction() as sessao:
        sessao.update(user_id=2, law_firm_id=2, user_role='admin')
    check('outro escritório não vê a decisão (404)', outro.get(f'/process-panel/jurisprudencia/decisao/{d.id}').status_code == 404)
    check('outro escritório vê a base vazia', 'A base ainda está vazia' in outro.get('/process-panel/jurisprudencia/').get_data(as_text=True))


def test_geracao_no_painel():
    print('\n10. Geração no Painel de Processos (wizard, gravação, worker, detalhe)')
    from app.models import (JudicialProcess, JudicialProcessBenefit, JudicialLegalThesis,
                            JudicialProcessGeneratedDocument, JurisprudenceDecision as D)
    from app.blueprints import process_panel as pp
    processo = JudicialProcess(law_firm_id=1, user_id=1, process_number='5009876-12.2025.4.04.7205',
                               title='Cerâmica Sul', tribunal='TRF4', origin_unit='2ª Vara Federal de Blumenau')
    db.session.add(processo)
    db.session.flush()
    beneficio = JudicialProcessBenefit(process_id=processo.id, benefit_number='6012389500')
    beneficio.legal_theses = [db.session.get(JudicialLegalThesis, 1)]
    db.session.add(beneficio)
    db.session.commit()

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(user_id=1, law_firm_id=1, user_role='admin')
    base = f'/process-panel/{processo.id}/documentos-gerados'
    resp = cliente.post(f'{base}/preview-documentos',
                        json={'document_type': 'impugnacao_contestacao', 'selections': [f'{beneficio.id}:1']})
    dados = resp.get_json() or {}
    juris = dados.get('jurisprudencia') or []
    check('preview traz a jurisprudência da tese do benefício',
          resp.status_code == 200 and juris and juris[0]['tese'] == 'TRAJETO - B91', dados.get('jurisprudencia_erro'))
    resp = cliente.post(f'{base}/preview-documentos',
                        json={'document_type': 'manifestacao', 'selections': [f'{beneficio.id}:1']})
    check('fora da impugnação não traz jurisprudência', resp.get_json().get('jurisprudencia') is None)

    novo = [r.rule for r in app.url_map.iter_rules() if r.endpoint == 'process_panel.generated_document_new'][0]
    resp = cliente.get(novo.replace('<int:process_id>', str(processo.id)))
    check('wizard abre com o bloco de jurisprudência',
          resp.status_code == 200 and 'docs-jurisprudence-block' in resp.get_data(as_text=True), resp.status_code)

    disparos = []
    original = pp._spawn_generated_document_generation
    pp._spawn_generated_document_generation = lambda *a, **k: disparos.append(a)
    try:
        escolhida = juris[0]['decisoes'][0]['id']
        resp = cliente.post(f'{base}/gerar', data={
            'document_type': 'impugnacao_contestacao', 'selections[]': [f'{beneficio.id}:1'],
            'documents_confirmed': '1', 'confirmed_jurisprudence[]': [f'{escolhida}:1', 'lixo'],
        })
    finally:
        pp._spawn_generated_document_generation = original
    doc = JudicialProcessGeneratedDocument.query.filter_by(process_id=processo.id).first()
    confirmado = doc.current_version.confirmed_documents_json if doc else None
    check('a escolha é gravada na versão como pares',
          resp.status_code == 302 and confirmado and confirmado.get('jurisprudence') == [{'decision_id': escolhida, 'thesis_id': 1}],
          confirmado)

    capturado = {}

    class _AgenteFalso:
        def __init__(self, model_name=None):
            pass

        def dispatch(self, *args, **kwargs):
            capturado.update(kwargs)
            return {}, 'texto gerado'
    processo_id, doc_id, versao_id = processo.id, doc.id, doc.current_version_id
    originais = (pp.AgentGeneratedDocument, pp._resolve_latest_contestation_pdf_path,
                 pp._resolve_latest_contestation_summary_payload)
    # A geração exige a contestação do processo — fora do escopo deste teste.
    pp.AgentGeneratedDocument = _AgenteFalso
    pp._resolve_latest_contestation_pdf_path = lambda processo: None
    pp._resolve_latest_contestation_summary_payload = lambda processo, firma: None
    try:
        pp._run_generated_document_generation(app, 1, processo_id, doc_id, versao_id, None, 'fake')
    finally:
        (pp.AgentGeneratedDocument, pp._resolve_latest_contestation_pdf_path,
         pp._resolve_latest_contestation_summary_payload) = originais
    from app.models import JudicialProcessGeneratedDocumentVersion as V
    versao = db.session.get(V, versao_id)
    bloco = capturado.get('jurisprudence_block') or ''
    decisao = db.session.get(D, escolhida)
    check('o worker entrega o bloco ao agente, com a citação da decisão escolhida',
          '[Tese: TRAJETO - B91]' in bloco and (decisao.processo or '')[:15] in bloco,
          f'{versao.generation_status} {versao.error_message} {bloco[:200]}')

    resp = cliente.get(f'{base}/{doc_id}')
    check('detalhe lista a jurisprudência citada',
          resp.status_code == 200 and 'Jurisprudência citada' in resp.get_data(as_text=True), resp.status_code)


def test_planilha_real():
    print('\n11. Planilha real do escritório (se estiver no diretório)')
    if not os.path.exists(PLANILHA_REAL):
        check('planilha real ausente — pulado', True)
        return
    from app.models import LawFirm
    from app.services import jurisprudence_import_service as imp
    from app.services import jurisprudence_search_service as s
    db.session.add(LawFirm(id=3, name='Real', cnpj='00000000000353'))
    db.session.commit()
    c = imp.conferir(3, PLANILHA_REAL)
    check('515 lidas, 6 repetidas na própria planilha', (c['lidas'], c['repetidas_na_planilha']) == (515, 6),
          (c['lidas'], c['repetidas_na_planilha']))
    check('155 textos de tribunal → 8 siglas', (c['padronizacao']['tribunais_brutos'], len(c['padronizacao']['siglas'])) == (155, 8))
    check('251 grafias de tese → 219 teses', (c['padronizacao']['teses_brutas'], c['padronizacao']['teses']) == (251, 219))
    r = imp.importar(3, PLANILHA_REAL)
    check('importa 509', r['criadas'] == 509, r)
    from werkzeug.datastructures import MultiDict
    res = s.buscar(3, s.Filtros.do_request(MultiDict({'q': 'trajeto', 'tribunal': 'TRF4'})))
    check('trajeto no TRF4: 198 decisões', res['total'] == 198, res['total'])


def main():
    print('=' * 60)
    print('BASE DE JURISPRUDÊNCIA')
    print('=' * 60)
    test_normalizacao()
    with app.app_context():
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        _preparar_base()
        test_importacao()
        test_teses()
        test_busca()
        test_correcao_manual()
        test_agente()
        test_fila()
        test_geracao()
    test_rotas_ctx()
    with app.app_context():
        test_geracao_no_painel()
        test_planilha_real()
    print('\n' + '=' * 60)
    if FALHAS:
        print(f'❌ {len(FALHAS)} falha(s): {", ".join(FALHAS)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


def test_rotas_ctx():
    with app.app_context():
        test_rotas()


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        import shutil
        for sobra in (DB_FILE,):
            if os.path.exists(sobra):
                os.remove(sobra)
        shutil.rmtree(PASTA_TMP, ignore_errors=True)
