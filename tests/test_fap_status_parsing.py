import unittest

from app.services.fap_contestation_judgment_report_service import (
    FapContestationJudgmentReportService,
)


class FapStatusParsingTests(unittest.TestCase):
    def setUp(self):
        self.service = FapContestationJudgmentReportService.__new__(
            FapContestationJudgmentReportService
        )

    def test_extract_instance_decision_ignores_status_word_inside_justification(self):
        section = """Justificativa
status de acidentárias definido de forma definitiva, sob pena de afronta aos mais basilares princípios de direito, até porque, nos termos do art. 151, do CTN, as impugnações administrativas suspendem a eficácia de qualquer ato administrativo tendente a gerar obrigações tributárias, como é o caso. Apenas após decisão final sobre o nexo causal é que a ocorrência poderia ser considerada. Portanto, a inclusão dessa ocorrência é ilegal, devendo ser excluída do FAP.
Status Indeferido
Parecer
texto qualquer
"""

        parsed = self.service._extract_instance_decision(section)

        self.assertEqual(parsed["status"], "Indeferido")
        self.assertEqual(parsed["status_raw"], "Indeferido")
        self.assertIn("status de acidentárias definido de forma definitiva", parsed["justification"])
        self.assertEqual(parsed["opinion"], "texto qualquer")


if __name__ == "__main__":
    unittest.main()
