"""
Migration: cria a tabela fap_web_procuracoes.

Armazena as procurações eletrônicas sincronizadas da API FAP/Dataprev
(endpoint /gateway/fap/v1/procuracoes).

Executar:
    uv run python database/add_fap_web_procuracoes_table.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


DDL = """
CREATE TABLE IF NOT EXISTS fap_web_procuracoes (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    law_firm_id               INTEGER NOT NULL REFERENCES law_firms(id),

    protocolo                 VARCHAR(50) NOT NULL,

    tipo_procuracao_codigo    VARCHAR(100),
    tipo_procuracao_descricao VARCHAR(255),

    situacao_codigo           VARCHAR(100),
    situacao_descricao        VARCHAR(255),

    data_inicio               DATE,
    data_fim                  DATE,

    cnpj_raiz_outorgante      VARCHAR(20),
    nome_empresa_outorgante   VARCHAR(500),

    cpf_outorgado             VARCHAR(20),
    cnpj_raiz_outorgado       VARCHAR(20),

    data_cadastro             DATETIME,

    raw_data                  TEXT,

    last_synced_at            DATETIME NOT NULL,
    created_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_fap_web_procuracoes_law_firm_protocolo
        UNIQUE (law_firm_id, protocolo)
);

CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_law_firm_id
    ON fap_web_procuracoes (law_firm_id);
CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_protocolo
    ON fap_web_procuracoes (protocolo);
CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_situacao_codigo
    ON fap_web_procuracoes (situacao_codigo);
CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_cnpj_raiz_outorgante
    ON fap_web_procuracoes (cnpj_raiz_outorgante);
CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_cpf_outorgado
    ON fap_web_procuracoes (cpf_outorgado);
CREATE INDEX IF NOT EXISTS ix_fap_web_procuracoes_cnpj_raiz_outorgado
    ON fap_web_procuracoes (cnpj_raiz_outorgado);
"""


def run():
    with app.app_context():
        dialect = db.engine.dialect.name
        if dialect == 'mysql':
            from app.models import FapWebProcuracao  # noqa: F401
            db.create_all()
            print('[OK] Tabela fap_web_procuracoes criada/verificada via SQLAlchemy (MySQL).')
        else:
            # SQLite — executa DDL direto
            with db.engine.connect() as conn:
                for stmt in DDL.strip().split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(db.text(stmt))
                conn.commit()
            print('[OK] Tabela fap_web_procuracoes criada/verificada via DDL (SQLite).')


if __name__ == '__main__':
    run()
