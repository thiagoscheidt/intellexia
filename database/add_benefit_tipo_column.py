"""Migration: adiciona coluna `tipo` na tabela benefits."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db


def upgrade():
    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(db.text(
                "ALTER TABLE benefits ADD COLUMN tipo VARCHAR(20) NOT NULL DEFAULT 'benefit'"
            ))
            conn.commit()
        print("Coluna 'tipo' adicionada com sucesso na tabela benefits.")


if __name__ == '__main__':
    upgrade()
