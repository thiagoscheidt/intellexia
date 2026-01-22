"""
Script para adicionar as colunas data_inicio_beneficio e data_fim_beneficio na tabela case_benefits
Execute este script para atualizar o banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_benefit_dates_columns():
    """Adiciona as colunas data_inicio_beneficio e data_fim_beneficio na tabela case_benefits"""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('case_benefits')]

            # Coluna data_inicio_beneficio
            if 'data_inicio_beneficio' in columns:
                print("ℹ️  A coluna 'data_inicio_beneficio' já existe na tabela 'case_benefits'")
            else:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE case_benefits ADD COLUMN data_inicio_beneficio DATE NULL"
                    ))
                    conn.commit()
                print("✓ Coluna 'data_inicio_beneficio' adicionada com sucesso à tabela 'case_benefits'")

            # Atualizar lista de colunas após possível inclusão
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('case_benefits')]

            # Coluna data_fim_beneficio
            if 'data_fim_beneficio' in columns:
                print("ℹ️  A coluna 'data_fim_beneficio' já existe na tabela 'case_benefits'")
            else:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE case_benefits ADD COLUMN data_fim_beneficio DATE NULL"
                    ))
                    conn.commit()
                print("✓ Coluna 'data_fim_beneficio' adicionada com sucesso à tabela 'case_benefits'")

            print("✅ Migração concluída!")

        except Exception as e:
            print(f"✗ Erro ao adicionar colunas: {e}")
            raise


if __name__ == '__main__':
    print("🔄 Adicionando colunas de início e fim de benefício na tabela 'case_benefits'...")
    add_benefit_dates_columns()
    print("Migração finalizada.")
