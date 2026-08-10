"""
Cria as tabelas do módulo Diário Oficial: dou_editions, dou_articles e
dou_sync_runs.

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_dou_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouEdition, DouArticle, DouSyncRun

# Ordem importa: dou_articles tem FK para dou_editions
MODELOS = (DouEdition, DouArticle, DouSyncRun)


def add_dou_tables():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            existentes = set(inspector.get_table_names())

            criadas = []
            for modelo in MODELOS:
                nome = modelo.__tablename__
                if nome in existentes:
                    print(f"✓ A tabela '{nome}' já existe — pulando")
                    continue
                modelo.__table__.create(db.engine)
                criadas.append(nome)
                print(f"✓ Tabela '{nome}' criada com sucesso")

            if not criadas:
                print('\nNada a fazer: todas as tabelas já existiam.')
            else:
                print(f"\n✓ {len(criadas)} tabela(s) criada(s): {', '.join(criadas)}")

        except Exception as e:
            print(f'✗ Erro ao criar as tabelas do DOU: {str(e)}')
            raise


if __name__ == '__main__':
    print('Criando as tabelas do módulo Diário Oficial...')
    add_dou_tables()
    print('Migração concluída!')
