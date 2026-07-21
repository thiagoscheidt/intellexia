#!/usr/bin/env python3
"""
Limpa os dados de petições/revisões do Revisor FAP — sem tocar em agentes e
configurações (prompts, referências, settings e execuções de treinamento são
preservados, assim como a auditoria de configuração).

Remove:
  - fap_review_finding_checks        (triagem dos pontos de atenção)
  - fap_review_ignored_findings      (descartes "não pertinente")
  - fap_review_executions            (apenas execution_type='revision')
  - fap_review_petitions             (todas as petições)
  - fap_review_audit_logs            (apenas entity_type 'petition'/'execution')
  - opcional (--remover-arquivos): arquivos de upload das revisões no disco

Por padrão roda em SIMULAÇÃO (mostra o que seria removido). Use --confirmar
para executar de fato.

Uso:
  uv run python scripts/clear_fap_review_petitions.py [--law-firm-id 1] [--remover-arquivos] --confirmar
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import (
    db,
    FapReviewAuditLog,
    FapReviewExecution,
    FapReviewFindingCheck,
    FapReviewIgnoredFinding,
    FapReviewPetition,
)

UPLOAD_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'uploads' / 'fap_review'


def scoped(query, model, law_firm_id):
    if law_firm_id:
        return query.filter(model.law_firm_id == law_firm_id)
    return query


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='limita a um escritório (padrão: todos)')
    parser.add_argument('--remover-arquivos', action='store_true',
                        help='também apaga os arquivos de upload das revisões no disco')
    parser.add_argument('--confirmar', action='store_true',
                        help='executa de fato (sem esta flag, apenas simula)')
    args = parser.parse_args()

    with app.app_context():
        checks = scoped(FapReviewFindingCheck.query, FapReviewFindingCheck, args.law_firm_id)
        ignored = scoped(FapReviewIgnoredFinding.query, FapReviewIgnoredFinding, args.law_firm_id)
        revisions = scoped(
            FapReviewExecution.query.filter(FapReviewExecution.execution_type == 'revision'),
            FapReviewExecution, args.law_firm_id)
        petitions = scoped(FapReviewPetition.query, FapReviewPetition, args.law_firm_id)
        audit = scoped(
            FapReviewAuditLog.query.filter(FapReviewAuditLog.entity_type.in_(['petition', 'execution'])),
            FapReviewAuditLog, args.law_firm_id)

        revision_rows = revisions.all()
        upload_files: set[Path] = set()
        for execution in revision_rows:
            for path in (execution.main_document_path, execution.compared_document_path):
                if path:
                    upload_files.add(Path(path))
            try:
                aux_docs = json.loads(execution.auxiliary_documents_json or '[]')
            except (TypeError, json.JSONDecodeError):
                aux_docs = []
            for doc in aux_docs if isinstance(aux_docs, list) else []:
                if isinstance(doc, dict) and doc.get('path'):
                    upload_files.add(Path(doc['path']))
            try:
                benefits = json.loads(execution.benefits_spreadsheet_json or 'null')
            except (TypeError, json.JSONDecodeError):
                benefits = None
            if isinstance(benefits, dict) and benefits.get('path'):
                upload_files.add(Path(benefits['path']))
        existing_files = [f for f in upload_files if f.is_file()]

        scope_label = f'escritório {args.law_firm_id}' if args.law_firm_id else 'TODOS os escritórios'
        print(f'Escopo: {scope_label}')
        print(f'  - checks de triagem:        {checks.count()}')
        print(f'  - descartes memorizados:    {ignored.count()}')
        print(f'  - execuções de revisão:     {len(revision_rows)}')
        print(f'  - petições:                 {petitions.count()}')
        print(f'  - logs de auditoria (pet/exec): {audit.count()}')
        print(f'  - arquivos no disco:        {len(existing_files)}'
              + ('' if args.remover_arquivos else ' (mantidos — use --remover-arquivos)'))

        training = scoped(
            FapReviewExecution.query.filter(FapReviewExecution.execution_type != 'revision'),
            FapReviewExecution, args.law_firm_id).count()
        print(f'Preservados: prompts, referências, settings, {training} execução(ões) de treinamento '
              'e auditoria de configuração.')

        if not args.confirmar:
            print('\nSIMULAÇÃO — nada foi removido. Rode novamente com --confirmar para executar.')
            return 0

        try:
            checks.delete(synchronize_session=False)
            ignored.delete(synchronize_session=False)
            # petições referenciam latest_revision_id → limpar antes de apagar execuções
            petitions.update({'latest_revision_id': None}, synchronize_session=False)
            revisions.delete(synchronize_session=False)
            petitions.delete(synchronize_session=False)
            audit.delete(synchronize_session=False)
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            print(f'✗ Erro ao limpar (nada foi alterado): {error}')
            return 1

        removed_files = 0
        if args.remover_arquivos:
            for file in existing_files:
                try:
                    # segurança: só apaga dentro de uploads/fap_review
                    file.resolve().relative_to(UPLOAD_ROOT.resolve())
                    file.unlink()
                    removed_files += 1
                except Exception:
                    continue
            print(f'✓ {removed_files} arquivo(s) removidos do disco')

        print('✓ Limpeza concluída com sucesso!')
        return 0


if __name__ == '__main__':
    sys.exit(main())
