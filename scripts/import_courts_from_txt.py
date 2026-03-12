#!/usr/bin/env python3
"""Importa tribunais/órgãos de arquivo JSON para a tabela courts.

Formato esperado (JSON):
[
    {
        "tribunal": "TRF-3",
        "secao_judiciaria": "Seção Judiciária de São Paulo",
        "subsecao": "Mogi das Cruzes",
        "orgao_julgador": "2ª Vara Federal"
    }
]

Uso:
    uv run scripts/import_courts_from_txt.py --all-law-firms
    uv run scripts/import_courts_from_txt.py scripts/varas_unificado.json --law-firm-id 1
    uv run scripts/import_courts_from_txt.py scripts/varas_unificado.json --all-law-firms
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import Case, Court, JudicialProcess, LawFirm, db  # noqa: E402


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


def _iter_records(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("JSON inválido: esperado um array de objetos.")

    for item in data:
        if not isinstance(item, dict):
            continue

        tribunal = _clean_text(str(item.get("tribunal") or ""))
        secao_judiciaria = _clean_text(str(item.get("secao_judiciaria") or ""))
        subsecao_judiciaria = _clean_text(
            str(item.get("subsecao_judiciaria") or item.get("subsecao") or "")
        )
        orgao_julgador = _clean_text(str(item.get("orgao_julgador") or ""))

        if tribunal and orgao_julgador:
            yield tribunal, secao_judiciaria, subsecao_judiciaria, orgao_julgador


def import_courts(file_path: Path, law_firm_ids: list[int]) -> dict[str, int]:
    rows = list(_iter_records(file_path))
    if not rows:
        raise ValueError("Nenhum registro válido encontrado no arquivo.")

    created = 0
    updated = 0
    skipped = 0

    unlinked_cases = 0
    unlinked_judicial_processes = 0

    for law_firm_id in law_firm_ids:
        unlinked_cases += Case.query.filter_by(law_firm_id=law_firm_id).filter(Case.court_id.isnot(None)).update(
            {Case.court_id: None},
            synchronize_session=False,
        )
        unlinked_judicial_processes += (
            JudicialProcess.query.filter_by(law_firm_id=law_firm_id)
            .filter(JudicialProcess.court_id.isnot(None))
            .update({JudicialProcess.court_id: None}, synchronize_session=False)
        )

        Court.query.filter_by(law_firm_id=law_firm_id).delete(synchronize_session=False)

        for tribunal, secao_judiciaria, subsecao_judiciaria, orgao_julgador in rows:
            db.session.add(
                Court(
                    law_firm_id=law_firm_id,
                    tribunal=tribunal,
                    secao_judiciaria=secao_judiciaria,
                    subsecao_judiciaria=subsecao_judiciaria,
                    orgao_julgador=orgao_julgador,
                )
            )
            created += 1

    db.session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "input_rows": len(rows),
        "law_firms": len(law_firm_ids),
        "unlinked_cases": unlinked_cases,
        "unlinked_judicial_processes": unlinked_judicial_processes,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importa tribunais/varas para courts.")
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=Path("scripts/varas_unificado.json"),
        help="Caminho do arquivo JSON (padrão: scripts/varas_unificado.json)",
    )
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
    print(f"- Casos desvinculados de vara: {summary['unlinked_cases']}")
    print(f"- Processos judiciais desvinculados de vara: {summary['unlinked_judicial_processes']}")
    print(f"- Registros criados: {summary['created']}")
    print(f"- Registros atualizados: {summary['updated']}")
    print(f"- Registros já existentes (sem alteração): {summary['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
