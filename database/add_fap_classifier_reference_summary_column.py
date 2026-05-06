"""Add reference_summary_markdown to classifier reference versions and backfill summaries.

Usage:
    uv run python database/add_fap_classifier_reference_summary_column.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.agents.fap.fap_contestation_classifier_agent import FAPContestationClassifierAgent
from app.models import FapContestationClassifierReferenceVersion, db


def _get_existing_columns(connection, table_name: str, is_mysql: bool = False) -> set[str]:
    if is_mysql:
        result = connection.execute(db.text(f"SHOW COLUMNS FROM {table_name}"))
        return {row[0] for row in result.fetchall()}

    result = connection.execute(db.text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


def run_migration() -> None:
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            columns = _get_existing_columns(
                connection,
                "fap_contestation_classifier_reference_versions",
                is_mysql,
            )

            if "reference_summary_markdown" not in columns:
                print("+ adicionando coluna reference_summary_markdown")
                if is_mysql:
                    connection.execute(
                        db.text(
                            "ALTER TABLE fap_contestation_classifier_reference_versions "
                            "ADD COLUMN reference_summary_markdown LONGTEXT NULL"
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            "ALTER TABLE fap_contestation_classifier_reference_versions "
                            "ADD COLUMN reference_summary_markdown TEXT"
                        )
                    )
            else:
                print("- coluna ja existe: reference_summary_markdown")

            transaction.commit()
        except Exception as exc:
            transaction.rollback()
            print(f"Erro ao alterar schema: {exc}")
            raise
        finally:
            connection.close()

        versions = (
            FapContestationClassifierReferenceVersion.query
            .order_by(FapContestationClassifierReferenceVersion.id.asc())
            .all()
        )

        updated = 0
        for version in versions:
            if (version.reference_summary_markdown or "").strip():
                continue

            summary = FAPContestationClassifierAgent.summarize_reference_markdown(
                version.reference_markdown or ""
            )
            version.reference_summary_markdown = summary
            updated += 1

        if updated:
            db.session.commit()
            print(f"+ referencias resumidas preenchidas: {updated}")
        else:
            print("- nenhuma referencia precisava de backfill")

        print("Migracao concluida com sucesso.")


if __name__ == "__main__":
    run_migration()
