"""
Placar de teses (PRC-24 e PRC-25): o que cada decisão julgou de fato.

    + tipo_julgamento          VARCHAR(20)  merito | homologacao | sem_merito (+ índice)
    + resultado_por_tese_json  JSON         [{"tese", "resultado"}] — resultado de cada tese

As decisões novas já vêm com os dois campos na leitura. As que já estão na base
são preenchidas por `scripts/preencher_placar_jurisprudencia.py`.

Idempotente: coluna já existente é reportada e pulada.

    uv run python database/alter_jurisprudence_decisions_add_placar_columns.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

TABELA = 'jurisprudence_decisions'


def _colunas(dialeto: str) -> list[tuple[str, str]]:
    return [
        ('tipo_julgamento', 'VARCHAR(20)'),
        ('resultado_por_tese_json', 'JSON' if dialeto == 'mysql' else 'TEXT'),
    ]


def alter_decisions():
    with app.app_context():
        inspector = db.inspect(db.engine)
        if TABELA not in set(inspector.get_table_names()):
            print(f'✗ Tabela {TABELA} não existe.')
            print('  Rode antes: uv run python database/add_jurisprudence_tables.py')
            return

        existentes = {c['name'] for c in inspector.get_columns(TABELA)}
        criadas = []
        for nome, tipo in _colunas(db.engine.dialect.name):
            if nome in existentes:
                print(f'✓ {TABELA}.{nome} já existe — pulando')
                continue
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(f'ALTER TABLE {TABELA} ADD COLUMN {nome} {tipo} NULL'))
                    if nome == 'tipo_julgamento':
                        conexao.execute(text(
                            f'CREATE INDEX ix_{TABELA}_tipo_julgamento ON {TABELA} (tipo_julgamento)'))
            except Exception as e:
                print(f'✗ Erro ao criar {TABELA}.{nome}: {e}')
                raise
            criadas.append(nome)
            print(f'✓ {TABELA}.{nome} criada')

        if not criadas:
            print('\nNada a fazer: as colunas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} coluna(s): {', '.join(criadas)}")
            print('\nAgora preencha as decisões que já estão na base:')
            print('    uv run python scripts/preencher_placar_jurisprudencia.py --escritorio <id>')


if __name__ == '__main__':
    alter_decisions()
