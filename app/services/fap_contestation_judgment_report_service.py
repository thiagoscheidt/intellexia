from __future__ import annotations

from datetime import datetime

from rich import print

from app.models import FapContestationJudgmentReport, db


class FapContestationJudgmentReportService:
    """Service para gerenciamento e processamento de relatórios de julgamento de contestação do FAP.

    Nota: a extração/importação de benefícios ainda não está implementada.
    """

    def __init__(self, flask_app):
        self.app = flask_app

    def process_pending_reports(
        self,
        batch_size: int = 10,
        report_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        """Processa relatórios pendentes (placeholder sem lógica de extração ainda)."""
        with self.app.app_context():
            query = FapContestationJudgmentReport.query

            if report_id:
                query = query.filter(FapContestationJudgmentReport.id == report_id)
            else:
                statuses = ['pending']
                if include_errors:
                    statuses.append('error')
                query = query.filter(FapContestationJudgmentReport.status.in_(statuses))

            reports = (
                query.order_by(FapContestationJudgmentReport.uploaded_at.asc())
                .limit(max(1, int(batch_size)))
                .all()
            )

            if not reports:
                print('Nenhum relatório pendente para processamento.')
                return 0

            for report in reports:
                # Placeholder de pipeline: a implementação de parsing/importação será adicionada depois.
                report.status = 'processing'
                report.error_message = None
                db.session.commit()

                report.status = 'pending'
                report.error_message = 'Processing pipeline not implemented yet.'
                report.updated_at = datetime.utcnow()
                db.session.commit()

                print(f"Relatório #{report.id} marcado para processamento (placeholder).")

            return 0
