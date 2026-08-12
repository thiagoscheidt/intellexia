"""
Procurações eletrônicas do FAP Web — sincronização e leitura para notificação.

Fonte única de três chamadores: o script dedicado
(``scripts/fap_procuracoes_sync.py``), a etapa do cron completo
(``scripts/fap_sync_cron.py``) e a rota ``POST /fap-panel/sync/procuracoes``.

Duas regras que sustentam as notificações:

- **mudança é diff campo a campo**, não "o registro existia". O upsert reescreve
  ``raw_data`` e ``last_synced_at`` em toda execução, e por isso os dois ficam de
  fora de ``TRACKED_FIELDS`` — senão todo run seria uma mudança;
- **só ``ALERT_FIELDS`` gera e-mail.** O resto é gravado no histórico como
  auditoria, com ``is_alertavel=False``: correção de razão social no portal não
  acorda ninguém.

**Instantes são gravados em UTC** (``_utcnow``), não em ``datetime.now()``. O
``main.py`` define ``TZ=America/Sao_Paulo``, então ``datetime.now()`` devolve a
hora local — três horas atrás do UTC. Como a janela das notificações é o
``NotificationSetting.last_sent_at``, que é UTC, gravar ``synced_at`` em hora
local deixaria a janela três horas no futuro e o alerta só sairia em rajadas
atrasadas. Datas de vigência continuam em data local: ``data_fim`` é data
comercial brasileira, não instante.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

from app.models import db, FapWebProcuracao, FapWebProcuracaoChangeHistory
from app.utils.timezone import SP_TZ

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Agora em UTC, naive — a base das colunas DateTime e da janela do e-mail."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Campos comparados a cada sincronização para decidir se houve mudança real.
# raw_data e last_synced_at ficam fora de propósito (mudam sempre).
TRACKED_FIELDS = (
    'tipo_procuracao_codigo', 'tipo_procuracao_descricao',
    'situacao_codigo', 'situacao_descricao',
    'data_inicio', 'data_fim',
    'cnpj_raiz_outorgante', 'nome_empresa_outorgante',
    'cpf_outorgado', 'cnpj_raiz_outorgado',
    'data_cadastro',
)

# Subconjunto que gera e-mail de alerta — as mudanças com consequência jurídica.
ALERT_FIELDS = ('situacao_codigo', 'data_inicio', 'data_fim')

FIELD_LABELS = {
    'tipo_procuracao_codigo': 'Tipo',
    'tipo_procuracao_descricao': 'Tipo',
    'situacao_codigo': 'Situação',
    'situacao_descricao': 'Situação',
    'data_inicio': 'Início da vigência',
    'data_fim': 'Fim da vigência',
    'cnpj_raiz_outorgante': 'CNPJ do outorgante',
    'nome_empresa_outorgante': 'Outorgante',
    'cpf_outorgado': 'CPF do outorgado',
    'cnpj_raiz_outorgado': 'CNPJ do outorgado',
    'data_cadastro': 'Cadastro',
}

# Janelas do resumo diário.
VENCIMENTO_DIAS = 30          # até onde olhar para frente
VENCIDA_LOOKBACK_DIAS = 30    # até quando uma vencida continua no e-mail
URGENTE_DIAS = 7              # faixa de urgência dentro da janela

# Só procuração vigente interessa para aviso de vencimento.
SITUACAO_VIGENTE = 'DEFERIDA'

# Considera a captura atrasada a partir daqui (rodapé de saúde do e-mail).
SYNC_ATRASO_HORAS = 24

# Corte do corpo do e-mail. O total continua inteiro no resumo e nos contadores;
# o que passa disso vira "e mais N" com link para o painel.
LIMITE_POR_BLOCO = 10
LIMITE_ULTIMAS = 5


# ---------------------------------------------------------------------------
# Parsers do payload da API
# ---------------------------------------------------------------------------

def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00').split('+')[0])
    except Exception:
        return None


def _as_str(value):
    """CNPJ/CPF chegam como número na API — normaliza para string, mantendo None."""
    return None if value is None else str(value)


def _fields_from_item(item: dict) -> dict:
    """Payload da API → dicionário de colunas do modelo (sem raw_data/controle)."""
    tipo = item.get('tipoProcuracao') or {}
    situacao = item.get('situacao') or {}
    return {
        'tipo_procuracao_codigo': tipo.get('codigo'),
        'tipo_procuracao_descricao': tipo.get('descricao'),
        'situacao_codigo': situacao.get('codigo'),
        'situacao_descricao': situacao.get('descricao'),
        'data_inicio': _parse_date(item.get('dataInicio')),
        'data_fim': _parse_date(item.get('dataFim')),
        'cnpj_raiz_outorgante': _as_str(item.get('cnpjRaizOutorgante')),
        'nome_empresa_outorgante': item.get('nomeEmpresaOutorgante'),
        'cpf_outorgado': _as_str(item.get('cpfOutorgado')),
        'cnpj_raiz_outorgado': _as_str(item.get('cnpjRaizOutorgado')),
        'data_cadastro': _parse_datetime(item.get('dataCadastro')),
    }


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------

def sync_procuracoes(svc, law_firm_id: int) -> dict:
    """Busca as procurações no portal FAP e faz o upsert com detecção de mudança.

    ``svc`` é um ``FapWebService`` já autenticado — quem chama monta a
    autenticação (a tela usa a da sessão, os scripts usam ``FAP_AUTH_JSON``).

    Retorna ``{'ok', 'total', 'created', 'updated', 'unchanged', 'alertaveis',
    'expired', 'message'}``. Falha na busca não toca no banco.
    """
    result = svc.fetch_procuracoes()
    if not result.ok:
        return {
            'ok': False,
            'expired': bool(getattr(result, 'expired', False)),
            'message': result.message,
            'total': 0, 'created': 0, 'updated': 0, 'unchanged': 0, 'alertaveis': 0,
        }

    items = result.data if isinstance(result.data, list) else []
    now = _utcnow()
    created = updated = unchanged = alertaveis = 0

    for item in items:
        protocolo = str(item.get('protocolo') or '').strip()
        if not protocolo:
            continue

        fields = _fields_from_item(item)
        existing = FapWebProcuracao.query.filter_by(
            law_firm_id=law_firm_id, protocolo=protocolo
        ).first()

        if existing is None:
            rec = FapWebProcuracao(
                law_firm_id=law_firm_id,
                protocolo=protocolo,
                raw_data=json.dumps(item, ensure_ascii=False),
                last_synced_at=now,
                **fields,
            )
            db.session.add(rec)
            db.session.flush()   # precisa do id para a FK do histórico

            db.session.add(FapWebProcuracaoChangeHistory(
                law_firm_id=law_firm_id,
                procuracao_db_id=rec.id,
                protocolo=protocolo,
                cnpj_raiz_outorgante=fields['cnpj_raiz_outorgante'],
                nome_empresa_outorgante=fields['nome_empresa_outorgante'],
                change_type='created',
                changed_fields=json.dumps(sorted(fields.keys()), ensure_ascii=False),
                old_values='{}',
                new_values=json.dumps(fields, ensure_ascii=False, default=str),
                is_alertavel=True,
                synced_at=now,
            ))
            created += 1
            alertaveis += 1
            continue

        changed_old = {}
        changed_new = {}
        for name in TRACKED_FIELDS:
            atual = getattr(existing, name)
            novo = fields[name]
            if atual != novo:
                changed_old[name] = atual
                changed_new[name] = novo

        if not changed_new:
            # Nada mudou: só marca que foi conferida agora.
            existing.last_synced_at = now
            existing.raw_data = json.dumps(item, ensure_ascii=False)
            unchanged += 1
            continue

        is_alertavel = bool(set(changed_new) & set(ALERT_FIELDS))
        db.session.add(FapWebProcuracaoChangeHistory(
            law_firm_id=law_firm_id,
            procuracao_db_id=existing.id,
            protocolo=protocolo,
            cnpj_raiz_outorgante=fields['cnpj_raiz_outorgante'],
            nome_empresa_outorgante=fields['nome_empresa_outorgante'],
            change_type='updated',
            changed_fields=json.dumps(sorted(changed_new.keys()), ensure_ascii=False),
            old_values=json.dumps(changed_old, ensure_ascii=False, default=str),
            new_values=json.dumps(changed_new, ensure_ascii=False, default=str),
            is_alertavel=is_alertavel,
            synced_at=now,
        ))

        for name, value in fields.items():
            setattr(existing, name, value)
        existing.raw_data = json.dumps(item, ensure_ascii=False)
        existing.last_synced_at = now
        updated += 1
        if is_alertavel:
            alertaveis += 1

    db.session.commit()

    return {
        'ok': True, 'expired': False, 'message': '',
        'total': len(items), 'created': created, 'updated': updated,
        'unchanged': unchanged, 'alertaveis': alertaveis,
    }


# ---------------------------------------------------------------------------
# Leitura para os e-mails
# ---------------------------------------------------------------------------

def ultima_sincronizacao(law_firm_id: int):
    """Instante da última conferência de procurações do escritório (ou None)."""
    return db.session.query(
        db.func.max(FapWebProcuracao.last_synced_at)
    ).filter(FapWebProcuracao.law_firm_id == law_firm_id).scalar()


def _loads(raw):
    try:
        data = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _fmt_valor(campo: str, valor):
    """Valor cru do JSON do histórico → texto para o e-mail."""
    if valor in (None, ''):
        return '—'
    if campo in ('data_inicio', 'data_fim'):
        parsed = _parse_date(valor)
        return parsed.strftime('%d/%m/%Y') if parsed else str(valor)
    if campo == 'data_cadastro':
        parsed = _parse_datetime(valor)
        return parsed.strftime('%d/%m/%Y %H:%M') if parsed else str(valor)
    return str(valor)


def _identificacao(row) -> dict:
    return {
        'protocolo': row.protocolo,
        'outorgante': (row.nome_empresa_outorgante or '').strip() or '—',
        'cnpj_raiz': row.cnpj_raiz_outorgante or '',
    }


def build_procuracoes_alert(law_firm_id: int, since: datetime) -> dict:
    """Procurações novas e alteradas na janela — corpo do alerta imediato.

    Lê só o histórico com ``is_alertavel=True``: mudança cadastral irrelevante
    fica gravada, mas não vira e-mail.
    """
    rows = (
        FapWebProcuracaoChangeHistory.query
        .filter(
            FapWebProcuracaoChangeHistory.law_firm_id == law_firm_id,
            FapWebProcuracaoChangeHistory.is_alertavel.is_(True),
            FapWebProcuracaoChangeHistory.synced_at > since,
        )
        .order_by(
            FapWebProcuracaoChangeHistory.synced_at.desc(),
            FapWebProcuracaoChangeHistory.id.desc(),
        )
        .all()
    )

    novas = []
    alteradas = []

    for row in rows:
        base = _identificacao(row)
        if row.change_type == 'created':
            valores = _loads(row.new_values)
            base.update({
                'tipo': valores.get('tipo_procuracao_descricao') or valores.get('tipo_procuracao_codigo') or '—',
                'situacao': valores.get('situacao_descricao') or valores.get('situacao_codigo') or '—',
                'data_inicio': _fmt_valor('data_inicio', valores.get('data_inicio')),
                'data_fim': _fmt_valor('data_fim', valores.get('data_fim')),
                'synced_at': row.synced_at,
            })
            novas.append(base)
            continue

        antigos = _loads(row.old_values)
        novos = _loads(row.new_values)
        mudancas = []
        vistos = set()
        for campo in ALERT_FIELDS:
            if campo not in novos:
                continue
            rotulo = FIELD_LABELS.get(campo, campo)
            if rotulo in vistos:      # situacao_codigo e _descricao têm o mesmo rótulo
                continue
            vistos.add(rotulo)
            mudancas.append({
                'campo': rotulo,
                'de': _fmt_valor(campo, antigos.get(campo)),
                'para': _fmt_valor(campo, novos.get(campo)),
            })

        if not mudancas:
            continue
        base.update({'mudancas': mudancas, 'synced_at': row.synced_at})
        alteradas.append(base)

    totais = {
        'novas': len(novas),
        'alteradas': len(alteradas),
        'total': len(novas) + len(alteradas),
    }
    return {
        'novas': novas,
        'alteradas': alteradas,
        'totais': totais,
        'has_novidades': totais['total'] > 0,
    }


def _linha_procuracao(rec, hoje: date) -> dict:
    dias = (rec.data_fim - hoje).days if rec.data_fim else None
    return {
        'protocolo': rec.protocolo,
        'outorgante': (rec.nome_empresa_outorgante or '').strip() or '—',
        'cnpj_raiz': rec.cnpj_raiz_outorgante or '',
        'tipo': rec.tipo_procuracao_descricao or rec.tipo_procuracao_codigo or '—',
        'data_inicio': rec.data_inicio.strftime('%d/%m/%Y') if rec.data_inicio else '—',
        'data_fim': rec.data_fim.strftime('%d/%m/%Y') if rec.data_fim else '—',
        'dias': dias,
    }


def _renovadas(vigentes: list, vencidas: list) -> set:
    """Protocolos de vencidas que já têm substituta.

    A renovação chega do portal como protocolo NOVO, não como alteração da
    antiga. Sem esta supressão, o e-mail cobraria por 30 dias uma renovação
    que já foi feita.
    """
    mais_recente = {}
    for rec in vigentes:
        if not rec.data_fim:
            continue
        chave = (rec.cnpj_raiz_outorgante, rec.tipo_procuracao_codigo)
        atual = mais_recente.get(chave)
        if atual is None or rec.data_fim > atual:
            mais_recente[chave] = rec.data_fim

    suprimidos = set()
    for rec in vencidas:
        chave = (rec.cnpj_raiz_outorgante, rec.tipo_procuracao_codigo)
        posterior = mais_recente.get(chave)
        if posterior and rec.data_fim and posterior > rec.data_fim:
            suprimidos.add(rec.protocolo)
    return suprimidos


def build_procuracoes_digest(law_firm_id: int, since: datetime, hoje: date | None = None) -> dict:
    """Resumo diário: o que está chegando ao fim e o que entrou na janela.

    Só procurações ``DEFERIDA`` entram nos blocos de vencimento — pendente ou
    excluída não tem vigência a proteger.
    """
    hoje = hoje or date.today()
    limite_futuro = hoje + timedelta(days=VENCIMENTO_DIAS)
    limite_urgente = hoje + timedelta(days=URGENTE_DIAS)
    limite_passado = hoje - timedelta(days=VENCIDA_LOOKBACK_DIAS)

    vigentes = (
        FapWebProcuracao.query
        .filter(
            FapWebProcuracao.law_firm_id == law_firm_id,
            FapWebProcuracao.situacao_codigo == SITUACAO_VIGENTE,
            FapWebProcuracao.data_fim.isnot(None),
        )
        .order_by(FapWebProcuracao.data_fim)
        .all()
    )

    vencidas_raw = [r for r in vigentes if limite_passado <= r.data_fim < hoje]
    suprimidos = _renovadas(vigentes, vencidas_raw)

    vencidas = [_linha_procuracao(r, hoje) for r in vencidas_raw if r.protocolo not in suprimidos]
    vence_7 = [_linha_procuracao(r, hoje) for r in vigentes if hoje <= r.data_fim <= limite_urgente]
    vence_30 = [_linha_procuracao(r, hoje) for r in vigentes
                if limite_urgente < r.data_fim <= limite_futuro]

    ultimas, novas_no_periodo = _ultimas_cadastradas(law_firm_id, since, hoje)

    ultima = ultima_sincronizacao(law_firm_id)
    atrasado = (
        ultima is None
        or (_utcnow() - ultima) > timedelta(hours=SYNC_ATRASO_HORAS)
    )

    totais = {
        'vencidas': len(vencidas),
        'vence_7': len(vence_7),
        'vence_30': len(vence_30),
        'novas': novas_no_periodo,
        'vencendo': len(vencidas) + len(vence_7) + len(vence_30),
    }
    totais['total'] = totais['vencendo'] + totais['novas']

    # Blocos longos são cortados no corpo do e-mail — 88 cartões ninguém lê. O
    # total continua inteiro no resumo e o restante fica a um clique no painel.
    restantes = {
        'vencidas': max(0, len(vencidas) - LIMITE_POR_BLOCO),
        'vence_7': max(0, len(vence_7) - LIMITE_POR_BLOCO),
        'vence_30': max(0, len(vence_30) - LIMITE_POR_BLOCO),
    }

    return {
        'vencidas': vencidas[:LIMITE_POR_BLOCO],
        'vence_7': vence_7[:LIMITE_POR_BLOCO],
        'vence_30': vence_30[:LIMITE_POR_BLOCO],
        'ultimas': ultimas,
        'restantes': restantes,
        'totais': totais,
        'ultima_sincronizacao': ultima,
        'sync_atrasado': atrasado,
        'janela_dias': VENCIMENTO_DIAS,
        # Diferente dos outros digests: um vencimento próximo sem evento novo é
        # justamente o aviso mais importante — exigir novidade o silenciaria.
        'has_novidades': totais['total'] > 0,
    }


def _sp_naive(momento: datetime) -> datetime:
    """UTC naive → hora de São Paulo, naive.

    ``data_cadastro`` vem do portal em horário de Brasília; a janela do e-mail
    vem de ``last_sent_at``, em UTC. Comparar as duas direto engoliria 3 h de
    cadastros a cada envio.
    """
    return momento.replace(tzinfo=timezone.utc).astimezone(SP_TZ).replace(tzinfo=None)


def _ultimas_cadastradas(law_firm_id: int, since: datetime, hoje: date) -> tuple[list, int]:
    """As últimas procurações cadastradas no portal, e quantas são do período.

    A fonte é ``data_cadastro`` — quando o **portal FAP** registrou a procuração
    —, não o histórico de sincronização. O histórico só conhece o que apareceu
    depois que este código entrou no ar: numa base já sincronizada, toda
    procuração existente casa por protocolo no primeiro run e nenhuma vira
    ``created``, então o bloco ficaria vazio por semanas. ``data_cadastro`` vale
    retroativamente e é a verdade da origem.
    """
    corte = _sp_naive(since)

    recentes = (
        FapWebProcuracao.query
        .filter(
            FapWebProcuracao.law_firm_id == law_firm_id,
            FapWebProcuracao.data_cadastro.isnot(None),
        )
        .order_by(FapWebProcuracao.data_cadastro.desc(), FapWebProcuracao.id.desc())
        .limit(LIMITE_ULTIMAS)
        .all()
    )

    novas_no_periodo = (
        FapWebProcuracao.query
        .filter(
            FapWebProcuracao.law_firm_id == law_firm_id,
            FapWebProcuracao.data_cadastro >= corte,
        )
        .count()
    )

    itens = []
    for rec in recentes:
        item = _linha_procuracao(rec, hoje)
        item.update({
            'situacao': rec.situacao_descricao or rec.situacao_codigo or '—',
            'data_cadastro': rec.data_cadastro.strftime('%d/%m/%Y'),
            'is_nova': rec.data_cadastro >= corte,
        })
        itens.append(item)

    return itens, novas_no_periodo
