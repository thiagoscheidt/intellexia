"""
Script de migração para criar as tabelas judicial_phases e judicial_document_types,
com carga inicial de fases judiciais e tipos de documento por escritório.

Uso:
    python database/add_judicial_phases_and_document_types_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, JudicialPhase, JudicialDocumentType


PHASE_ORDER = {
    "inicio_processo": 1,
    "citacao": 2,
    "defesa_reu": 3,
    "manifestacao_autor": 4,
    "saneamento": 5,
    "producao_provas": 6,
    "audiencia": 7,
    "alegacoes_finais": 8,
    "julgamento": 9,
    "recursos": 10,
    "julgamento_tribunal": 11,
    "execucao": 12,
}


JUDICIAL_PHASES = {
    "inicio_processo": "Início do Processo",
    "citacao": "Citação e Intimação",
    "defesa_reu": "Defesa do Réu",
    "manifestacao_autor": "Manifestação do Autor",
    "saneamento": "Saneamento do Processo",
    "producao_provas": "Produção de Provas",
    "audiencia": "Audiência",
    "alegacoes_finais": "Alegações Finais",
    "julgamento": "Julgamento",
    "recursos": "Recursos",
    "julgamento_tribunal": "Julgamento em Tribunal",
    "execucao": "Execução / Cumprimento de Sentença",
    "decisoes_judiciais": "Decisões Judiciais",
    "medidas_urgentes": "Tutelas e Medidas Urgentes",
    "documentos_processuais": "Documentos Processuais",
    "peticoes_diversas": "Petições Diversas"
}


DOCUMENT_TYPES = {
    "peticao_inicial": {"name": "Petição Inicial", "phase": "inicio_processo"},
    "emenda_inicial": {"name": "Emenda à Petição Inicial", "phase": "inicio_processo"},
    "citacao": {"name": "Citação", "phase": "citacao"},
    "contestacao": {"name": "Contestação", "phase": "defesa_reu"},
    "reconvencao": {"name": "Reconvenção", "phase": "defesa_reu"},
    "replica": {"name": "Réplica", "phase": "manifestacao_autor"},
    "manifestacao": {"name": "Manifestação", "phase": "peticoes_diversas"},
    "peticao_intermediaria": {"name": "Petição Intermediária", "phase": "peticoes_diversas"},
    "juntada_documentos": {"name": "Juntada de Documentos", "phase": "peticoes_diversas"},
    "pedido_tutela_urgencia": {"name": "Pedido de Tutela de Urgência", "phase": "medidas_urgentes"},
    "pedido_liminar": {"name": "Pedido de Liminar", "phase": "medidas_urgentes"},
    "despacho": {"name": "Despacho", "phase": "decisoes_judiciais"},
    "decisao_interlocutoria": {"name": "Decisão Interlocutória", "phase": "decisoes_judiciais"},
    "decisao_saneamento": {"name": "Decisão de Saneamento", "phase": "saneamento"},
    "requerimento_prova": {"name": "Requerimento de Prova", "phase": "producao_provas"},
    "laudo_pericial": {"name": "Laudo Pericial", "phase": "producao_provas"},
    "manifestacao_laudo": {"name": "Manifestação sobre Laudo", "phase": "producao_provas"},
    "ata_audiencia": {"name": "Ata de Audiência", "phase": "audiencia"},
    "termo_audiencia": {"name": "Termo de Audiência", "phase": "audiencia"},
    "memoriais": {"name": "Memoriais / Alegações Finais", "phase": "alegacoes_finais"},
    "sentenca": {"name": "Sentença", "phase": "julgamento"},
    "embargos_declaracao": {"name": "Embargos de Declaração", "phase": "recursos"},
    "decisao_ed": {"name": "Decisão de ED", "phase": "recursos"},
    "apelacao": {"name": "Apelação", "phase": "recursos"},
    "contrarrazoes_apelacao": {"name": "Contrarrazões de Apelação", "phase": "recursos"},
    "agravo_instrumento": {"name": "Agravo de Instrumento", "phase": "recursos"},
    "agravo_interno": {"name": "Agravo Interno", "phase": "recursos"},
    "recurso_especial": {"name": "Recurso Especial", "phase": "recursos"},
    "recurso_extraordinario": {"name": "Recurso Extraordinário", "phase": "recursos"},
    "acordao": {"name": "Acórdão", "phase": "julgamento_tribunal"},
    "certidao_julgamento": {"name": "Certidão de Julgamento", "phase": "julgamento_tribunal"},
    "cumprimento_sentenca": {"name": "Pedido de Cumprimento de Sentença", "phase": "execucao"},
    "impugnacao_cumprimento": {"name": "Impugnação ao Cumprimento de Sentença", "phase": "execucao"},
    "calculo_liquidacao": {"name": "Cálculo de Liquidação", "phase": "execucao"},
    "pedido_penhora": {"name": "Pedido de Penhora", "phase": "execucao"},
    "auto_penhora": {"name": "Auto de Penhora", "phase": "execucao"},
    "avaliacao_bens": {"name": "Avaliação de Bens", "phase": "execucao"},
    "edital_leilao": {"name": "Edital de Leilão", "phase": "execucao"},
    "certidao": {"name": "Certidão", "phase": "documentos_processuais"},
    "oficio": {"name": "Ofício Judicial", "phase": "documentos_processuais"},
    "mandado": {"name": "Mandado Judicial", "phase": "documentos_processuais"},
    "alvara": {"name": "Alvará Judicial", "phase": "documentos_processuais"}
}


def migrate():
    with app.app_context():
        try:
            print("🔄 Garantindo criação das tabelas judicial_phases e judicial_document_types...")
            JudicialPhase.__table__.create(bind=db.engine, checkfirst=True)
            JudicialDocumentType.__table__.create(bind=db.engine, checkfirst=True)

            law_firms = LawFirm.query.all()
            if not law_firms:
                print("⚠️ Nenhum escritório encontrado. Tabelas criadas sem carga inicial.")
                return

            total_phases_created = 0
            total_types_created = 0

            for law_firm in law_firms:
                phases_by_key = {
                    phase.key: phase
                    for phase in JudicialPhase.query.filter_by(law_firm_id=law_firm.id).all()
                }

                for order, (phase_key, phase_name) in enumerate(JUDICIAL_PHASES.items(), start=1):
                    if phase_key in phases_by_key:
                        continue

                    display_order = PHASE_ORDER.get(phase_key, order)

                    phase = JudicialPhase(
                        law_firm_id=law_firm.id,
                        key=phase_key,
                        name=phase_name,
                        display_order=display_order,
                        is_active=True,
                    )
                    db.session.add(phase)
                    phases_by_key[phase_key] = phase
                    total_phases_created += 1

                db.session.flush()

                existing_type_keys = {
                    doc_type.key
                    for doc_type in JudicialDocumentType.query.filter_by(law_firm_id=law_firm.id).all()
                }

                for order, (doc_key, doc_payload) in enumerate(DOCUMENT_TYPES.items(), start=1):
                    if doc_key in existing_type_keys:
                        continue

                    phase = phases_by_key.get(doc_payload['phase'])
                    if not phase:
                        continue

                    db.session.add(
                        JudicialDocumentType(
                            law_firm_id=law_firm.id,
                            phase_id=phase.id,
                            key=doc_key,
                            name=doc_payload['name'],
                            display_order=order,
                            is_active=True,
                        )
                    )
                    total_types_created += 1

            db.session.commit()
            print("✅ Migração concluída com sucesso!")
            print(f"✅ Fases criadas: {total_phases_created}")
            print(f"✅ Tipos de documento criados: {total_types_created}")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == '__main__':
    print("=" * 75)
    print("🔧 MIGRAÇÃO: Criar tabelas judicial_phases e judicial_document_types")
    print("=" * 75)
    migrate()
    print("=" * 75)
