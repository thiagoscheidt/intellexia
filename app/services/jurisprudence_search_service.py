"""Pesquisa na Base de Jurisprudência — fonte única da tela de busca e da
busca avulsa do passo de geração.

**Sem Meilisearch, de propósito.** A escala é de centenas a poucos milhares de
decisões por escritório: ler as colunas leves e filtrar em Python custa
milissegundos, funciona igual no SQLite e no MySQL e não deixa índice nenhum
para reconstruir ou sair de sincronia com o banco.

Semântica herdada da ferramenta que os advogados já usavam: **todos** os termos
precisam aparecer (E), cada um expandido pelos sinônimos, em qualquer campo.
Número de processo é reconhecido com ou sem pontuação.

As facetas são disjuntivas: a contagem de cada dimensão considera os filtros
das **outras** dimensões — marcar TRF4 não zera a contagem de TRF3.
"""
from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.models import db, JudicialLegalThesis, JurisprudenceDecision, JurisprudenceThesis
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as svc

ORDENS = {
    'recentes': 'Julgadas mais recentemente',
    'instancia': 'Instância mais alta primeiro',
    'favoraveis': 'Favoráveis primeiro',
}
POR_PAGINA = 20


@dataclass
class Filtros:
    q: str = ''
    catalogo: list[int] = field(default_factory=list)   # JudicialLegalThesis.id
    teses: list[int] = field(default_factory=list)      # JurisprudenceThesis.id
    resultados: list[str] = field(default_factory=list)
    tribunais: list[str] = field(default_factory=list)
    tipos: list[str] = field(default_factory=list)
    uf: str = ''
    vigencia: Optional[int] = None
    de: Optional[date] = None
    ate: Optional[date] = None
    ordem: str = 'recentes'
    agrupar: str = 'processo'
    pagina: int = 1

    @classmethod
    def do_request(cls, args) -> 'Filtros':
        def inteiros(nome):
            saida = []
            for valor in args.getlist(nome):
                try:
                    saida.append(int(valor))
                except (TypeError, ValueError):
                    continue
            return saida

        def mes(nome, fim=False):
            valor = (args.get(nome) or '').strip()
            m = re.match(r'^(\d{4})-(\d{2})$', valor)
            if not m:
                return norm.para_data(valor)
            ano, mes_ = int(m.group(1)), int(m.group(2))
            if not 1 <= mes_ <= 12:
                return None
            if not fim:
                return date(ano, mes_, 1)
            proximo = date(ano + (mes_ == 12), mes_ % 12 + 1, 1)
            return date.fromordinal(proximo.toordinal() - 1)

        try:
            vigencia = int(args.get('vigencia')) if args.get('vigencia') else None
        except ValueError:
            vigencia = None
        try:
            pagina = max(1, int(args.get('pagina') or 1))
        except ValueError:
            pagina = 1
        ordem = args.get('ordem') if args.get('ordem') in ORDENS else 'recentes'
        return cls(
            q=(args.get('q') or '').strip()[:300],
            catalogo=inteiros('tese'),
            teses=inteiros('tese_livre'),
            resultados=[r for r in args.getlist('resultado') if r in norm.RESULTADO_LABELS],
            tribunais=[t for t in args.getlist('tribunal') if t][:20],
            tipos=[t for t in args.getlist('tipo') if t in norm.TIPO_LABELS],
            uf=(args.get('uf') or '').strip().upper()[:2],
            vigencia=vigencia,
            de=mes('de'),
            ate=mes('ate', fim=True),
            ordem=ordem,
            agrupar='decisao' if args.get('agrupar') == 'decisao' else 'processo',
            pagina=pagina,
        )

    @property
    def ativos(self) -> bool:
        return bool(self.q or self.catalogo or self.teses or self.resultados or self.tribunais
                    or self.tipos or self.uf or self.vigencia or self.de or self.ate)


@dataclass
class _Linha:
    id: int
    processo_digits: Optional[str]
    tribunal: Optional[str]
    uf: Optional[str]
    tipo: Optional[str]
    resultado: Optional[str]
    data: Optional[date]
    vig_ini: Optional[int]
    vig_fim: Optional[int]
    texto: str
    teses: set
    catalogo: set

    @property
    def grupo(self) -> str:
        return self.processo_digits or f'id:{self.id}'


