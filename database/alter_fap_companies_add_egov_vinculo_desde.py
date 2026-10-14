#!/usr/bin/env python3
"""
Adiciona fap_companies.egov_vinculo_desde (DATE, nullable).

Data em que a empresa vinculou o CPF do login no gov.br (campo ``dataCriacao``
de ``empresasVinculadas`` no token do FAP). É assim que o escritório acessa o
grupo Vale sem procuração no FAP, e a tela passa a dizer "Vinculada pelo e-gov
desde dd/mm/aaaa" em vez de só "sem procuração vigente". NULL = a empresa não
veio nas vinculadas da última leitura completa.

Idempotente. Uso: uv run python database/alter_fap_companies_add_egov_vinculo_desde.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db
from sqlalchemy import inspect, text

with app.app_context():
    try:
        inspector = inspect(db.engine)
        if 'fap_companies' not in inspector.get_table_names():
            print("• fap_companies não existe — nada a fazer")
            sys.exit(0)
        colunas = {c['name'] for c in inspector.get_columns('fap_companies')}
        if 'egov_vinculo_desde' in colunas:
            print("✓ fap_companies.egov_vinculo_desde já existe — nada a fazer")
            sys.exit(0)
        db.session.execute(text("ALTER TABLE fap_companies ADD COLUMN egov_vinculo_desde DATE NULL"))
        db.session.commit()
        print("✓ fap_companies.egov_vinculo_desde criada")
        print("  Preenchida na próxima sincronização de empresas com a sessão completa.")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
