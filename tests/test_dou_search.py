#!/usr/bin/env python3
"""
Testes da busca do DOU (app/services/dou_search_service.py).

As partes 1 a 5 são função pura: sem rede, sem banco, sem Flask.

    uv run python tests/test_dou_search.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import dou_search_service as busca

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_so_digitos():
    print('\n1. Normalização para dígitos')
    check('tira pontuação do CNPJ',
          busca.so_digitos('19.630.496/0001-05') == '19630496000105',
          busca.so_digitos('19.630.496/0001-05'))
    check('tira pontuação do processo',
          busca.so_digitos('15414.630210/2026-80') == '15414630210202680',
          busca.so_digitos('15414.630210/2026-80'))
    check('None vira string vazia', busca.so_digitos(None) == '')
    check('texto sem dígito vira vazio', busca.so_digitos('Previdência') == '')


def test_extrair_cnpjs():
    print('\n2. Extração de CNPJ do texto')
    texto = ('Autoriza o funcionamento de BESSO RE BRASIL CORRETORA LTDA, '
             'CNPJ nº 19.630.496/0001-05, com sede na cidade do Rio.')
    check('acha o CNPJ formatado e normaliza',
          busca.extrair_cnpjs(texto) == ['19630496000105'],
          str(busca.extrair_cnpjs(texto)))

    dois = 'CNPJ: 04.898.857/0002-02 e também 05.917.351/0001-85.'
    check('acha os dois', busca.extrair_cnpjs(dois) == ['04898857000202', '05917351000185'],
          str(busca.extrair_cnpjs(dois)))

    check('acha CNPJ já em dígitos',
          busca.extrair_cnpjs('inscrito sob 19630496000105 nesta data') == ['19630496000105'],
          str(busca.extrair_cnpjs('inscrito sob 19630496000105 nesta data')))

    check('não inventa CNPJ onde não há',
          busca.extrair_cnpjs('Portaria nº 1.234, de 8 de agosto') == [],
          str(busca.extrair_cnpjs('Portaria nº 1.234, de 8 de agosto')))

    check('não duplica o mesmo CNPJ',
          busca.extrair_cnpjs('19.630.496/0001-05 e de novo 19.630.496/0001-05') ==
          ['19630496000105'],
          str(busca.extrair_cnpjs('19.630.496/0001-05 e de novo 19.630.496/0001-05')))

    check('texto vazio devolve lista vazia', busca.extrair_cnpjs(None) == [])


def test_extrair_processos():
    print('\n3. Extração de número de processo')
    texto = 'Processo nº 15414.630210/2026-80, referente à contestação.'
    check('acha e normaliza',
          busca.extrair_processos(texto) == ['15414630210202680'],
          str(busca.extrair_processos(texto)))
    check('17 dígitos, não 14',
          len(busca.extrair_processos(texto)[0]) == 17,
          str(len(busca.extrair_processos(texto)[0])))
    check('não confunde CNPJ com processo',
          busca.extrair_processos('CNPJ nº 19.630.496/0001-05') == [],
          str(busca.extrair_processos('CNPJ nº 19.630.496/0001-05')))


def test_classificar_consulta():
    print('\n4. Roteamento da consulta')
    for entrada in ('19.630.496/0001-05', '19630496000105', ' 19.630.496/0001-05 '):
        tipo, termo = busca.classificar_consulta(entrada)
        check(f'{entrada!r} vai para o campo de CNPJ',
              (tipo, termo) == ('cnpj', '19630496000105'), f'{tipo}/{termo}')

    tipo, termo = busca.classificar_consulta('15414.630210/2026-80')
    check('processo vai para o campo de processo',
          (tipo, termo) == ('processo', '15414630210202680'), f'{tipo}/{termo}')

    tipo, termo = busca.classificar_consulta('Fator Acidentário de Prevenção')
    check('texto livre continua texto', tipo == 'texto', tipo)

    # O guarda que evita falso positivo: número embutido numa frase é texto
    tipo, _ = busca.classificar_consulta('portaria 19630496000105 de agosto')
    check('número dentro de frase NÃO vira busca de CNPJ', tipo == 'texto', tipo)

    tipo, _ = busca.classificar_consulta('12345')
    check('número curto continua texto', tipo == 'texto', tipo)

    tipo, termo = busca.classificar_consulta('   ')
    check('termo em branco é texto vazio', (tipo, termo) == ('texto', ''), f'{tipo}/{termo}')


def test_orgao_raiz():
    print('\n5. Raiz da hierarquia do órgão')
    h = 'Ministério da Previdência Social/Instituto Nacional do Seguro Social/Diretoria'
    check('pega o primeiro nível',
          busca.orgao_raiz(h) == 'Ministério da Previdência Social', busca.orgao_raiz(h))
    check('sem barra devolve o próprio',
          busca.orgao_raiz('Presidência da República') == 'Presidência da República')
    check('None devolve None', busca.orgao_raiz(None) is None)
    check('vazio devolve None', busca.orgao_raiz('   ') is None)


def main():
    print('=' * 60)
    print('TESTES DA BUSCA DO DOU')
    print('=' * 60)

    test_so_digitos()
    test_extrair_cnpjs()
    test_extrair_processos()
    test_classificar_consulta()
    test_orgao_raiz()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
