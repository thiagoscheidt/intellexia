"""
FAP Review Agents - Agentes para Revisão de Petição Inicial FAP

Este módulo contém:
1. Agente Revisor de Petições - Responsável exclusivamente por revisar petições
2. Agente de Treinamento e Evolução - Responsável por manter e evoluir a base de conhecimento
"""

from .reviewer_agent import FapPetitionReviewerAgent
from .training_agent import FapTrainingEvolutionAgent
from .training_apply_agent import FapTrainingApplySubAgent
from .auxiliary_extractor_agent import (
	AuxDocumentExtraction,
	AuxExtractedFact,
	AuxRelatedBenefit,
	FapAuxiliaryDocumentExtractorAgent,
)

__all__ = [
	'FapPetitionReviewerAgent',
	'FapTrainingEvolutionAgent',
	'FapTrainingApplySubAgent',
	'FapAuxiliaryDocumentExtractorAgent',
	'AuxDocumentExtraction',
	'AuxExtractedFact',
	'AuxRelatedBenefit',
]
