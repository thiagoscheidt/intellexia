"""Contexto de busca de referências de impugnação a partir do processo.

Fonte única do TRF/vara/juiz usados para priorizar peças-modelo:
- TRF: derivado do número CNJ (fallback: texto do tribunal/órgão julgador)
- vara: snapshot DataJud (menor grau) -> Court.orgao_julgador -> process.section
- juiz: JudicialProcess.judge_name (frequentemente ausente -> None)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.utils.cnj import tribunal_sigla_from_cnj

_TRF_TEXT_RE = re.compile(
    r"\btrf\s*([1-6])\b|tribunal\s+regional\s+federal\s+da\s+([1-6])\D{0,3}regi[aã]o",
    re.IGNORECASE,
)
_SECTION_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,2}(?:\.\d+)*\s*[\.\)\-:]?\s*")


def normalize_context_value(text) -> str:
    """Caixa alta sem acentos, espaços colapsados — para match exato de vara/juiz."""
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', normalized).strip().upper()


def normalize_section_title(text) -> str:
    """Título de seção sem numeração inicial, caixa alta sem acentos.

    Mesma remoção de numeração usada pelo gerador
    (_normalize_section_label_for_prompt).
    """
    value = _SECTION_NUMBER_PREFIX_RE.sub('', str(text or '').strip())
    return normalize_context_value(value)


def trf_region_from_process(process) -> Optional[str]:
    sigla = tribunal_sigla_from_cnj(getattr(process, 'process_number', None))
    if sigla and sigla.startswith('TRF'):
        return sigla

    court = getattr(process, 'court', None)
    candidates = [
        getattr(court, 'tribunal', None),
        getattr(court, 'orgao_julgador', None),
        getattr(process, 'tribunal', None),
        getattr(process, 'tribunal_name', None),
    ]
    for value in candidates:
        match = _TRF_TEXT_RE.search(str(value or ''))
        if match:
            return f"TRF{match.group(1) or match.group(2)}"
    return None


def orgao_julgador_from_process(process) -> Optional[str]:
    try:
        from app.services import datajud_snapshot_service
        snapshot = datajud_snapshot_service.get_snapshot(process.id, process.law_firm_id)
        instancias = ((snapshot.payload_json or {}).get('instancias') if snapshot else None) or []
        # Menor grau primeiro (G1 antes de G2): vara onde o processo tramita.
        for instancia in sorted(instancias, key=lambda i: str(i.get('grau') or 'Z')):
            nome = str(instancia.get('orgao_julgador') or '').strip()
            if nome:
                return nome
    except Exception as error:
        print(f"[impugnacao_process_context] snapshot DataJud indisponível: {error}")

    court = getattr(process, 'court', None)
    for value in (getattr(court, 'orgao_julgador', None), getattr(process, 'section', None)):
        cleaned = str(value or '').strip()
        if cleaned and cleaned.lower() not in ('none', 'null'):
            return cleaned
    return None


def build_reference_search_context(process) -> dict:
    judge = str(getattr(process, 'judge_name', '') or '').strip() or None
    orgao = orgao_julgador_from_process(process)
    return {
        'trf_region': trf_region_from_process(process),
        'orgao_julgador': orgao,
        'orgao_julgador_norm': normalize_context_value(orgao) or None,
        'judge_name': judge,
        'judge_name_norm': normalize_context_value(judge) or None,
    }
