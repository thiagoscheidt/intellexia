"""
Catálogo de teses do escritório (PRC-23) — `catalogo_teses_service`.

1. Planilha: abas e colunas pelo título, e o que a carga recusa (inativa sem
   destino, destino inexistente ou inativo, equivalência para tese inativa,
   código fora do padrão).
2. Plano: simular não grava; cria o que falta, casa as existentes pelo nome,
   separa ligação nova, trocada e igual, e mostra o uso da tese a juntar fora
   da Jurisprudência.
3. Aplicar: catálogo, códigos, áreas e ligações; rodar de novo não muda nada;
   código já gravado não se troca.
4. Juntar: benefícios do Painel (sem duplicar o vínculo), análise da
   contestação (vale a do destino), peças-modelo, trechos, Qdrant, ligações da
   Jurisprudência, origem inativa apontando para o destino — e o outro
   escritório intocado. Repetir a junção é seguro.
5. Área: só as teses de FAP (ou sem área) entram no seletor do benefício.

Roda contra SQLite descartável e Qdrant em memória; não toca o Meilisearch.

    uv run python tests/test_catalogo_teses.py
"""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_catalogo_teses.db')
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

import openpyxl  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.http import models as rest  # noqa: E402

from app.models import (  # noqa: E402
    ImpugnacaoReferenceChunk, ImpugnacaoReferenceModel, JudicialLegalThesis, JudicialProcess,
    JudicialProcessBenefit, JudicialProcessBenefitThesisContestation, JurisprudenceThesis, LawFirm, User,
    judicial_process_benefit_legal_theses as beneficio_tese,
)
from app.services import catalogo_teses_service as svc  # noqa: E402
from app.services import jurisprudence_normalizer as norm  # noqa: E402

QDRANT = QdrantClient(':memory:')
svc.COLECAO_PECAS = 'impugnacao_test'
svc._cliente_qdrant = lambda: QDRANT
MEILI_ATUALIZADO = []
svc._atualizar_busca_das_pecas = lambda pontos, destino: MEILI_ATUALIZADO.append((sorted(pontos), destino))

FALHAS = []
PASTA = tempfile.mkdtemp(prefix='catalogo_teses_')


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


CAB_CATALOGO = ['Código', 'Tese do catálogo', 'Área', 'Descrição (quando usar)', 'Situação', 'Juntar com',
                'No IntellexIA?']
CAB_EQUIV = ['Tese original (como veio na decisão)', 'Decisões', 'Área', 'Tese do catálogo', 'Código']

CATALOGO = [
    ('T-FAP-001', 'TRAJETO - B91', 'FAP', 'Trajeto casa-trabalho.', 'Ativa', None),
    ('T-FAP-003', 'RESTABELECIMENTO DE BENEFICIO', 'FAP', 'Benefício que volta.', 'Ativa', None),
    ('T-FAP-010', '60 DIAS', 'FAP', None, 'Inativa', 'RESTABELECIMENTO DE BENEFICIO'),
    ('T-FAP-041', 'OUTRA EMPRESA', 'FAP', None, 'Inativa', 'BENEFICIO SEM VINCULO COM A EMPRESA'),
    ('T-FAP-052', 'BENEFICIO SEM VINCULO COM A EMPRESA', 'FAP', 'Segurado sem vínculo.', 'Ativa', None),
    ('T-PRO-001', 'PRESCRICAO QUINQUENAL', 'Processual', 'Prescrição.', 'Ativa', None),
    ('T-PRO-004', 'HONORARIOS E SUCUMBENCIA', 'Processual', 'Honorários.', 'Ativa', None),
]
EQUIVALENCIAS = [
    ('ACIDENTE DE TRAJETO', 280, 'FAP', 'TRAJETO - B91'),
    ('60 dias', 3, 'FAP', 'RESTABELECIMENTO DE BENEFICIO'),
    ('HONORÁRIOS ADVOCATÍCIOS', 2, 'Processual', 'HONORARIOS E SUCUMBENCIA'),
    ('GRAFIA QUE NAO ESTA NA BASE', 1, 'FAP', 'TRAJETO - B91'),
]


