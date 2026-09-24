"""Base de Jurisprudência — gravação das decisões e resolução das teses.

Fonte única de "registro bruto → decisão no banco", usada pela importação da
planilha, pela leitura de PDF e pela correção manual. As três portas passam
por `normalizar_registro`, então gravam exatamente o mesmo formato.

Registro bruto = dict com as chaves do Banco Mestre FAP (as mesmas do JSON que
a IA devolve): processo, tribunal, orgao_julgador, relator, data_julgamento,
tipo_documento, classe_processual, resultado, motivo_resultado, parte_autora,
vigencia_fap, teses, ementa, fundamentos, precedentes, argumentos_acolhidos,
argumentos_rejeitados, resumo_executivo, palavras_chave (+ uf, opcional).
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

# Campos que a pessoa pode corrigir à mão. Corrigido = protegido do
# reprocessamento pela IA (entra em manual_fields_json).
CAMPOS_EDITAVEIS = (
    'processo', 'tribunal', 'orgao_julgador', 'uf', 'relator', 'data_julgamento',
    'tipo_documento', 'classe_processual', 'resultado', 'motivo_resultado',
    'parte_autora', 'vigencia_texto', 'ementa', 'resumo_executivo',
    'fundamentos_json', 'precedentes_json', 'argumentos_acolhidos_json',
    'argumentos_rejeitados_json', 'teses_brutas_json',
)

_LISTAS = {
    'fundamentos': 'fundamentos_json',
    'precedentes': 'precedentes_json',
    'argumentos_acolhidos': 'argumentos_acolhidos_json',
    'argumentos_rejeitados': 'argumentos_rejeitados_json',
    'palavras_chave': 'palavras_chave_json',
}


# ── Registro bruto → campos do modelo ─────────────────────────────────

def normalizar_registro(bruto: dict) -> dict:
    """Registro da planilha ou da IA → dict com os campos de JurisprudenceDecision.

    As teses vão em `teses_brutas_json` (como vieram); a ligação com
    JurisprudenceThesis é feita por `definir_teses`.
    """
    tribunal, orgao = norm.separar_tribunal(bruto.get('tribunal'), bruto.get('orgao_julgador'))
    processo = norm.texto_limpo(bruto.get('processo'), 60)
    vig_texto, vig_ini, vig_fim = norm.vigencia(bruto.get('vigencia_fap'))
    campos = {
        'processo': processo,
        'processo_digits': norm.digitos(processo)[:25] or None,
        'tribunal': tribunal,
        'orgao_julgador': orgao,
        'uf': norm.uf_do_processo(processo, orgao, bruto.get('uf')),
        'relator': norm.texto_limpo(bruto.get('relator'), 255),
        'data_julgamento': norm.para_data(bruto.get('data_julgamento')),
        'tipo_documento': norm.tipo_documento(bruto.get('tipo_documento')),
        'classe_processual': norm.texto_limpo(bruto.get('classe_processual'), 255),
        'resultado': norm.resultado(bruto.get('resultado')),
        'motivo_resultado': norm.texto_limpo(bruto.get('motivo_resultado')),
        'parte_autora': norm.texto_limpo(bruto.get('parte_autora'), 255),
        'vigencia_texto': vig_texto,
        'vigencia_inicio': vig_ini,
        'vigencia_fim': vig_fim,
        'ementa': norm.texto_limpo(bruto.get('ementa')),
        'resumo_executivo': norm.texto_limpo(bruto.get('resumo_executivo')),
        'teses_brutas_json': [t.upper() for t in norm.para_lista(bruto.get('teses'))],
    }
    for origem, destino in _LISTAS.items():
        campos[destino] = norm.para_lista(bruto.get(origem))
    return campos


def montar_texto_de_busca(decisao: JurisprudenceDecision) -> str:
    partes = [
        decisao.processo, decisao.processo_digits, decisao.tribunal, decisao.orgao_julgador,
        decisao.uf, decisao.relator, decisao.classe_processual, decisao.parte_autora,
        decisao.vigencia_texto, decisao.motivo_resultado, decisao.ementa,
        decisao.resumo_executivo, decisao.original_filename,
        norm.TIPO_LABELS.get(decisao.tipo_documento or ''),
        norm.RESULTADO_LABELS.get(decisao.resultado or ''),
    ]
    for coluna in (*_LISTAS.values(), 'teses_brutas_json'):
        partes.extend(getattr(decisao, coluna) or [])
    partes.extend(t.name for t in decisao.theses)
    return norm.texto_de_busca(' | '.join(str(p) for p in partes if p))


def aplicar_campos(decisao: JurisprudenceDecision, campos: dict, *, respeitar_manual: bool = True) -> None:
    """Grava os campos na decisão. Campo corrigido à mão não é sobrescrito."""
    protegidos = set(decisao.manual_fields_json or []) if respeitar_manual else set()
    for nome, valor in campos.items():
        if nome in protegidos:
            continue
        # vigência e dígitos do processo acompanham o campo de onde derivam
        if nome in ('vigencia_inicio', 'vigencia_fim') and 'vigencia_texto' in protegidos:
            continue
        if nome == 'processo_digits' and 'processo' in protegidos:
            continue
        setattr(decisao, nome, valor)


# ── Duplicata ──────────────────────────────────────────────────────────

def mesma_decisao(law_firm_id: int, processo_digits: Optional[str], tipo: Optional[str],
                  data_julgamento) -> Optional[JurisprudenceDecision]:
    """Duplicata exata: mesmo processo, instância e data."""
    if not processo_digits:
        return None
    return JurisprudenceDecision.query.filter_by(
        law_firm_id=law_firm_id, processo_digits=processo_digits,
        tipo_documento=tipo, data_julgamento=data_julgamento,
    ).first()


def mesma_instancia(law_firm_id: int, processo_digits: Optional[str],
                    tipo: Optional[str]) -> Optional[JurisprudenceDecision]:
    """Mesmo processo e instância, qualquer data — caso para o advogado decidir."""
    if not processo_digits or not tipo:
        return None
    return (JurisprudenceDecision.query
            .filter_by(law_firm_id=law_firm_id, processo_digits=processo_digits, tipo_documento=tipo)
            .order_by(JurisprudenceDecision.data_julgamento.desc())
            .first())


# ── Teses ──────────────────────────────────────────────────────────────

class ResolvedorDeTeses:
    """Resolve o nome de uma tese para a JurisprudenceThesis canônica.

    Cria a tese que ainda não existe e liga sozinha ao catálogo quando o nome
    normalizado é idêntico ao de uma tese do catálogo. Guarda em memória o que
    já resolveu — a importação de 515 decisões resolve a mesma tese centenas de
    vezes.
    """

    def __init__(self, law_firm_id: int):
        self.law_firm_id = law_firm_id
        self._por_chave = {
            t.key: t for t in JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).all()
        }
        self._catalogo = {}
        for tese in JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, is_active=True).all():
            for nome in (tese.name, (tese.key or '').replace('_', ' ')):
                if norm.chave(nome):
                    self._catalogo.setdefault(norm.chave(nome), tese)
        self.criadas = 0
        self.ligadas_sozinhas = 0

    def resolver(self, nome: str) -> Optional[JurisprudenceThesis]:
        k = norm.chave(nome)[:255]
        if not k:
            return None
        tese = self._por_chave.get(k)
        if tese is None:
            tese = JurisprudenceThesis(law_firm_id=self.law_firm_id, key=k, name=k,
                                       status=JurisprudenceThesis.STATUS_PENDENTE)
            do_catalogo = self._catalogo.get(k)
            if do_catalogo is not None:
                tese.catalog_theses.append(do_catalogo)
                tese.status = JurisprudenceThesis.STATUS_LIGADA
                self.ligadas_sozinhas += 1
            db.session.add(tese)
            self._por_chave[k] = tese
            self.criadas += 1
        # Grafia mesclada resolve para a canônica (a cadeia tem no máximo um
        # passo, mas o laço protege de dado torto).
        visitadas = set()
        while tese.merged_into_id and tese.id not in visitadas:
            visitadas.add(tese.id)
            tese = tese.merged_into or tese
        return tese

    def existe(self, nome: str) -> bool:
        return norm.chave(nome) in self._por_chave

    def ligaria_sozinha(self, nome: str) -> bool:
        k = norm.chave(nome)
        existente = self._por_chave.get(k)
        if existente is not None:
            return existente.status == JurisprudenceThesis.STATUS_LIGADA
        return k in self._catalogo


def definir_teses(decisao: JurisprudenceDecision, nomes: Iterable[str],
                  resolvedor: ResolvedorDeTeses) -> None:
    teses = []
    for nome in nomes:
        tese = resolvedor.resolver(nome)
        if tese is not None and tese not in teses:
            teses.append(tese)
    decisao.theses = teses


# ── Criar, atualizar, excluir ─────────────────────────────────────────

def criar_decisao(law_firm_id: int, bruto: dict, *, source: str, resolvedor: ResolvedorDeTeses,
                  user_id: Optional[int] = None, **extras) -> JurisprudenceDecision:
    campos = normalizar_registro(bruto)
    decisao = JurisprudenceDecision(law_firm_id=law_firm_id, source=source, created_by_id=user_id)
    aplicar_campos(decisao, campos, respeitar_manual=False)
    for nome, valor in extras.items():
        setattr(decisao, nome, valor)
    definir_teses(decisao, campos['teses_brutas_json'], resolvedor)
    decisao.search_text = montar_texto_de_busca(decisao)
    db.session.add(decisao)
    return decisao


def atualizar_da_ia(decisao: JurisprudenceDecision, bruto: dict, resolvedor: ResolvedorDeTeses,
                    **extras) -> None:
    """Reprocessamento: regrava o que a IA leu, preservando o corrigido à mão."""
    campos = normalizar_registro(bruto)
    aplicar_campos(decisao, campos, respeitar_manual=True)
    for nome, valor in extras.items():
        setattr(decisao, nome, valor)
    if 'teses_brutas_json' not in (decisao.manual_fields_json or []):
        definir_teses(decisao, campos['teses_brutas_json'], resolvedor)
    decisao.search_text = montar_texto_de_busca(decisao)


def corrigir_manualmente(decisao: JurisprudenceDecision, bruto: dict,
                         resolvedor: ResolvedorDeTeses) -> list[str]:
    """Aplica a correção da tela. Devolve os campos que de fato mudaram."""
    campos = normalizar_registro(bruto)
    campos.pop('palavras_chave_json', None)
    mudaram = []
    for nome in CAMPOS_EDITAVEIS:
        if nome not in campos:
            continue
        if (getattr(decisao, nome) or None) != (campos[nome] or None):
            mudaram.append(nome)
    if not mudaram:
        return []
    aplicar = {nome: campos[nome] for nome in mudaram}
    if 'processo' in mudaram:
        aplicar['processo_digits'] = campos['processo_digits']
    if 'vigencia_texto' in mudaram:
        aplicar['vigencia_inicio'] = campos['vigencia_inicio']
        aplicar['vigencia_fim'] = campos['vigencia_fim']
    aplicar_campos(decisao, aplicar, respeitar_manual=False)
    decisao.manual_fields_json = sorted(set(decisao.manual_fields_json or []) | set(mudaram))
    if 'teses_brutas_json' in mudaram:
        definir_teses(decisao, campos['teses_brutas_json'], resolvedor)
    decisao.search_text = montar_texto_de_busca(decisao)
    return mudaram


def excluir_decisao(decisao: JurisprudenceDecision) -> None:
    db.session.delete(decisao)


# ── Consultas de apoio às telas ───────────────────────────────────────

def decisoes_do_processo(decisao: JurisprudenceDecision) -> list[JurisprudenceDecision]:
    if not decisao.processo_digits:
        return [decisao]
    irmas = JurisprudenceDecision.query.filter_by(
        law_firm_id=decisao.law_firm_id, processo_digits=decisao.processo_digits).all()
    return ordenar_trilha(irmas)


def ordenar_trilha(decisoes: list) -> list:
    return sorted(decisoes, key=lambda d: (
        d.data_julgamento is None, d.data_julgamento or date.min,
        norm.TIPO_ORDEM.get(d.tipo_documento, 9), d.id))


def precedentes_com_link(decisao: JurisprudenceDecision) -> list[dict]:
    """Precedentes citados; os que também estão na base viram link."""
    precedentes = decisao.precedentes_json or []
    numeros = {}
    for texto in precedentes:
        d = norm.digitos(texto)
        if len(d) >= 15:
            numeros[texto] = d[:20]
    na_base = {}
    if numeros:
        for d_id, digits in (db.session.query(JurisprudenceDecision.id, JurisprudenceDecision.processo_digits)
                             .filter(JurisprudenceDecision.law_firm_id == decisao.law_firm_id,
                                     JurisprudenceDecision.processo_digits.in_(set(numeros.values())),
                                     JurisprudenceDecision.id != decisao.id)
                             .all()):
            na_base.setdefault(digits, d_id)
    return [{'texto': t, 'decision_id': na_base.get(numeros.get(t))} for t in precedentes]


def catalogo_por_tese(law_firm_id: int) -> dict[int, list[int]]:
    """{jurisprudence_thesis_id: [judicial_legal_thesis_id, ...]}"""
    linhas = (db.session.query(jurisprudence_thesis_catalog_links.c.thesis_id,
                               jurisprudence_thesis_catalog_links.c.legal_thesis_id)
              .join(JurisprudenceThesis, JurisprudenceThesis.id == jurisprudence_thesis_catalog_links.c.thesis_id)
              .filter(JurisprudenceThesis.law_firm_id == law_firm_id)
              .all())
    resultado: dict[int, list[int]] = {}
    for tese_id, catalogo_id in linhas:
        resultado.setdefault(tese_id, []).append(catalogo_id)
    return resultado


def teses_por_decisao(law_firm_id: int) -> dict[int, list[int]]:
    """{decision_id: [jurisprudence_thesis_id, ...]}"""
    linhas = (db.session.query(jurisprudence_decision_theses.c.decision_id,
                               jurisprudence_decision_theses.c.thesis_id)
              .join(JurisprudenceDecision, JurisprudenceDecision.id == jurisprudence_decision_theses.c.decision_id)
              .filter(JurisprudenceDecision.law_firm_id == law_firm_id)
              .all())
    resultado: dict[int, list[int]] = {}
    for decisao_id, tese_id in linhas:
        resultado.setdefault(decisao_id, []).append(tese_id)
    return resultado


def contar_teses_pendentes(law_firm_id: int) -> int:
    """Teses com decisão e sem correspondência — é a pendência do badge."""
    return (db.session.query(db.func.count(db.distinct(JurisprudenceThesis.id)))
            .join(jurisprudence_decision_theses,
                  jurisprudence_decision_theses.c.thesis_id == JurisprudenceThesis.id)
            .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                    JurisprudenceThesis.status == JurisprudenceThesis.STATUS_PENDENTE,
                    JurisprudenceThesis.merged_into_id.is_(None))
            .scalar()) or 0


def totais(law_firm_id: int) -> dict:
    decisoes = JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id).count()
    processos = (db.session.query(db.func.count(db.distinct(JurisprudenceDecision.processo_digits)))
                 .filter(JurisprudenceDecision.law_firm_id == law_firm_id,
                         JurisprudenceDecision.processo_digits.isnot(None))
                 .scalar()) or 0
    sem_processo = (JurisprudenceDecision.query
                    .filter_by(law_firm_id=law_firm_id)
                    .filter(JurisprudenceDecision.processo_digits.is_(None)).count())
    return {'decisoes': decisoes, 'processos': processos + sem_processo}


# ── Reset da base ─────────────────────────────────────────────────────

def o_que_o_reset_apaga(law_firm_id: int) -> dict:
    from app.models import JurisprudenceUpload
    return {
        'decisoes': JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id).count(),
        'pdfs': JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id)
                .filter(JurisprudenceDecision.pdf_path.isnot(None)).count(),
        'teses': JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).count(),
        'envios': JurisprudenceUpload.query.filter_by(law_firm_id=law_firm_id).count(),
    }


def resetar_base(law_firm_id: int) -> dict:
    """Apaga a Base de Jurisprudência inteira do escritório — decisões, teses e
    correspondência com o catálogo, fila de PDFs, arquivos e índice.

    Irreversível. Ordem igual à do reset das peças-modelo: índices primeiro
    (se falharem, o banco ainda reflete a realidade e dá para repetir),
    depois arquivos, depois banco. O catálogo do painel não é tocado.
    Recusa com leitura ou busca no Drive em andamento — a thread gravaria
    decisão no meio da limpeza.
    """
    import os
    import shutil
    from app.models import JurisprudenceUpload
    from app.services import jurisprudence_index_service as indice
    from app.services import jurisprudence_upload_service as envios

    lendo = [u for u in JurisprudenceUpload.query.filter(
        JurisprudenceUpload.law_firm_id == law_firm_id,
        JurisprudenceUpload.status.in_([JurisprudenceUpload.STATUS_QUEUED, JurisprudenceUpload.STATUS_PROCESSING])).all()
        if not envios.travada(u)]
    if lendo or envios.drive_em_andamento(law_firm_id):
        raise ValueError('Há leitura de PDF ou busca no Drive em andamento. Espere terminar para resetar a base.')

    apagado = o_que_o_reset_apaga(law_firm_id)
    avisos = indice.remover_escritorio(law_firm_id)

    pasta = os.path.join(envios.UPLOAD_BASE_DIR, str(law_firm_id))
    if os.path.isdir(pasta):
        try:
            shutil.rmtree(pasta)
        except Exception as erro:
            print(f'[jurisprudence.reset] arquivos em {pasta}: {erro}')
            avisos.append('arquivos enviados')

    decisoes = db.session.query(JurisprudenceDecision.id).filter(JurisprudenceDecision.law_firm_id == law_firm_id)
    teses = db.session.query(JurisprudenceThesis.id).filter(JurisprudenceThesis.law_firm_id == law_firm_id)
    try:
        JurisprudenceUpload.query.filter_by(law_firm_id=law_firm_id).delete(synchronize_session=False)
        db.session.execute(jurisprudence_decision_theses.delete().where(
            jurisprudence_decision_theses.c.decision_id.in_(decisoes.scalar_subquery())))
        db.session.execute(jurisprudence_thesis_catalog_links.delete().where(
            jurisprudence_thesis_catalog_links.c.thesis_id.in_(teses.scalar_subquery())))
        JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id).delete(synchronize_session=False)
        # merged_into_id aponta para a própria tabela: soltar antes de apagar,
        # senão o MySQL recusa o DELETE pela chave estrangeira.
        JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).update(
            {'merged_into_id': None}, synchronize_session=False)
        JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {**apagado, 'avisos': sorted(set(avisos))}
