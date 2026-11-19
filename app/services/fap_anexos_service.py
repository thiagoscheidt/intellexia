"""Anexos das contestações administrativas do FAP (FB-08).

Os documentos que o escritório anexou a cada contestação (laudo, CNIS,
comprovante de vínculo de cada benefício…) ficam no portal, no recálculo que a
contestação gerou: "Visualizar Anexos" da Consulta do FAP. Aqui eles são
listados e baixados para o disco (``executar``, que não toca no banco) e depois
registrados em ``fap_contestacao_anexos`` (``registrar``: liga ao benefício da
Central, lê o texto e indexa). As duas etapas são separadas de propósito: o
disco é a cópia do portal, o banco se refaz dele.

De onde vêm os recálculos: o histórico de cálculos já sincronizado em
``fap_calculo_estabelecimentos`` (``scripts/fap_calculo_sync.py``) — todo
cálculo do histórico menos o original, que não tem contestação por trás. Um
recálculo novo só aparece aqui depois da sincronização do cálculo.

Pasta: ``<pasta>/<vigência>/<CNPJ>/<id do recálculo>/<id do anexo> - <nome>``,
com ``_anexos.json`` (a lista do portal) em cada pasta de recálculo e
``indice.csv`` na raiz, refeito ao fim de cada execução a partir de todos os
``_anexos.json`` — o índice cobre tudo o que já foi baixado, não só a rodada.

Retomável: anexo já no disco não é baixado de novo. Arquivo só vira arquivo
depois de conferido (base64 válido e tamanho igual ao anunciado): ``.part`` →
rename.
"""
from __future__ import annotations

import base64
import binascii
import csv
import json
import os
import re
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.models import db, FapCalculoEstabelecimento, FapContestacaoAnexo
from app.services import fap_calculo_client as client
from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CNPJ_RAIZ, apenas_digitos, completar_zeros

PASTA_PADRAO = Path(__file__).resolve().parents[2] / 'instance' / 'fap_anexos'
LISTA_DA_PASTA = '_anexos.json'
INDICE = 'indice.csv'
_TAM_NOME = 150


class AnexoInvalido(Exception):
    pass


@dataclass(frozen=True)
class Recalculo:
    ano: int
    cnpj: str
    calculo_id: int
    tipo: Optional[str]
    data: Optional[str]


def recalculos(law_firm_id: int, *, anos: Optional[Iterable[int]] = None,
               raizes: Optional[Iterable[str]] = None,
               cnpjs: Optional[Iterable[str]] = None) -> list[Recalculo]:
    """Recálculos (todo cálculo menos o original) dos estabelecimentos do escritório."""
    q = FapCalculoEstabelecimento.query.filter(
        FapCalculoEstabelecimento.law_firm_id == law_firm_id,
        FapCalculoEstabelecimento.situacao == 'ok',
        FapCalculoEstabelecimento.historico_json.isnot(None),
    )
    if anos:
        q = q.filter(FapCalculoEstabelecimento.ano_vigencia.in_(list(anos)))
    if raizes:
        q = q.filter(FapCalculoEstabelecimento.cnpj_raiz.in_(
            [completar_zeros(r, TAMANHO_CNPJ_RAIZ) for r in raizes]))
    if cnpjs:
        q = q.filter(FapCalculoEstabelecimento.cnpj.in_([completar_zeros(c, TAMANHO_CNPJ) for c in cnpjs]))

    saida = []
    for e in q.order_by(FapCalculoEstabelecimento.ano_vigencia.desc(), FapCalculoEstabelecimento.cnpj,
                        FapCalculoEstabelecimento.id):
        try:
            historico = json.loads(e.historico_json or '[]')
        except ValueError:
            continue
        for h in historico:
            if not h.get('id') or h['id'] == e.calculo_original_id or h.get('tipo') == 'CALCULO_ORIGINAL':
                continue
            saida.append(Recalculo(e.ano_vigencia, e.cnpj, int(h['id']), h.get('tipo'), h.get('data')))
    return saida


def nome_seguro(nome: Optional[str]) -> str:
    """Nome de arquivo vindo do portal sem barra, controle nem ponto na frente."""
    limpo = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', '_', str(nome or '')).strip().lstrip('.')
    if len(limpo) > _TAM_NOME:
        raiz, ext = os.path.splitext(limpo)
        limpo = raiz[:_TAM_NOME - len(ext)] + ext
    return limpo or 'anexo'


def pasta_do_recalculo(pasta: Path, rec: Recalculo) -> Path:
    return pasta / str(rec.ano) / rec.cnpj / str(rec.calculo_id)


