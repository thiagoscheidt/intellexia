"""
Processador de recursos judiciais (pendentes).

Uso:
  python scripts/process_judicial_appeals.py

Este script processa recursos pendentes e os gera usando IA.
"""

import os
import sys
import json
from datetime import datetime
from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import db, JudicialAppeal, JudicialSentenceAnalysis
from app.agents.legal_drafting.agent_appeal_generator import AgentAppealGenerator
from app.agents.legal_drafting.document_docx_export_agent import OfficeDocxExportAgent


def create_docx_from_appeal(appeal_content: dict, output_path: str) -> bool:
    """Cria DOCX do recurso usando o agente de exportação padrão do escritório."""
    try:
        buffer = OfficeDocxExportAgent(model_name="gpt-5-mini").export_appeal_content(
            appeal_content=appeal_content,
            run_ai_normalization=True,
        )

        with open(output_path, 'wb') as file_handle:
            file_handle.write(buffer.getvalue())

        print(f"✓ Documento criado com dados da IA: {output_path}")
        return True
    except Exception as e:
        print(f"✗ Erro ao criar documento DOCX: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_appeal_with_ai(
    appeal_type: str,
    sentence_analysis_dict: dict,
    user_notes: str | None = None,
    petition_path: str | None = None
) -> dict | None:
    """
    Gera um recurso judicial usando IA.
    
    Args:
        appeal_type: Tipo de recurso (Apelação, Embargos, etc)
        sentence_analysis_dict: Dicionário com a análise da sentença
        user_notes: Observações do usuário
        petition_path: Caminho da petição inicial (opcional)
        
    Returns:
        dict: Recurso gerado ou None em caso de erro
    """
    try:
        print(f"Gerando {appeal_type} com IA...")
        
        # Extrair conteúdo da petição se disponível
        petition_content = None
        if petition_path and os.path.exists(petition_path):
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(petition_path)
            petition_content = result.text_content[:5000] if result.text_content else None
        
        # Gerar recurso com IA
        agent = AgentAppealGenerator(model_name="gpt-5-mini")
        appeal_result = agent.generate_appeal(
            appeal_type=appeal_type,
            sentence_analysis=sentence_analysis_dict,
            user_notes=user_notes,
            petition_content=petition_content
        )
        
        print("✓ Recurso gerado com sucesso!")
        return appeal_result
        
    except Exception as e:
        print(f"✗ Erro ao gerar recurso: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_pending_appeals(batch_size: int = 10) -> int:
    """Processa um lote de recursos pendentes. Retorna quantidade processada."""
    pending_appeals = (
        JudicialAppeal.query
        .filter(JudicialAppeal.status == 'pending')
        .order_by(JudicialAppeal.created_at.asc())
        .limit(batch_size)
        .all()
    )
    
    if not pending_appeals:
        print("Nenhum recurso pendente encontrado.")
        return 0
    
    processed = 0
    
    for appeal in pending_appeals:
        try:
            # Marcar como processando
            print(f"Iniciando processamento: {appeal.id} - {appeal.appeal_type}")
            appeal.status = 'processing'
            appeal.error_message = None
            db.session.commit()
            
            # Buscar análise da sentença
            sentence = JudicialSentenceAnalysis.query.get(appeal.sentence_analysis_id)
            if not sentence or not sentence.analysis_result:
                raise Exception("Análise da sentença não disponível")
            
            # Converter análise para dict
            sentence_analysis_dict = json.loads(sentence.analysis_result)
            
            # Gerar recurso com IA
            appeal_content = generate_appeal_with_ai(
                appeal_type=appeal.appeal_type,
                sentence_analysis_dict=sentence_analysis_dict,
                user_notes=appeal.user_notes,
                petition_path=sentence.petition_file_path
            )
            
            if not appeal_content:
                raise Exception("Falha ao gerar recurso pela IA")
            
            # Salvar conteúdo como JSON
            appeal.generated_content = json.dumps(appeal_content, ensure_ascii=False, indent=2)
            
            # Criar arquivo DOCX
            upload_dir = os.path.join('uploads', 'appeals')
            os.makedirs(upload_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            docx_filename = f"{timestamp}_appeal_{appeal.id}_{appeal.appeal_type.replace(' ', '_')}.docx"
            docx_path = os.path.join(upload_dir, docx_filename)
            
            if create_docx_from_appeal(appeal_content, docx_path):
                appeal.generated_file_path = docx_path
            
            # Atualizar status
            appeal.processed_at = datetime.utcnow()
            appeal.status = 'completed'
            db.session.commit()
            
            processed += 1
            print(f"✓ Processado: {appeal.id} - {appeal.appeal_type}")
            
        except Exception as e:
            db.session.rollback()
            appeal.status = 'error'
            appeal.error_message = str(e)
            db.session.commit()
            import traceback
            print(f"✗ Erro ao processar {appeal.id}: {e}")
            traceback.print_exc()
    
    return processed


if __name__ == '__main__':
    with app.app_context():
        total = process_pending_appeals(batch_size=10)
        print(f"Total processado: {total}")
