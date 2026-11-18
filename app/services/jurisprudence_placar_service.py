"""Placar de teses das decisões que já estão na base (PRC-24 e PRC-25).

As decisões lidas depois do placar já vêm com `tipo_julgamento` e
`resultado_por_tese_json` da leitura. As anteriores — as da planilha Banco
Mestre e as lidas de PDF antes do placar — são preenchidas aqui, lendo o texto
de cada uma pelo `JurisprudenceThesisResultAgent`, que devolve só os dois campos
e não toca no resto da decisão (teses, resultado, ementa e a correspondência com
o catálogo continuam como estão).

De onde vem o texto, nesta ordem:
1. o inteiro teor já extraído (`texto_integral`);
2. o arquivo anexado à decisão (`pdf_path`, PDF ou .md);
3. o lote de Markdown do escritório (`instance/importacao/lote_md/decisoes`),
   pelo índice CSV: "PDF de origem" é o `nome_arquivo` da planilha, a mesma
   chave de `original_filename` — é assim que as 509 da planilha, sem PDF no
   sistema, ganham texto;
4. um arquivo com o mesmo nome enviado à fila de leitura (o PDF que ficou em
   "Revisar" como repetido da decisão da planilha).

Decisão sem texto em nenhum dos três fica de fora e é contada no relatório.
A IA roda em paralelo (só rede); o banco só é tocado no fluxo principal.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from app.models import db, JurisprudenceDecision
from app.services import jurisprudence_normalizer as norm

WORKERS_PADRAO = 8


def pasta_do_lote() -> Optional[Path]:
    from app.services import lote_md_import_service as lote
    pasta = Path(lote.PASTA_PADRAO) / lote.PASTA_DECISOES
    return pasta if pasta.is_dir() else None


def textos_do_lote(pastas: list[Path]) -> dict[str, Path]:
    """{chave do nome do PDF de origem: .md} a partir do índice CSV de cada pasta."""
    from app.services import jurisprudence_upload_service as envios
    from app.services import lote_md_import_service as lote

    mapa: dict[str, Path] = {}
    for pasta in pastas:
        if not pasta or not pasta.is_dir():
            continue
        indice = lote._indice_da_pasta(pasta)
        if indice is None:
            continue
        arquivos = lote._arquivos_md(pasta)
        for linha in lote.ler_indice(indice):
            origem = lote._col(linha, 'PDF de origem')
            md = arquivos.get(lote._chave_nome(lote._col(linha, 'Arquivo .md')))
            if origem and md is not None:
                mapa.setdefault(envios._chave_do_arquivo(origem), md)
    return mapa


def arquivos_da_fila(law_firm_id: int) -> dict[str, Path]:
    """{chave do nome: arquivo} dos envios do escritório que ainda estão no disco."""
    from app.models import JurisprudenceUpload
    from app.services import jurisprudence_upload_service as envios

    mapa: dict[str, Path] = {}
    for nome, caminho in (db.session.query(JurisprudenceUpload.original_filename, JurisprudenceUpload.file_path)
                          .filter(JurisprudenceUpload.law_firm_id == law_firm_id)
                          .order_by(JurisprudenceUpload.id).all()):
        if nome and caminho and os.path.isfile(caminho):
            mapa.setdefault(envios._chave_do_arquivo(nome), Path(caminho))
    return mapa


def fonte(decisao: JurisprudenceDecision, lote: dict[str, Path],
          fila: Optional[dict[str, Path]] = None) -> Optional[dict]:
    """{'texto': ...} ou {'arquivo': ...} — de onde ler a decisão."""
    from app.services import jurisprudence_upload_service as envios

    if (decisao.texto_integral or '').strip():
        return {'texto': decisao.texto_integral.replace('\f', '\n\n'), 'origem': 'inteiro teor'}
    if decisao.pdf_path and os.path.isfile(decisao.pdf_path):
        return {'arquivo': decisao.pdf_path, 'origem': 'arquivo anexado'}
    if decisao.original_filename:
        chave = envios._chave_do_arquivo(decisao.original_filename)
        if lote.get(chave) is not None:
            return {'arquivo': str(lote[chave]), 'origem': 'lote de Markdown'}
        if fila and fila.get(chave) is not None:
            return {'arquivo': str(fila[chave]), 'origem': 'arquivo da fila de leitura'}
    return None


def pendentes(law_firm_id: int, *, refazer: bool = False):
    q = JurisprudenceDecision.query.filter(JurisprudenceDecision.law_firm_id == law_firm_id)
    if not refazer:
        q = q.filter(JurisprudenceDecision.tipo_julgamento.is_(None))
    return q.order_by(JurisprudenceDecision.id)


def aplicar(decisao: JurisprudenceDecision, lido: dict) -> None:
    """Grava o placar lido. Campo corrigido à mão fica."""
    protegidos = set(decisao.manual_fields_json or [])
    if 'tipo_julgamento' not in protegidos:
        decisao.tipo_julgamento = norm.tipo_julgamento(lido.get('tipo_julgamento'))
    if 'resultado_por_tese_json' not in protegidos:
        decisao.resultado_por_tese_json = norm.resultados_por_tese(lido.get('resultado_por_tese'))


def preencher(law_firm_id: int, *, gravar: bool = False, limite: Optional[int] = None,
              refazer: bool = False, pastas: Optional[list[Path]] = None, workers: int = WORKERS_PADRAO,
              agente=None, ao_progredir: Optional[Callable[[dict], None]] = None) -> dict:
    """Lê e grava o placar das decisões sem `tipo_julgamento` (todas, com `refazer`).

    Sem `gravar`, só conta de onde viria o texto de cada uma — não chama a IA.
    """
    from app.agents.jurisprudence.thesis_result_agent import JurisprudenceThesisResultAgent, LeituraFalhou
    from app.services import ai_model_settings_service

    lote = textos_do_lote(pastas if pastas is not None else [p for p in [pasta_do_lote()] if p])
    fila = arquivos_da_fila(law_firm_id)
    decisoes = pendentes(law_firm_id, refazer=refazer).all()
    if limite:
        decisoes = decisoes[:limite]

    relatorio = {'decisoes': len(decisoes), 'por_origem': {}, 'sem_texto': [], 'gravadas': 0,
                 'falhas': [], 'julgamento': {}, 'teses_com_resultado': 0}
    tarefas = []
    for d in decisoes:
        f = fonte(d, lote, fila)
        if f is None:
            relatorio['sem_texto'].append({'id': d.id, 'arquivo': d.original_filename})
            continue
        relatorio['por_origem'][f['origem']] = relatorio['por_origem'].get(f['origem'], 0) + 1
        tarefas.append((d.id, list(d.teses_brutas_json or []), f))
    if not gravar:
        return relatorio

    agente = agente or JurisprudenceThesisResultAgent(
        model_name=ai_model_settings_service.get_model(law_firm_id, 'jurisprudence_extractor'))

    def ler(tarefa):
        decision_id, teses, f = tarefa
        return decision_id, agente.ler(teses=teses, texto=f.get('texto'), arquivo=f.get('arquivo'),
                                       law_firm_id=law_firm_id, decision_id=decision_id)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futuros = {pool.submit(ler, t): t[0] for t in tarefas}
        for futuro in as_completed(futuros):
            decision_id = futuros[futuro]
            try:
                _, lido = futuro.result()
            except LeituraFalhou as erro:
                relatorio['falhas'].append({'id': decision_id, 'motivo': str(erro)})
                continue
            except Exception as erro:
                relatorio['falhas'].append({'id': decision_id, 'motivo': f'erro inesperado: {str(erro)[:200]}'})
                continue
            decisao = db.session.get(JurisprudenceDecision, decision_id)
            aplicar(decisao, lido)
            db.session.commit()
            relatorio['gravadas'] += 1
            j = decisao.tipo_julgamento or 'não informado'
            relatorio['julgamento'][j] = relatorio['julgamento'].get(j, 0) + 1
            relatorio['teses_com_resultado'] += len(decisao.resultado_por_tese_json or [])
            if ao_progredir:
                ao_progredir(relatorio)
    return relatorio
