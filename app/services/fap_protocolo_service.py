"""
Protocolo administrativo da contestação FAP — busca única para tela e MCP.

O protocolo (NUP, ex.: ``10128.053144/2025-42``) identifica a contestação no
FAP Web; a de 1ª e a de 2ª instância compartilham o mesmo número. Os
benefícios não guardam protocolo: pertencem à vigência (CNPJ + ano), e é por
ela que se chega do protocolo aos benefícios.

Fonte única de:
- filtro por protocolo da tela de Benefícios (Central de Contestações);
- ``listar_contestacoes_fap`` e ``listar_beneficios_fap`` do MCP.
Tela e IA têm de devolver o mesmo número para o mesmo protocolo.
"""
from sqlalchemy import String, cast, func

from app.models import FapVigenciaCnpj, FapWebContestacao, db


def digitos(texto):
    """Só os dígitos do protocolo ('' se vazio)."""
    return ''.join(ch for ch in (texto or '') if ch.isdigit())


def _cnpj14(cnpj):
    """CNPJ em 14 dígitos — mesma normalização da sincronização do FAP Web.

    `FapWebContestacao.cnpj` é gravado com zero à esquerda e
    `FapVigenciaCnpj.employer_cnpj` só existe com 14 dígitos: normalizar os dois
    lados pela mesma regra é o que faz o par (CNPJ, ano) casar.
    """
    d = digitos(cnpj)
    if not d:
        return ''
    return d.zfill(14) if len(d) <= 14 else d


def _protocolo_normalizado():
    col = cast(FapWebContestacao.protocolo, String)
    for sep in ('.', '/', '-', ' '):
        col = func.replace(col, sep, '')
    return col


def contestacoes_query(law_firm_id, protocolo_texto):
    """Contestações do escritório cujo protocolo contém os dígitos informados.

    Aceita com ou sem máscara, completo ou só um trecho do número (LIKE nos
    dígitos). Devolve None quando o texto não tem dígito (não filtrar).
    """
    d = digitos(protocolo_texto)
    if not d:
        return None
    return FapWebContestacao.query.filter(
        FapWebContestacao.law_firm_id == law_firm_id,
        _protocolo_normalizado().like(f'%{d}%'),
    )


def vigencia_ids(law_firm_id, protocolo_texto):
    """Ids de vigência (CNPJ + ano) das contestações com esse protocolo.

    Devolve None quando não há termo (não filtrar) e [] quando o termo não casa
    com nada (filtrar para vazio, em vez de ignorar o filtro).
    """
    query = contestacoes_query(law_firm_id, protocolo_texto)
    if query is None:
        return None

    pares = {
        (_cnpj14(cnpj), str(ano or '').strip())
        for cnpj, ano in query.with_entities(FapWebContestacao.cnpj, FapWebContestacao.ano_vigencia)
    }
    if not pares:
        return []

    # O par (CNPJ, ano) é resolvido em Python: `ano_vigencia` é inteiro e
    # `vigencia_year` é texto, e o CNPJ precisa da mesma normalização da
    # sincronização — comparar direto no SQL dependeria de cast frágil.
    return [
        vigencia_id
        for vigencia_id, cnpj, ano in db.session.query(
            FapVigenciaCnpj.id,
            FapVigenciaCnpj.employer_cnpj,
            FapVigenciaCnpj.vigencia_year,
        ).filter(FapVigenciaCnpj.law_firm_id == law_firm_id)
        if (_cnpj14(cnpj), str(ano or '').strip()) in pares
    ]
