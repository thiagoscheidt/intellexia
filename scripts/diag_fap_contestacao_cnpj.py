#!/usr/bin/env python3
"""DIAGNÓSTICO (read-only) do CNPJ das contestações FAP.

NÃO altera nada no banco — apenas lê e imprime. Serve para entender por que
contestações antigas ficam sem PDF: compara o `cnpj` gravado no banco com os
campos de CNPJ presentes no `raw_data` (JSON cru retornado pelo portal FAP).

Uso:
  # Uma contestação específica (imprime o raw_data inteiro):
  uv run python scripts/diag_fap_contestacao_cnpj.py --contestacao_id 19692

  # Resumo de um ano (padrão de cnpj gravado + amostra):
  uv run python scripts/diag_fap_contestacao_cnpj.py --ano_vigencia 2016

  # Vários anos + só as sem PDF:
  uv run python scripts/diag_fap_contestacao_cnpj.py --ano_vigencia 2014 2015 2016 --only_missing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _cnpj_fields_from_raw(raw_data: str | None) -> dict:
    """Extrai do raw_data todas as chaves cujo nome contém 'cnpj' ou 'estab'."""
    if not raw_data:
        return {}
    try:
        data = json.loads(raw_data)
    except (ValueError, TypeError):
        return {'__erro__': 'raw_data não é JSON'}
    out = {}
    for k, v in data.items():
        kl = k.lower()
        if 'cnpj' in kl or 'estab' in kl:
            out[k] = v
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description='Diagnóstico read-only do CNPJ das contestações FAP')
    parser.add_argument('--ano_vigencia', type=int, nargs='+', default=None, help='Ano(s) de vigência')
    parser.add_argument('--law_firm_id', type=int, default=1, help='ID do escritório (padrão: 1)')
    parser.add_argument('--contestacao_id', type=int, default=None, help='Uma contestação específica (imprime raw_data completo)')
    parser.add_argument('--only_missing', action='store_true', help='Somente contestações sem PDF (file_path nulo)')
    parser.add_argument('--limit', type=int, default=25, help='Máx. de linhas na amostra por ano (padrão: 25)')
    args = parser.parse_args()

    from main import app
    from app.models import db, FapWebContestacao  # noqa: F401

    with app.app_context():
        # ── Modo 1: contestação específica ────────────────────────────────
        if args.contestacao_id is not None:
            rec = FapWebContestacao.query.filter_by(
                law_firm_id=args.law_firm_id,
                contestacao_id=args.contestacao_id,
            ).first()
            if not rec:
                print(f"Nenhuma contestação {args.contestacao_id} para law_firm_id={args.law_firm_id}.")
                return
            print("=" * 70)
            print(f"Contestação {rec.contestacao_id} (ano {rec.ano_vigencia})")
            print("=" * 70)
            print(f"  cnpj (gravado)     : {rec.cnpj!r}")
            print(f"  cnpj_raiz (gravado): {rec.cnpj_raiz!r}")
            print(f"  situacao           : {rec.situacao_codigo} / {rec.situacao_descricao}")
            print(f"  file_path          : {rec.file_path!r}")
            print(f"  campos de CNPJ no raw_data: {json.dumps(_cnpj_fields_from_raw(rec.raw_data), ensure_ascii=False)}")
            print("\n  raw_data completo:")
            try:
                print(json.dumps(json.loads(rec.raw_data), ensure_ascii=False, indent=2))
            except Exception:
                print(f"  {rec.raw_data!r}")
            return

        # ── Modo 2: resumo por ano ────────────────────────────────────────
        anos = args.ano_vigencia or []
        if not anos:
            # Sem ano: mostra distribuição geral por ano
            print("Distribuição de contestações por ano (law_firm_id="
                  f"{args.law_firm_id}):")
            rows = (
                FapWebContestacao.query
                .filter_by(law_firm_id=args.law_firm_id)
                .with_entities(FapWebContestacao.ano_vigencia)
                .all()
            )
            from collections import Counter
            for ano, qtd in sorted(Counter(r[0] for r in rows).items(), reverse=True):
                print(f"  {ano}: {qtd}")
            print("\nRode de novo passando --ano_vigencia <ano> para detalhar.")
            return

        for ano in sorted(anos, reverse=True):
            q = FapWebContestacao.query.filter_by(
                law_firm_id=args.law_firm_id, ano_vigencia=ano,
            )
            if args.only_missing:
                q = q.filter(FapWebContestacao.file_path.is_(None))
            recs = q.order_by(FapWebContestacao.cnpj).all()

            total = len(recs)
            sem_pdf = sum(1 for r in recs if not r.file_path)
            com_pdf = total - sem_pdf

            # Classifica o cnpj gravado:
            #  - "raiz_zfill": começa com >=6 zeros e o resto bate com cnpj_raiz  → provável BUG
            #  - "estab_zerada": começa com 00000000 mas resto != cnpj_raiz       → estabelecimento (raiz mascarada)
            #  - "normal": raiz real nos 8 primeiros dígitos
            from collections import Counter
            padroes: Counter = Counter()
            for r in recs:
                c = (r.cnpj or '')
                raiz = (r.cnpj_raiz or '')
                if c[:8] == '00000000':
                    padroes['estab_raiz_mascarada(00000000/....)'] += 1
                elif c.startswith('000000') and c[6:8] != '00':
                    padroes['raiz_da_empresa_zfill(000000+raiz)'] += 1
                else:
                    padroes['outro'] += 1

            print("=" * 70)
            print(f"Ano {ano}: {total} contestação(ões) | com PDF={com_pdf} | sem PDF={sem_pdf}"
                  + ("  [only_missing]" if args.only_missing else ""))
            print("  Padrões do campo cnpj gravado:")
            for nome, qtd in padroes.most_common():
                print(f"    {qtd:5d}  {nome}")

            print(f"\n  Amostra (até {args.limit}):")
            print(f"    {'contestacao':>12} {'cnpj_gravado':>16} {'cnpj_raiz':>10} {'pdf':>4}  raw_cnpj_fields")
            for r in recs[:args.limit]:
                raw_fields = _cnpj_fields_from_raw(r.raw_data)
                print(f"    {r.contestacao_id:>12} {str(r.cnpj):>16} {str(r.cnpj_raiz):>10} "
                      f"{'sim' if r.file_path else 'NAO':>4}  {json.dumps(raw_fields, ensure_ascii=False)}")
            print()


if __name__ == '__main__':
    main()
