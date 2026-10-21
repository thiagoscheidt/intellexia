#!/usr/bin/env python3
"""
Estima quanto custa classificar a Categoria FAP de toda a base (E04 da R09).

Só lê — não chama IA nem grava nada. Junta três números:

1. **Quantas decisões o classificador pegaria** — o mesmo filtro de
   ``classify_benefits_contestation_topics`` (decisões sem tópico) com texto
   para classificar (justificativa ou parecer).
2. **Quanto cada classificação custou de verdade** — média de tokens, custo e
   latência registrados em ``agent_token_usage`` para
   ``FAPContestationClassifierAgent/classify``, por modelo.
3. **O modelo que o escritório usa hoje** (Configurações do classificador) e o
   preço dele no OpenRouter — para estimar mesmo sem histórico, pelo tamanho
   do prompt, da referência e do texto médio.

Também mostra o custo do Jev para o mesmo volume (~US$ 0,00022 por benefício,
medido em scripts/jev_avaliar_categoria_fap.py).

Uso:
  uv run python scripts/estimar_custo_categoria_fap.py
  uv run python scripts/estimar_custo_categoria_fap.py --workers 10
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env

JEV_CUSTO_POR_ITEM = Decimal('0.00022')
CARACTERES_POR_TOKEN = Decimal('3.6')  # português; só para a estimativa sem histórico
SAIDA_ESTIMADA = 150                   # tokens do JSON de resposta


def _usd(v) -> str:
    v = Decimal(v)
    return f'US$ {v:,.5f}' if 0 < v < Decimal('0.01') else f'US$ {v:,.2f}'


def _duracao(segundos: float) -> str:
    if segundos < 3600:
        return f'{segundos / 60:.0f} min'
    return f'{segundos / 3600:.1f} h'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Estima o custo de classificar a Categoria FAP da base toda.')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    ap.add_argument('--workers', type=int, default=5, help='paralelismo previsto para o tempo total (padrão 5)')
    args = ap.parse_args(argv)
    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        print('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return 1

    from sqlalchemy import func, or_

    from app.agents.fap.fap_contestation_classifier_agent import FAPContestationClassifierAgent as Cls
    from app.models import AgentTokenUsage, Benefit, BenefitContestationDecision as Dec, db
    from app.services.token_usage_service import TokenUsageService

    with app.app_context():
        modelo = Cls._load_selected_model_name(law_firm_id) or Cls.get_default_model_name()

        # 1. Volume — o mesmo filtro do classify_benefits_contestation_topics.
        sem_topico = or_(Dec.fap_contestation_topics_json.is_(None), Dec.fap_contestation_topics_json == '')
        base = Dec.query.filter(Dec.law_firm_id == law_firm_id)
        total_decisoes = base.count()
        pendentes = base.filter(sem_topico)
        com_texto = pendentes.filter(or_(
            func.length(func.trim(func.coalesce(Dec.justification, ''))) > 0,
            func.length(func.trim(func.coalesce(Dec.opinion, ''))) > 0,
        ))
        n_pendentes, n_com_texto = pendentes.count(), com_texto.count()
        media_chars = com_texto.with_entities(
            func.avg(func.length(func.coalesce(func.nullif(func.trim(Dec.justification), ''), Dec.opinion)))
        ).scalar() or 0
        beneficios = (db.session.query(func.count(func.distinct(Dec.benefit_id)))
                      .filter(Dec.law_firm_id == law_firm_id).filter(sem_topico).scalar() or 0)
        total_beneficios = Benefit.query.filter_by(law_firm_id=law_firm_id).count()

        # 2. Histórico real.
        hist = (db.session.query(
            AgentTokenUsage.model_name, func.count(AgentTokenUsage.id), func.avg(AgentTokenUsage.input_tokens),
            func.avg(AgentTokenUsage.output_tokens), func.avg(AgentTokenUsage.estimated_cost_usd),
            func.avg(AgentTokenUsage.latency_ms))
            .filter(AgentTokenUsage.agent_name == 'FAPContestationClassifierAgent',
                    AgentTokenUsage.action_name == 'classify',
                    AgentTokenUsage.law_firm_id == law_firm_id)
            .group_by(AgentTokenUsage.model_name).all())

        # 3. Estimativa pelo tamanho do prompt (sem depender de histórico).
        prompt_chars = (len(Cls.SYSTEM_PROMPT or '') + len(Cls._load_user_prompt_markdown(law_firm_id) or '')
                        + len(Cls._load_reference_markdown_for_llm(law_firm_id) or ''))
        entrada_est = int((Decimal(prompt_chars) + Decimal(media_chars) + 400) / CARACTERES_POR_TOKEN)
        tus = TokenUsageService()
        custo_est, preco_in, preco_out, fonte = tus._estimate_cost_usd(
            model_name=modelo, input_tokens=entrada_est, output_tokens=SAIDA_ESTIMADA)

    print(f'Escritório {law_firm_id} · modelo do classificador: {modelo}')
    print(f'\nVolume')
    print(f'  benefícios no escritório:           {total_beneficios:,}')
    print(f'  decisões no escritório:             {total_decisoes:,}')
    print(f'  decisões sem categoria:             {n_pendentes:,}  ({beneficios:,} benefícios)')
    print(f'  … com texto para classificar:       {n_com_texto:,}  (texto médio {int(media_chars):,} caracteres)')
    print('  O classificador roda uma vez por DECISÃO (1ª e 2ª instância contam separado).')

    print('\nHistórico real (agent_token_usage, FAPContestationClassifierAgent/classify)')
    if not hist:
        print('  nenhuma classificação registrada para este escritório.')
    melhor = None
    for nome, n, ent, sai, custo, lat in sorted(hist, key=lambda h: -h[1]):
        custo = Decimal(str(custo or 0))
        print(f'  {nome or "?":<32} {n:>6} chamadas · ~{int(ent or 0):,} tokens entrada · ~{int(sai or 0):,} saída · '
              f'{_usd(custo)}/chamada · {int(lat or 0) / 1000:.1f}s')
        if (nome or '').strip().lower() == modelo.strip().lower() and n >= 5:
            melhor = (custo, (lat or 0) / 1000, n)

    print(f'\nEstimativa pelo tamanho do prompt ({modelo}, preço via {fonte})')
    print(f'  ~{entrada_est:,} tokens de entrada + ~{SAIDA_ESTIMADA} de saída · '
          f'US$ {preco_in:.5f}/1k entrada · US$ {preco_out:.5f}/1k saída → {_usd(custo_est)}/chamada')

    n = n_com_texto
    print(f'\nCusto para classificar as {n:,} decisões com texto')
    if melhor:
        custo_un, lat, amostra = melhor
        print(f'  pelo histórico ({amostra} chamadas de {modelo}): {_usd(custo_un * n)} · '
              f'~{_duracao(lat * n / max(args.workers, 1))} com {args.workers} em paralelo')
    print(f'  pela estimativa do prompt:                     {_usd(custo_est * n)}')
    print(f'  Jev (comparação):                              {_usd(JEV_CUSTO_POR_ITEM * n)}')
    if not melhor:
        print(f'  (sem histórico suficiente de {modelo}: vale classificar ~50 decisões com '
              f'scripts/classify_fap_benefits.py e rodar este script de novo)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
