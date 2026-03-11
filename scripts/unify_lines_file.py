#!/usr/bin/env python3
"""Remove linhas em branco e duplicadas de um arquivo texto.

Preserva a ordem da primeira ocorrencia de cada linha.

Uso:
  python scripts/unify_lines_file.py scripts/varas.txt --in-place
  python scripts/unify_lines_file.py scripts/varas.txt --output scripts/varas_unificado.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path


def unify_lines(input_path: Path, output_path: Path) -> tuple[int, int, int]:
    """Processa o arquivo em streaming e grava linhas unicas nao vazias.

    Retorna: (linhas_lidas, linhas_escritas, linhas_removidas)
    """
    seen: set[str] = set()
    read_count = 0
    write_count = 0

    with input_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for raw_line in src:
            read_count += 1
            line = raw_line.strip()

            if not line:
                continue

            if line in seen:
                continue

            seen.add(line)
            dst.write(f"{line}\n")
            write_count += 1

    removed_count = read_count - write_count
    return read_count, write_count, removed_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unifica linhas de um arquivo, removendo vazias e duplicadas."
    )
    parser.add_argument("input", type=Path, help="Arquivo de entrada")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Arquivo de saida (se omitido, use --in-place)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Sobrescreve o proprio arquivo de entrada",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path: Path = args.input

    if not input_path.exists() or not input_path.is_file():
        print(f"Erro: arquivo nao encontrado: {input_path}")
        return 1

    if args.in_place and args.output is not None:
        print("Erro: use apenas --in-place ou --output, nao ambos.")
        return 1

    if not args.in_place and args.output is None:
        print("Erro: informe --in-place ou --output.")
        return 1

    output_path = args.output if args.output is not None else input_path.with_suffix(input_path.suffix + ".tmp")

    read_count, write_count, removed_count = unify_lines(input_path, output_path)

    if args.in_place:
        output_path.replace(input_path)
        target = input_path
    else:
        target = output_path

    print(f"Arquivo gerado: {target}")
    print(f"Linhas lidas: {read_count}")
    print(f"Linhas finais: {write_count}")
    print(f"Linhas removidas (duplicadas/vazias): {removed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
