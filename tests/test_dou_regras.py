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


def main():
    print('=' * 60)
    print('TESTES DAS REGRAS DE PALAVRA-CHAVE DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_fronteira_de_palavra()
    test_acento_e_caixa()
    test_modos()
    test_sonda()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
