"""
Migration: cria a tabela fap_company_groups (CNPJ raiz → grupo empresarial).

Um grupo empresarial reúne várias empresas outorgantes — ADSERVI, por exemplo,
tem ~15 CNPJs raiz. Até aqui o filtro "Grupo Empresarial" do Disputes Center
chamava de grupo uma empresa outorgante só.

A tabela é chaveada por ``cnpj_raiz``, sem FK para ``fap_companies``, de
propósito: duas das três sincronizações de empresas apagam quem não voltou da
API, e a planilha do escritório inclui empresas de que ele *já teve* procuração.

Nasce vazia — é populada pela importação da planilha ou pelo cadastro manual.

Executar:
    uv run python database/add_fap_company_groups_table.py
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


TABLE = 'fap_company_groups'


def run():
    with app.app_context():
        from sqlalchemy import inspect
        from app.models import FapCompanyGroup

        inspector = inspect(db.engine)
        if TABLE in inspector.get_table_names():
            print(f'Tabela {TABLE} já existe. Pulando criação.')
        else:
            FapCompanyGroup.__table__.create(db.engine)
            print(f'Tabela {TABLE} criada com sucesso.')

        # Confere o que ficou de pé (a criação traz constraint e índice juntos).
        inspector = inspect(db.engine)
        colunas = [c['name'] for c in inspector.get_columns(TABLE)]
        indices = {ix['name'] for ix in inspector.get_indexes(TABLE)}
        print(f'  colunas: {", ".join(colunas)}')
        print(f'  índices: {", ".join(sorted(indices)) or "(nenhum)"}')

        total = db.session.query(FapCompanyGroup).count()
        print(f'  registros: {total}')


if __name__ == '__main__':
    run()
