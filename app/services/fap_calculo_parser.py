"""Respostas da Consulta do FAP → dicts prontos para gravar. Funções puras.

O portal manda CNPJ, CPF e NB como número (o zero à esquerda some), datas
``YYYY-MM-DD`` e valores como string decimal (``"1598.72"``).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CPF, apenas_digitos, completar_zeros

_QUANTIDADES = ('quantidadeB91', 'quantidadeB92', 'quantidadeB93', 'quantidadeB94', 'quantidadeCat')


def _data(valor) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _decimal(valor) -> Decimal | None:
    if valor is None or valor == '':
        return None
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return None


def _digitos(valor) -> str | None:
    d = apenas_digitos(None if valor is None else str(valor))
    return d or None


def resumir_calculos(calculos: list[dict]) -> dict:
    """Histórico do ``/calculos`` → cálculo atual, original e se há itens.

    O portal devolve eventos (sem ``id``, ex. início do efeito suspensivo) e
    cálculos (com ``id``), o mais recente primeiro. ``tem_itens`` olha todos os
    cálculos: depois de uma contestação ganha o atual pode ter quantidade zero
    e ainda listar os itens como EXCLUIDO.
    """
    com_id = [c for c in (calculos or []) if c.get('id')]
    if not com_id:
        return {'atual_id': None, 'atual_tipo': None, 'atual_data': None, 'original_id': None,
                'tem_itens': False, 'historico': [], 'protocolo': None}
    atual = com_id[0]
    original = next((c for c in com_id if c.get('tipoProcessamento') == 'CALCULO_ORIGINAL'), com_id[-1])
    return {
        'atual_id': atual['id'],
        'atual_tipo': atual.get('tipoProcessamento'),
        'atual_data': _data(atual.get('dataProcessamento')),
        'original_id': original['id'],
        'tem_itens': any(sum(int(c.get(q) or 0) for q in _QUANTIDADES) > 0 for c in com_id),
        'historico': [{'id': c['id'], 'tipo': c.get('tipoProcessamento'), 'data': c.get('dataProcessamento')}
                      for c in com_id],
        'protocolo': atual.get('protocolo'),
    }


def normalizar_beneficio(d: dict) -> dict:
    """Um item de ``/calculos/{id}/beneficios/`` (B91–B94)."""
    return {
        'tipo': d.get('especie'),
        'identificador': _digitos(d.get('nb')),
        'nit': _digitos(d.get('nit')),
        'cpf': completar_zeros(d.get('cpf'), TAMANHO_CPF),
        'data_nascimento': _data(d.get('dataNascimento')),
        'cnpj': completar_zeros(d.get('cnpj'), TAMANHO_CNPJ),
        'valor_mensal': _decimal(d.get('valorMensal')),
        'total_pago': _decimal(d.get('totalPago')),
        'data_despacho': _data(d.get('dataDespacho')),
        'data_inicio': _data(d.get('dataInicio')),
        'data_cessacao': _data(d.get('dataCessacao')),
        'data_inicio_contabilizacao': _data(d.get('dataInicioContabilizacao')),
        'data_fim_contabilizacao': _data(d.get('dataFimContabilizacao')),
        'meses_contabilizacao': _decimal(d.get('mesesContabilizacao')),
        'bloqueio': bool(d.get('bloqueio')),
        'estado_atual': d.get('estado'),
        'raw_json': json.dumps(d, ensure_ascii=False),
    }


def normalizar_cat(d: dict) -> dict:
    """Um item de ``/calculos/{id}/cats``."""
    return {
        'tipo': 'CAT',
        'identificador': _digitos(d.get('numeroCat')),
        'nit': _digitos(d.get('nit')),
        'cpf': completar_zeros(d.get('cpf'), TAMANHO_CPF),
        'data_nascimento': _data(d.get('dataNascimento')),
        'cnpj_original': completar_zeros(d.get('cnpjOriginal'), TAMANHO_CNPJ),
        'cnpj_atribuido': completar_zeros(d.get('cnpjAtribuido'), TAMANHO_CNPJ),
        'data_acidente': _data(d.get('dataAcidente')),
        'data_cadastro_cat': _data(d.get('dataCadastroCat')),
        'data_obito': _data(d.get('dataObito')),
        'recibo_esocial': d.get('reciboEsocial'),
        'bloqueio': bool(d.get('bloqueio')),
        'estado_atual': d.get('estado'),
        'raw_json': json.dumps(d, ensure_ascii=False),
    }
