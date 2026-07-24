"""
Script para adicionar as colunas do login com Google na tabela users:

- google_sub: ID imutável da conta Google ('sub' do id_token), único
- google_linked_at: quando o vínculo foi gravado (auditoria)

Execute este script para atualizar o banco de dados existente.
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_google_auth_columns():
    """Adiciona google_sub e google_linked_at na tabela users (idempotente)."""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('users')]
            indexes = [idx['name'] for idx in inspector.get_indexes('users')]

            with db.engine.connect() as conn:
                if 'google_sub' in columns:
                    print("✓ A coluna 'google_sub' já existe na tabela 'users'")
                else:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN google_sub VARCHAR(64) NULL"
                    ))
                    conn.commit()
                    print("✓ Coluna 'google_sub' adicionada à tabela 'users'")

                if 'google_linked_at' in columns:
                    print("✓ A coluna 'google_linked_at' já existe na tabela 'users'")
                else:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN google_linked_at DATETIME NULL"
                    ))
                    conn.commit()
                    print("✓ Coluna 'google_linked_at' adicionada à tabela 'users'")

                if 'ix_users_google_sub' in indexes:
                    print("✓ O índice 'ix_users_google_sub' já existe")
                else:
                    conn.execute(text(
                        "CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub)"
                    ))
                    conn.commit()
                    print("✓ Índice único 'ix_users_google_sub' criado")

        except Exception as e:
            print(f"✗ Erro ao aplicar a migração: {str(e)}")
            raise


if __name__ == '__main__':
    print("Adicionando colunas do login com Google na tabela 'users'...")
    add_google_auth_columns()
    print("Migração concluída!")
