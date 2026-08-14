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


def test_peneira_e_superconjunto():
    """A propriedade que autoriza a otimização — sem ela o teste mente.

    O LIKE roda no banco e a regex decide; se a peneira deixar de fora algo que
    a regex casaria, o "testar antes de salvar" mostraria menos do que vai
    chegar. O caso perigoso é o termo que só aparece em `identifica`: peneirar
    apenas `texto` perderia a matéria inteira.
    """
    print('\n7. A peneira SQL é superconjunto')

    from main import app
    from app.models import DouArticle, db

    with app.app_context():
        todos = db.session.query(DouArticle.id, DouArticle.identifica,
                                 DouArticle.ementa, DouArticle.texto).all()
        if not todos:
            check('acervo vazio — nada a conferir', True)
            return
        for termo in ('FAP', 'Fator Acidentário de Prevenção', 'aposentadoria',
                      'PORTARIA'):
            if not regras.sonda(termo):
                continue
            peneirados = {r.id for r in
                          regras.filtrar_candidatas(termo, [], None).all()}
            padroes = regras.compilar(termo, regras.MODO_FRASE)
            exatos = {m.id for m in todos
                      if regras.casa_texto(regras.normalizar(regras.corpus(m)),
                                           padroes)}
            escaparam = exatos - peneirados
            check(f'peneira de {termo!r} contém todos os casamentos',
                  not escaparam,
                  f'{len(escaparam)} de {len(exatos)} escapariam')


def test_janela_do_teste():
    """A janela é de edições publicadas, não de dias de calendário.

    Com o acervo indo até 11/08 e "hoje" em 14/08, a janela de 7 dias corridos
    pegava duas datas — uma delas com 356 matérias em vez das ~3.000 de sempre.
    "licitação" achava 768, dividia por 7 e anunciava 110/dia quando o real é
    660. Fim de semana e feriado produzem o mesmo buraco toda semana.
    """
    print('\n7b. Janela do teste')

    from main import app
    from app.models import DouArticle, db

    with app.app_context():
        datas = regras.datas_do_teste(7)
        if not datas:
            check('sem acervo, o teste diz que é do acervo',
                  regras.testar('FAP')['nivel'] == regras.NIVEL_SEM_ACERVO)
            return

        check('a janela só traz data com edição', len(datas) <= 7 and all(datas))
        check('vem da mais nova para a mais velha',
              datas == sorted(datas, reverse=True), str(datas))

        # O denominador tem de ser o número de edições, não o de dias corridos.
        resultado = regras.testar('licitação', dias=7)
        materias_na_janela = (db.session.query(DouArticle.id)
                              .filter(DouArticle.pub_date.in_(datas)).count())
        check('o denominador é o nº de edições da janela',
              resultado['dias'] == len(datas),
              f"dias={resultado['dias']} datas={len(datas)}")
        check('por_dia bate com total/edições',
              abs(resultado['por_dia']
                  - round(resultado['total'] / len(datas), 1)) < 0.05,
              str(resultado))
        check('a janela cobre o acervo, não um pedaço dele',
              materias_na_janela > 0)


def test_trecho_do_casamento():
    """O recorte do teste tem de mostrar onde casou, não o começo da matéria."""
    print('\n7c. Trecho do casamento')

    from app.services.dou_search_service import MARCA_INI, MARCA_FIM

    class M:
        identifica = 'PORTARIA Nº 1'
        ementa = ''
        texto = ('Considerando o disposto no artigo primeiro. ' * 12
                 + 'Trata do Fator Acidentário de Prevenção da empresa. '
                 + 'E segue por mais um bom tanto de texto. ' * 12)

    padroes = regras.compilar('Fator Acidentário de Prevenção', regras.MODO_FRASE)
    t = regras.trecho_do_casamento(M(), padroes, janela=180)
    check('recorta em volta do achado, não do começo',
          'Fator Acidentário de Prevenção' in t and not t.startswith('Considerando o disposto no artigo primeiro. Considerando'),
          repr(t[:80]))
    check('marca o termo', MARCA_INI in t and MARCA_FIM in t, repr(t[:120]))
    check('cabe na janela', len(t) < 320, str(len(t)))

    # O offset vem do texto normalizado; sem o mapa de índices, um caractere de
    # compatibilidade antes do achado (º, ﬁ) desloca o recorte.
    class MCompat:
        identifica = ''
        ementa = ''
        texto = 'O 1º ofício e a ﬁcha do contribuinte. Trata do FAP da empresa aqui.'

    t2 = regras.trecho_do_casamento(MCompat(), regras.compilar('FAP'), janela=180)
    check('o mapa de índices mantém o recorte alinhado',
          f'{MARCA_INI}FAP{MARCA_FIM}' in t2, repr(t2))

    # Acento: o termo casa sem acento, mas o recorte devolve o texto original.
    class MAcento:
        identifica = ''
        ementa = ''
        texto = 'Trata da CONTRIBUIÇÃO previdenciária da empresa.'

    t3 = regras.trecho_do_casamento(MAcento(), regras.compilar('contribuicao'),
                                    janela=180)
    check('a marca preserva a grafia original, com acento',
          f'{MARCA_INI}CONTRIBUIÇÃO{MARCA_FIM}' in t3, repr(t3))

    # Regra sem termo (só órgão): mostra o começo, sem prometer destaque — e
    # sem repetir o `identifica`, que já é a linha de cima do exemplo.
    t4 = regras.trecho_do_casamento(M(), [], janela=120)
    check('sem termo, mostra o início da matéria',
          t4.startswith('Considerando o disposto'), repr(t4[:60]))
    check('e não repete o identifica da linha de cima',
          'PORTARIA Nº 1' not in t4, repr(t4[:60]))
    check('e sem marca nenhuma', MARCA_INI not in t4)

    # Matéria sem texto não pode quebrar o teste da regra.
    class MVazia:
        identifica = None
        ementa = None
        texto = None

    check('matéria sem texto devolve None',
          regras.trecho_do_casamento(MVazia(), padroes) is None)


def test_veredito():
    """Os cortes são ancorados na carteira real (~6 alertas/dia), não chutados."""
    print('\n8. Veredito de volume')

    check('zero é vazio', regras.nivel(0) == regras.NIVEL_VAZIO)
    check('1/dia é ok', regras.nivel(1) == regras.NIVEL_OK)
    check('5/dia ainda é ok', regras.nivel(5) == regras.NIVEL_OK)
    check('6/dia é alto', regras.nivel(6) == regras.NIVEL_ALTO)
    check('20/dia ainda é alto', regras.nivel(20) == regras.NIVEL_ALTO)
    check('660/dia é ruidoso (o caso "licitação")',
          regras.nivel(660) == regras.NIVEL_RUIDOSO)


def test_validacao():
    print('\n9. Validação da regra')

    check('sem nome é recusada',
          regras.validar('', 'FAP', regras.MODO_FRASE, [], None))
    check('sem termo e sem órgão é recusada',
          regras.validar('x', '', regras.MODO_FRASE, ['DO1'], None))
    check('só órgão é aceita',
          not regras.validar('x', '', regras.MODO_FRASE, [],
                             'Ministério da Previdência Social'))
    check('só termo é aceita',
          not regras.validar('x', 'FAP', regras.MODO_FRASE, [], None))
    check('modo inválido é recusado',
          regras.validar('x', 'FAP', 'ou', [], None))
    check('termo só de pontuação é recusado',
          regras.validar('x', '...', regras.MODO_FRASE, [], None))


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
    test_peneira_e_superconjunto()
    test_janela_do_teste()
    test_trecho_do_casamento()
    test_veredito()
    test_validacao()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
