"""
Script para adicionar a tabela fap_companies ao banco de dados existente.

Uso:
    uv run python database/add_fap_companies_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import FapCompany, db


def add_fap_companies_table():
    """Cria a tabela fap_companies no banco."""
    with app.app_context():
        try:
            print('Criando tabela fap_companies...')

            FapCompany.__table__.create(bind=db.engine, checkfirst=True)

            print('Tabela fap_companies criada com sucesso!')
            print('')
            print('Estrutura da tabela:')
            print('  - law_firm_id              (FK -> law_firms.id, NOT NULL)')
            print('  - cnpj                     (CNPJ raiz, NOT NULL)')
            print('  - nome')
            print('  - tipo_procuracao_codigo')
            print('  - tipo_procuracao_descricao')
            print('  - synced_at')
            print('  - created_at / updated_at')
            print('')
            print('Migração concluída!')
        except Exception as e:
            print(f'Erro ao criar tabela: {e}')
            raise


if __name__ == '__main__':
    add_fap_companies_table()
