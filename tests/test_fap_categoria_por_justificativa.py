#!/usr/bin/env python3
"""
Categoria FAP por justificativa, uma chamada por texto distinto (E04 da R09).

O classificador rodava por DECISÃO (119.906 na homologação, US$ 326) e, sem
justificativa, usava o parecer do analista. A categoria é o argumento da
empresa: agora sai da justificativa do benefício — a da 1ª instância, a da 2ª
só se não houver a da 1ª, nunca o parecer — e cada texto distinto é
classificado uma vez (30.905 na homologação, ~US$ 84).

Sem IA: o classificador é trocado por um dublê que registra o que recebeu.
Escritório descartável.

    uv run python tests/test_fap_categoria_por_justificativa.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, Benefit
from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService as Svc

TEST_CNPJ = '00000000001799'
OUTRO_CNPJ = '00000000001899'

_falhas = []


def check(nome, cond, detalhe=''):
    print(('  ✅ ' if cond else '  ❌ ') + nome + ((' — ' + str(detalhe)) if detalhe and not cond else ''))
    if not cond:
        _falhas.append(nome)


class ClassificadorFalso:
    def __init__(self):
        self.textos = []

    def classify(self, text, law_firm_id=None, **kw):
        self.textos.append(text)
        if 'TRAJETO' in text.upper():
            return {'topics': ['ACIDENTE DE TRAJETO']}
        if 'NTEP' in text.upper():
            return {'topics': ['NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO']}
        return {'topics': []}  # confiança baixa → "OUTROS ARGUMENTOS"


def _firm(cnpj, nome):
    firm = LawFirm.query.filter_by(cnpj=cnpj).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name=nome, cnpj=cnpj)
    db.session.add(firm)
    db.session.flush()
    return firm


def cleanup(firm):
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def setup():
    firm = _firm(TEST_CNPJ, 'Escritório Teste Categoria A')
    outra = _firm(OUTRO_CNPJ, 'Escritório Teste Categoria B')
    trajeto = 'Acidente de trajeto comprovado pela CAT 2019.'
    b = lambda n, **kw: Benefit(law_firm_id=firm.id, benefit_number=n, **kw)
    db.session.add_all([
        # três benefícios com o mesmo texto → uma chamada
        b('7000000001', first_instance_justification=trajeto),
        b('7000000002', first_instance_justification=trajeto + '  '),
        b('7000000003', first_instance_justification=trajeto, second_instance_justification='Recurso: NTEP pendente.'),
        # só 2ª instância → usa a 2ª
        b('7000000004', second_instance_justification='Contestamos o NTEP, pendente de julgamento.'),
        # sem justificativa, só parecer → não classifica (o parecer não serve)
        b('7000000005', first_instance_opinion='Parecer: indeferido, acidente de trajeto não comprovado.'),
        # texto sem tópico claro → OUTROS ARGUMENTOS
        b('7000000006', first_instance_justification='O índice é desproporcional.'),
        # já classificado → pulado sem --forcar
        b('7000000007', first_instance_justification='Outro texto qualquer.',
          fap_contestation_topics_json=json.dumps(['PRÉ-FAP']), fap_contestation_topic='PRÉ-FAP'),
        Benefit(law_firm_id=outra.id, benefit_number='7000000008', first_instance_justification=trajeto),
    ])
    db.session.commit()
    return firm, outra


def topicos(firm_id, numero):
    # O serviço grava no próprio contexto; sem encerrar a transação deste lado, o
    # REPEATABLE READ do MySQL mostraria a foto de antes da gravação.
    db.session.rollback()
    ben = Benefit.query.filter_by(law_firm_id=firm_id, benefit_number=numero).one()
    return json.loads(ben.fap_contestation_topics_json) if ben.fap_contestation_topics_json else None


def main():
    with app.app_context():
        firm, outra = setup()
        try:
            print('\n1. Simulação: classifica, não grava')
            svc = Svc(app)
            svc.classifier_agent = falso = ClassificadorFalso()
            r = svc.classify_benefits_by_justification(firm.id, parallel_workers=2)
            check('uma chamada por texto distinto (5 benefícios com justificativa, 3 textos)',
                  len(falso.textos) == 3 and r['textos'] == 3, str((len(falso.textos), r)))
            check('benefícios elegíveis contados', r['beneficios'] == 5, str(r))
            check('sem justificativa fica de fora (o parecer nunca é usado)',
                  r['sem_justificativa'] == 1 and not any('Parecer' in t for t in falso.textos), str(r))
            check('regra A: com as duas, usa a da 1ª instância',
                  not any('Recurso' in t for t in falso.textos))
            check('só com a 2ª instância, usa a 2ª', any('Contestamos o NTEP' in t for t in falso.textos))
            check('simulação não grava nada', topicos(firm.id, '7000000001') is None)

            print('\n2. --limite')
            svc.classifier_agent = falso = ClassificadorFalso()
            r = svc.classify_benefits_by_justification(firm.id, limite_textos=1)
            check('classifica só N textos', len(falso.textos) == 1 and r['textos'] == 1, str(r))

            print('\n3. Aplicando')
            svc.classifier_agent = falso = ClassificadorFalso()
            r = svc.classify_benefits_by_justification(firm.id, aplicar=True, parallel_workers=2)
            check('os três do mesmo texto recebem a mesma categoria',
                  all(topicos(firm.id, n) == ['ACIDENTE DE TRAJETO'] for n in ('7000000001', '7000000002', '7000000003')))
            check('só 2ª instância → nexo pendente',
                  topicos(firm.id, '7000000004') == ['NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO'])
            check('sem tópico claro → OUTROS ARGUMENTOS', topicos(firm.id, '7000000006') == ['OUTROS ARGUMENTOS'])
            db.session.rollback()
            check('campo legado acompanha o primeiro tópico',
                  Benefit.query.filter_by(law_firm_id=firm.id, benefit_number='7000000001').one().fap_contestation_topic
                  == 'ACIDENTE DE TRAJETO')
            check('sem justificativa continua sem categoria', topicos(firm.id, '7000000005') is None)
            check('já classificado não é tocado', topicos(firm.id, '7000000007') == ['PRÉ-FAP'])
            check('outro escritório não é tocado', topicos(outra.id, '7000000008') is None)
            check('gravados contados', r['gravados'] == 5, str(r))

            print('\n4. Rodar de novo não chama a IA; --forcar reclassifica')
            svc.classifier_agent = falso = ClassificadorFalso()
            r = svc.classify_benefits_by_justification(firm.id, aplicar=True)
            check('nada pendente, nenhuma chamada', len(falso.textos) == 0 and r['beneficios'] == 0, str(r))
            r = svc.classify_benefits_by_justification(firm.id, forcar=True)
            check('--forcar inclui os já classificados', r['beneficios'] == 6, str(r))

            print('\n5. Botão "Classificar" da tela segue a mesma regra')
            ben = Benefit.query.filter_by(law_firm_id=firm.id, benefit_number='7000000003').one()
            texto = Svc._build_benefit_classification_text(ben)
            check('usa a justificativa da 1ª instância', 'trajeto' in texto.lower() and 'Recurso' not in texto, texto[:120])
            ben5 = Benefit.query.filter_by(law_firm_id=firm.id, benefit_number='7000000005').one()
            check('sem justificativa não usa o parecer', Svc._build_benefit_classification_text(ben5) == '')
        finally:
            db.session.rollback()
            cleanup(firm)
            cleanup(outra)

    print('\n' + ('✅ Tudo verde' if not _falhas else f'❌ {len(_falhas)} falha(s): {_falhas}'))
    return 1 if _falhas else 0


if __name__ == '__main__':
    sys.exit(main())
