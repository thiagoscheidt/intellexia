"""
Cria as tabelas dos alertas de cliente no DOU: dou_client_alerts e
dou_client_alert_matches.

Ao contrário de dou_editions/dou_articles, estas **têm law_firm_id**: o alerta
nasce do cruzamento com a carteira de clientes, que é do escritório.

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_dou_client_alert_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouClientAlert, DouClientAlertMatch

# Ordem importa: matches tem FK para alerts
MODELOS = (DouClientAlert, DouClientAlertMatch)


def add_dou_client_alert_tables():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            existentes = set(inspector.get_table_names())

            faltando = [m.__tablename__ for m in (DouClientAlert,)
                        if 'dou_articles' not in existentes]
            if faltando:
                print("✗ A tabela 'dou_articles' não existe. Rode antes:")
                print('    uv run python database/add_dou_tables.py')
                return

            criadas = []
            for modelo in MODELOS:
                nome = modelo.__tablename__
                if nome in existentes:
                    print(f"✓ A tabela '{nome}' já existe — pulando")
                    continue
                modelo.__table__.create(db.engine)
                criadas.append(nome)
                print(f"✓ Tabela '{nome}' criada com sucesso")

            if not criadas:
                print('\nNada a fazer: todas as tabelas já existiam.')
            else:
                print(f"\n✓ {len(criadas)} tabela(s) criada(s): {', '.join(criadas)}")
                print('\nPara varrer o acervo já capturado:')
                print('    uv run python scripts/gerar_alertas_dou.py --tudo')

        except Exception as e:
            print(f'✗ Erro ao criar as tabelas de alertas do DOU: {str(e)}')
            raise


if __name__ == '__main__':
    print('Criando as tabelas de alertas de cliente do Diário Oficial...')
    add_dou_client_alert_tables()
