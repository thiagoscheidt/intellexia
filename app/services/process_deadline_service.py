"""Regras de Cumprimento de Prazos do Painel de Processos.

Fonte única para a tela do processo e para o chip do header. Contagem de
prazo sugerida a partir de intimação DJEN (simplificação documentada:
somente fins de semana são pulados; feriados não são considerados):
publicação = 1º dia útil após a disponibilização; vencimento = publicação
+ N dias úteis (padrão 15, editável na criação).
"""
from datetime import date, datetime, timedelta

from app.models import db, ProcessDeadline

SOON_WINDOW_DAYS = 7


def add_business_days(start: date, days: int) -> date:
    """Avança `days` dias úteis (seg-sex) a partir de `start` (exclusivo)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def suggest_deadline_from_disponibilizacao(disponibilizacao: date, useful_days: int = 15) -> date:
    publicacao = add_business_days(disponibilizacao, 1)
    return add_business_days(publicacao, useful_days)


def classify_deadline(deadline, today=None):
    today = today or date.today()
    if deadline.status == ProcessDeadline.STATUS_DONE:
        return {'state': 'done', 'days_left': 0}
    days_left = (deadline.due_date - today).days
    if days_left < 0:
        state = 'overdue'
    elif days_left == 0:
        state = 'today'
    elif days_left <= SOON_WINDOW_DAYS:
        state = 'soon'
    else:
        state = 'ok'
    return {'state': state, 'days_left': days_left}


def list_for_process(process_id, law_firm_id):
    pending = ProcessDeadline.query.filter_by(
        process_id=process_id, law_firm_id=law_firm_id,
        status=ProcessDeadline.STATUS_PENDING,
    ).order_by(ProcessDeadline.due_date.asc(), ProcessDeadline.id.asc()).all()
    done = ProcessDeadline.query.filter_by(
        process_id=process_id, law_firm_id=law_firm_id,
        status=ProcessDeadline.STATUS_DONE,
    ).order_by(ProcessDeadline.due_date.desc(), ProcessDeadline.id.desc()).all()
    return pending + done


def create_deadline(law_firm_id, process_id, *, kind, title, due_date, due_time=None,
                    location=None, origin='manual', communication_id=None,
                    responsible_user_id=None, notes=None, created_by_user_id=None):
    deadline = ProcessDeadline(
        law_firm_id=law_firm_id,
        process_id=process_id,
        kind=kind if kind in (ProcessDeadline.KIND_PRAZO, ProcessDeadline.KIND_AUDIENCIA)
        else ProcessDeadline.KIND_PRAZO,
        title=title.strip(),
        due_date=due_date,
        due_time=due_time,
        location=(location or '').strip() or None,
        origin=origin,
        communication_id=communication_id,
        responsible_user_id=responsible_user_id,
        notes=(notes or '').strip() or None,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(deadline)
    db.session.commit()
    return deadline


def set_deadline_status(deadline_id, law_firm_id, *, done: bool, user_id=None):
    deadline = ProcessDeadline.query.filter_by(id=deadline_id, law_firm_id=law_firm_id).first()
    if not deadline:
        return None
    if done:
        deadline.status = ProcessDeadline.STATUS_DONE
        deadline.done_at = datetime.now()
        deadline.done_by_user_id = user_id
    else:
        deadline.status = ProcessDeadline.STATUS_PENDING
        deadline.done_at = None
        deadline.done_by_user_id = None
    db.session.commit()
    return deadline


def delete_deadline(deadline_id, law_firm_id):
    deadline = ProcessDeadline.query.filter_by(id=deadline_id, law_firm_id=law_firm_id).first()
    if not deadline:
        return False
    db.session.delete(deadline)
    db.session.commit()
    return True


def list_pending_for_firm(law_firm_id, limit=8):
    """Prazos pendentes de todos os processos do escritório, por data-limite.

    Retorna (prazos, total_pendentes) — usado pela mesa de trabalho da listagem.
    """
    base = ProcessDeadline.query.filter_by(
        law_firm_id=law_firm_id, status=ProcessDeadline.STATUS_PENDING)
    total = base.count()
    rows = base.order_by(ProcessDeadline.due_date.asc(),
                         ProcessDeadline.id.asc()).limit(limit).all()
    return rows, total


def firm_counts(law_firm_id):
    today = date.today()
    soon_limit = today + timedelta(days=SOON_WINDOW_DAYS)
    base = ProcessDeadline.query.filter_by(
        law_firm_id=law_firm_id, status=ProcessDeadline.STATUS_PENDING)
    overdue = base.filter(ProcessDeadline.due_date < today).count()
    soon = base.filter(ProcessDeadline.due_date >= today,
                       ProcessDeadline.due_date <= soon_limit).count()
    return {'overdue': overdue, 'soon': soon}