def planilha(nome, catalogo=CATALOGO, equivalencias=EQUIVALENCIAS):
    wb = openpyxl.Workbook()
    wb.active.title = 'INÍCIO'
    ws = wb.create_sheet('CATÁLOGO')
    ws.append(CAB_CATALOGO)
    for linha in catalogo:
        ws.append([*linha, 'Sim'])
    ws = wb.create_sheet('EQUIVALÊNCIAS')
    ws.append(CAB_EQUIV)
    for grafia, n, area, tese in equivalencias:
        ws.append([grafia, n, area, tese, None])
    caminho = os.path.join(PASTA, nome)
    wb.save(caminho)
    return caminho


def _tese(lf, nome, key, area=None):
    t = JudicialLegalThesis(law_firm_id=lf, key=key, name=nome, description='antiga', is_active=True, area=area)
    db.session.add(t)
    return t


def _tese_base(lf, nome, ligadas=()):
    t = JurisprudenceThesis(law_firm_id=lf, key=norm.chave(nome), name=nome,
                            status='ligada' if ligadas else 'pendente')
    t.catalog_theses = list(ligadas)
    db.session.add(t)
    return t


def preparar():
    db.create_all()
    db.session.add_all([LawFirm(id=1, name='Escritório', cnpj='00000000000191'),
                        LawFirm(id=2, name='Outro', cnpj='00000000000272'),
                        User(id=1, law_firm_id=1, name='Admin', email='a@b.c', password_hash='x', role='admin')])
    db.session.flush()
    t = {
        'trajeto': _tese(1, 'TRAJETO - B91', 'trajeto_b91'),
        'restab': _tese(1, 'RESTABELECIMENTO DE BENEFICIO', 'restabelecimento_de_beneficio'),
        '60': _tese(1, '60 DIAS', 'beneficio_60_dias'),
        'outra': _tese(1, 'OUTRA EMPRESA', 'outra_empresa'),
        'prescricao': _tese(1, 'PRESCRICAO QUINQUENAL', 'prescricao_quinquenal'),
        'fora': _tese(1, 'TESE SÓ DO SISTEMA', 'tese_so_do_sistema'),
        '60_outro': _tese(2, '60 DIAS', 'beneficio_60_dias'),
    }
    db.session.flush()

    processo = JudicialProcess(law_firm_id=1, user_id=1, process_number='50000000020264047200')
    db.session.add(processo)
    db.session.flush()
    b1 = JudicialProcessBenefit(process_id=processo.id, benefit_number='111')
    b2 = JudicialProcessBenefit(process_id=processo.id, benefit_number='222')
    db.session.add_all([b1, b2])
    db.session.flush()
    for beneficio, tese in ((b1, '60'), (b2, '60'), (b2, 'restab'), (b1, 'outra')):
        db.session.execute(beneficio_tese.insert().values(benefit_id=beneficio.id, legal_thesis_id=t[tese].id))
    for beneficio, tese, decisao in ((b1, '60', 'b1-60'), (b2, '60', 'b2-60'), (b2, 'restab', 'b2-restab')):
        db.session.add(JudicialProcessBenefitThesisContestation(
            law_firm_id=1, process_id=processo.id, process_benefit_id=beneficio.id,
            legal_thesis_id=t[tese].id, contestation_decision=decisao))

    peca = ImpugnacaoReferenceModel(law_firm_id=1, title='Peça', thesis_catalog_ids=[
        'beneficio_60_dias', 'restabelecimento_de_beneficio', 'trajeto_b91'])
    peca_outro = ImpugnacaoReferenceModel(law_firm_id=2, title='Peça outro', thesis_catalog_ids=['beneficio_60_dias'])
    db.session.add_all([peca, peca_outro])
    db.session.flush()
    ponto = str(uuid.uuid4())
    ponto_outro = str(uuid.uuid4())
    db.session.add_all([
        ImpugnacaoReferenceChunk(reference_id=peca.id, law_firm_id=1, thesis_catalog_id='beneficio_60_dias',
                                 qdrant_point_id=ponto),
        ImpugnacaoReferenceChunk(reference_id=peca_outro.id, law_firm_id=2, thesis_catalog_id='beneficio_60_dias',
                                 qdrant_point_id=ponto_outro),
    ])

    _tese_base(1, 'ACIDENTE DE TRAJETO', [t['trajeto']])
    _tese_base(1, '60 DIAS', [t['60']])
    _tese_base(1, 'HONORARIOS ADVOCATICIOS')
    _tese_base(1, 'TESE SOLTA DA BASE')
    db.session.commit()

    QDRANT.create_collection('impugnacao_test', vectors_config=rest.VectorParams(size=2, distance=rest.Distance.COSINE))
    QDRANT.upsert('impugnacao_test', points=[
        rest.PointStruct(id=ponto, vector=[1, 0], payload={
            'law_firm_id': 1, 'thesis_catalog_id': 'beneficio_60_dias',
            'thesis_catalog_ids': ['beneficio_60_dias', 'restabelecimento_de_beneficio'],
            'document_thesis_catalog_ids': ['beneficio_60_dias', 'restabelecimento_de_beneficio', 'trajeto_b91']}),
        rest.PointStruct(id=ponto_outro, vector=[0, 1], payload={
            'law_firm_id': 2, 'thesis_catalog_id': 'beneficio_60_dias',
            'thesis_catalog_ids': ['beneficio_60_dias'], 'document_thesis_catalog_ids': ['beneficio_60_dias']}),
    ])
    return {k: v.id for k, v in t.items()}, (b1.id, b2.id), (peca.id, peca_outro.id), (ponto, ponto_outro)


