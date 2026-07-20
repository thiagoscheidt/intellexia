"""
Cliente da API pública do Comunica PJe (DJEN — Diário de Justiça Eletrônico Nacional).

API REST sem autenticação usada pelo portal https://comunica.pje.jus.br.
Não é documentada oficialmente pelo CNJ, então TODO o acesso fica isolado aqui:
se o CNJ mudar parâmetros ou schema, só este arquivo muda.

Endpoint principal:
    GET {base}/comunicacao
        pagina, itensPorPagina (máx. 100)
        numeroOab + ufOab            → radar por advogado
        numeroProcesso               → histórico de um processo (só dígitos)
        dataDisponibilizacaoInicio / dataDisponibilizacaoFim (YYYY-MM-DD)
        siglaTribunal, nomeParte, nomeAdvogado, meio

Resposta: {"status": ..., "count": N, "items": [...]}
"""
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

COMUNICA_PJE_API_URL = os.getenv('COMUNICA_PJE_API_URL', 'https://comunicaapi.pje.jus.br/api/v1')

MAX_ITENS_POR_PAGINA = 100
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2.0
REQUEST_TIMEOUT = 30


class ComunicaPjeError(Exception):
    """Erro de comunicação com a API do Comunica PJe (após esgotar retries)."""


def only_digits(value: Optional[str]) -> str:
    """Número CNJ (ou OAB) apenas com dígitos — formato que a API espera."""
    return re.sub(r'\D', '', value or '')


class ComunicaPjeClient:
    """Cliente HTTP do Comunica PJe, no molde do DataJudAPI."""

    def __init__(self, base_url: Optional[str] = None, pause_seconds: float = 0.5):
        self.base_url = (base_url or COMUNICA_PJE_API_URL).rstrip('/')
        # Pausa entre requisições paginadas — a API aplica rate limit (429)
        self.pause_seconds = pause_seconds
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})

    # ------------------------------------------------------------------ HTTP

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET com backoff exponencial para 429/5xx. Levanta ComunicaPjeError no fim."""
        url = f'{self.base_url}{path}'
        clean_params = {k: v for k, v in params.items() if v not in (None, '')}

        last_error: Optional[str] = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, params=clean_params, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_error = f'Falha de rede: {exc}'
                logger.warning('Comunica PJe: %s (tentativa %d/%d)', last_error, attempt + 1, MAX_RETRIES)
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise ComunicaPjeError(f'Resposta não é JSON válido: {exc}') from exc
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f'HTTP {response.status_code}'
                    logger.warning('Comunica PJe: %s em %s (tentativa %d/%d)',
                                   last_error, url, attempt + 1, MAX_RETRIES)
                else:
                    raise ComunicaPjeError(f'HTTP {response.status_code}: {response.text[:300]}')

            time.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))

        raise ComunicaPjeError(f'Esgotadas {MAX_RETRIES} tentativas em {url} ({last_error})')

    # ----------------------------------------------------------------- API

    def get_comunicacoes(self,
                         numero_oab: Optional[str] = None,
                         uf_oab: Optional[str] = None,
                         numero_processo: Optional[str] = None,
                         data_inicio: Optional[date] = None,
                         data_fim: Optional[date] = None,
                         sigla_tribunal: Optional[str] = None,
                         pagina: int = 1,
                         itens_por_pagina: int = MAX_ITENS_POR_PAGINA) -> Dict[str, Any]:
        """Uma página de comunicações. Retorna o payload cru da API."""
        params = {
            'pagina': pagina,
            'itensPorPagina': min(itens_por_pagina, MAX_ITENS_POR_PAGINA),
            'numeroOab': only_digits(numero_oab) or None,
            'ufOab': (uf_oab or '').strip().upper() or None,
            'numeroProcesso': only_digits(numero_processo) or None,
            'siglaTribunal': sigla_tribunal,
            'dataDisponibilizacaoInicio': data_inicio.isoformat() if data_inicio else None,
            'dataDisponibilizacaoFim': data_fim.isoformat() if data_fim else None,
        }
        return self._get('/comunicacao', params)

    def iter_comunicacoes(self, **kwargs) -> Iterator[Dict[str, Any]]:
        """Itera todas as comunicações de uma consulta, encapsulando a paginação.

        Aceita os mesmos argumentos de ``get_comunicacoes`` (exceto ``pagina``).
        """
        kwargs.pop('pagina', None)
        itens_por_pagina = kwargs.pop('itens_por_pagina', MAX_ITENS_POR_PAGINA)

        pagina = 1
        while True:
            payload = self.get_comunicacoes(pagina=pagina, itens_por_pagina=itens_por_pagina, **kwargs)
            items = self._extract_items(payload)
            if not items:
                return
            yield from items
            if len(items) < itens_por_pagina:
                return
            pagina += 1
            time.sleep(self.pause_seconds)

    def get_comunicacoes_processo(self, numero_processo: str) -> List[Dict[str, Any]]:
        """Histórico completo de comunicações de um processo (todas as páginas)."""
        return list(self.iter_comunicacoes(numero_processo=numero_processo))

    # -------------------------------------------------------------- parsing

    @staticmethod
    def _extract_items(payload: Any) -> List[Dict[str, Any]]:
        """Lista de itens do payload, tolerante a variações de envelope."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ('items', 'itens', 'content', 'data'):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def parse_comunicacao(item: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza um item da API para o formato do ProcessCommunication.

        Parse tolerante: campo ausente vira None — nunca derruba o batch.
        O item cru completo é preservado em ``raw_json`` pelo chamador.
        """
        def _get(*keys):
            for key in keys:
                value = item.get(key)
                if value not in (None, ''):
                    return value
            return None

        data_disp = _get('data_disponibilizacao', 'dataDisponibilizacao', 'datadisponibilizacao')
        parsed_date = None
        if data_disp:
            try:
                parsed_date = date.fromisoformat(str(data_disp)[:10])
            except ValueError:
                logger.warning('Comunica PJe: data inválida %r', data_disp)

        advogados = []
        for entry in item.get('destinatarioadvogados') or []:
            adv = (entry or {}).get('advogado') or {}
            if adv:
                advogados.append({
                    'nome': adv.get('nome'),
                    'numero_oab': adv.get('numero_oab'),
                    'uf_oab': adv.get('uf_oab'),
                })

        destinatarios = [
            {'nome': d.get('nome'), 'polo': d.get('polo')}
            for d in (item.get('destinatarios') or []) if isinstance(d, dict)
        ]

        comunica_id = _get('id')
        try:
            comunica_id = int(comunica_id) if comunica_id is not None else None
        except (TypeError, ValueError):
            comunica_id = None

        return {
            'comunica_id': comunica_id,
            'hash': _get('hash'),
            'sigla_tribunal': _get('siglaTribunal', 'sigla_tribunal'),
            'tipo_comunicacao': _get('tipoComunicacao', 'tipo_comunicacao'),
            'tipo_documento': _get('tipoDocumento', 'tipo_documento'),
            'nome_orgao': _get('nomeOrgao', 'nome_orgao'),
            'nome_classe': _get('nomeClasse', 'nome_classe'),
            'codigo_classe': _get('codigoClasse', 'codigo_classe'),
            'meio': _get('meio', 'meiocompleto'),
            'data_disponibilizacao': parsed_date,
            'numero_processo': only_digits(_get('numero_processo', 'numeroProcesso')) or None,
            'numero_processo_mascara': _get('numeroprocessocommascara', 'numeroProcessoComMascara'),
            'texto': _get('texto'),
            'link': _get('link'),
            'destinatarios_json': destinatarios or None,
            'advogados_json': advogados or None,
        }
