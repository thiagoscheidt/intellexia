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


ALTERATIONS = [
    ('benefits', 'notes'),
    ('benefits', 'first_instance_justification'),
    ('benefits', 'first_instance_opinion'),
    ('benefits', 'second_instance_justification'),
    ('benefits', 'second_instance_opinion'),
    ('benefits', 'justification'),
    ('benefits', 'opinion'),
    ('benefit_contestation_decisions', 'justification'),
    ('benefit_contestation_decisions', 'opinion'),
]


def main():
    with app.app_context():
        with db.engine.connect() as conn:
            for table, col in ALTERATIONS:
                sql = f'ALTER TABLE `{table}` MODIFY COLUMN `{col}` MEDIUMTEXT'
                print(f'  Alterando {table}.{col} → MEDIUMTEXT...', end=' ', flush=True)
                try:
                    conn.execute(db.text(sql))
                    conn.commit()
                    print('OK')
                except Exception as exc:
                    print(f'ERRO: {exc}')

        print('Concluído.')


if __name__ == '__main__':
    main()
