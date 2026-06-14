"""
Script de migração: cria a estrutura de petições do FAP Review e vincula revisões existentes.

Uso:
    uv run python database/add_fap_review_petitions_structure.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db, FapReviewExecution, FapReviewPetition


EXECUTIONS_TABLE = 'fap_review_executions'
PETITIONS_TABLE = 'fap_review_petitions'
EXECUTIONS_PETITION_INDEX = 'ix_fap_review_executions_petition_id'


def _get_existing_columns(connection, table_name: str, is_mysql: bool) -> set[str]:
    if is_mysql:
        result = connection.execute(text(f'SHOW COLUMNS FROM {table_name}'))
        return {row[0] for row in result.fetchall()}

    result = connection.execute(text(f'PRAGMA table_info({table_name})'))
    return {row[1] for row in result.fetchall()}


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _derive_workflow_status(execution_status: str) -> str:
    if execution_status in {'pending', 'processing'}:
        return 'in_review'
    if execution_status == 'completed':
        return 'ready_for_filing'
    if execution_status == 'failed':
        return 'awaiting_adjustments'
    return 'new'


def _build_petition_title(main_document_filename: str | None, identifier: str) -> str:
    if main_document_filename:
        filename = Path(str(main_document_filename)).stem.strip()
        if filename:
            return filename
    return identifier


def migrate() -> bool:
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri
        inspector = inspect(db.engine)

        print('[FAP Review] Iniciando migração de petições...')

        if EXECUTIONS_TABLE not in inspector.get_table_names():
            print(f'Tabela {EXECUTIONS_TABLE} não encontrada.')
            return False

        try:
            FapReviewPetition.__table__.create(bind=db.engine, checkfirst=True)
            print(f'Tabela {PETITIONS_TABLE} verificada/criada com sucesso.')

            connection = db.engine.connect()
            transaction = connection.begin()
            try:
                existing_columns = _get_existing_columns(connection, EXECUTIONS_TABLE, is_mysql)

                if 'petition_id' not in existing_columns:
                    ddl = (
                        f'ALTER TABLE {EXECUTIONS_TABLE} ADD COLUMN petition_id INT NULL'
                        if is_mysql else
                        f'ALTER TABLE {EXECUTIONS_TABLE} ADD COLUMN petition_id INTEGER'
                    )
                    connection.execute(text(ddl))
                    print('+ coluna adicionada: petition_id')
                else:
                    print('- coluna já existe: petition_id')

                if 'revision_number' not in existing_columns:
                    ddl = (
                        f'ALTER TABLE {EXECUTIONS_TABLE} ADD COLUMN revision_number INT NULL'
                        if is_mysql else
                        f'ALTER TABLE {EXECUTIONS_TABLE} ADD COLUMN revision_number INTEGER'
                    )
                    connection.execute(text(ddl))
                    print('+ coluna adicionada: revision_number')
                else:
                    print('- coluna já existe: revision_number')

                transaction.commit()
            except Exception:
                transaction.rollback()
                raise
            finally:
                connection.close()

            inspector = inspect(db.engine)
            if not _index_exists(inspector, EXECUTIONS_TABLE, EXECUTIONS_PETITION_INDEX):
                with db.engine.begin() as connection:
                    connection.execute(
                        text(
                            f'CREATE INDEX {EXECUTIONS_PETITION_INDEX} '
                            f'ON {EXECUTIONS_TABLE}(petition_id)'
                        )
                    )
                print(f'+ índice criado: {EXECUTIONS_PETITION_INDEX}')
            else:
                print(f'- índice já existe: {EXECUTIONS_PETITION_INDEX}')

            revision_executions = FapReviewExecution.query.filter_by(
                execution_type='revision',
            ).order_by(
                FapReviewExecution.law_firm_id.asc(),
                FapReviewExecution.created_at.asc(),
                FapReviewExecution.id.asc(),
            ).all()

            petition_cache: dict[tuple[int, str], FapReviewPetition] = {}
            revision_groups: dict[int, list[FapReviewExecution]] = {}

            for execution in revision_executions:
                identifier = str(execution.law_firm_document_identifier or '').strip()
                if not identifier:
                    identifier = f'LEGACY-REV-{execution.id}'

                cache_key = (execution.law_firm_id, identifier)
                petition = petition_cache.get(cache_key)

                if not petition:
                    petition = FapReviewPetition.query.filter_by(
                        law_firm_id=execution.law_firm_id,
                        office_document_identifier=identifier,
                    ).first()

                if not petition:
                    petition = FapReviewPetition(
                        law_firm_id=execution.law_firm_id,
                        created_by_id=execution.user_id,
                        office_document_identifier=identifier,
                        title=_build_petition_title(execution.main_document_filename, identifier),
                        workflow_status='new',
                    )
                    db.session.add(petition)
                    db.session.flush()

                petition_cache[cache_key] = petition

                execution.law_firm_document_identifier = identifier
                execution.petition_id = petition.id
                revision_groups.setdefault(petition.id, []).append(execution)

            for petition_id, revisions in revision_groups.items():
                revisions.sort(key=lambda item: (item.created_at or item.updated_at, item.id))
                petition = revisions[0].petition
                latest_revision = revisions[-1]

                for index, execution in enumerate(revisions, start=1):
                    execution.revision_number = index

                petition.revision_count = len(revisions)
                petition.latest_revision_id = latest_revision.id
                petition.last_reviewed_at = (
                    latest_revision.completed_at
                    or latest_revision.updated_at
                    or latest_revision.created_at
                )
                petition.workflow_status = _derive_workflow_status(latest_revision.status)

            db.session.commit()
            print('[FAP Review] Migração concluída com sucesso.')
            return True

        except Exception as error:
            db.session.rollback()
            print(f'Erro durante migração: {error}')
            return False


if __name__ == '__main__':
    success = migrate()
    raise SystemExit(0 if success else 1)