def arquivo_do_anexo(pasta: Path, rec: Recalculo, anexo: dict) -> Path:
    return pasta_do_recalculo(pasta, rec) / f"{anexo['id']} - {nome_seguro(anexo.get('nome'))}"


def decodificar(dados, tamanho_esperado: Optional[int]) -> bytes:
    if not isinstance(dados, dict) or not dados.get('base64'):
        raise AnexoInvalido('resposta sem o arquivo')
    try:
        conteudo = base64.b64decode(dados['base64'], validate=True)
    except (binascii.Error, ValueError) as e:
        raise AnexoInvalido('base64 inválido') from e
    if tamanho_esperado and len(conteudo) != int(tamanho_esperado):
        raise AnexoInvalido(f'tamanho {len(conteudo)} diferente do anunciado ({tamanho_esperado})')
    return conteudo


def _gravar(destino: Path, conteudo: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + '.part')
    parcial.write_bytes(conteudo)
    os.replace(parcial, destino)


def _gravar_lista(pasta: Path, rec: Recalculo, anexos: list[dict]) -> None:
    destino = pasta_do_recalculo(pasta, rec) / LISTA_DA_PASTA
    dados = {'ano': rec.ano, 'cnpj': rec.cnpj, 'calculo_id': rec.calculo_id, 'tipo': rec.tipo,
             'data': rec.data, 'anexos': anexos}
    _gravar(destino, json.dumps(dados, ensure_ascii=False, indent=1, default=str).encode('utf-8'))


def refazer_indice(pasta: Path) -> int:
    """``indice.csv`` com tudo o que está na pasta. Devolve o número de linhas."""
    linhas = []
    for lista in sorted(pasta.glob(f'*/*/*/{LISTA_DA_PASTA}')):
        try:
            dados = json.loads(lista.read_text(encoding='utf-8'))
        except ValueError:
            continue
        rec = Recalculo(dados['ano'], dados['cnpj'], dados['calculo_id'], dados.get('tipo'), dados.get('data'))
        for a in dados.get('anexos') or []:
            arq = arquivo_do_anexo(pasta, rec, a)
            linhas.append({
                'vigencia': rec.ano, 'cnpj': rec.cnpj, 'recalculo_id': rec.calculo_id,
                'recalculo_tipo': rec.tipo or '', 'recalculo_data': rec.data or '',
                'anexo_id': a.get('id'), 'elemento': (a.get('tipoElemento') or {}).get('codigo') or '',
                'nb': a.get('nb') or '', 'id_elemento': a.get('idElemento') or '',
                'nome': a.get('nome') or '', 'data_envio': a.get('dataEnvio') or '',
                'bytes': a.get('quantidadeBytes') or '',
                'arquivo': str(arq.relative_to(pasta)) if arq.exists() else '',
            })
    if not linhas:
        return 0
    parcial = pasta / (INDICE + '.part')
    with parcial.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=';')
        w.writeheader()
        w.writerows(linhas)
    os.replace(parcial, pasta / INDICE)
    return len(linhas)


def _motivo(r) -> str:
    return f'HTTP {r.status_code}' if r.status_code else (r.message or 'falha')[:80]


