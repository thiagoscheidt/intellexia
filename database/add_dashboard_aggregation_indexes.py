"""
Migration: índices compostos para as agregações do dashboard.

O dashboard conta e agrupa benefícios por status/categoria e varre as tags da
base de conhecimento. Sem índice composto, o MySQL filtra por ``law_firm_id`` e
resolve o resto lendo as linhas — e cada linha de ``benefits`` carrega 11
colunas ``longtext``, guardadas fora da página. Medido em produção: ~1,3 s por
carregamento só nessas consultas.

Com os índices abaixo (todos começando em law_firm_id e incluindo a coluna
agregada), as consultas viram index-only scan e não tocam nas linhas.

Nenhum índice é removido: os índices de coluna única que já existem
(ix_benefits_first_instance_status etc.) continuam servindo consultas que
filtram só por aquela coluna.

Executar:
    uv run python database/add_dashboard_aggregation_indexes.py
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


# (tabela, nome do índice, colunas)
INDEXES = [
    ('benefits', 'ix_benefits_law_firm_first_instance_status',
     ('law_firm_id', 'first_instance_status')),
    ('benefits', 'ix_benefits_law_firm_second_instance_status',
     ('law_firm_id', 'second_instance_status')),
    ('benefits', 'ix_benefits_law_firm_contestation_topic',
     ('law_firm_id', 'fap_contestation_topic')),
    ('knowledge_base', 'ix_knowledge_base_law_firm_active_tags',
     ('law_firm_id', 'is_active', 'tags')),
    # "Contestações cadastradas recentemente": ORDER BY created_at sem índice
    # caía em "Using filesort" sobre a tabela inteira.
    ('fap_web_contestacoes', 'ix_fap_web_contestacoes_firm_created_at',
     ('law_firm_id', 'created_at', 'id')),
    # Gráficos de contestações por situação (geral e por empresa) e por
    # vigência: agrupavam lendo as linhas, que carregam o raw_data.
    ('fap_web_contestacoes', 'ix_fap_web_contestacoes_firm_raiz_situacao',
     ('law_firm_id', 'cnpj_raiz', 'situacao_descricao')),
    ('fap_web_contestacoes', 'ix_fap_web_contestacoes_firm_ano_vigencia',
     ('law_firm_id', 'ano_vigencia')),
]


def run():
    with app.app_context():
        from sqlalchemy import text, inspect

        inspector = inspect(db.engine)
        criados = 0
        pulados = 0

        with db.engine.connect() as conn:
            for tabela, nome, colunas in INDEXES:
                existentes = {ix['name'] for ix in inspector.get_indexes(tabela)}
                if nome in existentes:
                    print(f'Índice {nome} já existe em {tabela}. Pulando.')
                    pulados += 1
                    continue

                ddl = f"CREATE INDEX {nome} ON {tabela} ({', '.join(colunas)})"
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                    print(f'Índice {nome} criado em {tabela} ({", ".join(colunas)}).')
                    criados += 1
                except Exception as e:
                    print(f'Aviso: não foi possível criar {nome} em {tabela} ({e}).')

        print(f'\nConcluído: {criados} índice(s) criado(s), {pulados} já existia(m).')


if __name__ == '__main__':
    run()
