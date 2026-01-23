"""
Script para adicionar as colunas numero_cat e numero_bo na tabela case_benefits
Execute este script para atualizar o banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_benefit_cat_bo_columns():
    """Adiciona as colunas numero_cat e numero_bo na tabela case_benefits"""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('case_benefits')]

            # Coluna numero_cat
            if 'numero_cat' in columns:
                print("ℹ️  A coluna 'numero_cat' já existe na tabela 'case_benefits'")
            else:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE case_benefits ADD COLUMN numero_cat VARCHAR(100) NULL"
                    ))
                    conn.commit()
                print("✓ Coluna 'numero_cat' adicionada com sucesso à tabela 'case_benefits'")

            # Atualizar lista após possível inclusão
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('case_benefits')]

            # Coluna numero_bo
            if 'numero_bo' in columns:
                print("ℹ️  A coluna 'numero_bo' já existe na tabela 'case_benefits'")
            else:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE case_benefits ADD COLUMN numero_bo VARCHAR(100) NULL"
                    ))
                    conn.commit()
                print("✓ Coluna 'numero_bo' adicionada com sucesso à tabela 'case_benefits'")

            print("✅ Migração concluída!")

        except Exception as e:
            print(f"✗ Erro ao adicionar colunas: {e}")
            raise


if __name__ == '__main__':
    print("🔄 Adicionando colunas numero_cat e numero_bo na tabela 'case_benefits'...")
    add_benefit_cat_bo_columns()
    print("Migração finalizada.")
