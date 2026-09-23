"""
Cria as tabelas da Base de Jurisprudência (submódulo do Painel de Processos):

    jurisprudence_theses                 tese como aparece nas decisões
    jurisprudence_thesis_catalog_links   tese ↔ catálogo do painel (N:N)
    jurisprudence_decisions              decisão classificada
    jurisprudence_decision_theses        decisão ↔ tese (N:N)
    jurisprudence_uploads                fila dos PDFs lidos pela IA

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_jurisprudence_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import (
    db,
    JurisprudenceThesis,
    JurisprudenceDecision,
    JurisprudenceUpload,
    jurisprudence_decision_theses,
    jurisprudence_thesis_catalog_links,
)

# Ordem das chaves estrangeiras: tese e decisão antes das tabelas de ligação.
TABELAS = (
    JurisprudenceThesis.__table__,
    jurisprudence_thesis_catalog_links,
    JurisprudenceDecision.__table__,
    jurisprudence_decision_theses,
    JurisprudenceUpload.__table__,
)


def add_jurisprudence_tables():
    with app.app_context():
        existentes = set(db.inspect(db.engine).get_table_names())
        criadas = []
        for tabela in TABELAS:
            if tabela.name in existentes:
                print(f'✓ {tabela.name} já existe — pulando')
                continue
            try:
                tabela.create(db.engine)
                criadas.append(tabela.name)
                print(f'✓ {tabela.name} criada')
            except Exception as e:
                print(f'✗ Erro ao criar {tabela.name}: {e}')
                raise

        if not criadas:
            print('\nNada a fazer: as tabelas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} tabela(s): {', '.join(criadas)}")


if __name__ == '__main__':
    print('Criando as tabelas da Base de Jurisprudência...')
    add_jurisprudence_tables()
