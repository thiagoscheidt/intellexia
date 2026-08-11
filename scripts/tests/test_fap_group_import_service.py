"""
Testes do parser da planilha de grupos empresariais.

O parser é função pura, então estes testes não tocam banco nem Flask — rodam
sobre listas de linhas, como se viessem do openpyxl.

Executar:
    uv run python scripts/tests/test_fap_group_import_service.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.services.fap_group_import_service import (  # noqa: E402
    SpreadsheetFormatError,
    parse_rows,
)

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


CABECALHO = ['CNPJ Raiz Outorgante', 'Grupo', 'Razão Social']


def test_planilha_do_cliente():
    """Formato exato da planilha enviada, com a barra solta no CNPJ."""
    print('\n1. formato real da planilha')
    linhas = [
        CABECALHO,
        ['60.659.463/', 'ACHE', 'ACHE LABORATORIOS FARMACEUTICOS SA'],
        ['11.377.588/', 'ADISER', 'ADISER COMERCIO DE ALIMENTOS LTDA'],
        ['00.383.649/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE LIMP E SERV AUXILIARES LTDA'],
        ['11.312.620/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE NORTE NORDESTE SERVICOS LTDA.'],
        ['11.312.655/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE SUL SUDESTE SERVICOS LTDA.'],
    ]
    registros, erros = parse_rows(linhas)
    check('5 registros lidos', len(registros) == 5, len(registros))
    check('sem erros', erros == [], erros)
    check('barra solta não atrapalha o CNPJ',
          registros[0]['cnpj_raiz'] == '60659463', registros[0]['cnpj_raiz'])
    adservi = [r for r in registros if r['grupo_nome'] == 'ADSERVI']
    check('ADSERVI com 3 CNPJs distintos', len(adservi) == 3, len(adservi))
    check('razão social preservada',
          registros[0]['razao_social'] == 'ACHE LABORATORIOS FARMACEUTICOS SA')
    check('número da linha é o do Excel', registros[0]['linha'] == 2, registros[0]['linha'])


def test_cabecalho_deslocado():
    print('\n2. cabeçalho fora da primeira linha')
    linhas = [
        ['Relatório de Grupos Empresariais', None, None],
        [None, None, None],
        ['Atualizado em 10/08/2026', None, None],
        CABECALHO,
        ['60.659.463/', 'ACHE', 'ACHE LABORATORIOS'],
    ]
    registros, erros = parse_rows(linhas)
    check('encontra o cabeçalho na linha 4', len(registros) == 1 and not erros, (registros, erros))
    check('numeração considera o deslocamento',
          registros[0]['linha'] == 5, registros[0]['linha'])


def test_sinonimos_de_coluna():
    print('\n3. variações de nome de coluna')
    for cabecalho in (
        ['CNPJ', 'Grupo Empresarial', 'Empresa'],
        ['cnpj raiz', 'grupo', 'razao social'],
        ['CNPJ RAIZ OUTORGANTE', 'GRUPO', 'RAZÃO SOCIAL'],
    ):
        registros, erros = parse_rows([cabecalho, ['60.659.463/', 'ACHE', 'X']])
        check(f'{cabecalho} aceito', len(registros) == 1 and not erros, (registros, erros))


def test_ordem_das_colunas():
    print('\n4. colunas em outra ordem')
    linhas = [
        ['Razão Social', 'Grupo', 'CNPJ Raiz Outorgante'],
        ['ACHE LABORATORIOS', 'ACHE', '60.659.463/'],
    ]
    registros, erros = parse_rows(linhas)
    check('lê pela posição do cabeçalho, não pela ordem fixa',
          len(registros) == 1 and registros[0]['cnpj_raiz'] == '60659463', (registros, erros))


def test_linhas_invalidas():
    print('\n5. linhas inválidas são reportadas com o número')
    linhas = [
        CABECALHO,
        ['60.659.463/', 'ACHE', 'OK'],
        ['123', 'GRUPO X', 'CNPJ curto'],
        ['11.377.588/', '   ', 'Grupo em branco'],
        [None, None, None],
        ['11.312.620/', 'ADSERVI', 'OK'],
    ]
    registros, erros = parse_rows(linhas)
    check('só os válidos entram', len(registros) == 2, [r['cnpj_raiz'] for r in registros])
    check('2 erros reportados', len(erros) == 2, erros)
    check('erro de CNPJ aponta a linha 3',
          any(e['linha'] == 3 and 'CNPJ' in e['mensagem'] for e in erros), erros)
    check('erro de grupo aponta a linha 4',
          any(e['linha'] == 4 and 'Grupo' in e['mensagem'] for e in erros), erros)
    check('linha totalmente vazia é ignorada em silêncio',
          not any(e['linha'] == 5 for e in erros), erros)


def test_duplicatas():
    print('\n6. CNPJ repetido')
    iguais = [
        CABECALHO,
        ['11.312.620/', 'ADSERVI', 'Filial A'],
        ['11.312.620/', 'Adservi', 'Filial A de novo'],   # grafia diferente, mesmo grupo
    ]
    registros, erros = parse_rows(iguais)
    check('mesmo grupo repetido: conta uma vez, sem erro',
          len(registros) == 1 and not erros, (registros, erros))

    conflito = [
        CABECALHO,
        ['11.312.620/', 'ADSERVI', 'Filial A'],
        ['11.312.620/', 'OUTRO GRUPO', 'Conflito'],
    ]
    registros, erros = parse_rows(conflito)
    check('grupos diferentes: vira erro', len(erros) == 1, erros)
    check('o erro cita as duas linhas',
          erros and '2' in erros[0]['mensagem'] and erros[0]['linha'] == 3, erros)
    check('mantém o primeiro valor em vez de adivinhar',
          len(registros) == 1 and registros[0]['grupo_nome'] == 'ADSERVI', registros)


def test_planilha_sem_colunas():
    print('\n7. planilha fora do formato')
    erro = None
    try:
        parse_rows([['Coluna A', 'Coluna B'], ['x', 'y']])
    except SpreadsheetFormatError as e:
        erro = str(e)
    check('levanta SpreadsheetFormatError', erro is not None, erro)
    check('mensagem em PT-BR, sem jargão',
          erro and 'Grupo' in erro and 'CNPJ' in erro, erro)

    erro = None
    try:
        parse_rows([])
    except SpreadsheetFormatError as e:
        erro = str(e)
    check('planilha vazia também é recusada com mensagem', erro is not None, erro)


def test_tipos_do_openpyxl():
    print('\n8. tipos que o openpyxl devolve')
    # Célula numérica: o Excel pode entregar o CNPJ como número.
    linhas = [CABECALHO, [60659463, 'ACHE', None]]
    registros, erros = parse_rows(linhas)
    check('CNPJ como número funciona',
          len(registros) == 1 and registros[0]['cnpj_raiz'] == '60659463', (registros, erros))
    check('razão social None vira string vazia',
          registros[0]['razao_social'] == '', repr(registros[0]['razao_social']))

    # Linha mais curta que o cabeçalho (Excel corta colunas vazias à direita).
    registros, erros = parse_rows([CABECALHO, ['60.659.463/', 'ACHE']])
    check('linha sem a última coluna não estoura',
          len(registros) == 1 and not erros, (registros, erros))


if __name__ == '__main__':
    for teste in (
        test_planilha_do_cliente, test_cabecalho_deslocado, test_sinonimos_de_coluna,
        test_ordem_das_colunas, test_linhas_invalidas, test_duplicatas,
        test_planilha_sem_colunas, test_tipos_do_openpyxl,
    ):
        teste()

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    sys.exit(1 if FALHAS else 0)