def _carregar(law_firm_id: int) -> list[_Linha]:
    teses_da_decisao = svc.teses_por_decisao(law_firm_id)
    catalogo_da_tese = svc.catalogo_por_tese(law_firm_id)
    linhas = []
    for (d_id, digits, tribunal, uf, tipo, resultado, data_j, vi, vf, texto) in db.session.query(
            JurisprudenceDecision.id, JurisprudenceDecision.processo_digits,
            JurisprudenceDecision.tribunal, JurisprudenceDecision.uf,
            JurisprudenceDecision.tipo_documento, JurisprudenceDecision.resultado,
            JurisprudenceDecision.data_julgamento, JurisprudenceDecision.vigencia_inicio,
            JurisprudenceDecision.vigencia_fim, JurisprudenceDecision.search_text,
    ).filter(JurisprudenceDecision.law_firm_id == law_firm_id).all():
        teses = set(teses_da_decisao.get(d_id, []))
        catalogo = set()
        for tese_id in teses:
            catalogo.update(catalogo_da_tese.get(tese_id, []))
        linhas.append(_Linha(d_id, digits, tribunal, uf, tipo, resultado, data_j, vi, vf,
                             texto or '', teses, catalogo))
    return linhas


def _casa_texto(linha: _Linha, consulta: str, termos: list[list[str]]) -> bool:
    if not consulta:
        return True
    if norm.parece_numero_de_processo(consulta):
        return bool(linha.processo_digits) and norm.digitos(consulta) in linha.processo_digits
    return all(any(t in linha.texto for t in grupo) for grupo in termos)


def _passa(linha: _Linha, f: Filtros, exceto: Optional[str] = None) -> bool:
    if f.vigencia and not (linha.vig_ini and linha.vig_fim and linha.vig_ini <= f.vigencia <= linha.vig_fim):
        return False
    if f.de and (not linha.data or linha.data < f.de):
        return False
    if f.ate and (not linha.data or linha.data > f.ate):
        return False
    if exceto != 'catalogo' and f.catalogo and not (linha.catalogo & set(f.catalogo)):
        return False
    if exceto != 'teses' and f.teses and not (linha.teses & set(f.teses)):
        return False
    if exceto != 'resultado' and f.resultados and linha.resultado not in f.resultados:
        return False
    if exceto != 'tribunal' and f.tribunais and linha.tribunal not in f.tribunais:
        return False
    if exceto != 'tipo' and f.tipos and linha.tipo not in f.tipos:
        return False
    if exceto != 'uf' and f.uf and linha.uf != f.uf:
        return False
    return True


def _contar(linhas, chave) -> dict:
    contagem: dict = {}
    for linha in linhas:
        valores = chave(linha)
        for valor in (valores if isinstance(valores, (set, list)) else [valores]):
            if valor:
                contagem[valor] = contagem.get(valor, 0) + 1
    return contagem


def _nomes(law_firm_id: int) -> tuple[dict, dict]:
    catalogo = {t.id: t.name for t in JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id).all()}
    teses = {t.id: t.name for t in JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).all()}
    return catalogo, teses


def _ordenar_grupos(grupos: dict, linhas_por_id: dict, ordem: str) -> list[str]:
    def chave(nome):
        linhas = [linhas_por_id[i] for i in grupos[nome]]
        mais_recente = max((l.data for l in linhas if l.data), default=date.min)
        if ordem == 'instancia':
            return (-max(norm.TIPO_ORDEM.get(l.tipo, -1) if l.tipo != norm.TIPO_OUTRA else -1 for l in linhas),
                    -mais_recente.toordinal())
        if ordem == 'favoraveis':
            return (-max(norm.RESULTADO_PESO.get(l.resultado, -1) for l in linhas), -mais_recente.toordinal())
        return (-mais_recente.toordinal(),)
    return sorted(grupos, key=chave)


# ── Trecho destacado ──────────────────────────────────────────────────

def _normalizar_com_mapa(texto: str) -> tuple[str, list[int]]:
    """Texto em forma de busca + mapa de cada caractere de volta ao original.

    Sem o mapa, uma ligadura ou um "º" antes do achado deslocaria o recorte.
    """
    saida, mapa = [], []
    for i, c in enumerate(texto):
        for n in norm.sem_acento(c).lower():
            saida.append(' ' if n.isspace() else n)
            mapa.append(i)
    return ''.join(saida), mapa


def trecho(texto: Optional[str], termos: list[list[str]], janela: int = 170) -> Optional[str]:
    """Janela do texto em volta do primeiro achado, escapada e com <mark>."""
    if not texto:
        return None
    if not termos:
        corte = texto[:janela * 2]
        return html.escape(corte) + ('…' if len(texto) > len(corte) else '')
    normal, mapa = _normalizar_com_mapa(texto)
    faixas = []
    for grupo in termos:
        for termo in grupo:
            for m in re.finditer(re.escape(termo), normal):
                faixas.append((mapa[m.start()], mapa[m.end() - 1] + 1))
    if not faixas:
        return None
    faixas.sort()
    unidas = [list(faixas[0])]
    for ini, fim in faixas[1:]:
        if ini <= unidas[-1][1]:
            unidas[-1][1] = max(unidas[-1][1], fim)
        else:
            unidas.append([ini, fim])
    inicio = max(0, unidas[0][0] - janela)
    fim = min(len(texto), unidas[0][1] + janela)
    partes, cursor = [], inicio
    for ini, f in unidas:
        if ini < inicio or f > fim:
            continue
        partes.append(html.escape(texto[cursor:ini]))
        partes.append(f'<mark>{html.escape(texto[ini:f])}</mark>')
        cursor = f
    partes.append(html.escape(texto[cursor:fim]))
    return ('…' if inicio > 0 else '') + ''.join(partes) + ('…' if fim < len(texto) else '')


