"""
Teste do reuso de arquivos da revisão anterior (Revisor FAP).

Ao enviar nova versão de uma petição, o usuário pode reutilizar os documentos
auxiliares e a planilha de benefícios da revisão anterior sem reenviá-los — os
arquivos são copiados para a nova execução (autocontida no disco).

Uso: uv run python tests/test_fap_review_reuse_previous_files.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.blueprints.fap_review import _copy_reused_revision_files  # noqa: E402
from app.models import FapReviewExecution  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def run():
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / 'old'
        new_dir = Path(tmp) / 'new'
        old_dir.mkdir()
        new_dir.mkdir()

        aux1 = old_dir / '20260101_aux_0_cat.pdf'
        aux1.write_bytes(b'cat')
        aux2 = old_dir / '20260101_aux_1_cnis.pdf'
        aux2.write_bytes(b'cnis')
        missing = old_dir / 'sumiu.pdf'
        sheet = old_dir / '20260101_benefits_planilha.xlsx'
        sheet.write_bytes(b'xlsx')

        previous = FapReviewExecution()
        previous.auxiliary_documents_json = json.dumps([
            {'name': 'CAT.pdf', 'path': str(aux1)},
            {'name': 'CNIS.pdf', 'path': str(aux2)},
            {'name': 'Sumiu.pdf', 'path': str(missing)},
        ])
        previous.benefits_spreadsheet_json = json.dumps(
            {'name': 'Planilha Benefícios.xlsx', 'path': str(sheet)})

        print("[1] Reuso de auxiliares + planilha")
        aux_files, benefits = _copy_reused_revision_files(
            previous, new_dir, '20260721_120000_', reuse_auxiliary=True, reuse_benefits=True)

        check("2 auxiliares copiados (arquivo sumido ignorado)", len(aux_files) == 2,
              f"(obteve {len(aux_files)})")
        check("nomes originais preservados",
              [f['name'] for f in aux_files] == ['CAT.pdf', 'CNIS.pdf'])
        check("cópias existem no diretório novo",
              all(Path(f['path']).exists() and Path(f['path']).parent == new_dir for f in aux_files))
        check("conteúdo copiado", Path(aux_files[0]['path']).read_bytes() == b'cat')
        check("planilha copiada", benefits is not None and Path(benefits['path']).exists())
        check("nome da planilha preservado", benefits and benefits['name'] == 'Planilha Benefícios.xlsx')

        print("[2] Flags desligadas → nada copiado")
        aux_files, benefits = _copy_reused_revision_files(
            previous, new_dir, '20260721_120001_', reuse_auxiliary=False, reuse_benefits=False)
        check("sem auxiliares", aux_files == [])
        check("sem planilha", benefits is None)

        print("[3] Execução anterior sem arquivos → vazio sem erro")
        empty = FapReviewExecution()
        aux_files, benefits = _copy_reused_revision_files(
            empty, new_dir, '20260721_120002_', reuse_auxiliary=True, reuse_benefits=True)
        check("sem auxiliares", aux_files == [])
        check("sem planilha", benefits is None)

        print("[4] Sem execução anterior → vazio sem erro")
        aux_files, benefits = _copy_reused_revision_files(
            None, new_dir, '20260721_120003_', reuse_auxiliary=True, reuse_benefits=True)
        check("sem auxiliares", aux_files == [])
        check("sem planilha", benefits is None)


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
