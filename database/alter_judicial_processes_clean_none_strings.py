"""Higieniza strings-lixo ("None"/"null"/vazias) em campos texto de judicial_processes.

Importações antigas gravaram str(None) em campos como tribunal, section e
judge_name — valores truthy que vazam para a tela como "None". Converte tudo
para NULL de verdade. Idempotente: re-execução não encontra mais nada.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

COLUMNS = ['tribunal', 'section', 'judge_name', 'origin_unit',
           'process_class', 'valor_causa_texto', 'title', 'description']


def run():
    with app.app_context():
        total = 0
        for column in COLUMNS:
            result = db.session.execute(text(
                f"UPDATE judicial_processes SET {column} = NULL "
                f"WHERE TRIM(COALESCE({column}, '')) IN ('None', 'none', 'null', 'NULL', '')"
                f" AND {column} IS NOT NULL"
            ))
            if result.rowcount:
                print(f'[OK] {column}: {result.rowcount} registro(s) higienizado(s).')
                total += result.rowcount
        db.session.commit()
        if total == 0:
            print('[OK] Nenhuma string-lixo encontrada — nada a fazer.')
        else:
            print(f'[OK] Total: {total} valor(es) convertido(s) para NULL.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha na higienização: {exc}')
        raise
