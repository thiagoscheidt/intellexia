#!/usr/bin/env python3
"""Importa tribunais/varas de arquivo TXT para a tabela courts.

Formato esperado (TSV):
TRIBUNAL\tÓRGÃO JULGADOR
TRF-4\t1ª Vara Federal de Blumenau/SC
...

Uso:
  uv run scripts/import_courts_from_txt.py scripts/varas_unificado.txt --law-firm-id 1
  uv run scripts/import_courts_from_txt.py scripts/varas_unificado.txt --all-law-firms
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import Court, LawFirm, db  # noqa: E402


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _clean_text(value: str) -> str:
    value = (value or "").replace("\u00a0", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _normalize_key(value: str) -> str:
    value = _clean_text(value).lower()
    value = _strip_accents(value)
    value = value.replace("º", "o").replace("ª", "a")
    value = re.sub(r"\s*-\s*", " - ", value)
    value = re.sub(r"\s*/\s*", "/", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_city_state(orgao_julgador: str) -> tuple[str | None, str | None]:
    texto = _clean_text(orgao_julgador)

    # Ex.: "... de Blumenau/SC" ou "... de Belo Horizonte /MG"
    match_slash = re.search(r"de\s+([A-Za-zÀ-ÿ'\-\s]+?)\s*/\s*([A-Za-z]{2})\s*$", texto, re.IGNORECASE)
    if match_slash:
        city = _clean_text(match_slash.group(1))
        state = match_slash.group(2).upper()
        return city, state

    # Ex.: "... - SC" ou "... - PR"
    match_dash = re.search(r"-\s*([A-Za-z]{2})\s*$", texto, re.IGNORECASE)
    if match_dash:
        state = match_dash.group(1).upper()
        # tenta extrair cidade após o último "de"
        match_city = re.search(r"de\s+([A-Za-zÀ-ÿ'\-\s]+?)\s*(?:-|$)", texto, re.IGNORECASE)
        city = _clean_text(match_city.group(1)) if match_city else None
        return city or None, state

    return None, None


def _iter_records(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        header_skipped = False
        for raw_line in f:
            line = _clean_text(raw_line)
            if not line:
                continue

            if not header_skipped:
                header_skipped = True
                upper_line = _normalize_key(line)
                if "tribunal" in upper_line and ("orgao julgador" in upper_line or "órgao julgador" in upper_line):
                    continue

            parts = [p.strip() for p in raw_line.replace("\u00a0", " ").strip().split("\t") if p.strip()]
            if len(parts) < 2:
                continue

            tribunal = _clean_text(parts[0])
            orgao = _clean_text(parts[1])
            if tribunal and orgao:
                yield tribunal, orgao


def import_courts(file_path: Path, law_firm_ids: list[int]) -> dict[str, int]:
    rows = list(_iter_records(file_path))
    if not rows:
        raise ValueError("Nenhum registro válido encontrado no arquivo.")

    created = 0
    updated = 0
    skipped = 0

    for law_firm_id in law_firm_ids:
        existing_courts = Court.query.filter_by(law_firm_id=law_firm_id).all()
        existing_map: dict[tuple[str, str], Court] = {}

        for court in existing_courts:
            key = (_normalize_key(court.section or ""), _normalize_key(court.vara_name or ""))
            existing_map[key] = court

        for tribunal, orgao in rows:
            key = (_normalize_key(tribunal), _normalize_key(orgao))
            city, state = _extract_city_state(orgao)

            court = existing_map.get(key)
            if court is None:
                db.session.add(
                    Court(
                        law_firm_id=law_firm_id,
                        section=tribunal,
                        vara_name=orgao,
                        city=city,
                        state=state,
                    )
                )
                created += 1
                continue

            changed = False
            if city and not court.city:
                court.city = city
                changed = True
            if state and not court.state:
                court.state = state
                changed = True

            if changed:
                updated += 1
            else:
                skipped += 1

    db.session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "input_rows": len(rows),
        "law_firms": len(law_firm_ids),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importa tribunais/varas para courts.")
    parser.add_argument("file", type=Path, help="Caminho do arquivo TXT/TSV")
    parser.add_argument("--law-firm-id", type=int, help="Importar para um escritório específico")
    parser.add_argument(
        "--all-law-firms",
        action="store_true",
        help="Importar para todos os escritórios",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.file.exists() or not args.file.is_file():
        print(f"Erro: arquivo não encontrado: {args.file}")
        return 1

    if bool(args.law_firm_id) == bool(args.all_law_firms):
        print("Erro: informe apenas --law-firm-id ou --all-law-firms.")
        return 1

    with app.app_context():
        if args.law_firm_id:
            law_firm = LawFirm.query.get(args.law_firm_id)
            if not law_firm:
                print(f"Erro: law_firm_id {args.law_firm_id} não encontrado.")
                return 1
            law_firm_ids = [args.law_firm_id]
        else:
            law_firm_ids = [item.id for item in LawFirm.query.all()]
            if not law_firm_ids:
                print("Erro: nenhum escritório encontrado.")
                return 1

        try:
            summary = import_courts(args.file, law_firm_ids)
        except Exception as exc:
            db.session.rollback()
            print(f"Erro ao importar: {exc}")
            return 1

    print("Importação concluída com sucesso")
    print(f"- Linhas de entrada: {summary['input_rows']}")
    print(f"- Escritórios processados: {summary['law_firms']}")
    print(f"- Registros criados: {summary['created']}")
    print(f"- Registros atualizados: {summary['updated']}")
    print(f"- Registros já existentes (sem alteração): {summary['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
