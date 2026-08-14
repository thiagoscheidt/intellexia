"""
Prepara dou_client_alerts para os alertas de palavra-chave:

    + tem_regra    BOOLEAN NOT NULL DEFAULT 0
    match_type     passa a aceitar NULL

Um alerta que veio só de regra não tem casamento de CNPJ nenhum, e hoje
match_type é NOT NULL com default 'exato' — deixá-lo assim faria todo alerta de
palavra-chave se declarar casamento exato de cliente, poluindo o filtro e o
contador da tela.

O SQLite não sabe afrouxar NOT NULL com ALTER TABLE. Como no dev o banco é
recriado à vontade, ali o script só avisa; em MySQL ele executa o MODIFY.

Idempotente: o que já está no lugar é reportado e pulado.

    uv run python database/alter_dou_alerts_for_rules.py

Rode antes: uv run python database/add_dou_alert_rules_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

TABELA = 'dou_client_alerts'


def alter_alerts():
    with app.app_context():
        inspector = db.inspect(db.engine)
        if TABELA not in set(inspector.get_table_names()):
            print(f'✗ Tabela {TABELA} não existe.')
            print('  Rode antes: uv run python database/add_dou_client_alert_tables.py')
            return

        colunas = {c['name']: c for c in inspector.get_columns(TABELA)}
        mudou = False

        if 'tem_regra' in colunas:
            print(f'✓ {TABELA}.tem_regra já existe — pulando')
        else:
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(
                        f'ALTER TABLE {TABELA} '
                        'ADD COLUMN tem_regra BOOLEAN NOT NULL DEFAULT 0'))
                    conexao.execute(text(
                        'CREATE INDEX ix_dou_client_alerts_tem_regra '
                        f'ON {TABELA} (tem_regra)'))
            except Exception as e:
                print(f'✗ Erro ao criar {TABELA}.tem_regra: {e}')
                raise
            mudou = True
            print(f'✓ {TABELA}.tem_regra criada')

        if colunas.get('match_type', {}).get('nullable'):
            print(f'✓ {TABELA}.match_type já aceita NULL — pulando')
        elif db.engine.dialect.name == 'sqlite':
            print(f'⚠ {TABELA}.match_type continua NOT NULL: o SQLite não '
                  'afrouxa a restrição por ALTER TABLE.')
            print('  Em desenvolvimento, recrie o banco se precisar do NULL.')
        else:
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(
                        f'ALTER TABLE {TABELA} '
                        'MODIFY COLUMN match_type VARCHAR(10) NULL'))
            except Exception as e:
                print(f'✗ Erro ao afrouxar {TABELA}.match_type: {e}')
                raise
            mudou = True
            print(f'✓ {TABELA}.match_type agora aceita NULL')

        if not mudou:
            print('\nNada a fazer: o esquema já estava pronto.')
        else:
            print('\nAs regras são criadas na tela /dou/regras. Cada regra nova')
            print('gera sozinha os alertas dos últimos 7 dias; para varrer o')
            print('acervo inteiro há o botão "Rodar no acervo" na mesma tela.')


if __name__ == '__main__':
    print('Ajustando dou_client_alerts para os alertas de palavra-chave...')
    alter_alerts()
