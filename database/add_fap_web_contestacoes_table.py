"""
Migration: cria a tabela fap_web_contestacoes.

Tabela do Painel FAP — armazena contestações sincronizadas diretamente
da API FAP/Dataprev, independente do fluxo de importação de PDFs.

Executar:
    uv run python database/add_fap_web_contestacoes_table.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


DDL = """
CREATE TABLE IF NOT EXISTS fap_web_contestacoes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    law_firm_id         INTEGER NOT NULL REFERENCES law_firms(id),
    fap_company_id      INTEGER REFERENCES fap_companies(id),

    contestacao_id      INTEGER NOT NULL,
    cnpj                VARCHAR(20) NOT NULL,
    cnpj_raiz           VARCHAR(10) NOT NULL,
    ano_vigencia        INTEGER NOT NULL,

    instancia_codigo    VARCHAR(100),
    instancia_descricao VARCHAR(255),

    situacao_codigo     VARCHAR(100),
    situacao_descricao  VARCHAR(255),

    protocolo           VARCHAR(100),
    data_transmissao    DATETIME,

    report_id           INTEGER REFERENCES fap_contestation_judgment_reports(id),

    raw_data            TEXT,

    last_synced_at      DATETIME NOT NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_fap_web_contestacoes_law_firm_contestacao
        UNIQUE (law_firm_id, contestacao_id)
);

CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_law_firm_id
    ON fap_web_contestacoes (law_firm_id);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_fap_company_id
    ON fap_web_contestacoes (fap_company_id);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_contestacao_id
    ON fap_web_contestacoes (contestacao_id);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_cnpj
    ON fap_web_contestacoes (cnpj);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_cnpj_raiz
    ON fap_web_contestacoes (cnpj_raiz);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_ano_vigencia
    ON fap_web_contestacoes (ano_vigencia);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_situacao_codigo
    ON fap_web_contestacoes (situacao_codigo);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_protocolo
    ON fap_web_contestacoes (protocolo);
CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_report_id
    ON fap_web_contestacoes (report_id);
"""


def run():
    with app.app_context():
        dialect = db.engine.dialect.name
        if dialect == 'mysql':
            # MySQL — deixa o SQLAlchemy criar via create_all (mais confiável)
            from app.models import FapWebContestacao  # noqa: F401
            db.create_all()
            print('[OK] Tabela fap_web_contestacoes criada/verificada via SQLAlchemy (MySQL).')
        else:
            # SQLite — executa DDL direto
            with db.engine.connect() as conn:
                for stmt in DDL.strip().split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(db.text(stmt))
                conn.commit()
            print('[OK] Tabela fap_web_contestacoes criada/verificada via DDL (SQLite).')


if __name__ == '__main__':
    run()
