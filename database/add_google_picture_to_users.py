"""
Script para adicionar a coluna da foto de perfil do Google na tabela users:

- google_picture_url: URL da foto no CDN do Google (claim `picture` do OpenID),
  reescrita a cada login com Google e usada no avatar da header.

Nada é baixado: a URL é servida direto do CDN, com a inicial em círculo como
fallback quando o campo está vazio.

Execute este script para atualizar o banco de dados existente.
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_google_picture_column():
    """Adiciona google_picture_url em users (idempotente)."""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('users')]

            if 'google_picture_url' in columns:
                print("✓ A coluna 'google_picture_url' já existe na tabela 'users'")
                return

            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN google_picture_url VARCHAR(512) NULL"
                ))
                conn.commit()
                print("✓ Coluna 'google_picture_url' adicionada à tabela 'users'")

        except Exception as e:
            print(f"✗ Erro ao aplicar a migração: {str(e)}")
            raise


if __name__ == '__main__':
    print("Adicionando a coluna da foto do Google na tabela 'users'...")
    add_google_picture_column()
    print("Migração concluída!")
