#!/usr/bin/env python3
"""Cria a tabela benefit_contestation_decisions (idempotente).

Opcional: em dev/`recreate_database.py` a tabela nasce do model. Este script
serve para ambientes que não recriam a base do zero.

Uso:
  uv run python database/add_benefit_contestation_decisions_table.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, BenefitContestationDecision
from sqlalchemy import inspect


def main() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        table_name = BenefitContestationDecision.__tablename__
        if table_name in inspector.get_table_names():
            print(f'Tabela {table_name} já existe — nada a fazer.')
            return
        BenefitContestationDecision.__table__.create(bind=db.engine)
        print(f'Tabela {table_name} criada com sucesso.')


if __name__ == '__main__':
    main()
