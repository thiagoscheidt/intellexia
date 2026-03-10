"""
Script de migração para criar a tabela judicial_process_phase_history,
com backfill opcional baseado nos eventos existentes.

Uso:
    python database/add_judicial_process_phase_history_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import (
    db,
    JudicialEvent,
    JudicialPhase,
    JudicialProcess,
    JudicialProcessPhaseHistory,
)


def migrate():
    with app.app_context():
        try:
            print("🔄 Garantindo criação da tabela judicial_process_phase_history...")
            JudicialProcessPhaseHistory.__table__.create(bind=db.engine, checkfirst=True)

            # Backfill opcional: cria histórico com base em JudicialEvent.phase
            # quando existir fase correspondente no escritório do processo.
            processes = JudicialProcess.query.all()
            if not processes:
                db.session.commit()
                print("✅ Tabela criada. Nenhum processo encontrado para backfill.")
                return

            created_count = 0

            for process in processes:
                phases_by_key = {
                    phase.key: phase
                    for phase in JudicialPhase.query.filter_by(law_firm_id=process.law_firm_id).all()
                }

                events = (
                    JudicialEvent.query
                    .filter_by(process_id=process.id)
                    .order_by(JudicialEvent.event_date.asc())
                    .all()
                )

                for event in events:
                    phase = phases_by_key.get((event.phase or '').strip())
                    if not phase:
                        continue

                    already_exists = JudicialProcessPhaseHistory.query.filter_by(
                        process_id=process.id,
                        phase_id=phase.id,
                        source_event_id=event.id,
                    ).first()
                    if already_exists:
                        continue

                    db.session.add(
                        JudicialProcessPhaseHistory(
                            law_firm_id=process.law_firm_id,
                            process_id=process.id,
                            phase_id=phase.id,
                            occurred_at=event.event_date,
                            recorded_at=event.created_at,
                            source_event_id=event.id,
                            entered_by_user_id=process.user_id,
                            judge_name_snapshot=process.judge_name,
                            tribunal_snapshot=process.tribunal,
                            section_snapshot=process.section,
                            origin_unit_snapshot=process.origin_unit,
                            notes=event.description,
                        )
                    )
                    created_count += 1

            db.session.commit()
            print("✅ Migração concluída com sucesso!")
            print(f"✅ Históricos criados a partir de eventos: {created_count}")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == '__main__':
    print("=" * 80)
    print("🔧 MIGRAÇÃO: Criar tabela judicial_process_phase_history")
    print("=" * 80)
    migrate()
    print("=" * 80)
