"""
Migration: apaga a tabela fap_review_upload_links.

Era do link de envio do arquivo da revisão pedida pelo Claude (RPI-37), que
saiu em 28/10/2026: o Claude passou a revisar na própria conversa (ver
docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md). A tabela só
guardava o hash dos links (já vencidos) e o id da revisão que cada um gerou;
as revisões e os arquivos enviados continuam no histórico.

Roda só por decisão explícita: não faz parte do deploy da mudança. Idempotente.

Executar:
    uv run python database/remove_fap_review_upload_links_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db

TABELA = 'fap_review_upload_links'


def apagar_tabela() -> bool:
    """Apaga fap_review_upload_links se existir. True se apagou."""
    if not inspect(db.engine).has_table(TABELA):
        print(f'[OK] Tabela {TABELA} não existe.')
        return False
    try:
        with db.engine.begin() as conn:
            conn.execute(db.text(f'DROP TABLE {TABELA}'))
    except Exception as e:
        print(f'[ERRO] Falha ao apagar {TABELA}: {e}')
        raise
    print(f'[OK] Tabela {TABELA} apagada ({db.engine.dialect.name}).')
    return True


if __name__ == '__main__':
    with app.app_context():
        apagar_tabela()
