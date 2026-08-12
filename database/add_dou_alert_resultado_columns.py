"""
Adiciona as colunas do resultado de recurso FAP nos alertas do DOU:

    dou_client_alerts.tem_resultado         BOOLEAN NOT NULL DEFAULT 0
    dou_client_alert_matches.resultado      VARCHAR(60)

O edital do CRPS traz, na mesma linha do CNPJ, o desfecho do recurso —
"Indeferimento Total", "Deferimento Parcial". É o alerta de maior valor do
módulo, e vira coluna para o badge, o filtro e a ordenação não precisarem
abrir a tabela filha.

Idempotente: coluna já existente é apenas reportada e pulada.

    uv run python database/add_dou_alert_resultado_columns.py

Depois de rodar, preencha o que já está no acervo:

    uv run python scripts/gerar_alertas_dou.py --tudo
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

COLUNAS = (
    ('dou_client_alerts', 'tem_resultado',
     'ALTER TABLE dou_client_alerts '
     'ADD COLUMN tem_resultado BOOLEAN NOT NULL DEFAULT 0',
     'CREATE INDEX ix_dou_client_alerts_tem_resultado '
     'ON dou_client_alerts (tem_resultado)'),
    ('dou_client_alert_matches', 'resultado',
     'ALTER TABLE dou_client_alert_matches ADD COLUMN resultado VARCHAR(60)',
     None),
)


def add_resultado_columns():
    with app.app_context():
        inspector = db.inspect(db.engine)
        existentes = set(inspector.get_table_names())

        faltando = [t for t, *_ in COLUNAS if t not in existentes]
        if faltando:
            print(f"✗ Tabela(s) inexistente(s): {', '.join(sorted(set(faltando)))}")
            print('  Rode antes: uv run python database/add_dou_client_alert_tables.py')
            return

        criadas = []
        for tabela, coluna, ddl, ddl_indice in COLUNAS:
            colunas = {c['name'] for c in inspector.get_columns(tabela)}
            if coluna in colunas:
                print(f"✓ {tabela}.{coluna} já existe — pulando")
                continue
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(ddl))
                    if ddl_indice:
                        conexao.execute(text(ddl_indice))
                criadas.append(f'{tabela}.{coluna}')
                print(f"✓ {tabela}.{coluna} criada")
            except Exception as e:
                print(f"✗ Erro ao criar {tabela}.{coluna}: {e}")
                raise

        if not criadas:
            print('\nNada a fazer: as colunas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} coluna(s): {', '.join(criadas)}")
            print('\nPara preencher o que já está no acervo:')
            print('    uv run python scripts/gerar_alertas_dou.py --tudo')


if __name__ == '__main__':
    print('Adicionando as colunas de resultado FAP aos alertas do DOU...')
    add_resultado_columns()