def test_planilha():
    print('\n1. Planilha')
    p = svc.ler_planilha(planilha('ok.xlsx'))
    check('lê catálogo e equivalências sem erro', not p.erros and len(p.teses) == 7 and len(p.equivalencias) == 4,
          p.erros)
    inativa = next(t for t in p.teses if t.nome == '60 DIAS')
    check('situação e "Juntar com" lidos', not inativa.ativa and inativa.juntar_com == 'RESTABELECIMENTO DE BENEFICIO')
    check('área normalizada para o valor do sistema',
          next(t for t in p.teses if t.codigo == 'T-PRO-001').area == 'Processual')

    ruim = svc.ler_planilha(planilha('ruim.xlsx', catalogo=[
        ('T-FAP-001', 'TRAJETO - B91', 'FAP', None, 'Ativa', None),
        ('T-FAP-002', 'SEM DESTINO', 'FAP', None, 'Inativa', None),
        ('T-FAP-003', 'DESTINO SUMIU', 'FAP', None, 'Inativa', 'NAO EXISTE'),
        ('T-FAP-004', 'DESTINO INATIVO', 'FAP', None, 'Inativa', 'SEM DESTINO'),
        ('TFAP5', 'CODIGO TORTO', 'FAP', None, 'Ativa', None),
        ('T-FAP-001', 'CODIGO REPETIDO', 'FAP', None, 'Ativa', None),
    ], equivalencias=[('X', 1, 'FAP', 'SEM DESTINO'), ('Y', 1, 'FAP', 'NAO EXISTE')]))
    texto = ' | '.join(ruim.erros)
    for pedaco, rotulo in (('sem dizer com qual juntar', 'inativa sem destino'),
                           ('"NAO EXISTE", que não está no catálogo', 'destino inexistente'),
                           ('que também está inativa', 'destino inativo'),
                           ('fora do padrão', 'código fora do padrão'),
                           ('repetido', 'código repetido'),
                           ('"SEM DESTINO" está inativa', 'equivalência para tese inativa'),
                           ('tese "NAO EXISTE" não está no catálogo', 'equivalência para tese inexistente')):
        check(f'recusa {rotulo}', pedaco in texto, texto if pedaco not in texto else '')


