#!/usr/bin/env python3
"""Normaliza a coluna cnpj_raiz de fap_web_contestacoes.

Contexto:
    Registros antigos podem ter cnpj_raiz gravado com zeros de padding à esquerda
    (ex.: "00000079" em vez de "79894168"). Isso ocorria porque a raiz era
    derivada do CNPJ já preenchido para 14 dígitos (`cnpj.zfill(14)[:8]`) — o
    padding deslocava a raiz. O código de sincronização já foi corrigido para
    derivar a raiz dos dígitos originais; este script conserta os dados legados.

Fonte da raiz correta:
    O JSON bruto (coluna raw_data) traz o campo canônico `cnpjRaiz` retornado
    pelo portal FAP. Usamos ele como verdade. Como vem serializado como número,
    aplicamos zfill(8) para restaurar eventuais zeros à esquerda perdidos.

Uso:
    uv run python database/normalize_fap_web_contestacoes_cnpj_raiz.py

Idempotente: só atualiza registros cujo cnpj_raiz atual difere do correto.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import db, FapWebContestacao


def _raiz_from_raw(raw_data: str | None) -> str | None:
    """Extrai a raiz canônica (8 dígitos) do JSON bruto da contestação."""
    if not raw_data:
        return None
    try:
        data = json.loads(raw_data)
    except (ValueError, TypeError):
        return None
    raw_raiz = data.get('cnpjRaiz')
    if raw_raiz is None:
        return None
    digits = ''.join(ch for ch in str(raw_raiz) if ch.isdigit())
    if not digits:
        return None
    # cnpjRaiz vem como número → zfill(8) restaura zeros à esquerda perdidos.
    return digits.zfill(8)[:8]


def main() -> None:
    with app.app_context():
        total = FapWebContestacao.query.count()
        print(f"Total de contestações: {total}")

        updated = 0
        skipped_no_raw = 0
        already_ok = 0
        processed = 0

        # Itera em lotes para não carregar tudo na memória.
        BATCH = 1000
        offset = 0
        while True:
            rows = (
                FapWebContestacao.query
                .order_by(FapWebContestacao.id)
                .offset(offset)
                .limit(BATCH)
                .all()
            )
            if not rows:
                break

            for rec in rows:
                processed += 1
                correct = _raiz_from_raw(rec.raw_data)
                if correct is None:
                    skipped_no_raw += 1
                    continue
                if (rec.cnpj_raiz or '') == correct:
                    already_ok += 1
                    continue
                rec.cnpj_raiz = correct
                updated += 1

            db.session.commit()
            offset += BATCH
            print(f"  ... {processed}/{total} processados "
                  f"(corrigidos={updated}, ok={already_ok}, sem_raw={skipped_no_raw})")

        print("\nResumo:")
        print(f"  Corrigidos:            {updated}")
        print(f"  Já corretos:           {already_ok}")
        print(f"  Sem raw_data/cnpjRaiz: {skipped_no_raw}")
        print("Concluído.")


if __name__ == '__main__':
    main()
