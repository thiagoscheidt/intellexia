"""A Base de Jurisprudência na geração da impugnação.

Duas pontas, uma fonte:
- `sugestoes_por_tese`: o passo "Documentos e referências" do wizard mostra,
  para cada tese do catálogo selecionada, as decisões da base a citar — as do
  mesmo TRF, favoráveis, de instância mais alta e mais recentes primeiro — e
  deixa o advogado marcar.
- `bloco_do_prompt`: o que foi marcado vai ao agente gerador, agrupado por
  tese, com a citação pronta. Decisão desfavorável marcada vai rotulada
  CONTRÁRIA: serve para antecipar e rebater o entendimento, nunca para citar a
  favor.

A escolha viaja em `confirmed_documents_json['jurisprudence']` da versão, como
pares {decision_id, thesis_id} — sem coluna nova.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from app.models import (
    db,
    JudicialLegalThesis,
    JurisprudenceDecision,
    JurisprudenceThesis,
    jurisprudence_decision_theses,
    jurisprudence_thesis_catalog_links,
)
from app.services import jurisprudence_normalizer as norm
from app.services.jurisprudence_search_service import resumo_para_geracao

MARCADAS_POR_PADRAO = 3
MAX_A_FAVOR = 8
MAX_CONTRARIAS = 2
EMENTA_MAX = 1500


def _peso_instancia(d: JurisprudenceDecision) -> int:
    """Força da decisão como precedente citado."""
    if d.tribunal in ('STF', 'STJ') and d.tipo_documento == norm.TIPO_ACORDAO:
        return 4
    if d.tipo_documento == norm.TIPO_ACORDAO:
        return 3
    if d.tipo_documento == norm.TIPO_SENTENCA:
        return 2
    return 1


def decisoes_por_tese_do_catalogo(law_firm_id: int, catalogo_ids: Iterable[int]) -> dict[int, list[JurisprudenceDecision]]:
    catalogo_ids = [int(i) for i in catalogo_ids if i]
    if not catalogo_ids:
        return {}
    linhas = (db.session.query(jurisprudence_thesis_catalog_links.c.legal_thesis_id, JurisprudenceDecision)
              .join(JurisprudenceThesis, JurisprudenceThesis.id == jurisprudence_thesis_catalog_links.c.thesis_id)
              .join(jurisprudence_decision_theses,
                    jurisprudence_decision_theses.c.thesis_id == JurisprudenceThesis.id)
              .join(JurisprudenceDecision, JurisprudenceDecision.id == jurisprudence_decision_theses.c.decision_id)
              .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                      JurisprudenceDecision.law_firm_id == law_firm_id,
                      jurisprudence_thesis_catalog_links.c.legal_thesis_id.in_(catalogo_ids))
              .all())
    por_tese: dict[int, dict[int, JurisprudenceDecision]] = {}
    for catalogo_id, decisao in linhas:
        por_tese.setdefault(catalogo_id, {})[decisao.id] = decisao
    return {k: list(v.values()) for k, v in por_tese.items()}


def _contexto(process) -> dict:
    try:
        from app.agents.legal_drafting.impugnacao_process_context import build_reference_search_context
        ctx = build_reference_search_context(process)
    except Exception:
        ctx = {}
    return {
        'trf': (ctx.get('trf_region') or norm.regiao_do_processo(getattr(process, 'process_number', '')) or '').upper(),
        'orgao': norm.chave(ctx.get('orgao_julgador') or ''),
    }


def ordenar_para_citar(decisoes: list[JurisprudenceDecision], contexto: dict) -> list[JurisprudenceDecision]:
    def chave(d):
        mesmo_trf = bool(contexto.get('trf')) and (d.tribunal or '').upper() == contexto['trf']
        mesma_vara = bool(contexto.get('orgao')) and norm.chave(d.orgao_julgador or '') == contexto['orgao']
        return (
            -norm.RESULTADO_PESO.get(d.resultado, -1),
            -(mesmo_trf or d.tribunal in ('STF', 'STJ')),
            -_peso_instancia(d),
            -mesma_vara,
            -(d.data_julgamento or date.min).toordinal(),
            d.id,
        )
    return sorted(decisoes, key=chave)


def sugestoes_por_tese(law_firm_id: int, process, catalogo_ids: Iterable[int]) -> list[dict]:
    catalogo_ids = [int(i) for i in dict.fromkeys(catalogo_ids) if i]
    if not catalogo_ids:
        return []
    nomes = {t.id: t.name for t in JudicialLegalThesis.query.filter(
        JudicialLegalThesis.law_firm_id == law_firm_id, JudicialLegalThesis.id.in_(catalogo_ids)).all()}
    por_tese = decisoes_por_tese_do_catalogo(law_firm_id, catalogo_ids)
    contexto = _contexto(process)
    saida = []
    for catalogo_id in sorted(catalogo_ids, key=lambda i: nomes.get(i, '')):
        if catalogo_id not in nomes:
            continue
        ordenadas = ordenar_para_citar(por_tese.get(catalogo_id, []), contexto)
        a_favor = [d for d in ordenadas if d.resultado != norm.RESULTADO_DESFAVORAVEL][:MAX_A_FAVOR]
        contrarias = [d for d in ordenadas if d.resultado == norm.RESULTADO_DESFAVORAVEL][:MAX_CONTRARIAS]
        itens = []
        for pos, d in enumerate(a_favor + contrarias):
            item = resumo_para_geracao(d)
            item['marcada'] = d in a_favor and pos < MARCADAS_POR_PADRAO
            item['contraria'] = d.resultado == norm.RESULTADO_DESFAVORAVEL
            item['mesmo_trf'] = bool(contexto['trf']) and (d.tribunal or '').upper() == contexto['trf']
            item['mesma_vara'] = bool(contexto['orgao']) and norm.chave(d.orgao_julgador or '') == contexto['orgao']
            itens.append(item)
        saida.append({
            'thesis_id': catalogo_id,
            'tese': nomes[catalogo_id],
            'total_na_base': len(ordenadas),
            'decisoes': itens,
        })
    return saida


# ── Escolha confirmada → prompt ───────────────────────────────────────

def pares_do_formulario(valores: Iterable[str]) -> list[dict]:
    """ "decisao:tese" (tese pode faltar) → [{'decision_id', 'thesis_id'}]."""
    pares, vistos = [], set()
    for bruto in valores:
        partes = str(bruto).split(':', 1)
        try:
            decisao = int(partes[0])
            tese = int(partes[1]) if len(partes) > 1 and partes[1] else None
        except ValueError:
            continue
        if decisao > 0 and (decisao, tese) not in vistos:
            vistos.add((decisao, tese))
            pares.append({'decision_id': decisao, 'thesis_id': tese})
    return pares


def pares_confirmados(confirmed) -> Optional[list[dict]]:
    if not isinstance(confirmed, dict) or not isinstance(confirmed.get('jurisprudence'), list):
        return None
    return [p for p in confirmed['jurisprudence']
            if isinstance(p, dict) and isinstance(p.get('decision_id'), int)]


def carregar(law_firm_id: int, pares: list[dict]) -> list[tuple[JurisprudenceDecision, Optional[str]]]:
    """Pares → [(decisão, nome da tese)], só do escritório (nunca expor outro tenant)."""
    ids = {p['decision_id'] for p in pares}
    if not ids:
        return []
    decisoes = {d.id: d for d in JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id, JurisprudenceDecision.id.in_(ids)).all()}
    tese_ids = {p['thesis_id'] for p in pares if p.get('thesis_id')}
    nomes = {t.id: t.name for t in JudicialLegalThesis.query.filter(
        JudicialLegalThesis.law_firm_id == law_firm_id, JudicialLegalThesis.id.in_(tese_ids)).all()} if tese_ids else {}
    return [(decisoes[p['decision_id']], nomes.get(p.get('thesis_id'))) for p in pares if p['decision_id'] in decisoes]


def _linhas_da_decisao(n: int, d: JurisprudenceDecision) -> list[str]:
    contraria = d.resultado == norm.RESULTADO_DESFAVORAVEL
    rotulo = 'CONTRÁRIA — use para antecipar e rebater; NÃO cite a favor' if contraria \
        else norm.RESULTADO_LABELS.get(d.resultado or '', 'resultado não informado').upper()
    linhas = [f'{n}. {norm.citacao(d)} — {rotulo}']
    if d.motivo_resultado:
        linhas.append(f'   Por que: {d.motivo_resultado.strip()}')
    acolhidos = (d.argumentos_acolhidos_json or [])[:4]
    if acolhidos:
        linhas.append('   Acolheu: ' + '; '.join(acolhidos))
    if contraria and d.argumentos_rejeitados_json:
        linhas.append('   Rejeitou: ' + '; '.join((d.argumentos_rejeitados_json or [])[:4]))
    if d.ementa:
        ementa = d.ementa.strip()
        if len(ementa) > EMENTA_MAX:
            ementa = ementa[:EMENTA_MAX].rsplit(' ', 1)[0] + ' [...]'
        if d.ementa_modo == 'resumo':
            linhas.append(f'   Ementa (RESUMO — não transcrever como se fosse literal): {ementa}')
        else:
            linhas.append(f'   Ementa (transcrição literal): {ementa}')
    return linhas


def bloco_do_prompt(law_firm_id: int, pares: Optional[list[dict]]) -> str:
    """Texto que entra no prompt do gerador. Vazio quando nada foi marcado."""
    escolhidas = carregar(law_firm_id, pares or [])
    if not escolhidas:
        return ''
    grupos: dict[str, list[JurisprudenceDecision]] = {}
    for decisao, tese in escolhidas:
        grupos.setdefault(tese or 'Geral', [])
        if decisao not in grupos[tese or 'Geral']:
            grupos[tese or 'Geral'].append(decisao)
    linhas = [
        '=== JURISPRUDÊNCIA SELECIONADA PELO ADVOGADO (base de decisões do escritório) ===',
        'Use estas decisões como precedentes na tese indicada. Cite pela referência exatamente como '
        'está entre parênteses: não altere número, órgão, relator ou data, e não invente precedente que '
        'não esteja aqui ou no catálogo. Ementa marcada como RESUMO não pode ser transcrita entre aspas. '
        'Decisão marcada CONTRÁRIA serve para antecipar o entendimento desfavorável e rebatê-lo.',
    ]
    for tese, decisoes in grupos.items():
        linhas.append('')
        linhas.append(f'[Tese: {tese}]')
        for n, d in enumerate(decisoes, start=1):
            linhas.extend(_linhas_da_decisao(n, d))
    return '\n'.join(linhas)
