"""Sincronização da Consulta do FAP, um estabelecimento por vez.

Duas metades de propósito: ``buscar_estabelecimento`` só faz rede (segura em
thread) e ``gravar_estabelecimento`` só mexe no banco (fluxo principal).

Regras: nada é apagado por ausência; 401/403/erro de um estabelecimento só
registra a situação e **não** sobrescreve ``calculo_atual_id`` — assim a próxima
execução tenta de novo. Nada de CPF em log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.models import db, FapCalculoEstabelecimento, FapCalculoItem
from app.services import fap_calculo_client as client
from app.services import fap_calculo_parser as parser

SITUACOES_QUE_GRAVAM_ITENS = ('ok', 'sem_calculo')
_TAM_ERRO = 255


def _utcnow() -> datetime:
    """Agora em UTC, naive (``TZ=America/Sao_Paulo`` faz ``now()`` vir local)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class BuscaEstabelecimento:
    ano: int
    cnpj: str
    situacao: str  # ok | sem_calculo | sem_acesso | erro | expirada
    resumo: dict | None = None
    itens_atual: list[dict] | None = None  # None = não buscou
    estados_original: dict[tuple[str, str], str] = field(default_factory=dict)
    erro: str = ''


def _situacao_da_falha(r) -> str:
    if r.expired:
        return 'expirada'
    if r.status_code == 403:
        return 'sem_acesso'
    return 'erro'


def _itens(svc, ano: int, cnpj: str, calculo_id: int):
    """Benefícios + CATs normalizados de um cálculo: ``(itens, None)`` ou ``(None, falha)``."""
    rb = client.listar_beneficios(svc, ano, cnpj, calculo_id)
    if not rb.ok:
        return None, rb
    rc = client.listar_cats(svc, ano, cnpj, calculo_id)
    if not rc.ok:
        return None, rc
    itens = [parser.normalizar_beneficio(d) for d in (rb.data or [])]
    itens += [parser.normalizar_cat(d) for d in (rc.data or [])]
    return [i for i in itens if i.get('identificador')], None


def _falha(ano: int, cnpj: str, r) -> BuscaEstabelecimento:
    return BuscaEstabelecimento(ano, cnpj, _situacao_da_falha(r), erro=r.message or '')


def buscar_estabelecimento(svc, ano: int, cnpj14: str,
                           calculo_atual_id_gravado: int | None) -> BuscaEstabelecimento:
    """Só rede. Busca os itens apenas quando o cálculo atual mudou."""
    r = client.listar_calculos(svc, ano, cnpj14)
    if not r.ok:
        return _falha(ano, cnpj14, r)
    resumo = parser.resumir_calculos(r.data or [])
    if not resumo['atual_id']:
        return BuscaEstabelecimento(ano, cnpj14, 'sem_calculo', resumo=resumo)

    busca = BuscaEstabelecimento(ano, cnpj14, 'ok', resumo=resumo)
    if not resumo['tem_itens']:
        busca.itens_atual = []
        return busca
    if calculo_atual_id_gravado == resumo['atual_id']:
        return busca

    itens, falha = _itens(svc, ano, cnpj14, resumo['atual_id'])
    if falha:
        return _falha(ano, cnpj14, falha)
    if resumo['original_id'] != resumo['atual_id']:
        originais, falha = _itens(svc, ano, cnpj14, resumo['original_id'])
        if falha:
            return _falha(ano, cnpj14, falha)
        busca.estados_original = {
            (i['tipo'], i['identificador']): i['estado_atual'] for i in originais
        }
    busca.itens_atual = itens
    return busca


def _historico_json(historico: list[dict]) -> str:
    return json.dumps([
        {**h, 'data': h['data'].isoformat() if isinstance(h.get('data'), date) else h.get('data')}
        for h in historico
    ], ensure_ascii=False)


def gravar_estabelecimento(law_firm_id: int, busca: BuscaEstabelecimento) -> dict:
    """Só banco. Devolve ``{'itens_novos': n, 'itens_atualizados': n}``."""
    agora = _utcnow()
    estab = FapCalculoEstabelecimento.query.filter_by(
        law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj).first()
    if estab is None:
        estab = FapCalculoEstabelecimento(
            law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj,
            cnpj_raiz=busca.cnpj[:8], tem_itens=False)
        db.session.add(estab)

    estab.situacao = busca.situacao
    estab.erro = (busca.erro or '')[:_TAM_ERRO] or None
    estab.synced_at = agora
    contagem = {'itens_novos': 0, 'itens_atualizados': 0}

    if busca.situacao not in SITUACOES_QUE_GRAVAM_ITENS:
        db.session.commit()
        return contagem

    resumo = busca.resumo or {}
    estab.calculo_atual_id = resumo.get('atual_id')
    estab.calculo_atual_tipo = resumo.get('atual_tipo')
    estab.calculo_atual_data = resumo.get('atual_data')
    estab.calculo_original_id = resumo.get('original_id')
    estab.tem_itens = bool(resumo.get('tem_itens'))
    estab.historico_json = _historico_json(resumo.get('historico') or [])
    estab.protocolo = resumo.get('protocolo')

    if busca.itens_atual is not None:
        mesmo = resumo.get('atual_id') == resumo.get('original_id')
        existentes = {
            (i.tipo, i.identificador): i
            for i in FapCalculoItem.query.filter_by(
                law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj)
        }
        for dados in busca.itens_atual:
            chave = (dados['tipo'], dados['identificador'])
            campos = {k: v for k, v in dados.items()
                      if k not in ('cnpj', 'tipo', 'identificador')}
            campos['estado_original'] = (
                'ORIGINAL' if mesmo else busca.estados_original.get(chave))
            campos['calculo_id'] = resumo.get('atual_id')
            item = existentes.get(chave)
            if item is None:
                item = FapCalculoItem(
                    law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj,
                    cnpj_raiz=busca.cnpj[:8], tipo=chave[0], identificador=chave[1],
                    first_seen_at=agora)
                db.session.add(item)
                existentes[chave] = item
                contagem['itens_novos'] += 1
            else:
                contagem['itens_atualizados'] += 1
            for k, v in campos.items():
                setattr(item, k, v)
            item.last_seen_at = agora

    db.session.commit()
    return contagem
