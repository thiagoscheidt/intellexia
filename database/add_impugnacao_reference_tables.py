"""
Script de migração: Cria tabelas de peças-modelo de impugnação.

Cria duas tabelas usadas pela base de referências (peças premium do escritório)
do agente gerador de impugnações:

    - impugnacao_reference_models: metadados da peça-modelo (1 linha por arquivo)
    - impugnacao_reference_chunks:  trechos segmentados por subseção argumentativa
                                    (1 linha por chunk indexado no Qdrant)

Multi-tenant: todas as linhas trazem law_firm_id obrigatório.

Executar com:
    uv run python database/add_impugnacao_reference_tables.py
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db
from sqlalchemy import text


def _table_exists(table_name: str) -> bool:
    try:
        db.session.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
        return True
    except Exception:
        db.session.rollback()
        return False


def create_tables():
    with app.app_context():
        print("=" * 80)
        print("MIGRAÇÃO: Tabelas de peças-modelo de impugnação")
        print("=" * 80)

        if _table_exists("impugnacao_reference_models"):
            print("→ Tabela impugnacao_reference_models já existe (skip)")
        else:
            print("Criando tabela impugnacao_reference_models...")
            db.session.execute(text("""
                CREATE TABLE impugnacao_reference_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    law_firm_id INTEGER NOT NULL,
                    user_id INTEGER,
                    title VARCHAR(255) NOT NULL,
                    case_name VARCHAR(255),
                    trf_region VARCHAR(10),
                    generation_mode CHAR(1),
                    quality_score DECIMAL(3, 2) DEFAULT 3.00,
                    original_filename VARCHAR(255),
                    file_path VARCHAR(500),
                    file_size INTEGER,
                    file_type VARCHAR(20),
                    qdrant_collection VARCHAR(120),
                    chunks_count INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'active',
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (law_firm_id) REFERENCES law_firms(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """))
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_impugnacao_ref_models_law_firm "
                "ON impugnacao_reference_models(law_firm_id)"
            ))
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_impugnacao_ref_models_status "
                "ON impugnacao_reference_models(status)"
            ))
            db.session.commit()
            print("✓ impugnacao_reference_models criada")

        if _table_exists("impugnacao_reference_chunks"):
            print("→ Tabela impugnacao_reference_chunks já existe (skip)")
        else:
            print("Criando tabela impugnacao_reference_chunks...")
            db.session.execute(text("""
                CREATE TABLE impugnacao_reference_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference_id INTEGER NOT NULL,
                    law_firm_id INTEGER NOT NULL,
                    section_kind VARCHAR(60),
                    thesis_catalog_id VARCHAR(120),
                    benefit_type VARCHAR(10),
                    qdrant_point_id VARCHAR(64),
                    chunk_chars INTEGER DEFAULT 0,
                    order_in_doc INTEGER DEFAULT 0,
                    preview_text TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (reference_id) REFERENCES impugnacao_reference_models(id) ON DELETE CASCADE,
                    FOREIGN KEY (law_firm_id) REFERENCES law_firms(id) ON DELETE CASCADE
                )
            """))
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_impugnacao_ref_chunks_reference "
                "ON impugnacao_reference_chunks(reference_id)"
            ))
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_impugnacao_ref_chunks_law_firm "
                "ON impugnacao_reference_chunks(law_firm_id)"
            ))
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_impugnacao_ref_chunks_section "
                "ON impugnacao_reference_chunks(section_kind)"
            ))
            db.session.commit()
            print("✓ impugnacao_reference_chunks criada")

        print("\n✓ Migração concluída")


if __name__ == "__main__":
    create_tables()
