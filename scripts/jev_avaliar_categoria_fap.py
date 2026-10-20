#!/usr/bin/env python3
"""
Avalia o Jev (TypeSafe, via OpenRouter Decisions API) na Categoria FAP dos benefícios.

Só lê — não grava nada no banco. Pega benefícios que JÁ têm Categoria FAP
(``fap_contestation_topics_json`` / ``fap_contestation_topic``) e justificativa,
pergunta ao Jev qual é a categoria e compara. A pergunta é *choice* entre os 20
tópicos do ``FAPContestationClassifierAgent``; a descrição de cada tópico sai da
**referência ativa do escritório** (``fap_contestation_classifier_reference_versions``),
com a referência padrão do código quando o escritório não tem versão.

Serve para decidir se vale usar o Jev em cascata com o classificador atual: o Jev
decide quando a confiança passa do limiar, o resto segue para o classificador.
Medido na base local (20/10/2026, 40 benefícios, referência padrão): com
confiança ≥ 0,6 ele decidiu 27 de 40 e acertou todos; custo ~US$ 0,0002 por
benefício. O tópico gravado também pode ter vindo de um classificador — é
referência, não gabarito.

Também pergunta o tipo de pedido (exclusão / inclusão / revisão), para confirmar
que é sempre exclusão (79 de 80 na base local; o único "revisão" com confiança 0,34).

Uso:
  uv run python scripts/jev_avaliar_categoria_fap.py                     # 200 benefícios
  uv run python scripts/jev_avaliar_categoria_fap.py --amostra 500 --workers 8
  uv run python scripts/jev_avaliar_categoria_fap.py --referencia-padrao  # ignora a do escritório

Variáveis (.env): OPENAI_API_KEY e OPENAI_BASE_URL do OpenRouter (as mesmas do
resto do app); FAP_SYNC_LAW_FIRM_ID ou --escritorio.

O detalhe por benefício (com o texto da justificativa) vai para
instance/jev_categoria_fap.json — dado de cliente, não compartilhe.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env

MODELO_PADRAO = 'typesafe/jev-1.14'
LIMIARES = (0.0, 0.5, 0.6, 0.7, 0.8)
TIPO_PEDIDO = {
    'exclusao': 'A empresa pede que o benefício seja retirado (excluído) do cálculo do FAP.',
    'inclusao': 'A empresa pede que algo seja incluído no cálculo do FAP.',
    'revisao': 'A empresa pede a revisão ou correção de um dado do benefício (espécie, valor, datas, '
               'estabelecimento) sem pedir que ele saia do cálculo.',
}
# Sem descrição, "outros argumentos" vira ímã: tudo que o Jev não reconhece cai nele.
CATCH_ALL = {
    'outros_argumentos': 'OUTROS ARGUMENTOS. Use apenas quando nenhum outro tópico se aplica à justificativa.',
    'discussao_medica': 'DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS. A empresa discute o mérito médico da '
                        'incapacidade ou do nexo, sem nenhum dos fundamentos específicos dos outros tópicos.',
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _chave(texto: str) -> str:
    t = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+', ' ', t).strip()


def _secoes(md: str) -> dict[str, str]:
    """'# TÓPICO' da referência → texto da seção."""
    secoes, atual, linhas = {}, None, []
    for linha in (md or '').splitlines():
        m = re.match(r'^#{1,3}\s+(.+)$', linha)
        if m:
            if atual:
                secoes[atual] = ' '.join(linhas)
            atual, linhas = _chave(m.group(1)), []
        elif atual and linha.strip():
            linhas.append(linha.strip())
    if atual:
        secoes[atual] = ' '.join(linhas)
    return secoes


def criterios(md: str, slug_to_topic: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    secoes = _secoes(md)
    crit, faltou = {}, []
    for slug, nome in slug_to_topic.items():
        corpo = secoes.get(_chave(nome))
        if slug in CATCH_ALL:
            crit[slug] = CATCH_ALL[slug] + (f' Exemplo: {corpo[:400]}' if corpo else '')
        elif corpo:
            crit[slug] = f'{nome}. Exemplo de justificativa: {corpo[:700]}'
        else:
            crit[slug] = nome
            faltou.append(nome)
    return crit, faltou


def _topicos_gravados(b) -> set[str]:
    topicos = []
    if b.fap_contestation_topics_json:
        try:
            v = json.loads(b.fap_contestation_topics_json)
            topicos = v if isinstance(v, list) else []
        except (TypeError, ValueError):
            topicos = []
    if not topicos and b.fap_contestation_topic:
        topicos = [b.fap_contestation_topic]
    return {_chave(t) for t in topicos if t}


def _texto(b) -> str:
    justificativa = b.first_instance_justification or b.justification or ''
    parecer = b.first_instance_opinion or b.opinion or ''
    partes = [f'Espécie do benefício: {b.benefit_type}'] if b.benefit_type else []
    if justificativa.strip():
        partes.append('Justificativa da empresa: ' + justificativa.strip()[:4000])
    if parecer.strip():
        partes.append('Parecer do analista: ' + parecer.strip()[:3000])
    return '\n\n'.join(partes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Avalia o Jev na Categoria FAP (só leitura).')
    ap.add_argument('--amostra', type=int, default=200, help='benefícios com categoria a testar (padrão 200)')
    ap.add_argument('--workers', type=int, default=6, help='chamadas em paralelo (padrão 6)')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    ap.add_argument('--modelo', default=MODELO_PADRAO)
    ap.add_argument('--referencia-padrao', action='store_true', help='usa a referência do código, não a do escritório')
    ap.add_argument('--semente', type=int, default=7)
    args = ap.parse_args(argv)

    chave = os.environ.get('OPENAI_API_KEY', '').strip()
    base = os.environ.get('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1').strip()
    if not chave or 'openrouter' not in base:
        _log('ERRO: OPENAI_API_KEY/OPENAI_BASE_URL do OpenRouter não configurados no .env.')
        return 1
    url = base.split('/api/')[0] + '/api/alpha/decisions'
    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        _log('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return 1

    from sqlalchemy import or_

    from app.agents.fap.fap_contestation_classifier_agent import FAPContestationClassifierAgent as Cls
    from app.models import Benefit, FapContestationClassifierReferenceVersion as Ref

    slug_to_topic = dict(Cls.SLUG_TO_TOPIC)
    with app.app_context():
        ref = None if args.referencia_padrao else (
            Ref.query.filter_by(law_firm_id=law_firm_id, is_active=True).order_by(Ref.version.desc()).first())
        md = ref.reference_markdown if ref else Cls.get_default_reference_markdown()
        origem = f'do escritório (versão {ref.version})' if ref else 'padrão do código'
        crit, faltou = criterios(md, slug_to_topic)

        candidatos = (
            Benefit.query.filter(
                Benefit.law_firm_id == law_firm_id,
                or_(Benefit.fap_contestation_topic.isnot(None), Benefit.fap_contestation_topics_json.isnot(None)),
                or_(Benefit.first_instance_justification.isnot(None), Benefit.justification.isnot(None)),
            ).all()
        )
        casos = [(b.id, _topicos_gravados(b), _texto(b)) for b in candidatos]
        casos = [c for c in casos if c[1] and c[2]]
    random.seed(args.semente)
    casos = random.sample(casos, min(args.amostra, len(casos)))

    _log(f'Escritório {law_firm_id} · referência {origem} · {len(casos)} benefícios com categoria · modelo {args.modelo}')
    if faltou:
        _log(f'  tópicos sem seção na referência (vão só com o nome): {", ".join(faltou)}')
    if not casos:
        _log('Nenhum benefício com categoria e justificativa para comparar.')
        return 0

    sessao = requests.Session()
    sessao.headers.update({'Authorization': f'Bearer {chave}', 'Content-Type': 'application/json'})

    def perguntar(estado: str) -> dict:
        corpo = {
            'model': args.modelo,
            'state': {'beneficio_fap': estado},
            'questions': {
                'categoria': {'type': 'choice', 'criteria': crit,
                              'instructions': 'Qual é a categoria (tópico jurídico) principal da contestação deste '
                                              'benefício? Compare a justificativa da empresa com os exemplos de cada tópico.'},
                'tipo_pedido': {'type': 'choice', 'criteria': TIPO_PEDIDO,
                                'instructions': 'Qual é o pedido da empresa para este benefício na contestação do FAP?'},
            },
        }
        t0 = time.time()
        try:
            r = sessao.post(url, json=corpo, timeout=120)
        except requests.RequestException as e:
            return {'erro': type(e).__name__, 'segundos': time.time() - t0}
        if r.status_code != 200:
            return {'erro': f'HTTP {r.status_code}: {r.text[:200]}', 'segundos': time.time() - t0}
        return {'resposta': r.json(), 'segundos': time.time() - t0}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 16))) as pool:
        resultados = list(pool.map(lambda c: perguntar(c[2]), casos))

    custo, tempos, erros = 0.0, [], Counter()
    tipos, pares = Counter(), []
    detalhe = []
    for (bid, gravados, _), res in zip(casos, resultados):
        if 'erro' in res:
            erros[res['erro'][:60]] += 1
            continue
        d = res['resposta']
        tempos.append(res['segundos'])
        custo += float((d.get('usage') or {}).get('cost') or 0)
        a = d.get('answers') or {}
        cat, tp = a.get('categoria') or {}, a.get('tipo_pedido') or {}
        escolhido = slug_to_topic.get(cat.get('choice'), '')
        acertou = _chave(escolhido) in gravados
        pares.append((float(cat.get('confidence') or 0), acertou, escolhido, sorted(gravados)))
        tipos[(tp.get('choice'), 'conf≥0,8' if (tp.get('confidence') or 0) >= 0.8 else 'conf<0,8')] += 1
        detalhe.append({'id': bid, 'gravado': sorted(gravados), 'jev': escolhido, 'acertou': acertou,
                        'confianca': cat.get('confidence'), 'tipo_pedido': tp})

    (Path(app.root_path) / 'instance').mkdir(exist_ok=True)
    (Path(app.root_path) / 'instance' / 'jev_categoria_fap.json').write_text(
        json.dumps(detalhe, ensure_ascii=False, indent=1))

    n = len(pares)
    _log(f'\nRespostas: {n} · erros: {dict(erros) or 0} · custo US$ {custo:.4f} '
         f'(~US$ {custo / max(n, 1):.5f} por benefício) · {time.time() - t0:.0f}s no total, '
         f'{sum(tempos) / max(len(tempos), 1):.2f}s por chamada')
    _log('\nCategoria FAP — Jev x gravada:')
    _log('  limiar   decidiu        acertos   erros   sem decisão')
    for lim in LIMIARES:
        dec = [p for p in pares if p[0] >= lim]
        ok = sum(1 for p in dec if p[1])
        _log(f'  ≥{lim:.1f}    {len(dec):>4}/{n:<4} ({len(dec) / max(n, 1):>4.0%})  '
             f'{ok:>5}    {len(dec) - ok:>4}   {n - len(dec):>6}'
             + (f'   precisão {ok / len(dec):.0%}' if dec else ''))
    confusao = Counter((p[3][0] if p[3] else '?', p[2]) for p in pares if not p[1] and p[0] >= 0.5)
    if confusao:
        _log('\nErros com confiança ≥ 0,5 (gravada → Jev):')
        for (g, j), q in confusao.most_common(8):
            _log(f'  {q:>3}x  {g}  →  {j}')
    _log('\nTipo de pedido: ' + ', '.join(f'{t} ({c}): {q}' for (t, c), q in tipos.most_common()))
    _log('\nDetalhe por benefício em instance/jev_categoria_fap.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
