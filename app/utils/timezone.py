from datetime import datetime
from zoneinfo import ZoneInfo

SP_TZ = ZoneInfo('America/Sao_Paulo')


def now_sp() -> datetime:
    """Retorna datetime atual no fuso horário de São Paulo (multiplataforma)."""
    return datetime.now(SP_TZ)


def format_datetime_sp(value) -> str:
    """Formata datetime para string em São Paulo (DD/MM/YYYY HH:MM:SS)."""
    if not value:
        return ''
    
    try:
        # Se é string, fazer parse
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        
        # Se não tem timezone, assumir UTC
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo('UTC'))
        
        # Converter para São Paulo
        value_sp = value.astimezone(SP_TZ)
        return value_sp.strftime('%d/%m/%Y %H:%M:%S')
    except Exception:
        return str(value)


def format_date_sp(value) -> str:
    """Formata date/datetime para string em São Paulo (DD/MM/YYYY)."""
    if not value:
        return ''
    
    try:
        # Se é string, fazer parse
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        
        # Se não tem timezone, assumir UTC
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo('UTC'))
        
        # Converter para São Paulo se for datetime
        if isinstance(value, datetime):
            value = value.astimezone(SP_TZ)
        
        return value.strftime('%d/%m/%Y')
    except Exception:
        return str(value)
