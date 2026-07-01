"""
Migration: altera colunas Text do benefits para MEDIUMTEXT.

Motivo: benefícios de contestações FAP com múltiplas instâncias acumulam
histórico nos campos notes/justification/opinion que ultrapassa o limite
de 65KB do tipo TEXT padrão do MySQL.

Execução:
  uv run python database/alter_benefits_mediumtext.py
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from main import app
from app.models import db


COLUMNS = [
    'notes',
    'first_instance_justification',
    'first_instance_opinion',
    'second_instance_justification',
    'second_instance_opinion',
    'justification',
    'opinion',
]


def main():
    with app.app_context():
        with db.engine.connect() as conn:
            for col in COLUMNS:
                sql = f'ALTER TABLE benefits MODIFY COLUMN `{col}` MEDIUMTEXT'
                print(f'  Alterando benefits.{col} → MEDIUMTEXT...', end=' ', flush=True)
                try:
                    conn.execute(db.text(sql))
                    conn.commit()
                    print('OK')
                except Exception as exc:
                    print(f'ERRO: {exc}')

        print('Concluído.')


if __name__ == '__main__':
    main()
