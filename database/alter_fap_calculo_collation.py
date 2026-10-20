"""
Migration: alinha a collation de fap_calculo_estabelecimentos e fap_calculo_itens
à de ``benefits.benefit_number``.

A tela "Benefícios do cálculo" e as tools MCP comparam
``fap_calculo_itens.identificador`` com ``benefits.benefit_number`` e
``fap_contestation_cats.cat_number`` dentro do MySQL. Collations diferentes
fazem o MySQL recusar a comparação:

    (1267, "Illegal mix of collations (utf8mb4_0900_ai_ci,IMPLICIT) and
    (utf8mb4_unicode_ci,IMPLICIT) for operation '='")

Foi o que aconteceu na homologação em 20/10/2026: ``benefits`` está em
utf8mb4_0900_ai_ci e as tabelas novas tinham sido criadas fixadas em
utf8mb4_unicode_ci (a collation da base local de desenvolvimento). Cada
ambiente tem a sua — por isso a collation de destino é lida de ``benefits`` ali
mesmo, nunca escrita no código.

Idempotente: tabela que já está na collation certa não é tocada. Só altera as
duas tabelas novas. Em SQLite não faz nada (lá não existe collation por tabela).

Executar:
    uv run python database/alter_fap_calculo_collation.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text

from main import app
from app.models import db

TABELAS = ('fap_calculo_estabelecimentos', 'fap_calculo_itens')


def _collation_coluna(tabela: str, coluna: str):
    return db.session.execute(text(
        'SELECT CHARACTER_SET_NAME, COLLATION_NAME FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c'
    ), {'t': tabela, 'c': coluna}).fetchone()


def _collation_tabela(tabela: str):
    linha = db.session.execute(text(
        'SELECT TABLE_COLLATION FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': tabela}).fetchone()
    return linha[0] if linha else None


def run():
    with app.app_context():
        if db.engine.dialect.name != 'mysql':
            print(f'[OK] Banco {db.engine.dialect.name}: collation por tabela não se aplica — nada a fazer.')
            return

        alvo = _collation_coluna('benefits', 'benefit_number')
        if not alvo:
            print('[ERRO] Coluna benefits.benefit_number não encontrada — nada foi alterado.')
            sys.exit(1)
        charset, collation = alvo

        cats = _collation_coluna('fap_contestation_cats', 'cat_number')
        if cats and cats[1] != collation:
            print(f'[AVISO] fap_contestation_cats.cat_number está em {cats[1]} e benefits.benefit_number em '
                  f'{collation}: a comparação com CATs continuará falhando até as duas baterem.')

        for tabela in TABELAS:
            atual = _collation_tabela(tabela)
            if atual is None:
                print(f'[ERRO] Tabela {tabela} não existe — rode database/add_fap_calculo_tables.py antes.')
                sys.exit(1)
            if atual == collation:
                print(f'[OK] {tabela} já está em {collation} — nada a fazer.')
                continue
            try:
                db.session.execute(text(
                    f'ALTER TABLE {tabela} CONVERT TO CHARACTER SET {charset} COLLATE {collation}'
                ))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f'[ERRO] Falha ao converter {tabela}: {e}')
                raise
            print(f'[OK] {tabela}: {atual} → {collation}.')


if __name__ == '__main__':
    run()
