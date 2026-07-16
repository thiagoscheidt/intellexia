"""
Script para adicionar a tabela de configuração de notificações.

Cria:
  - notification_settings: uma linha por (escritório, tipo de notificação),
    com agendamento (frequência/hora/dia), destinatários e data do último envio.

Uso:
    uv run python database/add_notification_settings_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, NotificationSetting


def add_notification_settings_table():
    """Cria a tabela notification_settings (idempotente)."""
    with app.app_context():
        try:
            print("🔄 Criando tabela notification_settings...")

            NotificationSetting.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabela notification_settings criada (ou já existente)!")
        except Exception as e:
            print(f"❌ Erro ao criar tabela notification_settings: {e}")
            raise


if __name__ == "__main__":
    add_notification_settings_table()
