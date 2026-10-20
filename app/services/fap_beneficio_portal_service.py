"""Completa os benefícios da Central com os dados da Consulta do FAP.

E02 e E04 da Remessa R09: o relatório de julgamento importado não traz CPF, e
o parser dele não lê RMI nem total pago — os benefícios ficavam com segurado
"Não informado" e total pago R$ 0. A Consulta do FAP tem tudo isso por
benefício.

Cada benefício da Central já está ligado a uma vigência (``fap_vigencia_cnpjs``:
CNPJ do estabelecimento + ano), então a rota se monta sem procurar nada: o
``/calculos`` dá o cálculo atual e o ``/calculos/{id}/beneficios/`` traz os
benefícios dele — inclusive os EXCLUIDO no recálculo. Duas chamadas por
vigência, não por benefício.

Regras (desenho de 20/10/2026): CPF e nascimento o portal sobrescreve sempre —
o dado é dele; RMI e total pago só preenchem o que está vazio. Nada é apagado.

``buscar_vigencia`` só vai à rede (segura em thread); ``aplicar`` só mexe no
banco (fluxo principal) — a mesma divisão do ``fap_sync_cron``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services import fap_calculo_client as client
from app.services import fap_calculo_parser as parser
from app.utils.cnpj import apenas_digitos


@dataclass
class BuscaVigencia:
    ano: int
    cnpj: str
    situacao: str  # ok | sem_calculo | sem_acesso | expirada | erro
    itens: dict[str, dict] = field(default_factory=dict)  # NB sem zeros à esquerda → item normalizado
    erro: str = ''


def chave_nb(numero) -> str:
    return apenas_digitos(None if numero is None else str(numero)).lstrip('0')


def _falha(ano, cnpj14, r) -> BuscaVigencia:
    if r.expired:
        return BuscaVigencia(ano, cnpj14, 'expirada', erro=r.message)
    if r.status_code == 403:
        return BuscaVigencia(ano, cnpj14, 'sem_acesso', erro=r.message)
    return BuscaVigencia(ano, cnpj14, 'erro', erro=r.message)


def _juntar(destino: dict, r, procurados: set[str]) -> None:
    for bruto in r.data or []:
        item = parser.normalizar_beneficio(bruto)
        chave = chave_nb(item['identificador'])
        if chave in procurados and chave not in destino:
            destino[chave] = item


def buscar_vigencia(svc, ano: int, cnpj14: str, nbs: set[str]) -> BuscaVigencia:
    """Benefícios da vigência que interessam (``nbs``), do cálculo atual.

    NB que não aparece no atual é procurado no cálculo original antes de
    desistir. Só os NBs pedidos são guardados — o resto do cálculo (benefícios
    que a Central não tem) fica para a sincronização completa.
    """
    procurados = {chave_nb(n) for n in nbs if chave_nb(n)}
    r = client.listar_calculos(svc, ano, cnpj14)
    if not r.ok:
        return _falha(ano, cnpj14, r)
    resumo = parser.resumir_calculos(r.data)
    if not resumo['atual_id']:
        return BuscaVigencia(ano, cnpj14, 'sem_calculo')

    itens: dict[str, dict] = {}
    r = client.listar_beneficios(svc, ano, cnpj14, resumo['atual_id'])
    if not r.ok:
        return _falha(ano, cnpj14, r)
    _juntar(itens, r, procurados)

    if procurados - set(itens) and resumo['original_id'] != resumo['atual_id']:
        r = client.listar_beneficios(svc, ano, cnpj14, resumo['original_id'])
        if not r.ok:
            return _falha(ano, cnpj14, r)
        _juntar(itens, r, procurados)
    return BuscaVigencia(ano, cnpj14, 'ok', itens)


def aplicar(law_firm_id: int, vigencia_id: int, busca: BuscaVigencia) -> dict:
    """Grava nos benefícios da vigência o que veio do portal. Não faz commit.

    Devolve quantos campos mudaram (rodar de novo dá zero).
    """
    from app.models import Benefit

    conta = {'beneficios': 0, 'cpf': 0, 'nascimento': 0, 'rmi': 0, 'total_pago': 0, 'nao_encontrados': 0}
    beneficios = Benefit.query.filter_by(law_firm_id=law_firm_id, fap_vigencia_cnpj_id=vigencia_id).all()
    for b in beneficios:
        conta['beneficios'] += 1
        item = busca.itens.get(chave_nb(b.benefit_number))
        if item is None:
            conta['nao_encontrados'] += 1
            continue
        if item['cpf'] and b.insured_cpf != item['cpf']:
            b.insured_cpf = item['cpf']
            conta['cpf'] += 1
        if item['data_nascimento'] and b.insured_date_of_birth != item['data_nascimento']:
            b.insured_date_of_birth = item['data_nascimento']
            conta['nascimento'] += 1
        if b.initial_monthly_benefit is None and item['valor_mensal'] is not None:
            b.initial_monthly_benefit = item['valor_mensal']
            conta['rmi'] += 1
        if b.total_paid is None and item['total_pago'] is not None:
            b.total_paid = item['total_pago']
            conta['total_pago'] += 1
    return conta