def executar(law_firm_id: int, svc, *, pasta: Path = PASTA_PADRAO, baixar: bool = False,
             anos=None, raizes=None, cnpjs=None, limite: Optional[int] = None, workers: int = 8,
             somente_novos: bool = False, log: Callable[[str], None] = print) -> dict:
    """Lista os anexos de cada recálculo e, com ``baixar``, grava no disco.

    Sem ``baixar`` nada é gravado: só conta anexos e tamanho. ``somente_novos``
    pula o recálculo já consultado (tem ``_anexos.json``, inclusive o vazio de
    quem não tem anexo): os anexos de um recálculo publicado não mudam, e a
    rotina diária só precisa olhar os recálculos que apareceram.
    """
    recs = recalculos(law_firm_id, anos=anos, raizes=raizes, cnpjs=cnpjs)
    ja_consultados = 0
    if somente_novos:
        antes = len(recs)
        recs = [r for r in recs if not (pasta_do_recalculo(pasta, r) / LISTA_DA_PASTA).exists()]
        ja_consultados = antes - len(recs)
    if limite:
        recs = recs[:limite]
    rel = {'recalculos': len(recs), 'consultados': 0, 'com_anexo': 0, 'anexos': 0, 'bytes': 0,
           'por_elemento': Counter(), 'baixados': 0, 'ja_no_disco': 0, 'bytes_baixados': 0,
           'sem_acesso': 0, 'erros': 0, 'motivos_erro': Counter(), 'expirada': False,
           'ja_consultados': ja_consultados}
    log(f'{len(recs)} recálculo(s) para consultar.')

    def listar(rec):
        return 'lista', rec, None, client.listar_anexos(svc, rec.ano, rec.cnpj, rec.calculo_id)

    def baixar_um(rec, anexo):
        destino = arquivo_do_anexo(pasta, rec, anexo)
        if destino.exists() and (not anexo.get('quantidadeBytes')
                                 or destino.stat().st_size == int(anexo['quantidadeBytes'])):
            return 'disco', rec, anexo, None
        r = client.baixar_anexo(svc, rec.ano, rec.cnpj, rec.calculo_id, anexo['id'])
        if r.ok:
            conteudo = decodificar(r.data, anexo.get('quantidadeBytes'))
            _gravar(destino, conteudo)
            return 'baixado', rec, anexo, len(conteudo)
        return 'falha_download', rec, anexo, r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        pendentes = {pool.submit(listar, rec) for rec in recs}
        while pendentes:
            feitos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
            for f in feitos:
                try:
                    tipo, rec, anexo, r = f.result()
                except AnexoInvalido as e:
                    rel['erros'] += 1
                    rel['motivos_erro'][f'arquivo: {e}'] += 1
                    continue
                except Exception as e:  # disco, rede inesperada
                    rel['erros'] += 1
                    rel['motivos_erro'][f'{type(e).__name__}: {str(e)[:80]}'] += 1
                    continue

                if tipo == 'lista':
                    rel['consultados'] += 1
                    if not r.ok:
                        if r.expired:
                            rel['expirada'] = True
                        elif r.status_code == 403:
                            rel['sem_acesso'] += 1
                        else:
                            rel['erros'] += 1
                            rel['motivos_erro'][f'lista: {_motivo(r)}'] += 1
                        continue
                    anexos = [a for a in (r.data or []) if isinstance(a, dict) and a.get('id')]
                    if anexos:
                        rel['com_anexo'] += 1
                        rel['anexos'] += len(anexos)
                        for a in anexos:
                            rel['bytes'] += int(a.get('quantidadeBytes') or 0)
                            rel['por_elemento'][(a.get('tipoElemento') or {}).get('codigo') or '?'] += 1
                        if baixar:
                            _gravar_lista(pasta, rec, anexos)
                            pendentes |= {pool.submit(baixar_um, rec, a) for a in anexos}
                    elif baixar:
                        # Marca de "consultado, sem anexo", para o --somente-novos não voltar nele.
                        _gravar_lista(pasta, rec, [])
                    if rel['consultados'] % 500 == 0:
                        log(f"  {rel['consultados']}/{len(recs)} consultados, {rel['anexos']} anexos"
                            + (f", {rel['baixados']} baixados" if baixar else ''))
                elif tipo == 'disco':
                    rel['ja_no_disco'] += 1
                elif tipo == 'baixado':
                    rel['baixados'] += 1
                    rel['bytes_baixados'] += r
                else:  # falha_download
                    if r.expired:
                        rel['expirada'] = True
                    else:
                        rel['erros'] += 1
                        rel['motivos_erro'][f'download: {_motivo(r)}'] += 1

            if rel['expirada']:
                for p in pendentes:
                    p.cancel()
                break

    if baixar:
        rel['indice'] = refazer_indice(pasta)
    rel['incompleta'] = bool(rel['erros'] or rel['expirada'])
    return rel


# ------------------------------------------------------------ registro no banco