def trecho_da_decisao(decisao: JurisprudenceDecision, termos: list[list[str]]) -> Optional[str]:
    for campo in (decisao.motivo_resultado, decisao.resumo_executivo, decisao.ementa):
        achado = trecho(campo, termos)
        if achado and (not termos or '<mark>' in achado):
            return achado
    return trecho(decisao.motivo_resultado or decisao.resumo_executivo, [])


# ── Busca ──────────────────────────────────────────────────────────────

def buscar(law_firm_id: int, f: Filtros, por_pagina: int = POR_PAGINA) -> dict:
    todas = _carregar(law_firm_id)
    termos = [] if norm.parece_numero_de_processo(f.q) else norm.termos_da_consulta(f.q)
    candidatas = [l for l in todas if _casa_texto(l, f.q, termos)]
    finais = [l for l in candidatas if _passa(l, f)]

    nomes_catalogo, nomes_teses = _nomes(law_firm_id)
    facetas = {
        'catalogo': _contar([l for l in candidatas if _passa(l, f, 'catalogo')], lambda l: l.catalogo),
        'teses': _contar([l for l in candidatas if _passa(l, f, 'teses')], lambda l: l.teses),
        'resultado': _contar([l for l in candidatas if _passa(l, f, 'resultado')], lambda l: l.resultado),
        'tribunal': _contar([l for l in candidatas if _passa(l, f, 'tribunal')], lambda l: l.tribunal),
        'tipo': _contar([l for l in candidatas if _passa(l, f, 'tipo')], lambda l: l.tipo),
        'uf': _contar([l for l in candidatas if _passa(l, f, 'uf')], lambda l: l.uf),
    }
    anos_vigencia = sorted({a for l in todas if l.vig_ini and l.vig_fim
                            for a in range(l.vig_ini, l.vig_fim + 1)}, reverse=True)

    resultados = _contar(finais, lambda l: l.resultado)
    total = len(finais)
    exito = [
        {'resultado': r, 'rotulo': norm.RESULTADO_LABELS_CURTOS[r], 'n': resultados.get(r, 0),
         'pct': (100.0 * resultados.get(r, 0) / total) if total else 0}
        for r in (norm.RESULTADO_FAVORAVEL, norm.RESULTADO_PARCIAL, norm.RESULTADO_DESFAVORAVEL)
    ]

    linhas_por_id = {l.id: l for l in finais}
    grupos: dict[str, list[int]] = {}
    for linha in finais:
        grupos.setdefault(linha.grupo, []).append(linha.id)

    if f.agrupar == 'decisao':
        ordem_ids = [i for g in _ordenar_grupos(grupos, linhas_por_id, f.ordem)
                     for i in sorted(grupos[g], key=lambda i: linhas_por_id[i].data or date.min, reverse=True)]
        paginas = max(1, math.ceil(len(ordem_ids) / por_pagina))
        pagina = min(f.pagina, paginas)
        ids_da_pagina = ordem_ids[(pagina - 1) * por_pagina: pagina * por_pagina]
        grupos_da_pagina = [[i] for i in ids_da_pagina]
    else:
        ordem_grupos = _ordenar_grupos(grupos, linhas_por_id, f.ordem)
        paginas = max(1, math.ceil(len(ordem_grupos) / por_pagina))
        pagina = min(f.pagina, paginas)
        grupos_da_pagina = [grupos[g] for g in ordem_grupos[(pagina - 1) * por_pagina: pagina * por_pagina]]

    cartoes = _montar_cartoes(law_firm_id, grupos_da_pagina, f, termos,
                              completar_processo=(f.agrupar != 'decisao'))

    return {
        'total': total,
        'processos': len(grupos),
        'exito': exito,
        'facetas': facetas,
        'nomes_catalogo': nomes_catalogo,
        'nomes_teses': nomes_teses,
        'anos_vigencia': anos_vigencia,
        'cartoes': cartoes,
        'pagina': pagina,
        'paginas': paginas,
        'termos': termos,
    }


