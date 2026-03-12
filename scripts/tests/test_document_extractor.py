"""
Script de teste do AgentDocumentExtractor usando um arquivo real da KnowledgeBase.

Uso:
    /Users/thiagoscheidt/Projects/intellexia/.venv/bin/python scripts/tests/test_document_extractor.py
    /Users/thiagoscheidt/Projects/intellexia/.venv/bin/python scripts/tests/test_document_extractor.py --knowledge-id 123
    /Users/thiagoscheidt/Projects/intellexia/.venv/bin/python scripts/tests/test_document_extractor.py --law-firm-id 1
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from rich import print

# Configurar logging para ver mensagens de debug
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import KnowledgeBase
from app.agents.document_processing.agent_document_extractor import AgentDocumentExtractor
from app.agents.document_processing.agent_benefit_thesis_classifier import AgentBenefitThesisClassifier


def _build_query(knowledge_id: int | None = None, law_firm_id: int | None = None):
    query = KnowledgeBase.query.filter(KnowledgeBase.is_active.is_(True))

    if knowledge_id is not None:
        query = query.filter(KnowledgeBase.id == knowledge_id)

    if law_firm_id is not None:
        query = query.filter(KnowledgeBase.law_firm_id == law_firm_id)

    return query.order_by(KnowledgeBase.uploaded_at.desc())


def _pick_knowledge_item(knowledge_id: int | None = None, law_firm_id: int | None = None) -> KnowledgeBase | None:
    candidates = _build_query(knowledge_id=knowledge_id, law_firm_id=law_firm_id).all()

    if not candidates:
        return None

    for item in candidates:
        if item.file_path and Path(item.file_path).exists():
            return item

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description='Testa o AgentDocumentExtractor com arquivo da KnowledgeBase')
    parser.add_argument('--knowledge-id', type=int, help='ID específico da tabela knowledge_base')
    parser.add_argument('--law-firm-id', type=int, help='Filtrar por escritório (law_firm_id)')
    parser.add_argument('--model-name', default='gpt-5-mini', help='Modelo de chat para extração')
    parser.add_argument('--model-provider', default=None, help='Provider do modelo (ex.: openai)')

    args = parser.parse_args()

    with app.app_context():
        kb_item = _pick_knowledge_item(knowledge_id=args.knowledge_id, law_firm_id=args.law_firm_id)

        if not kb_item:
            print('Nenhum arquivo válido encontrado na KnowledgeBase para os filtros informados.')
            return 1

        print('Arquivo selecionado para teste:')
        print(f'- knowledge_base.id: {kb_item.id}')
        print(f'- law_firm_id: {kb_item.law_firm_id}')
        print(f'- filename: {kb_item.original_filename}')
        print(f'- file_path: {kb_item.file_path}')

        extractor = AgentDocumentExtractor(
            model_name=args.model_name,
            model_provider=args.model_provider,
        )

        try:
            result = extractor.extract_document_data(
                file_path=kb_item.file_path,
                law_firm_id=kb_item.law_firm_id,
            )
        except Exception as error:
            print(f'Erro ao executar AgentDocumentExtractor: {error}')
            return 1

        print('\nResultado da extração:')
        for key, value in result.items():
            print(f'- {key}: {value}')

        try:
            benefits_result = extractor.extract_benefits_from_petition(
                file_path=kb_item.file_path,
            )
        except Exception as error:
            print(f'Erro ao executar extract_benefits_from_petition: {error}')
            return 1

        print('\nResultado da extração de benefícios:')
        for key, value in benefits_result.items():
            print(f'- {key}: {value}')

        # Classificação de benefícios por tese jurídica
        # classifier = AgentBenefitThesisClassifier(
        #     model_name=args.model_name,
        #     model_provider=args.model_provider,
        # )

        # try:
        #     classification_result = classifier.classify_benefits(
        #         file_path=kb_item.file_path,
        #         benefits=benefits_result.get('benefits', []),
        #         law_firm_id=kb_item.law_firm_id,
        #     )
        # except Exception as error:
        #     print(f'Erro ao executar AgentBenefitThesisClassifier: {error}')
        #     return 1

        # print('\nResultado da classificação de benefícios por tese jurídica:')
        # for key, value in classification_result.items():
        #     print(f'- {key}: {value}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
