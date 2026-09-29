"""
Sincronização das empresas do Painel FAP (``fap_companies``) — fonte única.

Usada pelo cron (``scripts/fap_sync_cron.py``), pelo botão do Painel FAP e pela
importação automática da Central de Contestações.

A lista espelha o seletor "CNPJ Raiz" da tela de contestações do portal, que é a
**união** de duas origens:

* ``/procuracoes/empresas`` — empresas com procuração eletrônica no FAP;
* ``empresasVinculadas`` do ``/oauth2/token`` — empresas vinculadas ao CPF do
  login no gov.br, com ou sem procuração.

Só a primeira era lida, e o grupo Vale (VALE S.A., Salobo, Onça Puma…), que o
escritório acessa por vínculo, nunca entrou na sincronização de contestações —
embora a API devolva as contestações delas normalmente (medido em 29/09/2026:
16 vinculadas, 9 delas sem procuração).

**Poda só com as duas listas completas.** As vinculadas somem da sessão algumas
horas depois do login (``ACCESSTOKEN_MUSTBENOTEXPIRED``); podar com a lista
parcial apagaria justamente as empresas que só existem por vínculo.
"""

from __future__ import annotations

from datetime import datetime


def ultima_sincronizacao(law_firm_id: int):
    """``synced_at`` da sincronização mais recente — todas as empresas de uma
    execução recebem o mesmo instante."""
    from app.models import db, FapCompany
    from sqlalchemy import func

    return (
        db.session.query(func.max(FapCompany.synced_at))
        .filter(FapCompany.law_firm_id == law_firm_id)
        .scalar()
    )


def por_vinculo(company, ultima_sync) -> bool:
    """Empresa que está na lista só pelo vínculo gov.br — para exibição.

    Sem coluna de origem, a regra é: sem tipo de procuração **e** presente na
    última sincronização. A empresa que perde a procuração e fica só por ter
    contestação não é mais tocada, então mantém o tipo antigo e o ``synced_at``
    velho — não cai aqui. Se a última execução pegou a sessão parcial, as
    vinculadas não foram tocadas e o rótulo some até a próxima execução completa.
    """
    return (
        not (company.tipo_procuracao_descricao or company.tipo_procuracao_codigo)
        and ultima_sync is not None
        and company.synced_at == ultima_sync
    )


def unir_empresas(procuracoes: list, vinculadas: list) -> list[dict]:
    """Une as duas origens por CNPJ raiz — função pura.

    A procuração tem prioridade: traz o tipo de procuração, que a vinculada não
    tem. A vinculada só entra quando a raiz não veio pela procuração.
    """
    por_cnpj: dict[str, dict] = {}
    for item in procuracoes or []:
        cnpj = str(item.get('cnpj') or '').strip()
        if cnpj:
            por_cnpj[cnpj] = item
    for item in vinculadas or []:
        cnpj = str(item.get('cnpj') or '').strip()
        if cnpj and cnpj not in por_cnpj:
            por_cnpj[cnpj] = {'cnpj': cnpj, 'nome': item.get('nome') or '', 'tipoProcuracao': None}
    return list(por_cnpj.values())


def sync_companies(svc, law_firm_id: int) -> dict:
    """Busca as duas origens no portal e faz o upsert em ``fap_companies``.

    Empresa que não veio mais só é removida se não tiver contestação vinculada
    (FK em ``fap_web_contestacoes.fap_company_id``) e se a lista de vinculadas
    veio completa.

    Returns:
        dict com ``ok``, ``message``, ``companies`` (lista unida), ``total``,
        ``procuracoes``, ``so_vinculo``, ``vinculadas_ok``, ``vinculadas_msg``,
        ``removed``.
    """
    from app.models import db, FapCompany, FapWebContestacao

    result = svc.fetch_companies()
    if not result.ok:
        return {'ok': False, 'message': result.message, 'result': result}
    procuracoes = result.data if isinstance(result.data, list) else []

    vinc = svc.fetch_empresas_vinculadas()
    vinculadas = vinc.data if vinc.ok and isinstance(vinc.data, list) else []

    companies = unir_empresas(procuracoes, vinculadas)
    cnpjs_procuracao = {str(i.get('cnpj') or '').strip() for i in procuracoes}
    so_vinculo = sum(1 for c in companies if c['cnpj'] not in cnpjs_procuracao)

    now = datetime.now()  # horário local (synced_at é exibido cru)
    seen_cnpjs: set[str] = set()
    for item in companies:
        cnpj = item['cnpj']
        seen_cnpjs.add(cnpj)
        tipo = item.get('tipoProcuracao') or {}
        nome = (item.get('nome') or '').strip()
        rec = FapCompany.query.filter_by(law_firm_id=law_firm_id, cnpj=cnpj).first()
        if rec:
            rec.nome = nome or rec.nome
            rec.tipo_procuracao_codigo = tipo.get('codigo')
            rec.tipo_procuracao_descricao = tipo.get('descricao')
            rec.synced_at = now
        else:
            db.session.add(FapCompany(
                law_firm_id=law_firm_id,
                cnpj=cnpj,
                nome=nome,
                tipo_procuracao_codigo=tipo.get('codigo'),
                tipo_procuracao_descricao=tipo.get('descricao'),
                synced_at=now,
            ))

    removed = 0
    if seen_cnpjs and vinc.ok:
        stale = FapCompany.query.filter(
            FapCompany.law_firm_id == law_firm_id,
            FapCompany.cnpj.notin_(seen_cnpjs),
        ).all()
        for comp in stale:
            tem_contestacao = db.session.query(FapWebContestacao.id).filter_by(
                law_firm_id=law_firm_id, fap_company_id=comp.id,
            ).first()
            if tem_contestacao:
                continue  # mantém: empresa com histórico de contestações
            db.session.delete(comp)
            removed += 1

    db.session.commit()
    return {
        'ok': True,
        'message': '',
        'companies': companies,
        'total': len(seen_cnpjs),
        'procuracoes': len(seen_cnpjs) - so_vinculo,
        'so_vinculo': so_vinculo,
        'vinculadas_ok': vinc.ok,
        'vinculadas_msg': vinc.message,
        'removed': removed,
    }
