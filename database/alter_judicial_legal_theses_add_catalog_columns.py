"""
Catálogo de teses do escritório (PRC-23): código, área e junção.

    + code            VARCHAR(20)  código fixo da tese (T-FAP-001); único por escritório
    + area            VARCHAR(30)  FAP | Processual | Tributário | Trabalhista | Previdenciário
                                   (NULL = FAP: as teses cadastradas antes eram todas de benefício)
    + merged_into_id  INT          tese em que esta foi juntada (fica inativa)

As colunas são preenchidas pela importação da planilha do escritório:

    uv run python scripts/importar_catalogo_teses.py <planilha.xlsx>

Idempotente: coluna ou índice já existente é reportado e pulado.

    uv run python database/alter_judicial_legal_theses_add_catalog_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

TABELA = 'judicial_legal_theses'

COLUNAS = [
    ('code', 'VARCHAR(20)'),
    ('area', 'VARCHAR(30)'),
    ('merged_into_id', 'INTEGER'),
]

INDICES = [
    ('uq_judicial_legal_theses_firm_code', 'UNIQUE INDEX', '(law_firm_id, code)'),
    ('ix_judicial_legal_theses_merged_into_id', 'INDEX', '(merged_into_id)'),
]


def alter_catalogo():
    with app.app_context():
        inspector = db.inspect(db.engine)
        if TABELA not in set(inspector.get_table_names()):
            print(f'✗ Tabela {TABELA} não existe.')
            print('  Rode antes: uv run python database/add_judicial_legal_theses_table.py')
            return

        existentes = {c['name'] for c in inspector.get_columns(TABELA)}
        feitas = []
        for nome, tipo in COLUNAS:
            if nome in existentes:
                print(f'✓ {TABELA}.{nome} já existe — pulando')
                continue
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(f'ALTER TABLE {TABELA} ADD COLUMN {nome} {tipo} NULL'))
            except Exception as e:
                print(f'✗ Erro ao criar {TABELA}.{nome}: {e}')
                raise
            feitas.append(nome)
            print(f'✓ {TABELA}.{nome} criada')

        indices = {i['name'] for i in db.inspect(db.engine).get_indexes(TABELA)}
        for nome, tipo, colunas in INDICES:
            if nome in indices:
                print(f'✓ índice {nome} já existe — pulando')
                continue
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(f'CREATE {tipo} {nome} ON {TABELA} {colunas}'))
            except Exception as e:
                print(f'✗ Erro ao criar o índice {nome}: {e}')
                raise
            feitas.append(nome)
            print(f'✓ índice {nome} criado')

        if not feitas:
            print('\nNada a fazer: colunas e índices já existiam.')
        else:
            print(f"\n✓ {len(feitas)} alteração(ões): {', '.join(feitas)}")
            print('\nAgora confira a planilha do catálogo (simula por padrão):')
            print('    uv run python scripts/importar_catalogo_teses.py <planilha.xlsx>')


if __name__ == '__main__':
    alter_catalogo()
