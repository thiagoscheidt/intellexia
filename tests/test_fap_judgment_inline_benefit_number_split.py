"""Teste standalone: menção inline a "Número do benefício" dentro da justificativa
da 2ª instância não pode quebrar o bloco do benefício ao meio.

Caso real: benefício 1896815291 — a justificativa da 2ª instância contém
"NIT 12546101880 (Número do benefício 1896815291)." e o split por
"Número do Benefício" cortava a justificativa nesse ponto, perdendo o
status ("Deferido c/ exclusão do registro") e o parecer da 2ª instância.

Rode com: uv run python tests/test_fap_judgment_inline_benefit_number_split.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fap_contestation_judgment_report_service import (
    FapContestationJudgmentReportService,
)

SAMPLE_TEXT = """
Número do Benefício 1896815291 Espécie do Benefício B94 Data Início Benefício (DIB) 15/09/2012
Número da CAT CNPJ do Empregador 49.930.514/0001-35 Data Cessação Benefício (DCB)
NIT do Empregado 12546101880 Renda Mensal Inicial (RMI) R$ 361,79 Data Despacho Benefício (DDB) 26/02/2020
Total Pago R$ 184.081,09 Data de Nascimento do Empregado 12/03/1975
Administrativo 1ª instância
Justificativa O funcionário de NIT 12546101880 foi considerado para o cálculo do FAP como:
* B94 id 2 no detalhamento dos B94
No entanto esse B94 foi concedido em decorrência de acidente de trajeto.
Segundo a Resolução MF_CNP nº 1.329, de 25 de abril de 2017, os acidentes de trajeto e os benefícios decorrentes dos
mesmos deixaram de fazer parte do cálculo do FAP. Sendo assim, esse elemento não deve ser utilizado para o cálculo do
FAP.
Status Indeferido
Parecer Em contestação, a empresa requer exclusão do insumo do seu cálculo do FAP, alegando improcedência sobre a concessão
do benefício.
Ante o exposto, em face de ter sido julgada improcedente a alegação, essa demanda específica não implicará no recálculo do
FAP.
Administrativo 2ª instância
Justificativa Justificativa: NIT 12546101880 (Número do benefício 1896815291). No entanto esse beneficio foi concedido em decorrência
de acidente de trajeto. Segundo a Resolução MF_CNP nº 1.329, de 25 de abril de 2017, os acidentes de trajeto e os
benefícios decorrentes dos mesmos deixaram de fazer parte do cálculo do FAP. Sendo assim, esse elemento não deve ser
utilizado para o cálculo do FAP.
Status Deferido c/ exclusão do registro
Parecer Inconformada com indeferimento da contestação, a requerida em recurso alega que o benefício é derivado de acidente de
trajeto e que, por este motivo, deve ser excluído do cálculo do FAP.
Em face de ter sido contabilizado indevidamente por decorrer de acidente de trajeto, comandaremos a exclusão do benefício
em questão somente para fins de recálculo do FAP.
Número do Benefício 6180156421 Espécie do Benefício B91 Data Início Benefício (DIB) 01/02/2018
NIT do Empregado 10987654321 Renda Mensal Inicial (RMI) R$ 1.200,00
Administrativo 1ª instância
Justificativa Benefício de controle para garantir que o split normal continua funcionando.
Status Indeferido
Parecer Parecer de controle.
"""


def main() -> int:
    service = object.__new__(FapContestationJudgmentReportService)
    failures: list[str] = []

    typed_blocks = service._split_all_blocks(SAMPLE_TEXT)
    benefit_blocks = [content for kind, content in typed_blocks if kind == 'benefit']

    if len(benefit_blocks) != 2:
        failures.append(
            f'Esperava 2 blocos de benefício, obtive {len(benefit_blocks)} '
            '(menção inline quebrou o bloco).'
        )

    parsed = [service.parse_block(block) for block in benefit_blocks]
    parsed = [p for p in parsed if p]
    numbers = [p.get('benefit_number') for p in parsed]

    if numbers != ['1896815291', '6180156421']:
        failures.append(f'Números extraídos incorretos: {numbers}')

    target = next((p for p in parsed if p.get('benefit_number') == '1896815291'), None)
    if target is None:
        failures.append('Benefício 1896815291 não foi parseado.')
    else:
        just2 = target.get('second_instance_justification') or ''
        status2 = (target.get('second_instance_status_raw') or '') + (target.get('second_instance_status') or '')
        opinion2 = target.get('second_instance_opinion') or ''

        if 'Número do benefício 1896815291' not in just2:
            failures.append(f'Justificativa 2ª instância truncada: ...{just2[-80:]!r}')
        if 'esse elemento não deve ser utilizado' not in just2:
            failures.append('Justificativa 2ª instância não contém o final esperado.')
        if 'Deferido' not in status2:
            failures.append(f'Status 2ª instância incorreto: {status2!r}')
        if 'Inconformada com indeferimento' not in opinion2:
            failures.append(f'Parecer 2ª instância ausente/truncado: {opinion2[:80]!r}')

    control = next((p for p in parsed if p.get('benefit_number') == '6180156421'), None)
    if control is None:
        failures.append('Benefício de controle 6180156421 não foi parseado.')
    elif 'Benefício de controle' not in (control.get('first_instance_justification') or ''):
        failures.append('Justificativa do benefício de controle não extraída.')

    # split_blocks (caminho legado) também não pode cortar na menção inline.
    legacy_parts = FapContestationJudgmentReportService.split_blocks(SAMPLE_TEXT)
    legacy_blocks = [p for p in legacy_parts[1:] if p.strip()]
    if len(legacy_blocks) != 2:
        failures.append(
            f'split_blocks: esperava 2 blocos, obtive {len(legacy_blocks)}.'
        )

    if failures:
        print('FALHOU:')
        for failure in failures:
            print(f'  - {failure}')
        return 1

    print('OK: menção inline a "Número do benefício" não quebra mais o bloco.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
