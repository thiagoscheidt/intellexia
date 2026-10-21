"""
Tools: Insights e busca cruzada — prazos/alertas, comparação de vigências e
visão 360º por segurado.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.utils.cnpj import link_consulta_cpf_receita


def _iso(value):
    return value.isoformat() if value else None


def _decided(status: str | None) -> bool:
    """Status de instância que representa uma decisão (deferido/indeferido)."""
    if not status:
        return False
    s = status.lower()
    return "defer" in s or "indefer" in s  # deferido / indeferido / parcialmente...


# ── Prazos e alertas ──────────────────────────────────────────────────────────


def prazos_e_alertas_handler(law_firm_id: int, modules: list[str], dias: int = 30) -> dict:
    """Itens que pedem atenção: contestações aguardando resultado, decisões
    recentes (janela de recurso) e processos por fase."""
    from app.models import Benefit, FapWebContestacao, JudicialProcess

    since = datetime.now() - timedelta(days=dias)

    # Contestações transmitidas, ainda sem resultado publicado
    aguardando = (
        FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
        .filter(FapWebContestacao.situacao_codigo == "LIBERADA_PARA_ANALISE")
        .order_by(FapWebContestacao.data_transmissao.asc())
    )
    aguardando_itens = [
        {
            "contestacao_id": c.contestacao_id,
            "cnpj": c.cnpj,
            "ano_vigencia": c.ano_vigencia,
            "instancia": c.instancia_descricao,
            "data_transmissao": _iso(c.data_transmissao),
        }
        for c in aguardando.limit(100).all()
    ]

    # Benefícios com decisão registrada recentemente (possível janela de recurso)
    recentes_q = (
        Benefit.query.filter_by(law_firm_id=law_firm_id)
        .filter(Benefit.updated_at >= since)
        .order_by(Benefit.updated_at.desc())
    )
    decisoes_recentes = []
    for b in recentes_q.limit(200).all():
        if _decided(b.first_instance_status) or _decided(b.second_instance_status):
            decisoes_recentes.append({
                "id": b.id,
                "numero_beneficio": b.benefit_number,
                "segurado_nome": b.insured_name,
                "empregador_nome": b.employer_name,
                "status_primeira_instancia": b.first_instance_status,
                "status_segunda_instancia": b.second_instance_status,
                "atualizado_em": _iso(b.updated_at),
            })
        if len(decisoes_recentes) >= 50:
            break

    resultado = {
        "janela_dias": dias,
        "contestacoes_aguardando_resultado": {
            "total": aguardando.count(),
            "itens": aguardando_itens,
        },
        "decisoes_recentes": {
            "total": len(decisoes_recentes),
            "itens": decisoes_recentes,
        },
    }

    # Processos por fase — apenas se o usuário tem o módulo
    if "process_panel" in modules:
        processos = JudicialProcess.query.filter_by(law_firm_id=law_firm_id).all()
        por_fase: dict[str, int] = {}
        for p in processos:
            fase = p.phase_history[0].phase.name if (p.phase_history and p.phase_history[0].phase) else "(sem fase)"
            por_fase[fase] = por_fase.get(fase, 0) + 1
        resultado["processos_por_fase"] = {
            "total": len(processos),
            "distribuicao": dict(sorted(por_fase.items(), key=lambda kv: -kv[1])),
        }

    return resultado


# ── Comparar vigências ────────────────────────────────────────────────────────


def comparar_vigencias_handler(
    law_firm_id: int,
    vigencias: list[str],
    empresa: str | None = None,
    cnpj: str | None = None,
) -> dict:
    """Compara resultados de benefícios entre vigências FAP (deferido/indeferido
    por instância e tópicos de contestação)."""
    from app.models import Benefit
    from mcp_server.tools.fap import _filter_benefit_cnpj, _filter_benefit_empresa, _parse_topics

    comparativo = {}
    for vig in vigencias:
        q = Benefit.query.filter_by(law_firm_id=law_firm_id).filter(
            Benefit.fap_vigencia_years.like(f"%{vig}%")
        )
        if cnpj:
            q = _filter_benefit_cnpj(q, cnpj)
        if empresa:
            q = _filter_benefit_empresa(q, empresa, law_firm_id)

        beneficios = q.all()
        deferidos = sum(1 for b in beneficios if _decided(b.first_instance_status) and "defer" in (b.first_instance_status or "").lower() and "indefer" not in (b.first_instance_status or "").lower())
        indeferidos = sum(1 for b in beneficios if "indefer" in (b.first_instance_status or "").lower())
        aguardando = sum(1 for b in beneficios if not _decided(b.first_instance_status))

        topicos: dict[str, int] = {}
        total_pago = 0.0
        for b in beneficios:
            for t in _parse_topics(b):
                topicos[t] = topicos.get(t, 0) + 1
            if b.total_paid is not None:
                total_pago += float(b.total_paid)

        comparativo[str(vig)] = {
            "total_beneficios": len(beneficios),
            "primeira_instancia": {
                "deferidos": deferidos,
                "indeferidos": indeferidos,
                "aguardando_ou_outros": aguardando,
            },
            "total_pago_em_disputa": round(total_pago, 2),
            "topicos_contestacao": dict(sorted(topicos.items(), key=lambda kv: -kv[1])),
        }

    return {
        "filtros": {"empresa": empresa, "cnpj": cnpj},
        "vigencias_comparadas": list(comparativo.keys()),
        "comparativo": comparativo,
    }


# ── Buscar por segurado (visão 360º) ──────────────────────────────────────────


def buscar_por_segurado_handler(
    law_firm_id: int,
    modules: list[str],
    nit: str | None = None,
    cpf: str | None = None,
    nome: str | None = None,
) -> dict:
    """Reúne benefícios, CATs e (se permitido) processos de um segurado."""
    from app.models import Benefit, FapContestationCat, JudicialProcessBenefit
    from app.services import segurado_nome_service
    from mcp_server.tools.fap import AVISO_SEM_NOME, _parse_topics, cpf_condicao, nome_condicao

    if not any([nit, cpf, nome]):
        return {"erro": "Informe ao menos um identificador: nit, cpf ou nome."}

    # Benefícios
    bq = Benefit.query.filter_by(law_firm_id=law_firm_id)
    if nit:
        bq = bq.filter(Benefit.insured_nit == nit)
    if cpf:
        bq = bq.filter(cpf_condicao(Benefit.insured_cpf, cpf))
    if nome:
        bq = bq.filter(nome_condicao(law_firm_id, nome))
    encontrados = bq.order_by(Benefit.created_at.desc()).limit(50).all()
    revelados = segurado_nome_service.nomes_conhecidos(
        law_firm_id, [b.insured_cpf for b in encontrados if not b.insured_name])
    beneficios = [
        {
            "id": b.id,
            "numero_beneficio": b.benefit_number,
            "tipo_beneficio": b.benefit_type,
            "segurado_nome": b.insured_name or (revelados.get(
                segurado_nome_service.normalizar_cpf(b.insured_cpf) or '') or {}).get("nome"),
            "segurado_nit": b.insured_nit,
            "segurado_cpf": b.insured_cpf,
            "segurado_data_nascimento": _iso(b.insured_date_of_birth),
            "consulta_cpf_receita": link_consulta_cpf_receita(b.insured_cpf, b.insured_date_of_birth),
            "empregador_nome": b.employer_name,
            "empregador_cnpj": b.employer_cnpj,
            "vigencias_fap": b.fap_vigencia_years,
            "topicos_contestacao": _parse_topics(b),
            "status_primeira_instancia": b.first_instance_status,
            "status_segunda_instancia": b.second_instance_status,
            "total_pago": float(b.total_paid) if b.total_paid is not None else None,
        }
        for b in encontrados
    ]

    # CAT e processo não têm CPF: o elo é o NIT. Pedido só por CPF usa os NITs
    # dos benefícios daquele CPF — antes a consulta de CAT ia sem filtro e
    # devolvia 30 CATs quaisquer do escritório.
    nits = {nit} if nit else {b.insured_nit for b in encontrados if cpf and b.insured_nit}

    # CATs (mesmo domínio FAP; exige módulo de contestações)
    cats = []
    if "disputes_center" in modules and nits:
        cq = FapContestationCat.query.filter_by(law_firm_id=law_firm_id).filter(
            FapContestationCat.insured_nit.in_(nits))
        cats = [
            {
                "numero_cat": c.cat_number,
                "empregador_nome": c.employer_name,
                "data_acidente": _iso(c.accident_date),
                "status_primeira_instancia": c.first_instance_status,
            }
            for c in cq.order_by(FapContestationCat.accident_date.desc()).limit(30).all()
        ]

    # Processos judiciais vinculados (só se permitido)
    processos = []
    if "process_panel" in modules and nits:
        pbq = (
            JudicialProcessBenefit.query
            .join(JudicialProcessBenefit.process)
            .filter(JudicialProcessBenefit.nit_number.in_(nits))
        )
        for pb in pbq.limit(30).all():
            proc = pb.process
            if proc and proc.law_firm_id == law_firm_id:
                processos.append({
                    "processo_id": proc.id,
                    "numero_processo": proc.process_number,
                    "titulo": proc.title,
                    "status": proc.status,
                    "numero_beneficio": pb.benefit_number,
                })

    resultado = {
        "identificadores": {"nit": nit, "cpf": cpf, "nome": nome},
        "beneficios": {"total": len(beneficios), "itens": beneficios},
        "cats": {"total": len(cats), "itens": cats},
        "processos": {"total": len(processos), "itens": processos},
    }
    # Base do cálculo FAP (Consulta do portal): acha o segurado que não tem
    # contestação na Central. Só por CPF/NIT; o nome não existe nessa base.
    # A tool já exige o módulo fap_panel.
    if cpf or nit:
        from mcp_server.tools.fap_calculo import itens_do_segurado

        resultado["beneficios_calculo_fap"] = itens_do_segurado(law_firm_id, cpf, nit, limite=30)
    if nome:
        resultado["aviso"] = AVISO_SEM_NOME
    return resultado
