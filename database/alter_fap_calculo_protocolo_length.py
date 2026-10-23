"""
Migration: amplia ``fap_calculo_estabelecimentos.protocolo`` de VARCHAR(40) para
VARCHAR(80).

Quando o cálculo foi refeito por decisão judicial, o portal FAP põe no protocolo
o texto ``Processo Judicial nº 9999999-99.9999.9.99.9999`` — 46 caracteres. Com
a coluna em 40, o MySQL recusava a gravação (DataError 1406) e o estabelecimento
ficava fora da sincronização (medido em 23/10/2026: vigência 2024, CNPJ
07049845000382).

Mantém charset, collation e NULL da coluna: um MODIFY sem eles voltaria à
collation padrão da tabela, e a collation destas tabelas é alinhada à de
``benefits`` de cada ambiente (``alter_fap_calculo_collation.py``).

Idempotente: coluna já com 80 ou mais não é tocada. Em SQLite não faz nada
(lá o tamanho do VARCHAR não é imposto).

Executar:
    uv run python database/alter_fap_calculo_protocolo_length.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text

from main import app
from app.models import db

TABELA, COLUNA, TAMANHO = 'fap_calculo_estabelecimentos', 'protocolo', 80


def run():
    with app.app_context():
        if db.engine.dialect.name != 'mysql':
            print(f'[OK] Banco {db.engine.dialect.name}: tamanho de VARCHAR não é imposto — nada a fazer.')
            return

        linha = db.session.execute(text(
            'SELECT CHARACTER_MAXIMUM_LENGTH, CHARACTER_SET_NAME, COLLATION_NAME, IS_NULLABLE '
            'FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c'
        ), {'t': TABELA, 'c': COLUNA}).fetchone()
        if not linha:
            print(f'[ERRO] Coluna {TABELA}.{COLUNA} não encontrada — rode database/add_fap_calculo_tables.py antes.')
            sys.exit(1)

        atual, charset, collation, nulo = linha
        if atual >= TAMANHO:
            print(f'[OK] {TABELA}.{COLUNA} já tem VARCHAR({atual}) — nada a fazer.')
            return

        try:
            db.session.execute(text(
                f'ALTER TABLE {TABELA} MODIFY {COLUNA} VARCHAR({TAMANHO}) '
                f'CHARACTER SET {charset} COLLATE {collation} {"NULL" if nulo == "YES" else "NOT NULL"}'
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[ERRO] Falha ao alterar {TABELA}.{COLUNA}: {e}')
            raise
        print(f'[OK] {TABELA}.{COLUNA}: VARCHAR({atual}) → VARCHAR({TAMANHO}), {collation}.')


if __name__ == '__main__':
    run()
