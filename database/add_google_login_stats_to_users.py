"""
Script para adicionar as colunas de adoção do login com Google na tabela users:

- google_last_login_at: último login feito pelo botão "Continuar com Google"
- google_login_count: quantas vezes o usuário entrou por esse caminho

Alimentam a coluna "Login com Google" da tela de Atividade de Usuários.

Execute este script para atualizar o banco de dados existente.
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_google_login_stats_columns():
    """Adiciona google_last_login_at e google_login_count em users (idempotente)."""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('users')]

            with db.engine.connect() as conn:
                if 'google_last_login_at' in columns:
                    print("✓ A coluna 'google_last_login_at' já existe na tabela 'users'")
                else:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN google_last_login_at DATETIME NULL"
                    ))
                    conn.commit()
                    print("✓ Coluna 'google_last_login_at' adicionada à tabela 'users'")

                if 'google_login_count' in columns:
                    print("✓ A coluna 'google_login_count' já existe na tabela 'users'")
                else:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN google_login_count INTEGER NOT NULL DEFAULT 0"
                    ))
                    conn.commit()
                    print("✓ Coluna 'google_login_count' adicionada à tabela 'users'")

        except Exception as e:
            print(f"✗ Erro ao aplicar a migração: {str(e)}")
            raise


if __name__ == '__main__':
    print("Adicionando colunas de adoção do login com Google na tabela 'users'...")
    add_google_login_stats_columns()
    print("Migração concluída!")
