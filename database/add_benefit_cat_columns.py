"""Migration: adiciona colunas CAT na tabela benefits."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db


def upgrade():
    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(db.text(
                "ALTER TABLE benefits ADD COLUMN cat_registration_date DATE"
            ))
            conn.execute(db.text(
                "ALTER TABLE benefits ADD COLUMN insured_death_date DATE"
            ))
            conn.execute(db.text(
                "ALTER TABLE benefits ADD COLUMN cat_block VARCHAR(20)"
            ))
            conn.commit()
        print("Colunas 'cat_registration_date', 'insured_death_date', 'cat_block' adicionadas na tabela benefits.")


if __name__ == '__main__':
    upgrade()
