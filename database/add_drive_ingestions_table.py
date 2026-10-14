"""
Cria a tabela `drive_ingestions`: arquivos do Google Drive (conta de serviço)
enviados a uma base do IntellexIA — peça-modelo, decisão ou base de
conhecimento. Ver docs/superpowers/specs/2026-10-14-google-drive-conta-servico-design.md.

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_drive_ingestions_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DriveIngestion


def add_drive_ingestions_table():
    with app.app_context():
        tabela = DriveIngestion.__table__
        if tabela.name in set(db.inspect(db.engine).get_table_names()):
            print(f'✓ {tabela.name} já existe — nada a fazer')
            return
        try:
            tabela.create(db.engine)
        except Exception as e:
            print(f'✗ Erro ao criar {tabela.name}: {e}')
            raise
        print(f'✓ {tabela.name} criada')


if __name__ == '__main__':
    add_drive_ingestions_table()
