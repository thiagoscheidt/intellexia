"""Cache da movimentação DataJud por processo (process_datajud_snapshots).

Fonte única para a aba DataJud da tela do processo e para o cron
scripts/sync_datajud_snapshots.py. A resposta do CNJ é normalizada aqui
(instancias/movimentos) antes de persistir — a tela só renderiza o snapshot.
Atualização sob demanda (primeira visita / botão Atualizar) ou pelo cron.
"""
import re
import unicodedata
from datetime import datetime

from app.models import db, ProcessDatajudSnapshot
from app.utils.cnj import tribunal_sigla_from_cnj

DECISION_WORDS = (
    'procedencia', 'procedente', 'improcedencia', 'improcedente', 'sentenca',
    'acolhimento', 'homologacao', 'extincao', 'deferimento', 'indeferimento',
    'acordao', 'provimento',
)

FONTE = 'API pública do DataJud (CNJ) — dados podem ter defasagem em relação ao sistema do tribunal.'

def cnj_digits(process):
    return re.sub(r'\D', '', process.process_number or '')


def resolve_sigla(process):
    """Sigla do índice DataJud: usa o tribunal do processo ou deriva do número CNJ.

    A derivação (segmento J.TR do número, Resolução CNJ 65/2008) fica em
    app.utils.cnj — fonte única da regra.
    """
    from app.services.data_jud_api import DataJudAPI

    sigla = (process.tribunal or '').strip().upper()
    if sigla in DataJudAPI.TRIBUNAIS:
        return sigla
    return tribunal_sigla_from_cnj(process.process_number)


def can_query(process):
    """(ok, motivo) — se o processo tem número CNJ completo e tribunal coberto."""
    from app.services.data_jud_api import DataJudAPI

    if len(cnj_digits(process)) != 20:
        return False, 'Processo sem número CNJ completo — não é possível consultar o DataJud.'
    sigla = resolve_sigla(process)
    if not sigla or sigla not in DataJudAPI.TRIBUNAIS:
        return False, f"Tribunal '{process.tribunal or '?'}' não disponível na API pública do DataJud."
    return True, ''


def _parse_iso(value):
    if not value:
        return None
    raw = str(value).strip().replace('Z', '').split('.')[0]
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _normalize(api, resultado, process, sigla):
    instancias = []
    for processo in api.extrair_processos(resultado):
        movimentos = []
        for mov in (processo.get('movimentos') or []):
            complementos = [
                f"{c.get('descricao')}: {c.get('nome')}" if c.get('descricao') else c.get('nome')
                for c in (mov.get('complementosTabelados') or []) if isinstance(c, dict)
            ]
            movimentos.append({
                'data_hora': mov.get('dataHora'),
                'codigo': mov.get('codigo'),
                'nome': mov.get('nome'),
                'complementos': [c for c in complementos if c],
            })
        movimentos.sort(key=lambda m: m.get('data_hora') or '', reverse=True)
        instancias.append({
            'grau': processo.get('grau'),
            'classe': (processo.get('classe') or {}).get('nome'),
            'orgao_julgador': (processo.get('orgaoJulgador') or {}).get('nome'),
            'sistema': (processo.get('sistema') or {}).get('nome'),
            'data_ajuizamento': processo.get('dataAjuizamento'),
            'ultima_atualizacao': processo.get('dataHoraUltimaAtualizacao'),
            'total_movimentos': len(movimentos),
            'movimentos': movimentos[:200],
        })
    # Instância mais alta primeiro (G2 antes de G1)
    instancias.sort(key=lambda i: str(i.get('grau') or ''), reverse=True)

    return {
        'tribunal': sigla,
        'numero_processo': process.process_number,
        'total_instancias': len(instancias),
        'instancias': instancias,
        'fonte': FONTE,
    }


def get_snapshot(process_id, law_firm_id):
    return ProcessDatajudSnapshot.query.filter_by(
        process_id=process_id, law_firm_id=law_firm_id).first()


def latest_movement(snapshot):
    """(nome, data_hora_iso) do movimento mais recente registrado no snapshot."""
    latest_name, latest_iso = None, ''
    for inst in (snapshot.payload_json or {}).get('instancias', []):
        movimentos = inst.get('movimentos') or []
        if movimentos and (movimentos[0].get('data_hora') or '') > latest_iso:
            latest_iso = movimentos[0].get('data_hora') or ''
            latest_name = movimentos[0].get('nome')
    return latest_name, latest_iso


def is_decision_movement(name):
    """True se o nome do movimento indica decisão (sentença, acórdão, procedência...)."""
    normalized = unicodedata.normalize('NFD', (name or '').lower())
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    return any(word in normalized for word in DECISION_WORDS)


def acknowledge_movement(process_id, law_firm_id, user_id=None):
    """Marca a movimentação atual como "ciente" (some do radar até haver movimento novo)."""
    snapshot = get_snapshot(process_id, law_firm_id)
    if not snapshot:
        return None
    snapshot.movement_ack_at = datetime.now()
    snapshot.movement_ack_user_id = user_id
    db.session.commit()
    return snapshot


def delete_snapshot(process_id, law_firm_id):
    """Invalidação — usar quando o número do processo mudar."""
    snapshot = get_snapshot(process_id, law_firm_id)
    if snapshot:
        db.session.delete(snapshot)
        db.session.commit()


def refresh_snapshot(process):
    """Consulta o DataJud e faz upsert do snapshot. Retorna (snapshot, erro).

    Em falha da API com snapshot existente, marca o erro mas preserva o
    payload antigo (degradação graciosa).
    """
    from app.services.data_jud_api import DataJudAPI

    ok, motivo = can_query(process)
    if not ok:
        return None, motivo

    sigla = resolve_sigla(process)
    api = DataJudAPI()
    resultado = api.buscar_por_numero_processo(cnj_digits(process), sigla, size=5)

    snapshot = get_snapshot(process.id, process.law_firm_id)
    if resultado.get('error'):
        message = str(resultado.get('message') or 'falha na consulta')
        if snapshot:
            snapshot.fetch_status = 'error'
            snapshot.last_error = message
            db.session.commit()
        return snapshot, message

    payload = _normalize(api, resultado, process, sigla)

    last_movement_at = None
    for inst in payload['instancias']:
        movimentos = inst.get('movimentos') or []
        if movimentos:
            parsed = _parse_iso(movimentos[0].get('data_hora'))
            if parsed and (not last_movement_at or parsed > last_movement_at):
                last_movement_at = parsed

    if not snapshot:
        snapshot = ProcessDatajudSnapshot(
            law_firm_id=process.law_firm_id,
            process_id=process.id,
        )
        db.session.add(snapshot)
    snapshot.payload_json = payload
    snapshot.fetched_at = datetime.now()
    snapshot.last_movement_at = last_movement_at
    snapshot.fetch_status = 'ok'
    snapshot.last_error = None
    db.session.commit()
    return snapshot, None
