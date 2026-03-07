"""
Script de migração para criar a tabela judicial_process_notes
com migração opcional de conteúdo existente de internal_notes.

Uso:
    python database/add_judicial_process_notes_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, JudicialProcess, JudicialProcessNote


def migrate():
    with app.app_context():
        try:
            print("🔄 Garantindo criação da tabela judicial_process_notes...")
            JudicialProcessNote.__table__.create(bind=db.engine, checkfirst=True)

            processes_with_internal_notes = JudicialProcess.query.filter(
                JudicialProcess.internal_notes.isnot(None),
                JudicialProcess.internal_notes != ''
            ).all()

            migrated_count = 0
            for process in processes_with_internal_notes:
                already_has_migrated = JudicialProcessNote.query.filter_by(
                    process_id=process.id,
                    content=process.internal_notes.strip()
                ).first()
                if already_has_migrated:
                    continue

                db.session.add(
                    JudicialProcessNote(
                        law_firm_id=process.law_firm_id,
                        process_id=process.id,
                        user_id=process.user_id,
                        content=process.internal_notes.strip(),
                    )
                )
                migrated_count += 1

            db.session.commit()
            print("✅ Migração concluída com sucesso!")
            print(f"✅ Notas migradas de internal_notes: {migrated_count}")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == '__main__':
    print("=" * 70)
    print("🔧 MIGRAÇÃO: Criar tabela judicial_process_notes")
    print("=" * 70)
    migrate()
    print("=" * 70)
