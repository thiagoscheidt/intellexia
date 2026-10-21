"""Nome do segurado por CPF — fonte única do botão "Revelar nome", das telas e do MCP.

O FAP não informa nome: relatório e Consulta do FAP trazem CPF, NIT e
nascimento. O nome vem de uma consulta paga por CPF (``cpf_nome_client``) e
fica guardado em ``segurado_nomes``, uma linha por (escritório, CPF), para
nenhuma tela consultar de novo o que alguém já revelou.

Regras:
- Só se consulta CPF que **existe na base do escritório** (benefício da Central
  ou item do cálculo FAP). Sem isso o botão viraria consulta avulsa de
  qualquer CPF, paga pelo escritório e sem relação com o trabalho.
- CPF com dígito verificador inválido não vai ao fornecedor (paga e não acha).
- "Não encontrado" também é guardado — a mesma pergunta não é paga duas vezes.
- Falha de token, cota ou rede **não** é guardada: a próxima tentativa consulta.
- A data de nascimento do fornecedor é comparada com a do FAP. Divergiu, o
  nome é guardado com ``nascimento_diverge`` e as telas avisam: pode ser outra
  pessoa, e o advogado decide se usa.
- Nada aqui cruza ``segurado_nomes`` com ``benefits`` por JOIN de texto: as
  buscas são por lista de CPFs, sem depender de collation igual nas tabelas.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models import Benefit, FapCalculoItem, SeguradoNome, db
from app.services import cpf_nome_client
from app.utils.cnpj import TAMANHO_CPF, completar_zeros, cpf_valido, formatar_cpf


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalizar_cpf(cpf) -> str | None:
    digitos = completar_zeros(cpf, TAMANHO_CPF)
    return digitos if digitos and len(digitos) == TAMANHO_CPF else None


def disponivel() -> bool:
    """O botão só aparece com o fornecedor configurado no ``.env``."""
    return cpf_nome_client.configurado()


def _serializar(reg: SeguradoNome | None) -> dict | None:
    if reg is None:
        return None
    return {
        'cpf': reg.cpf,
        'status': reg.status,
        'nome': reg.nome,
        'nascimento_diverge': bool(reg.nascimento_diverge),
        'consultado_em': reg.consultado_em.isoformat() if reg.consultado_em else None,
    }


def nomes_conhecidos(law_firm_id: int, cpfs) -> dict[str, dict]:
    """``{cpf 11 dígitos: registro}`` do que já foi revelado — uma query por lista."""
    chaves = {c for c in (normalizar_cpf(x) for x in cpfs or []) if c}
    if not chaves:
        return {}
    regs = SeguradoNome.query.filter(
        SeguradoNome.law_firm_id == law_firm_id, SeguradoNome.cpf.in_(chaves)).all()
    return {r.cpf: _serializar(r) for r in regs}


def nome_conhecido(law_firm_id: int, cpf) -> str | None:
    """Nome guardado para o CPF, ou ``None`` (não revelado ou não encontrado)."""
    reg = nomes_conhecidos(law_firm_id, [cpf]).get(normalizar_cpf(cpf) or '')
    return reg['nome'] if reg and reg['status'] == SeguradoNome.STATUS_ENCONTRADO else None


def cpfs_por_nome(law_firm_id: int, termo: str, limite: int = 200) -> list[str]:
    """CPFs cujo nome revelado contém ``termo`` — para a busca por nome do MCP."""
    termo = (termo or '').strip()
    if not termo:
        return []
    rows = (SeguradoNome.query.with_entities(SeguradoNome.cpf)
            .filter(SeguradoNome.law_firm_id == law_firm_id,
                    SeguradoNome.status == SeguradoNome.STATUS_ENCONTRADO,
                    SeguradoNome.nome.ilike(f'%{termo}%'))
            .limit(limite).all())
    return [r[0] for r in rows]


def _nascimento_na_base(law_firm_id: int, cpf: str):
    """(o CPF é do escritório?, nascimento que o FAP informou)."""
    ben = (Benefit.query.with_entities(Benefit.insured_date_of_birth)
           .filter(Benefit.law_firm_id == law_firm_id,
                   Benefit.insured_cpf.in_({cpf, formatar_cpf(cpf)}))
           .order_by(Benefit.insured_date_of_birth.is_(None)).first())
    item = (FapCalculoItem.query.with_entities(FapCalculoItem.data_nascimento)
            .filter(FapCalculoItem.law_firm_id == law_firm_id, FapCalculoItem.cpf == cpf)
            .order_by(FapCalculoItem.data_nascimento.is_(None)).first())
    if ben is None and item is None:
        return False, None
    return True, (item[0] if item and item[0] else None) or (ben[0] if ben else None)


class NomeNaoRevelavel(Exception):
    """Pedido recusado antes de ir ao fornecedor; ``mensagem`` vai para a tela."""

    def __init__(self, mensagem: str, status_http: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_http = status_http


ORIGEM_TELA = 'tela'
ORIGEM_MCP = 'mcp'


def limite_diario_mcp() -> int:
    """Consultas pagas por usuário por dia (de São Paulo) pelo Claude/MCP."""
    try:
        return max(0, int(os.getenv('CPF_NOME_LIMITE_DIARIO_MCP', '30')))
    except ValueError:
        return 30


def _inicio_do_dia_utc():
    from app.utils.timezone import now_sp

    inicio = now_sp().replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio.astimezone(timezone.utc).replace(tzinfo=None)


def consultas_mcp_hoje(law_firm_id: int, user_id: int | None) -> int:
    """Consultas pagas que o usuário fez hoje pelo MCP — o que já estava salvo não conta."""
    if not user_id:
        return 0
    return SeguradoNome.query.filter(
        SeguradoNome.law_firm_id == law_firm_id,
        SeguradoNome.consultado_por_id == user_id,
        SeguradoNome.origem == ORIGEM_MCP,
        SeguradoNome.consultado_em >= _inicio_do_dia_utc(),
    ).count()


def revelar(law_firm_id: int, cpf, user_id: int | None, origem: str = ORIGEM_TELA) -> dict:
    """Devolve o nome do CPF, consultando o fornecedor só se ainda não foi revelado.

    Pelo MCP (``origem='mcp'``) vale o limite diário por usuário
    (``CPF_NOME_LIMITE_DIARIO_MCP``): uma pergunta mal entendida não pode virar
    centenas de consultas pagas. Nome já salvo não conta no limite.

    Levanta ``NomeNaoRevelavel`` (pedido inválido ou limite) ou
    ``cpf_nome_client.CpfNomeIndisponivel`` (fornecedor/token/cota).
    """
    chave = normalizar_cpf(cpf)
    if not chave or not cpf_valido(chave):
        raise NomeNaoRevelavel('CPF inválido.')

    existente = SeguradoNome.query.filter_by(law_firm_id=law_firm_id, cpf=chave).first()
    if existente:
        return {**_serializar(existente), 'ja_revelado': True}

    eh_do_escritorio, nascimento_fap = _nascimento_na_base(law_firm_id, chave)
    if not eh_do_escritorio:
        raise NomeNaoRevelavel('Este CPF não está entre os segurados do escritório.', 404)

    if origem == ORIGEM_MCP and consultas_mcp_hoje(law_firm_id, user_id) >= limite_diario_mcp():
        raise NomeNaoRevelavel(
            f'Limite diário de {limite_diario_mcp()} consultas de nome pelo Claude atingido para '
            'este usuário. Amanhã libera de novo; pela tela de Benefícios (botão "Revelar nome") '
            'continua disponível.', 429)

    resultado = cpf_nome_client.consultar_nome(chave)
    reg = SeguradoNome(
        law_firm_id=law_firm_id,
        cpf=chave,
        nome=resultado.nome if resultado.encontrado else None,
        status=(SeguradoNome.STATUS_ENCONTRADO if resultado.encontrado
                else SeguradoNome.STATUS_NAO_ENCONTRADO),
        nascimento_diverge=bool(
            resultado.encontrado and nascimento_fap and resultado.nascimento
            and resultado.nascimento != nascimento_fap),
        fonte=cpf_nome_client.FONTE,
        origem=origem,
        consultado_por_id=user_id,
        consultado_em=_utcnow(),
    )
    db.session.add(reg)
    try:
        db.session.commit()
    except IntegrityError:
        # Duas pessoas clicaram ao mesmo tempo: vale o que entrou primeiro.
        db.session.rollback()
        reg = SeguradoNome.query.filter_by(law_firm_id=law_firm_id, cpf=chave).first()
    return {**_serializar(reg), 'ja_revelado': False}


def resposta_revelar(law_firm_id: int, cpf, user_id: int | None) -> tuple[dict, int]:
    """(JSON, status HTTP) do botão — as duas telas usam a mesma resposta."""
    try:
        return {'ok': True, **revelar(law_firm_id, cpf, user_id)}, 200
    except NomeNaoRevelavel as e:
        return {'ok': False, 'message': e.mensagem}, e.status_http
    except cpf_nome_client.CpfNomeIndisponivel as e:
        return {'ok': False, 'message': e.mensagem}, 503
