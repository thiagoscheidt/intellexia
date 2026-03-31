from datetime import datetime
from zoneinfo import ZoneInfo

SP_TZ = ZoneInfo('America/Sao_Paulo')


def now_sp() -> datetime:
    """Retorna datetime atual no fuso horário de São Paulo (multiplataforma)."""
    return datetime.now(SP_TZ)
