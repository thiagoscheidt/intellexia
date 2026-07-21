#!/usr/bin/env python3
"""
Restaura as referências e prompts do Revisor FAP a partir dos arquivos de seed
em database/fap_review_seed/ (manual de revisão, casos de referência,
instruções do projeto e identidade do revisor).

Para cada tipo, cria uma NOVA versão (max+1) com o conteúdo do seed e a ativa —
apenas quando a versão ativa atual está vazia. Use --force para criar a versão
nova mesmo com conteúdo ativo existente (nunca sobrescreve versões antigas).

Idempotente. Uso:
  uv run python database/seed_fap_review_references.py [--law-firm-id 1] [--force]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db, FapReviewPromptVersion, FapReviewReferenceVersion

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fap_review_seed')

REFERENCE_SEEDS = {
    'manual_fap': 'MANUAL_REVISAO_FAP.md',
    'casos_referencia': 'CASOS_REFERENCIA.md',
    'project_instructions': 'PROJECT_INSTRUCTIONS.md',
}

PROMPT_SEEDS = {
    'revisor_identity': 'REVISOR_IDENTITY.md',
}


def _seed_content(filename: str) -> str:
    path = os.path.join(SEED_DIR, filename)
    with open(path, encoding='utf-8') as seed_file:
        return seed_file.read().strip()


def _restore(model, type_field: str, type_value: str, content: str,
             law_firm_id: int, force: bool) -> str:
    query = model.query.filter_by(law_firm_id=law_firm_id, **{type_field: type_value})
    active = query.filter_by(is_active=True).first()

    if active and (active.content or '').strip() == content.strip():
        return f'já idêntica ao seed (ativa v{active.version_number}) — nada a fazer'

    if active and (active.content or '').strip() and not force:
        return (f'mantida (ativa v{active.version_number} tem conteúdo próprio; '
                'use --force para criar nova versão a partir do seed)')

    max_version = max((v.version_number for v in query.all()), default=0)
    query.filter_by(is_active=True).update({'is_active': False})
    db.session.add(model(
        law_firm_id=law_firm_id,
        **{type_field: type_value},
        version_number=max_version + 1,
        content=content,
        change_note='Atualizada a partir do seed do repositório',
        is_active=True,
    ))
    return f'restaurada como v{max_version + 1} ({len(content)} chars, ativa)'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--law-firm-id', type=int, default=1)
    parser.add_argument('--force', action='store_true',
                        help='cria nova versão mesmo se a ativa tiver conteúdo')
    args = parser.parse_args()

    with app.app_context():
        try:
            for reference_type, filename in REFERENCE_SEEDS.items():
                result = _restore(FapReviewReferenceVersion, 'reference_type', reference_type,
                                  _seed_content(filename), args.law_firm_id, args.force)
                print(f'✓ {reference_type}: {result}')

            for prompt_type, filename in PROMPT_SEEDS.items():
                result = _restore(FapReviewPromptVersion, 'prompt_type', prompt_type,
                                  _seed_content(filename), args.law_firm_id, args.force)
                print(f'✓ {prompt_type}: {result}')

            db.session.commit()
            print('✓ Seed do Revisor FAP concluído com sucesso!')
        except Exception as e:
            db.session.rollback()
            print(f'✗ Erro durante o seed: {e}')
            sys.exit(1)
