"""Teste standalone: a frase "dados do benefício" em prosa não pode encerrar a
seção da 1ª instância.

Caso real: relatório 10128.053135/2025-51 (WEG DRIVES & CONTROLS, vigência 2026).
A justificativa do escritório termina com "...é indevida a utilização dos dados
do benefício B91 para composição do FAP da empresa." — e a quebra de linha do PDF
deixa "dados do benefício B91" no início de uma linha. O terminador de seção
"Dados do Benefício" (cabeçalho real de outro layout de relatório) casava nessa
frase, cortando a seção antes de "Status Indeferido" e do "Parecer": o benefício
era gravado como "Em análise" e o parecer se perdia.

Só é cabeçalho quando "Dados do Benefício" ocupa a linha inteira.

Rode com: uv run python tests/test_fap_judgment_dados_do_beneficio_em_prosa.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fap_contestation_judgment_report_service import (
    FapContestationJudgmentReportService,
)

# Trecho real (quebras de linha como o pdfplumber devolve).
SAMPLE_TEXT = """
Número do Benefício 6448142391 Espécie do Benefício B91 Data Início Benefício (DIB) 02/08/2023
Número da CAT CNPJ do Empregador 14.309.992/0001-48 Data Cessação Benefício (DCB) 29/01/2025
NIT do Empregado 12503849417 Renda Mensal Inicial (RMI) R$ 3.412,23 Data Despacho Benefício (DDB) 19/09/2023
Total Pago R$ 57.787,77 Data de Nascimento do Empregado 17/03/1973
Administrativo 1ª instância
Justificativa Solicita-se a exclusão do NIT 12503849417, CPF nº 889.314.120-53, da base de cálculo do Fator Acidentário de
Prevenção (FAP), especificamente da relação de benefícios de Auxílio por Incapacidade Temporária por Acidente de
Trabalho (espécie B91).
Ressalta-se que a empresa não pode ser prejudicada pela inércia da Administração Pública, à qual compete a apreciação
definitiva da impugnação apresentada. Assim, até que haja decisão final sobre o nexo técnico, é indevida a utilização dos
dados do benefício B91 para composição do FAP da empresa.
Status Indeferido
Parecer A empresa alega que não concorda com a natureza acidentária atribuída ao benefício e assim apresentou contestação
junto à Agência da Previdência Social e que está pendente de resposta.
Ante o exposto, essa demanda específica não implicará o recálculo do FAP.
Número do Benefício 2092640148 Espécie do Benefício B94 Data Início Benefício (DIB) 30/09/2021
NIT do Empregado 13217147722 Renda Mensal Inicial (RMI) R$ 1.393,88
Administrativo 1ª instância
Justificativa Benefício de controle: acidente de trajeto, sem a frase em prosa.
Status Deferido c/ exclusão do registro
Parecer Parecer de controle.
"""

# Layout em que "Dados do Benefício" é cabeçalho de verdade: linha inteira, e o
# que vem depois dele não pertence à decisão da 1ª instância.
SAMPLE_HEADER_TEXT = """
Número do Benefício 1234567890 Espécie do Benefício B91 Data Início Benefício (DIB) 02/08/2023
NIT do Empregado 12503849417 Renda Mensal Inicial (RMI) R$ 3.412,23
Administrativo 1ª instância
Justificativa Justificativa qualquer da empresa.
Status Indeferido
Parecer Parecer da análise.
Dados do Benefício
NB 1234567890 DIB 02/08/2023 Situação Cessado
"""


def main() -> int:
    service = object.__new__(FapContestationJudgmentReportService)
    failures: list[str] = []

    blocks = [c for kind, c in service._split_all_blocks(SAMPLE_TEXT) if kind == 'benefit']
    parsed = [p for p in (service.parse_block(b) for b in blocks) if p]

    target = next((p for p in parsed if p.get('benefit_number') == '6448142391'), None)
    if target is None:
        failures.append('Benefício 6448142391 não foi parseado.')
    else:
        status = target.get('first_instance_status')
        status_raw = target.get('first_instance_status_raw') or ''
        justification = target.get('first_instance_justification') or ''
        opinion = target.get('first_instance_opinion') or ''

        if status != 'Indeferido':
            failures.append(f'Status da 1ª instância: esperava "Indeferido", obtive {status!r}.')
        if 'Indeferido' not in status_raw:
            failures.append(f'Status bruto da 1ª instância ausente: {status_raw!r}.')
        if 'para composição do FAP da empresa' not in justification:
            failures.append(f'Justificativa truncada: ...{justification[-80:]!r}')
        if 'não concorda com a natureza acidentária' not in opinion:
            failures.append(f'Parecer da 1ª instância ausente/truncado: {opinion[:80]!r}')

    control = next((p for p in parsed if p.get('benefit_number') == '2092640148'), None)
    if control is None:
        failures.append('Benefício de controle 2092640148 não foi parseado.')
    elif control.get('first_instance_status') != 'Deferido':
        failures.append(
            f'Controle: status esperado "Deferido", obtive {control.get("first_instance_status")!r}.'
        )

    # O cabeçalho de verdade continua encerrando a seção.
    header_blocks = [c for kind, c in service._split_all_blocks(SAMPLE_HEADER_TEXT) if kind == 'benefit']
    header_parsed = [p for p in (service.parse_block(b) for b in header_blocks) if p]
    header_target = next((p for p in header_parsed if p.get('benefit_number') == '1234567890'), None)
    if header_target is None:
        failures.append('Benefício 1234567890 (layout com cabeçalho) não foi parseado.')
    else:
        header_opinion = header_target.get('first_instance_opinion') or ''
        if 'Parecer da análise' not in header_opinion:
            failures.append(f'Parecer não extraído no layout com cabeçalho: {header_opinion!r}')
        if 'Situação Cessado' in header_opinion:
            failures.append(
                'Cabeçalho "Dados do Benefício" deixou de encerrar a seção — '
                f'o parecer engoliu o bloco seguinte: {header_opinion!r}'
            )

    if failures:
        print('FALHOU:')
        for failure in failures:
            print(f'  - {failure}')
        return 1

    print('OK: "dados do benefício" em prosa não encerra mais a seção da 1ª instância.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
