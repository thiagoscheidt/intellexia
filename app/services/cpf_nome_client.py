"""Consulta de nome por CPF — todo acesso ao fornecedor fica aqui.

Hoje é a API CPF Brasil (``api.cpf-brasil.org``): ``GET /cpf/{cpf}`` com o
header ``X-API-Key``. Trocar de fornecedor (SERPRO, por exemplo) é reescrever
este arquivo mantendo ``consultar_nome`` e ``CpfNomeIndisponivel`` — serviço,
telas e tabela não mudam.

O fornecedor devolve também sexo e nome da mãe. Duas saídas, de propósito:

- ``consultar_nome`` (botão "Revelar nome", ``revelar_nome_segurado``): **só
  nome e nascimento**; o resto é descartado aqui (LGPD: o mínimo necessário).
- ``consultar_completo`` (ferramenta ``consultar_cpf`` e
  ``POST /api/v1/segurados/consultar-cpf``): a resposta **inteira**, como o
  fornecedor manda — decisão do Thiago em 22/10/2026. Vai só para quem pediu:
  nada dela é gravado no banco nem no log.

Config só no ``.env`` (o token nunca vai para o banco nem para o código):
    CPF_NOME_API_KEY   token do fornecedor — em branco desativa o botão
    CPF_NOME_API_URL   padrão https://api.cpf-brasil.org
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime

import requests

logger = logging.getLogger(__name__)

FONTE = 'cpf_brasil'
TIMEOUT = (5, 20)


class CpfNomeIndisponivel(Exception):
    """Falha que não diz nada sobre o CPF: token, cota, fornecedor fora do ar.

    ``mensagem`` já vem escrita para a tela; nada disso é gravado, para a
    próxima tentativa consultar de novo.
    """

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


@dataclass
class ResultadoNome:
    encontrado: bool
    nome: str | None = None
    nascimento: date | None = None


def configurado() -> bool:
    return bool((os.getenv('CPF_NOME_API_KEY') or '').strip())


def _nascimento(texto) -> date | None:
    try:
        return datetime.strptime(str(texto or '').strip()[:10], '%d/%m/%Y').date()
    except ValueError:
        return None


@dataclass
class ResultadoCompleto:
    encontrado: bool
    dados: dict


def consultar_nome(cpf: str) -> ResultadoNome:
    """Nome e nascimento do CPF (11 dígitos). Levanta ``CpfNomeIndisponivel``."""
    dados = _consultar(cpf)
    nome = (dados.get('NOME') or '').strip() if dados else ''
    if not nome:
        return ResultadoNome(encontrado=False)
    return ResultadoNome(encontrado=True, nome=nome, nascimento=_nascimento(dados.get('NASC')))


def consultar_completo(cpf: str) -> ResultadoCompleto:
    """Tudo o que o fornecedor devolve para o CPF (11 dígitos), sem filtrar campo.

    Levanta ``CpfNomeIndisponivel``. ``dados`` vazio = não encontrado.
    """
    dados = _consultar(cpf)
    if not dados:
        return ResultadoCompleto(encontrado=False, dados={})
    return ResultadoCompleto(encontrado=True, dados=dados)


def _consultar(cpf: str) -> dict | None:
    """O ``data`` da resposta do fornecedor; ``None`` quando o CPF não existe lá."""
    token = (os.getenv('CPF_NOME_API_KEY') or '').strip()
    if not token:
        raise CpfNomeIndisponivel('Consulta de nome não configurada nesta instalação.')
    base = (os.getenv('CPF_NOME_API_URL') or 'https://api.cpf-brasil.org').rstrip('/')

    try:
        resp = requests.get(f'{base}/cpf/{cpf}', headers={'X-API-Key': token}, timeout=TIMEOUT)
    except requests.RequestException as e:
        logger.warning('Consulta de nome por CPF falhou na rede: %s', e)
        raise CpfNomeIndisponivel('O serviço de consulta de CPF não respondeu. Tente de novo em alguns minutos.')

    try:
        corpo = resp.json()
    except ValueError:
        corpo = {}
    codigo = corpo.get('code') if isinstance(corpo, dict) else None

    if resp.status_code == 404 or codigo == 'CPF_NOT_FOUND':
        return None
    if resp.ok and isinstance(corpo, dict) and corpo.get('success'):
        dados = corpo.get('data')
        return dados if isinstance(dados, dict) and dados else None

    logger.warning('Consulta de nome por CPF: HTTP %s, código %s', resp.status_code, codigo)
    mensagens = {
        'QUOTA_EXCEEDED': 'A cota mensal de consultas de CPF acabou. Fale com o administrador.',
        'TOKEN_EXPIRED': 'O token da consulta de CPF venceu (expira a cada 30 dias). Fale com o administrador.',
        'INVALID_API_KEY': 'O token da consulta de CPF é inválido. Fale com o administrador.',
        'MISSING_API_KEY': 'O token da consulta de CPF é inválido. Fale com o administrador.',
        'PLAN_EXPIRED': 'O plano da consulta de CPF venceu. Fale com o administrador.',
        'PLAN_SUSPENDED': 'O plano da consulta de CPF está suspenso. Fale com o administrador.',
    }
    raise CpfNomeIndisponivel(mensagens.get(
        codigo, f'O serviço de consulta de CPF está indisponível agora (HTTP {resp.status_code}).'))
