"""Consulta do FAP no portal FAP Web — os insumos de cada cálculo.

A tela "Consulta do FAP" do portal mostra, por estabelecimento e vigência, o
FAP e os itens que entraram no cálculo; cada número da tela é um link que
chama a API abaixo. Endereços medidos em 20/10/2026 (ver
docs/superpowers/specs/2026-10-20-fap-beneficios-do-calculo-design.md).

Usa a mesma sessão e o mesmo ``_get`` do ``FapWebService`` (cookie do
``FAP_AUTH_JSON``), sem modificá-lo. Todas as funções devolvem
``FapWebResult``:

- 401 → ``expired=True`` (sessão do gov.br caiu; nada adianta seguir);
- 403 → sem acesso àquela empresa — sessão parcial (sem ``empresasVinculadas``)
  ou sem procuração; as outras empresas continuam;
- 404 → lista vazia: a raiz ou o estabelecimento não tem cálculo na vigência.

O portal manda CNPJ como número; aqui eles voltam com os zeros (E01 da R09).
"""

from __future__ import annotations

import json
import urllib.error

from app.services.fap_web_service import _BASE_URL, FapWebResult
from app.utils.cnpj import TAMANHO_CNPJ, completar_zeros

API = f'{_BASE_URL}/gateway/fap/v1'
REFERER = f'{_BASE_URL}/consultar-fap'
# /calculos já levou 34 s no portal (medido na contagem de 2026).
TIMEOUT = 60


def _consultar(svc, caminho: str) -> FapWebResult:
    try:
        body, _ = svc._get(f'{API}{caminho}', timeout=TIMEOUT, referer=REFERER)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return FapWebResult(ok=True, data=[], status_code=404)
        if e.code == 401:
            return FapWebResult(ok=False, expired=True, status_code=401,
                                message='Sessão FAP expirada (HTTP 401). Atualize o FAP_AUTH_JSON.')
        if e.code == 403:
            return FapWebResult(ok=False, status_code=403,
                                message='Sem acesso (HTTP 403): sessão parcial ou sem procuração.')
        return FapWebResult(ok=False, status_code=e.code, message=f'Erro HTTP {e.code} no portal FAP.')
    except Exception as e:  # rede, timeout
        # URLError embrulha a causa (timeout, conexão recusada); sem ela o log não diz qual foi.
        causa = getattr(e, 'reason', None)
        detalhe = f' ({causa})' if causa else ''
        return FapWebResult(ok=False, message=f'Falha de rede no portal FAP: {type(e).__name__}{detalhe}')
    try:
        return FapWebResult(ok=True, data=json.loads(body.decode('utf-8')))
    except ValueError:
        return FapWebResult(ok=False, message='Resposta do portal FAP não é JSON.')


def listar_anos(svc) -> FapWebResult:
    return _consultar(svc, '/vigencias/anos')


def listar_estabelecimentos(svc, ano: int, raiz8: str) -> FapWebResult:
    r = _consultar(svc, f'/vigencias/{ano}/empresa/{raiz8}/estabelecimentos')
    if r.ok:
        r.data = [completar_zeros(c, TAMANHO_CNPJ) for c in (r.data or [])]
    return r


def listar_calculos(svc, ano: int, cnpj14: str) -> FapWebResult:
    return _consultar(svc, f'/vigencias/{ano}/empresa/{cnpj14}/calculos')


def listar_beneficios(svc, ano: int, cnpj14: str, calculo_id: int) -> FapWebResult:
    # A barra final importa: sem a espécie, vêm B91, B92, B93 e B94 de uma vez.
    return _consultar(svc, f'/vigencias/{ano}/empresa/{cnpj14}/calculos/{calculo_id}/beneficios/')


def listar_cats(svc, ano: int, cnpj14: str, calculo_id: int) -> FapWebResult:
    return _consultar(svc, f'/vigencias/{ano}/empresa/{cnpj14}/calculos/{calculo_id}/cats')
