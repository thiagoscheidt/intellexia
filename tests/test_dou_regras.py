#!/usr/bin/env python3
"""
Testes das regras de palavra-chave do Diário Oficial.

Cada verificação tranca uma descoberta da medição, não uma linha de código.

    uv run python tests/test_dou_regras.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import dou_rule_service as regras

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _casa(texto, termo, modo=regras.MODO_FRASE):
    return regras.casa_texto(regras.normalizar(texto),
                             regras.compilar(termo, modo))


def test_fronteira_de_palavra():
    """O caso que decidiu o motor: o índice acha 92 "FAP", 80 são FAPESP."""
    print('\n1. Fronteira de palavra')

    check('FAP casa "o FAP da empresa"', _casa('o FAP da empresa caiu', 'FAP'))
    check('FAP casa com pontuação', _casa('trata do FAP.', 'FAP'))
    check('FAP NÃO casa FAPESP', not _casa('convênio com a FAPESP', 'FAP'))
    check('FAP NÃO casa FAPED', not _casa('edital FAPED 2026', 'FAP'))
    check('FAP NÃO casa FAPEMIG', not _casa('a FAPEMIG informa', 'FAP'))
    check('FAP NÃO casa UNIFAP', not _casa('a UNIFAP publica', 'FAP'))


def test_acento_e_caixa():
    print('\n2. Acento e caixa são indiferentes')

    check('ACIDENTÁRIO casa acidentario',
          _casa('FATOR ACIDENTÁRIO DE PREVENÇÃO', 'fator acidentario de prevencao'))
    check('acidentario casa ACIDENTÁRIO',
          _casa('fator acidentario de prevencao', 'Fator Acidentário de Prevenção'))


def test_modos():
    """Não existe modo OU — é ele o 748 contra 7."""
    print('\n3. Modos de casamento')

    texto = 'o fator de risco e a prevenção de acidentes'
    check('frase exata NÃO casa palavras espalhadas',
          not _casa(texto, 'Fator Acidentário de Prevenção'))
    check('todas as palavras NÃO casa se faltar uma',
          not _casa(texto, 'fator acidentário prevenção', regras.MODO_PALAVRAS))
    check('todas as palavras casa espalhado',
          _casa('o fator e a prevenção', 'fator prevenção', regras.MODO_PALAVRAS))
    check('frase exata casa a sequência',
          _casa('trata do Fator Acidentário de Prevenção hoje',
                'Fator Acidentário de Prevenção'))
    check('termo vazio não casa nada', regras.compilar('', regras.MODO_FRASE) == [])


def test_sonda():
    """A sonda é o pedaço sem acento que vira LIKE — tem de estar no texto."""
    print('\n4. Sonda da peneira SQL')

    check('licitação → licita', regras.sonda('licitação') == 'licita',
          repr(regras.sonda('licitação')))
    check('Fator Acidentário de Prevenção → "fator acident"',
          regras.sonda('Fator Acidentário de Prevenção') == 'fator acident',
          repr(regras.sonda('Fator Acidentário de Prevenção')))
    check('FAP → fap', regras.sonda('FAP') == 'fap')
    check('curto demais não vira sonda', regras.sonda('ré') is None)
    check('termo vazio não vira sonda', regras.sonda('') is None)
    check('a sonda está literalmente no termo, em minúsculas',
          all(regras.sonda(t) in t.lower()
              for t in ('licitação', 'FAP', 'aposentadoria',
                        'Fator Acidentário de Prevenção')))


def test_modelo():
    """As colunas de que a tela e o filtro dependem, sem abrir a filha."""
    print('\n5. Modelo')

    from app.models import DouAlertRule, DouAlertRuleHit, DouClientAlert

    colunas = {c.name for c in DouAlertRule.__table__.columns}
    check('regra tem law_firm_id (a regra é do escritório)',
          'law_firm_id' in colunas)
    check('regra tem dono registrado', 'created_by_id' in colunas)
    check('regra tem last_match_at', 'last_match_at' in colunas)

    unicas = [tuple(sorted(c.columns.keys()))
              for c in DouAlertRuleHit.__table__.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
    check('hit é único por (alerta, regra)',
          ('alert_id', 'rule_id') in unicas, str(unicas))

    check('alerta tem tem_regra',
          'tem_regra' in {c.name for c in DouClientAlert.__table__.columns})
    check('match_type é nullable (alerta só de regra não tem CNPJ)',
          DouClientAlert.__table__.columns['match_type'].nullable)

    r = DouAlertRule(nome='x', termo='FAP', modo='frase', secoes='DO1,DO3')
    check('lista_secoes separa o CSV', r.lista_secoes == ['DO1', 'DO3'],
          str(r.lista_secoes))
    check('sem seções, lista vazia',
          DouAlertRule(nome='x', termo='FAP').lista_secoes == [])
    check('resumo_do_casamento descreve a regra',
          'FAP' in r.resumo_do_casamento and 'DO1' in r.resumo_do_casamento,
          r.resumo_do_casamento)


class FakeMateria:
    """Matéria sem banco — o casamento não precisa de ORM."""

    def __init__(self, id, texto='', identifica='', ementa='',
                 pub_name='DO1', orgao_hierarquia=''):
        self.id, self.texto, self.identifica = id, texto, identifica
        self.ementa, self.pub_name = ementa, pub_name
        self.orgao_hierarquia = orgao_hierarquia


class FakeRegra:
    def __init__(self, id, termo=None, modo=regras.MODO_FRASE,
                 secoes=None, orgao=None):
        self.id, self.termo, self.modo = id, termo, modo
        self.lista_secoes = secoes or []
        self.orgao_raiz = orgao


def test_casar():
    print('\n6. Colheita')

    materias = [
        FakeMateria(1, texto='decisão sobre o FAP da empresa', pub_name='DO1',
                    orgao_hierarquia='Ministério da Previdência Social/CRPS'),
        FakeMateria(2, texto='convênio com a FAPESP', pub_name='DO3',
                    orgao_hierarquia='Ministério da Educação'),
        FakeMateria(3, texto='ata da reunião', identifica='PORTARIA CRPS Nº 9',
                    pub_name='DO1',
                    orgao_hierarquia='Ministério da Previdência Social'),
    ]

    achados = regras.casar([FakeRegra(10, termo='FAP')], materias)
    check('casa só a matéria certa', achados == {1: [10]}, str(achados))

    achados = regras.casar([FakeRegra(11, termo='CRPS')], materias)
    check('o corpus inclui identifica', achados == {3: [11]}, str(achados))

    achados = regras.casar([FakeRegra(12, termo='FAP', secoes=['DO3'])], materias)
    check('seção recorta', achados == {}, str(achados))

    achados = regras.casar(
        [FakeRegra(13, orgao='Ministério da Previdência Social')], materias)
    check('regra só de órgão casa pela raiz, não pela hierarquia inteira',
          achados == {1: [13], 3: [13]}, str(achados))

    achados = regras.casar([FakeRegra(14, termo='FAP'),
                            FakeRegra(15, termo='decisão')], materias)
    check('duas regras na mesma matéria dão uma entrada com dois ids',
          achados == {1: [14, 15]}, str(achados))

    check('sem regra, nada casa', regras.casar([], materias) == {})
    check('sem matéria, nada casa',
          regras.casar([FakeRegra(16, termo='FAP')], []) == {})


def main():
    print('=' * 60)
    print('TESTES DAS REGRAS DE PALAVRA-CHAVE DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_fronteira_de_palavra()
    test_acento_e_caixa()
    test_modos()
    test_sonda()
    test_modelo()
    test_casar()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
