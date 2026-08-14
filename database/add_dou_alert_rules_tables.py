"""
Cria as tabelas das regras de palavra-chave do Diário Oficial:

    dou_alert_rules       o que o escritório quer vigiar
    dou_alert_rule_hits   a regra que fez a matéria virar alerta

O hit é tabela filha, e não coluna no alerta, porque a unidade do alerta
continua sendo a matéria: uma portaria pode disparar três regras, e por par
(regra, matéria) ela viraria três linhas na tela e três no e-mail.

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_dou_alert_rules_tables.py

Rode depois: uv run python database/alter_dou_alerts_for_rules.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouAlertRule, DouAlertRuleHit

TABELAS = (DouAlertRule, DouAlertRuleHit)


def add_rule_tables():
    with app.app_context():
        existentes = set(db.inspect(db.engine).get_table_names())
        criadas = []
        for modelo in TABELAS:
            nome = modelo.__tablename__
            if nome in existentes:
                print(f'✓ {nome} já existe — pulando')
                continue
            try:
                modelo.__table__.create(db.engine)
                criadas.append(nome)
                print(f'✓ {nome} criada')
            except Exception as e:
                print(f'✗ Erro ao criar {nome}: {e}')
                raise

        if not criadas:
            print('\nNada a fazer: as tabelas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} tabela(s): {', '.join(criadas)}")
            print('\nAgora rode:')
            print('    uv run python database/alter_dou_alerts_for_rules.py')


if __name__ == '__main__':
    print('Criando as tabelas das regras de palavra-chave do DOU...')
    add_rule_tables()
