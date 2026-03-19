"""
Script de migração: Adicionar coluna errors_analysis_result em judicial_sentence_analysis
Criado: 18/03/2026
Descrição: Armazena o resultado da análise de erros materiais e omissões pelo AgentSentenceErrorsAnalysis.

Uso:
    uv run database/add_errors_analysis_column.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db


def migrate():
    with app.app_context():
        try:
            print("Adicionando coluna errors_analysis_result em judicial_sentence_analysis...")

            with db.engine.connect() as conn:
                conn.execute(db.text(
                    "ALTER TABLE judicial_sentence_analysis "
                    "ADD COLUMN errors_analysis_result LONGTEXT NULL"
                ))
                conn.commit()

            print("Coluna adicionada com sucesso!")

        except Exception as e:
            err = str(e).lower()
            if 'duplicate column' in err or 'already exists' in err:
                print("Coluna já existe, nada a fazer.")
            else:
                print(f"Erro na migração: {e}")
                raise


if __name__ == "__main__":
    print("=" * 70)
    print("MIGRAÇÃO: judicial_sentence_analysis.errors_analysis_result")
    print("=" * 70)
    migrate()
    print("=" * 70)
