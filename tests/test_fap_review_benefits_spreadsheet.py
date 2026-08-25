"""
Teste da leitura da planilha de benefícios do Revisor FAP com múltiplas abas.

Regressão: planilhas com uma aba por vigência (2021, 2022, ...) eram lidas só
na aba ativa — as demais eram ignoradas silenciosamente.

Regressão: a coluna da tese era casada só como "TESES"; planilha real com
"TESE" (singular) era recusada inteira com "Nenhuma aba da planilha contém...".

Uso: uv run python tests/test_fap_review_benefits_spreadsheet.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from openpyxl import Workbook  # noqa: E402

from app.blueprints.fap_review import _parse_benefits_spreadsheet  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def build_multi_tab_spreadsheet(path: Path) -> None:
    workbook = Workbook()

    sheet_2021 = workbook.active
    sheet_2021.title = '2021'
    sheet_2021.append(['Número do Benefício', 'TESES'])
    sheet_2021.append(['6407132987', 'BENEFÍCIO CANCELADO + DIB=DCB'])
    sheet_2021.append(['1111111111', ''])  # sem tese: fora da conferência

    sheet_2022 = workbook.create_sheet('2022')
    sheet_2022.append(['Número do Benefício', 'TESES'])
    sheet_2022.append(['6222222222', 'ACIDENTE DE TRAJETO'])

    # Aba sem as colunas esperadas: deve ser ignorada sem erro
    notes = workbook.create_sheet('Anotações')
    notes.append(['Observações gerais'])
    notes.append(['texto livre'])

    sheet_2024 = workbook.create_sheet('2024')
    sheet_2024.append(['Número do Benefício', 'TESES'])
    sheet_2024.append(['6444444444', 'B31 INDEVIDO'])

    # Simula o comportamento comum: última aba editada fica ativa ao salvar
    workbook.active = workbook.sheetnames.index('2024')
    workbook.save(str(path))


# Cabeçalho copiado de uma planilha real de revisão: a coluna da tese é "TESE"
# e há vizinhas parecidas ("Número da CAT", "NIT do Empregado", "OBS" repetida).
REAL_HEADER = [
    'ITEM', 'Número do Benefício', 'Número da CAT', 'CNPJ do Empregador', 'TIPO',
    'NIT do Empregado', 'CPF do Beneficiário', 'Data de Nascimento do Beneficiário',
    'Renda Mensal Inicial(RMI)(R$)', 'Data do Despacho do Benefício (DDB)',
    'Data de Início do Benefício (DIB)', 'Data de Cessação do Benefício (DCB)',
    'CUSTO', 'DATA DA CAT', 'NOME', 'OBS', 'TELA FAP', 'ESTÁ NO CÁLCULO?',
    'GERID', 'obs', 'OBS GUILHERME', 'TESE', 'OBS',
]


def build_real_world_spreadsheet(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '2021'
    sheet.append(REAL_HEADER)
    sheet.append([27, 6203869191, None, '43.035.146/0009-32', 94, '10392565770',
                  '675.559.428-87', '10/04/1954', 1178.36, '03/10/2017', '14/10/2005',
                  '03/03/2018', 175107.51, None, 'WALDEMAR GOGUSEWA', 'PRE FAP', 'OK',
                  'SIM', 'sim', 'PRE FAP', 'temos os documentos', 'PRE-FAP', None])
    sheet.append([43, 6186494827, '2.017.169.525.901', '43.035.146/0013-19', 91,
                  '19036463214', '231.927.278-02', '14/07/1989', 2676.73, '05/06/2017',
                  '17/05/2017', '14/11/2017', 15801.34, None, 'SERGIO JOSE DOS SANTOS',
                  'TRAJETO', 'OK', 'SIM', None, 'TRAJETO', 'temos os documentos',
                  'TRAJETO B91', 'incluído na ação 2019'])
    workbook.save(str(path))


def run():
    print("[1] Planilha com múltiplas abas")
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = Path(tmp) / 'beneficios.xlsx'
        build_multi_tab_spreadsheet(xlsx_path)
        rows = _parse_benefits_spreadsheet(str(xlsx_path))

    numbers = sorted(row['benefit_number_normalized'] for row in rows)
    check("lê linhas de todas as abas com tese", len(rows) == 3, f"(obteve {len(rows)}: {numbers})")
    check("benefício da aba 2021 presente", '6407132987' in numbers)
    check("benefício da aba 2022 presente", '6222222222' in numbers)
    check("benefício da aba 2024 presente", '6444444444' in numbers)
    check("linha sem tese fora", '1111111111' not in numbers)
    sheets = {row.get('sheet_name') for row in rows}
    check("aba de origem registrada", sheets == {'2021', '2022', '2024'}, f"(obteve {sheets})")

    print("[2] Nenhuma aba com as colunas esperadas → erro claro")
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = Path(tmp) / 'invalida.xlsx'
        workbook = Workbook()
        workbook.active.append(['Coluna qualquer'])
        workbook.save(str(xlsx_path))
        try:
            _parse_benefits_spreadsheet(str(xlsx_path))
            check("levantou ValueError", False, "(não levantou)")
        except ValueError as error:
            check("levantou ValueError", True)
            check("erro diz qual coluna faltou na aba", 'Sheet' in str(error),
                  f"(mensagem: {error})")

    print("[3] Planilha real: coluna 'TESE' no singular")
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = Path(tmp) / 'real.xlsx'
        build_real_world_spreadsheet(xlsx_path)
        try:
            rows = _parse_benefits_spreadsheet(str(xlsx_path))
        except ValueError as error:
            rows = []
            check("aceita 'TESE' no singular", False, f"({error})")

    if rows:
        check("aceita 'TESE' no singular", len(rows) == 2, f"(obteve {len(rows)})")
        by_number = {row['benefit_number_normalized']: row['thesis'] for row in rows}
        check("tese lida da coluna certa (não da OBS vizinha)",
              by_number.get('6203869191') == 'PRE-FAP', f"(obteve {by_number})")
        check("número do benefício lido da coluna certa (não da CAT)",
              '6186494827' in by_number, f"(obteve {sorted(by_number)})")

    print("[4] Variações do cabeçalho da tese")
    for header_name, expected in (('TESES', True), ('Tese', True), ('TESE(S)', True),
                                  ('TESES APLICADAS', True), ('OBS', False)):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / 'variacao.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(['Número do Benefício', header_name])
            sheet.append(['6407132987', 'BENEFÍCIO CANCELADO'])
            workbook.save(str(xlsx_path))
            try:
                got = len(_parse_benefits_spreadsheet(str(xlsx_path))) == 1
            except ValueError:
                got = False
        check(f"cabeçalho {header_name!r} {'aceito' if expected else 'recusado'}",
              got is expected, f"(obteve {got})")


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