def _data(valor) -> Optional[date]:
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def mapa_de_beneficios(law_firm_id: int) -> dict[tuple, int]:
    """{(vigência, CNPJ14, NB): benefit_id} da Central, em Python — sem cruzar
    texto com ``benefits`` dentro do banco (collation)."""
    from app.models import Benefit, FapVigenciaCnpj

    mapa = {}
    linhas = (db.session.query(Benefit.id, Benefit.benefit_number, FapVigenciaCnpj.vigencia_year,
                               FapVigenciaCnpj.employer_cnpj)
              .join(FapVigenciaCnpj, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
              .filter(Benefit.law_firm_id == law_firm_id))
    for bid, numero, ano, cnpj in linhas:
        nb, cnpj = apenas_digitos(numero), apenas_digitos(cnpj)
        try:
            chave = (int(str(ano).strip()[:4]), cnpj.zfill(TAMANHO_CNPJ), nb)
        except ValueError:
            continue
        if nb and cnpj:
            mapa.setdefault(chave, bid)
    return mapa


def registrar(law_firm_id: int, pasta: Path, *, ler_texto: bool = True, indexar: bool = True,
              log: Callable[[str], None] = print) -> dict:
    """Carrega no banco o que está na pasta (``_anexos.json`` + arquivos), liga
    ao benefício da Central, lê o texto e indexa. Idempotente: anexo já
    registrado só ganha o que faltava (arquivo, benefício, texto)."""
    from app.services import fap_anexos_busca_service as busca
    from app.services import fap_anexos_conteudo as conteudo

    rel = {'listas': 0, 'novos': 0, 'atualizados': 0, 'ligados_a_beneficio': 0,
           'textos_lidos': 0, 'sem_texto': 0, 'erros_leitura': 0, 'por_tipo': Counter()}
    beneficios = mapa_de_beneficios(law_firm_id)
    existentes = {aid: rid for aid, rid in db.session.query(FapContestacaoAnexo.anexo_id, FapContestacaoAnexo.id)
                  .filter(FapContestacaoAnexo.law_firm_id == law_firm_id)}
    pendentes = 0
    for lista in sorted(pasta.glob(f'*/*/*/{LISTA_DA_PASTA}')):
        try:
            dados = json.loads(lista.read_text(encoding='utf-8'))
        except ValueError:
            continue
        rel['listas'] += 1
        rec = Recalculo(dados['ano'], dados['cnpj'], dados['calculo_id'], dados.get('tipo'), dados.get('data'))
        for a in dados.get('anexos') or []:
            if not a.get('id'):
                continue
            arq = arquivo_do_anexo(pasta, rec, a)
            relativo = str(arq.relative_to(pasta)) if arq.exists() else None
            nb = apenas_digitos(str(a.get('nb') or '')) or None
            bid = beneficios.get((rec.ano, rec.cnpj, nb)) if nb else None
            rid = existentes.get(int(a['id']))
            if rid is None:
                linha = FapContestacaoAnexo(
                    law_firm_id=law_firm_id, anexo_id=int(a['id']), ano_vigencia=rec.ano, cnpj=rec.cnpj,
                    cnpj_raiz=rec.cnpj[:8], recalculo_id=rec.calculo_id, recalculo_tipo=rec.tipo,
                    recalculo_data=_data(rec.data), instancia=conteudo.instancia_do_recalculo(rec.tipo),
                    elemento=(a.get('tipoElemento') or {}).get('codigo'), id_elemento=a.get('idElemento'),
                    nb=nb, benefit_id=bid, nome=(a.get('nome') or '')[:255], data_envio=_data(a.get('dataEnvio')),
                    tamanho=a.get('quantidadeBytes'), arquivo=relativo,
                    texto_status=FapContestacaoAnexo.TEXTO_PENDENTE)
                db.session.add(linha)
                db.session.flush()
                existentes[linha.anexo_id] = linha.id
                rel['novos'] += 1
                rel['ligados_a_beneficio'] += 1 if bid else 0
            else:
                linha = db.session.get(FapContestacaoAnexo, rid)
                mudou = False
                if relativo and not linha.arquivo:
                    linha.arquivo, mudou = relativo, True
                if bid and not linha.benefit_id:
                    linha.benefit_id, mudou = bid, True
                    rel['ligados_a_beneficio'] += 1
                rel['atualizados'] += 1 if mudou else 0
            pendentes += 1
            if pendentes % 1000 == 0:
                db.session.commit()
                log(f'  {rel["novos"]} novos, {rel["atualizados"]} atualizados…')
    db.session.commit()

    if ler_texto:
        ids = [i for (i,) in db.session.query(FapContestacaoAnexo.id).filter(
            FapContestacaoAnexo.law_firm_id == law_firm_id,
            FapContestacaoAnexo.texto_status == FapContestacaoAnexo.TEXTO_PENDENTE,
            FapContestacaoAnexo.arquivo.isnot(None)).order_by(FapContestacaoAnexo.id)]
        log(f'Lendo o texto de {len(ids)} anexo(s)…')
        for n, rid in enumerate(ids, 1):
            linha = db.session.get(FapContestacaoAnexo, rid)
            try:
                texto = conteudo.extrair_texto(str(pasta / linha.arquivo)) if linha.arquivo.lower().endswith('.pdf') else ''
            except Exception:
                linha.texto_status = FapContestacaoAnexo.TEXTO_ERRO
                rel['erros_leitura'] += 1
                texto = None
            if texto is not None:
                tipo, extra = conteudo.classificar(texto)
                if len(texto) >= conteudo.MINIMO_DE_TEXTO:
                    linha.texto, linha.texto_status = texto, FapContestacaoAnexo.TEXTO_OK
                    rel['textos_lidos'] += 1
                else:
                    # Digitalizado (ou .doc): o tipo sai do nome; o texto, do OCR (``aplicar_ocr``).
                    tipo = conteudo.tipo_pelo_nome(linha.nome)
                    linha.texto_status = FapContestacaoAnexo.TEXTO_VAZIO
                    rel['sem_texto'] += 1
                linha.tipo_documento = tipo
                linha.campos_json = json.dumps(extra, ensure_ascii=False) if extra else None
                rel['por_tipo'][tipo] += 1
                linha.index_status = None
            if n % 500 == 0:
                db.session.commit()
                log(f'  {n}/{len(ids)} lidos')
        db.session.commit()

    if indexar:
        rel['indice'] = busca.indexar_pendentes(law_firm_id, log=log)
    return rel


# ------------------------------------------------------------ OCR dos digitalizados

# Ordem do OCR: o que só se acha lendo (perícia, CAT, não identificado) primeiro;
# CONBAS e INFBEN por último — a busca já os acha pelo NB, que é filtro.
_PRIORIDADE_OCR = {'HISMED': 0, 'CAT': 1, 'OUTRO': 2, 'CNIS': 3, 'ESOCIAL': 4, 'INFBEN': 5, 'CONBAS': 6}


def aplicar_ocr(law_firm_id: int, pasta: Path, *, minutos: Optional[float] = None,
                limite: Optional[int] = None, log: Callable[[str], None] = print) -> dict:
    """Lê por OCR os PDFs digitalizados (``sem_texto``), por ordem de valor,
    até o tempo ou a quantidade acabar. Cada um é tentado uma vez
    (``ocr_tentado`` em ``campos_json``); o texto lido leva ``ocr: true``."""
    import time

    from app.services import fap_anexos_busca_service as busca
    from app.services import fap_anexos_conteudo as conteudo

    inicio = time.time()
    rel = {'candidatos': 0, 'lidos': 0, 'sem_texto_mesmo_assim': 0, 'erros': 0, 'por_tipo': Counter(),
           'parou_por_tempo': False}
    linhas = (db.session.query(FapContestacaoAnexo.id, FapContestacaoAnexo.tipo_documento, FapContestacaoAnexo.nome)
              .filter(FapContestacaoAnexo.law_firm_id == law_firm_id,
                      FapContestacaoAnexo.texto_status == FapContestacaoAnexo.TEXTO_VAZIO,
                      FapContestacaoAnexo.arquivo.ilike('%.pdf'),
                      db.or_(FapContestacaoAnexo.campos_json.is_(None),
                             ~FapContestacaoAnexo.campos_json.like('%ocr_tentado%')))
              .all())
    fila = sorted(linhas, key=lambda r: (_PRIORIDADE_OCR.get(r.tipo_documento or conteudo.tipo_pelo_nome(r.nome), 2), r.id))
    if limite:
        fila = fila[:limite]
    rel['candidatos'] = len(fila)
    log(f'OCR: {len(fila)} PDF(s) digitalizado(s) na fila.')
    for n, (rid, _tipo, _nome) in enumerate(fila, 1):
        if minutos and (time.time() - inicio) / 60 >= minutos:
            rel['parou_por_tempo'] = True
            break
        linha = db.session.get(FapContestacaoAnexo, rid)
        extra = busca.campos(linha)
        extra['ocr_tentado'] = True
        try:
            texto = conteudo.ocr(str(pasta / linha.arquivo))
        except Exception as erro:
            rel['erros'] += 1
            log(f'  OCR falhou no documento {rid}: {type(erro).__name__}')
            texto = ''
        if len(texto) >= conteudo.MINIMO_DE_TEXTO:
            tipo, campos_texto = conteudo.classificar(texto)
            if tipo == 'OUTRO':
                tipo = conteudo.tipo_pelo_nome(linha.nome)
            extra.update(campos_texto)
            extra['ocr'] = True
            linha.texto, linha.texto_status, linha.tipo_documento = texto, FapContestacaoAnexo.TEXTO_OK, tipo
            linha.index_status = None
            rel['lidos'] += 1
            rel['por_tipo'][tipo] += 1
        else:
            linha.tipo_documento = linha.tipo_documento or conteudo.tipo_pelo_nome(linha.nome)
            rel['sem_texto_mesmo_assim'] += 1
        linha.campos_json = json.dumps(extra, ensure_ascii=False)
        db.session.commit()
        if n % 50 == 0:
            log(f'  {n}/{len(fila)} lidos por OCR ({(time.time() - inicio) / 60:.0f} min)')
    rel['indice'] = busca.indexar_pendentes(law_firm_id, log=log)
    return rel
