"""Anexos das contestações administrativas do FAP (FB-08).

Os documentos que o escritório anexou a cada contestação (laudo, CNIS,
comprovante de vínculo de cada benefício…) ficam no portal, no recálculo que a
contestação gerou: "Visualizar Anexos" da Consulta do FAP. Aqui eles são
listados e baixados para o disco, sem tocar no banco.

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
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.models import FapCalculoEstabelecimento
from app.services import fap_calculo_client as client
from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CNPJ_RAIZ, completar_zeros

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
             log: Callable[[str], None] = print) -> dict:
    """Lista os anexos de cada recálculo e, com ``baixar``, grava no disco.

    Sem ``baixar`` nada é gravado: só conta anexos e tamanho.
    """
    recs = recalculos(law_firm_id, anos=anos, raizes=raizes, cnpjs=cnpjs)
    if limite:
        recs = recs[:limite]
    rel = {'recalculos': len(recs), 'consultados': 0, 'com_anexo': 0, 'anexos': 0, 'bytes': 0,
           'por_elemento': Counter(), 'baixados': 0, 'ja_no_disco': 0, 'bytes_baixados': 0,
           'sem_acesso': 0, 'erros': 0, 'motivos_erro': Counter(), 'expirada': False}
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
