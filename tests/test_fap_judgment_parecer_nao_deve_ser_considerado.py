"""Teste standalone: a frase "não deve ser considerado" em prosa não pode
encerrar o Parecer.

Caso real: 207878_relatorioContestacao.pdf (vigência 2025), benefícios
6415794306 e 6437742520. O parecer do analista narra o pedido da empresa —
"Sustenta, portanto, que o respectivo insumo não deve ser considerado no cálculo
do FAP enquanto pendente de julgamento." — e o terminador `Não deve ser
considerado` casava aí: gravavam-se 243 caracteres e perdiam-se 1.985 (89% do
parecer), cortados no meio da frase. O status continuava "Indeferido", então o
dano não aparecia em tela.

Esse terminador entrou de carona no commit c889834 ("Ajuste para não pegar o
sumário"), cujo objetivo — declarado no comentário — era o `Sumário dos
Elementos Contestados`. Em 220 PDFs do acervo ele nunca apareceu como cabeçalho
e apareceu 2x em prosa; passa a valer só quando ocupa a linha inteira.

Rode com: uv run python tests/test_fap_judgment_parecer_nao_deve_ser_considerado.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fap_contestation_judgment_report_service import (
    FapContestationJudgmentReportService,
)

# Trecho real, com as quebras de linha como o pdfplumber devolve — inclusive o
# "não / deve ser considerado" partido entre duas linhas.
SAMPLE_TEXT = """
Número do Benefício 6415794306 Espécie do Benefício B91 Data Início Benefício (DIB) 04/12/2022
Número da CAT CNPJ do Empregador 90.400.888/2446-02 Data Cessação Benefício (DCB) 11/01/2023
NIT do Empregado 13005320064 Renda Mensal Inicial (RMI) R$ 4.899,13 Data Despacho Benefício (DDB) 17/01/2023
Total Pago R$ 6.005,39 Data de Nascimento do Empregado 15/10/1981
Administrativo 1ª instância
Justificativa CONTESTADO E SEM RESPOSTA - A empresa apresentou defesa administrativa para esta ocorrência
acidentária e ainda não obteve resposta por parte da Previdência Social.
Status Indeferido
Parecer A empresa alega que a natureza acidentária atribuída ao benefício foi formalmente contestada junto à Agência da Previdência
Social e que, até o momento, não houve decisão definitiva acerca do pedido. Sustenta, portanto, que o respectivo insumo não
deve ser considerado no cálculo do FAP enquanto pendente de julgamento. Ressalta, ainda, que não lhe foi disponibilizada a
Classificação Internacional de Doenças (CID) referente ao benefício em questão, o que compromete o pleno conhecimento
das razões que motivaram a caracterização acidentária.
Em consulta ao Sistema Integrado de Benefícios SIBE, constatou-se que até a presente data não houve revisão ou
transformação da espécie para previdenciária, permanecendo válida a classificação acidentária originalmente atribuída.
Ante o exposto, essa demanda específica não implicará o recálculo do FAP.
"""

# Layout em que a frase é cabeçalho de verdade: sozinha na linha, e o que vem
# depois não pertence ao parecer.
SAMPLE_HEADER_TEXT = """
Número do Benefício 1234567890 Espécie do Benefício B91 Data Início Benefício (DIB) 04/12/2022
NIT do Empregado 13005320064 Renda Mensal Inicial (RMI) R$ 4.899,13
Administrativo 1ª instância
Justificativa Justificativa qualquer da empresa.
Status Indeferido
Parecer Parecer da análise, que termina aqui.
Não deve ser considerado
Conteúdo de outra seção que não é parecer.
"""


def main() -> int:
    service = object.__new__(FapContestationJudgmentReportService)
    failures: list[str] = []

    blocks = [c for kind, c in service._split_all_blocks(SAMPLE_TEXT) if kind == 'benefit']
    parsed = [p for p in (service.parse_block(b) for b in blocks) if p]
    target = next((p for p in parsed if p.get('benefit_number') == '6415794306'), None)

    if target is None:
        failures.append('Benefício 6415794306 não foi parseado.')
    else:
        opinion = target.get('first_instance_opinion') or ''
        if 'deve ser considerado no cálculo do FAP' not in opinion:
            failures.append(f'Parecer cortado na frase em prosa: ...{opinion[-90:]!r}')
        if 'Classificação Internacional de Doenças' not in opinion:
            failures.append('Parecer perdeu o parágrafo do CID.')
        if 'não implicará o recálculo do FAP' not in opinion:
            failures.append('Parecer perdeu o fecho ("não implicará o recálculo do FAP").')
        if target.get('first_instance_status') != 'Indeferido':
            failures.append(
                f'Status da 1ª instância: esperava "Indeferido", '
                f'obtive {target.get("first_instance_status")!r}.'
            )

    header_blocks = [c for kind, c in service._split_all_blocks(SAMPLE_HEADER_TEXT) if kind == 'benefit']
    header_parsed = [p for p in (service.parse_block(b) for b in header_blocks) if p]
    header_target = next((p for p in header_parsed if p.get('benefit_number') == '1234567890'), None)

    if header_target is None:
        failures.append('Benefício 1234567890 (layout com cabeçalho) não foi parseado.')
    else:
        header_opinion = header_target.get('first_instance_opinion') or ''
        if 'termina aqui' not in header_opinion:
            failures.append(f'Parecer não extraído no layout com cabeçalho: {header_opinion!r}')
        if 'Conteúdo de outra seção' in header_opinion:
            failures.append(
                'Cabeçalho "Não deve ser considerado" deixou de encerrar o parecer — '
                f'ele engoliu a seção seguinte: {header_opinion!r}'
            )

    if failures:
        print('FALHOU:')
        for failure in failures:
            print(f'  - {failure}')
        return 1

    print('OK: "não deve ser considerado" em prosa não encerra mais o Parecer.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
