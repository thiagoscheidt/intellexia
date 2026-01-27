"""
Script para popular categorias padrão de documentos da base de conhecimento

Uso:
    python database/populate_default_categories.py
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, KnowledgeCategory, LawFirm

# Categorias padrão do sistema
DEFAULT_CATEGORIES = [
    {
        'name': 'Jurisprudência',
        'icon': '📚',
        'description': 'Decisões judiciais relevantes, súmulas, precedentes',
        'color': '#007bff',
        'display_order': 1
    },
    {
        'name': 'Legislação',
        'icon': '⚖️',
        'description': 'Leis, decretos, portarias, normas regulamentares',
        'color': '#28a745',
        'display_order': 2
    },
    {
        'name': 'Modelos',
        'icon': '📄',
        'description': 'Modelos de documentos, petições, contratos',
        'color': '#17a2b8',
        'display_order': 3
    },
    {
        'name': 'Artigos',
        'icon': '📰',
        'description': 'Artigos jurídicos, estudos, análises doutrinárias',
        'color': '#ffc107',
        'display_order': 4
    },
    {
        'name': 'Manuais',
        'icon': '📖',
        'description': 'Manuais, guias práticos, tutoriais',
        'color': '#6f42c1',
        'display_order': 5
    },
    {
        'name': 'Procedimentos',
        'icon': '🔧',
        'description': 'Procedimentos internos, fluxos de trabalho',
        'color': '#fd7e14',
        'display_order': 6
    },
    {
        'name': 'Outros',
        'icon': '📦',
        'description': 'Outros documentos e arquivos diversos',
        'color': '#6c757d',
        'display_order': 7
    }
]

def populate_categories():
    """Popula categorias padrão para todos os escritórios"""
    
    with app.app_context():
        try:
            # Buscar todos os escritórios
            law_firms = LawFirm.query.all()
            
            if not law_firms:
                print("⚠️  Nenhum escritório encontrado. Execute populate_sample_data.py primeiro.")
                return
            
            total_created = 0
            
            for law_firm in law_firms:
                print(f"\n📂 Processando escritório: {law_firm.name}")
                
                # Verificar se já tem categorias
                existing = KnowledgeCategory.query.filter_by(law_firm_id=law_firm.id).count()
                
                if existing > 0:
                    print(f"   ⚠️  Escritório já possui {existing} categoria(s). Pulando...")
                    continue
                
                # Criar categorias padrão
                for cat_data in DEFAULT_CATEGORIES:
                    category = KnowledgeCategory(
                        law_firm_id=law_firm.id,
                        name=cat_data['name'],
                        icon=cat_data['icon'],
                        description=cat_data['description'],
                        color=cat_data['color'],
                        display_order=cat_data['display_order'],
                        is_active=True
                    )
                    db.session.add(category)
                    total_created += 1
                
                print(f"   ✅ {len(DEFAULT_CATEGORIES)} categorias criadas")
            
            db.session.commit()
            
            print(f"\n✅ Total de {total_created} categorias criadas com sucesso!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao popular categorias: {e}")
            raise

if __name__ == '__main__':
    print("=" * 70)
    print("📚 POPULAR CATEGORIAS PADRÃO")
    print("=" * 70)
    populate_categories()
    print("=" * 70)
    print("✅ Processo concluído!")
    print("=" * 70)
