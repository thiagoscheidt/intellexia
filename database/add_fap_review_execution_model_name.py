"""
Adiciona a coluna model_name em fap_review_executions (remessa R02, RPI-18).

A execução já gravava versões de prompt e referência, tokens e custo — mas não
o modelo. Sem a coluna, a tela de debug só podia chutar, e chutava
'gpt-4o-mini' enquanto o Sonnet rodava.

Execuções anteriores ficam com NULL e a tela mostra "não registrado". Não
preencher retroativamente a partir de fap_review_settings.reviewer_model: a
configuração do escritório pode ter mudado desde então, e o palpite recriaria
exatamente o defeito que esta coluna corrige.

    uv run python database/add_fap_review_execution_model_name.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

TABELA = 'fap_review_executions'
COLUNA = 'model_name'


def add_model_name_column():
    """Adiciona a coluna, se ainda não existir."""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)

            if TABELA not in inspector.get_table_names():
                print(f"✗ A tabela '{TABELA}' não existe neste banco.")
                print("  Rode a aplicação uma vez (cria as tabelas) antes desta migration.")
                return

            colunas = [col['name'] for col in inspector.get_columns(TABELA)]
            if COLUNA in colunas:
                print(f"✓ A coluna '{COLUNA}' já existe em '{TABELA}' — nada a fazer")
                return

            with db.engine.connect() as conn:
                conn.execute(text(
                    f"ALTER TABLE {TABELA} ADD COLUMN {COLUNA} VARCHAR(100) NULL"
                ))
                conn.commit()

            print(f"✓ Coluna '{COLUNA}' adicionada com sucesso à tabela '{TABELA}'")
            print("  Execuções anteriores ficam sem modelo e a tela dirá 'não registrado'.")

        except Exception as e:
            print(f"✗ Erro ao adicionar coluna: {e}")
            raise


if __name__ == '__main__':
    print(f"Adicionando coluna '{COLUNA}' na tabela '{TABELA}'...")
    add_model_name_column()
    print("Migração concluída!")
