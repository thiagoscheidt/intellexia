"""
Script para popular as tags padrão para todos os escritórios
"""

import sys
from pathlib import Path

# Adicionar o diretório pai ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Importar o app do main.py
from main import app
from app.models import db, LawFirm, KnowledgeTag
from datetime import datetime

def populate_default_tags():
    """Popula tags padrão para todos os escritórios"""
    
    default_tags = [
        {"name": "Trabalhista", "icon": "⚖️", "description": "Direito do trabalho", "color": "#007bff", "order": 1},
        {"name": "Previdenciário", "icon": "🏛️", "description": "Direito previdenciário", "color": "#6c757d", "order": 2},
        {"name": "STJ", "icon": "🏛️", "description": "Superior Tribunal de Justiça", "color": "#28a745", "order": 3},
        {"name": "STF", "icon": "⚖️", "description": "Supremo Tribunal Federal", "color": "#dc3545", "order": 4},
        {"name": "Súmula", "icon": "📋", "description": "Súmulas", "color": "#ffc107", "order": 5},
        {"name": "Jurisprudência", "icon": "📚", "description": "Decisões judiciais", "color": "#17a2b8", "order": 6},
        {"name": "Legislação", "icon": "📜", "description": "Leis e normas", "color": "#6f42c1", "order": 7},
        {"name": "Petição", "icon": "📝", "description": "Peças processuais", "color": "#fd7e14", "order": 8},
        {"name": "Recurso", "icon": "📄", "description": "Recursos judiciais", "color": "#20c997", "order": 9},
        {"name": "Acórdão", "icon": "⚖️", "description": "Decisões colegiadas", "color": "#e83e8c", "order": 10},
        {"name": "Sentença", "icon": "🔨", "description": "Decisões judiciais", "color": "#343a40", "order": 11},
        {"name": "Despacho", "icon": "📋", "description": "Decisões interlocutórias", "color": "#6c757d", "order": 12},
        {"name": "FAP", "icon": "💼", "description": "Fator Acidentário de Prevenção", "color": "#007bff", "order": 13},
        {"name": "INSS", "icon": "🏛️", "description": "Instituto Nacional do Seguro Social", "color": "#28a745", "order": 14},
        {"name": "Acidente", "icon": "🚑", "description": "Acidente de trabalho", "color": "#dc3545", "order": 15},
        {"name": "Aposentadoria", "icon": "👴", "description": "Benefícios de aposentadoria", "color": "#17a2b8", "order": 16},
        {"name": "Auxílio-doença", "icon": "🏥", "description": "Benefício por incapacidade", "color": "#ffc107", "order": 17},
        {"name": "Pensão", "icon": "👨‍👩‍👧", "description": "Pensão por morte", "color": "#6f42c1", "order": 18},
    ]
    
    with app.app_context():
        try:
            # Buscar todos os escritórios
            law_firms = LawFirm.query.all()
            
            if not law_firms:
                print("⚠️  Nenhum escritório encontrado no banco de dados")
                return
            
            tags_created = 0
            
            for firm in law_firms:
                print(f"\n🏢 Processando escritório: {firm.name} (ID: {firm.id})")
                
                # Verificar se já existem tags para este escritório
                existing_tags_count = KnowledgeTag.query.filter_by(law_firm_id=firm.id).count()
                
                if existing_tags_count > 0:
                    print(f"   ℹ️  Escritório já possui {existing_tags_count} tag(s). Pulando...")
                    continue
                
                # Criar tags padrão para este escritório
                for tag_data in default_tags:
                    tag = KnowledgeTag(
                        law_firm_id=firm.id,
                        name=tag_data["name"],
                        icon=tag_data["icon"],
                        description=tag_data["description"],
                        color=tag_data["color"],
                        display_order=tag_data["order"],
                        is_active=True,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    db.session.add(tag)
                    tags_created += 1
                
                print(f"   ✅ {len(default_tags)} tags criadas com sucesso!")
            
            db.session.commit()
            print(f"\n🎉 Total de {tags_created} tags criadas em {len(law_firms)} escritório(s)!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao popular tags: {e}")
            raise

if __name__ == "__main__":
    populate_default_tags()