def test_plano_e_aplicacao(ids):
    print('\n2. Plano (simulação)')
    p = svc.ler_planilha(planilha('ok.xlsx'))
    antes = JudicialLegalThesis.query.count()
    plano = svc.planejar(1, p)
    check('simular não grava', JudicialLegalThesis.query.count() == antes)
    check('cria só as que faltam', sorted(c['nome'] for c in plano['criar']) ==
          ['BENEFICIO SEM VINCULO COM A EMPRESA', 'HONORARIOS E SUCUMBENCIA'], plano['criar'])
    prescricao = next(a for a in plano['atualizar'] if a['nome'] == 'PRESCRICAO QUINQUENAL')
    check('existente ganha código e área', prescricao['mudancas'].get('code') == 'T-PRO-001'
          and prescricao['mudancas'].get('area') == 'Processual', prescricao)
    check('descrição existente não é sobrescrita sem --descricoes', 'description' not in prescricao['mudancas'])
    plano_desc = svc.planejar(1, p, descricoes=True)
    check('--descricoes sobrescreve', next(a for a in plano_desc['atualizar']
                                           if a['nome'] == 'PRESCRICAO QUINQUENAL')['mudancas'].get('description')
          == 'Prescrição.')
    juntar = {j['origem']: j for j in plano['juntar']}
    check('junta as duas inativas', set(juntar) == {'60 DIAS', 'OUTRA EMPRESA'}, list(juntar))
    check('uso da tese a juntar fora da Jurisprudência', juntar['60 DIAS']['uso'] == {
        'beneficios': 2, 'contestacoes': 2, 'pecas': 1, 'trechos': 1, 'teses_da_base': 1}, juntar['60 DIAS']['uso'])
    check('ligação: nova, trocada e igual separadas',
          [i['grafia'] for i in plano['ligar']] == ['HONORÁRIOS ADVOCATÍCIOS']
          and [i['grafia'] for i in plano['trocar_ligacao']] == ['60 dias']
          and plano['ligacao_igual'] == 1, (plano['ligar'], plano['trocar_ligacao'], plano['ligacao_igual']))
    check('grafia fora da base é listada', [g['grafia'] for g in plano['grafia_fora_da_base']] ==
          ['GRAFIA QUE NAO ESTA NA BASE'])
    check('tese da base que a planilha não cobre é listada',
          [t['nome'] for t in plano['teses_da_base_sem_equivalencia']] == ['TESE SOLTA DA BASE'])
    check('tese do sistema fora da planilha é listada (e não mexida)',
          [t['nome'] for t in plano['fora_da_planilha']] == ['TESE SÓ DO SISTEMA'])

    print('\n3. Aplicar sem juntar')
    resultado = svc.executar(plano)
    check('grava criadas, atualizadas e ligadas', (resultado['criadas'], resultado['ligadas']) == (2, 2), resultado)
    honorarios = JudicialLegalThesis.query.filter_by(law_firm_id=1, code='T-PRO-004').one()
    check('tese nova com código, área e descrição da planilha',
          (honorarios.name, honorarios.area, honorarios.description) ==
          ('HONORARIOS E SUCUMBENCIA', 'Processual', 'Honorários.'))
    base_honorarios = JurisprudenceThesis.query.filter_by(law_firm_id=1, key='HONORARIOS ADVOCATICIOS').one()
    check('grafia ligada à tese nova', [c.id for c in base_honorarios.catalog_theses] == [honorarios.id]
          and base_honorarios.status == 'ligada')
    base_60 = JurisprudenceThesis.query.filter_by(law_firm_id=1, key='60 DIAS').one()
    check('ligação trocada para a da planilha', [c.id for c in base_60.catalog_theses] == [ids['restab']])
    check('sem --juntar a inativa continua ativa', db.session.get(JudicialLegalThesis, ids['60']).is_active)

    de_novo = svc.planejar(1, p)
    check('rodar de novo não muda nada', not de_novo['criar'] and not de_novo['atualizar']
          and not de_novo['ligar'] and not de_novo['trocar_ligacao'] and de_novo['ligacao_igual'] == 3,
          (de_novo['criar'], de_novo['atualizar'], de_novo['ligar'], de_novo['trocar_ligacao']))

    trocado = svc.ler_planilha(planilha('codigo_trocado.xlsx', catalogo=[
        ('T-FAP-099', 'TRAJETO - B91', 'FAP', None, 'Ativa', None)], equivalencias=[]))
    check('código já gravado não se troca',
          any('Código não se troca' in e for e in svc.planejar(1, trocado)['erros']))
    return p


