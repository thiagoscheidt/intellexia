"""
Adiciona dou_articles.pagina_num — a página como inteiro, para ordenação.

A coluna ``pagina`` guarda o valor do XML verbatim (texto). Ordenar por ela dá
1, 101, 103, ..., 2, 23 — pior do que não ordenar. Esta coluna existe só para
ordenar na ordem de leitura do jornal, e é indexada porque o acervo chega a
milhões de linhas.

Idempotente: se a coluna já existir, só faz o backfill do que estiver nulo.

    uv run python database/add_dou_articles_pagina_num.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def add_pagina_num():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            if 'dou_articles' not in inspector.get_table_names():
                print("✗ A tabela 'dou_articles' não existe — rode antes "
                      "database/add_dou_tables.py")
                return

            colunas = [c['name'] for c in inspector.get_columns('dou_articles')]

            if 'pagina_num' in colunas:
                print("✓ A coluna 'pagina_num' já existe")
            else:
                with db.engine.connect() as conn:
                    conn.execute(text(
                        'ALTER TABLE dou_articles ADD COLUMN pagina_num INTEGER NULL'
                    ))
                    conn.execute(text(
                        'CREATE INDEX ix_dou_articles_pagina_num '
                        'ON dou_articles (pagina_num)'
                    ))
                    conn.commit()
                print("✓ Coluna 'pagina_num' e índice criados")

            # Backfill: converte o texto já gravado. Só as linhas cujo valor é
            # inteiramente numérico — o resto fica nulo e ordena por último.
            with db.engine.connect() as conn:
                pendentes = conn.execute(text(
                    'SELECT COUNT(*) FROM dou_articles '
                    'WHERE pagina_num IS NULL AND pagina IS NOT NULL'
                )).scalar()

                if not pendentes:
                    print('✓ Nada a preencher: todas as linhas já têm pagina_num')
                else:
                    conn.execute(text(
                        "UPDATE dou_articles SET pagina_num = CAST(pagina AS UNSIGNED) "
                        "WHERE pagina_num IS NULL AND pagina REGEXP '^[0-9]+$'"
                    ))
                    conn.commit()
                    restantes = conn.execute(text(
                        'SELECT COUNT(*) FROM dou_articles WHERE pagina_num IS NULL '
                        'AND pagina IS NOT NULL'
                    )).scalar()
                    print(f'✓ {pendentes - restantes} linha(s) preenchida(s)')
                    if restantes:
                        print(f'  ({restantes} com página não numérica ficaram nulas)')

        except Exception as e:
            print(f'✗ Erro ao adicionar pagina_num: {str(e)}')
            raise


if __name__ == '__main__':
    print("Adicionando 'pagina_num' em dou_articles...")
    add_pagina_num()
    print('Migração concluída!')