def virou_no_acordao(trilha: list) -> bool:
    """Sentença perdida (ou parcial) e acórdão melhor depois dela — é o
    precedente mais forte de citar, então o cartão ganha selo."""
    sentencas = [d for d in trilha if d.tipo_documento == norm.TIPO_SENTENCA and d.resultado]
    acordaos = [d for d in trilha if d.tipo_documento == norm.TIPO_ACORDAO and d.resultado]
    return any(
        norm.RESULTADO_PESO[a.resultado] > norm.RESULTADO_PESO[s.resultado]
        and (not s.data_julgamento or not a.data_julgamento or a.data_julgamento >= s.data_julgamento)
        for s in sentencas for a in acordaos
    )


def _montar_cartoes(law_firm_id: int, grupos: list[list[int]], f: Filtros,
                    termos: list[list[str]], completar_processo: bool) -> list[dict]:
    """Um cartão por processo (ou por decisão), com a trilha completa."""
    ids = {i for g in grupos for i in g}
    if not ids:
        return []
    achadas = {d.id: d for d in JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id, JurisprudenceDecision.id.in_(ids)).all()}
    irmas: dict[str, list[JurisprudenceDecision]] = {}
    if completar_processo:
        processos = {d.processo_digits for d in achadas.values() if d.processo_digits}
        if processos:
            for d in JurisprudenceDecision.query.filter(
                    JurisprudenceDecision.law_firm_id == law_firm_id,
                    JurisprudenceDecision.processo_digits.in_(processos)).all():
                irmas.setdefault(d.processo_digits, []).append(d)

    catalogo_da_tese = svc.catalogo_por_tese(law_firm_id) if f.catalogo else {}
    cartoes = []
    for grupo in grupos:
        principais = [achadas[i] for i in grupo if i in achadas]
        if not principais:
            continue
        base = principais[0]
        trilha = irmas.get(base.processo_digits) if completar_processo and base.processo_digits else None
        trilha = svc.ordenar_trilha(trilha or principais)
        ids_achados = {d.id for d in principais}

        teses, vistas = [], set()
        for d in sorted(principais, key=lambda d: -norm.TIPO_ORDEM.get(d.tipo_documento, 0)):
            for tese in d.theses:
                if tese.id in vistas:
                    continue
                vistas.add(tese.id)
                destaque = (tese.id in f.teses
                            or bool(set(catalogo_da_tese.get(tese.id, [])) & set(f.catalogo)))
                teses.append({'id': tese.id, 'nome': tese.name, 'destaque': destaque})
        teses.sort(key=lambda t: not t['destaque'])

        destaque = max(principais, key=lambda d: (norm.TIPO_ORDEM.get(d.tipo_documento, 0), d.data_julgamento or date.min))
        cartoes.append({
            'processo': base.processo or norm.formatar_cnj(base.processo_digits or ''),
            'parte_autora': next((d.parte_autora for d in trilha if d.parte_autora), None),
            'vigencia': next((d.vigencia_texto for d in trilha if d.vigencia_texto), None),
            'trilha': trilha,
            'achadas': ids_achados,
            'faltando': [norm.TIPO_LABELS_CURTOS[t] for t in (norm.TIPO_SENTENCA, norm.TIPO_ACORDAO, norm.TIPO_EMBARGOS)
                         if completar_processo and not any(d.tipo_documento == t for d in trilha)],
            'teses': teses,
            'virada': virou_no_acordao(trilha),
            'destaque': destaque,
            'trecho': trecho_da_decisao(destaque, termos),
            'citacao': norm.citacao(destaque),
        })
    return cartoes


def buscar_para_geracao(law_firm_id: int, consulta: str, limite: int = 15) -> list[dict]:
    """Busca avulsa ("buscar outra na base…") do passo de geração."""
    todas = _carregar(law_firm_id)
    termos = [] if norm.parece_numero_de_processo(consulta) else norm.termos_da_consulta(consulta)
    ids = [l.id for l in sorted((l for l in todas if _casa_texto(l, consulta, termos)),
                                key=lambda l: l.data or date.min, reverse=True)][:limite]
    if not ids:
        return []
    decisoes = {d.id: d for d in JurisprudenceDecision.query.filter(JurisprudenceDecision.id.in_(ids)).all()}
    return [resumo_para_geracao(decisoes[i]) for i in ids if i in decisoes]


def resumo_para_geracao(d: JurisprudenceDecision) -> dict:
    return {
        'id': d.id,
        'resultado': d.resultado,
        'resultado_rotulo': norm.RESULTADO_LABELS_CURTOS.get(d.resultado or '', ''),
        'tipo': norm.TIPO_LABELS_CURTOS.get(d.tipo_documento or '', ''),
        'tribunal': d.tribunal or '',
        'orgao': d.orgao_julgador or '',
        'processo': d.processo or '',
        'data': d.data_julgamento.strftime('%d/%m/%Y') if d.data_julgamento else '',
        'motivo': (d.motivo_resultado or d.resumo_executivo or '')[:220],
        'citacao': norm.citacao(d),
    }