def test_juntar(ids, beneficios, pecas, pontos, p):
    print('\n4. Juntar')
    plano = svc.planejar(1, p)
    resultado = svc.executar(plano, juntar=True)
    check('junta as duas', sorted(j['origem'] for j in resultado['juntadas']) == ['60 DIAS', 'OUTRA EMPRESA']
          and not resultado['avisos'], resultado)
    b1, b2 = beneficios
    vinculos = {(r.benefit_id, r.legal_thesis_id) for r in db.session.execute(beneficio_tese.select()).all()}
    sem_vinculo = JudicialLegalThesis.query.filter_by(law_firm_id=1, code='T-FAP-052').one()
    check('benefícios vão para o destino sem duplicar o vínculo',
          vinculos == {(b1, ids['restab']), (b2, ids['restab']), (b1, sem_vinculo.id)}, vinculos)
    analises = {(a.process_benefit_id, a.legal_thesis_id): a.contestation_decision
                for a in JudicialProcessBenefitThesisContestation.query.all()}
    check('análise da contestação: movida, e a do destino prevalece',
          analises == {(b1, ids['restab']): 'b1-60', (b2, ids['restab']): 'b2-restab'}, analises)
    peca, peca_outro = (db.session.get(ImpugnacaoReferenceModel, i) for i in pecas)
    check('peça-modelo troca a chave sem repetir', peca.thesis_catalog_ids ==
          ['restabelecimento_de_beneficio', 'trajeto_b91'], peca.thesis_catalog_ids)
    trechos = {c.law_firm_id: c.thesis_catalog_id for c in ImpugnacaoReferenceChunk.query.all()}
    check('trecho troca a chave principal', trechos[1] == 'restabelecimento_de_beneficio', trechos)
    p1, p2 = (QDRANT.retrieve('impugnacao_test', ids=[pid])[0].payload for pid in pontos)
    check('Qdrant: payload trocado', p1['thesis_catalog_id'] == 'restabelecimento_de_beneficio'
          and p1['thesis_catalog_ids'] == ['restabelecimento_de_beneficio']
          and p1['document_thesis_catalog_ids'] == ['restabelecimento_de_beneficio', 'trajeto_b91'], p1)
    check('busca das peças recebe os trechos do destino',
          (sorted([pontos[0].replace('-', '')]), 'restabelecimento_de_beneficio') in MEILI_ATUALIZADO, MEILI_ATUALIZADO)
    origem = db.session.get(JudicialLegalThesis, ids['60'])
    check('origem inativa apontando para o destino', not origem.is_active and origem.merged_into_id == ids['restab'])
    check('outro escritório intocado', db.session.get(JudicialLegalThesis, ids['60_outro']).is_active
          and peca_outro.thesis_catalog_ids == ['beneficio_60_dias'] and trechos[2] == 'beneficio_60_dias'
          and p2['thesis_catalog_id'] == 'beneficio_60_dias')

    check('rodar de novo não acha nada a juntar', svc.planejar(1, p)['juntar'] == [])
    check('repetir a junção à mão é seguro',
          svc.juntar_tese(1, ids['60'], ids['restab']) == {'beneficios': 0, 'contestacoes': 0, 'pecas': 0,
                                                            'trechos': 0, 'teses_da_base': 0})
    try:
        svc.juntar_tese(1, ids['restab'], ids['60'])
        check('recusa juntar numa tese inativa', False)
    except ValueError:
        check('recusa juntar numa tese inativa', True)


def test_area():
    print('\n5. Área')
    nomes = {t.name for t in JudicialLegalThesis.query.filter(
        JudicialLegalThesis.law_firm_id == 1, JudicialLegalThesis.is_active.is_(True),
        JudicialLegalThesis.filtro_de_beneficio()).all()}
    check('seletor do benefício: FAP e sem área entram', {'TRAJETO - B91', 'TESE SÓ DO SISTEMA'} <= nomes, nomes)
    check('seletor do benefício: processual fica de fora',
          not ({'PRESCRICAO QUINQUENAL', 'HONORARIOS E SUCUMBENCIA'} & nomes), nomes)


if __name__ == '__main__':
    with app.app_context():
        ids, beneficios, pecas, pontos = preparar()
        test_planilha()
        p = test_plano_e_aplicacao(ids)
        test_juntar(ids, beneficios, pecas, pontos, p)
        test_area()
        db.session.remove()
    os.remove(DB_FILE)
    print(f"\n{'✅ Tudo certo' if not FALHAS else f'❌ {len(FALHAS)} falha(s): ' + '; '.join(FALHAS)}")
    sys.exit(1 if FALHAS else 0)
