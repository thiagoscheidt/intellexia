#!/usr/bin/env python3
"""
Script para limpar dados de exemplo do sistema Intellexia

Execute: python clear_sample_data.py
"""

import os
import sys
from pathlib import Path

# Adicionar o diretório do projeto ao path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Importar a aplicação e modelos
from main import app
from app.models import (
    db, LawFirm, User, Client, Court, Lawyer, Case, CaseLawyer,
    CaseCompetence, CaseBenefit, Document, CaseActivity, CaseComment,
    KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate
)


def get_environment_name():
    """Obtém o ENVIRONMENT de forma robusta (env vars > arquivo .env)."""
    env_name = os.getenv('ENVIRONMENT')
    if env_name:
        return env_name.strip().lower()

    env_file = project_root / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            parsed = line.strip()
            if not parsed or parsed.startswith('#') or '=' not in parsed:
                continue
            key, value = parsed.split('=', 1)
            if key.strip() == 'ENVIRONMENT':
                return value.strip().strip('"').strip("'").lower()

    return 'development'


def ensure_not_production():
    """Impede execução do script quando ambiente estiver em produção."""
    environment = get_environment_name()
    if environment == 'production':
        print("❌ Execução bloqueada: ENVIRONMENT=production")
        print("Este script é destrutivo e não pode ser executado em produção.")
        raise SystemExit(1)


def delete_model_records(model):
    """Remove registros de um modelo, tratando casos especiais de FK."""
    count = model.query.count()
    if count == 0:
        return 0

    if model is CaseComment:
        db.session.query(CaseComment).filter(
            CaseComment.parent_comment_id.isnot(None)
        ).update(
            {CaseComment.parent_comment_id: None},
            synchronize_session=False
        )

    model.query.delete(synchronize_session=False)
    return count

def clear_all_data():
    """Remove todos os dados do banco de dados"""
    try:
        ensure_not_production()
        with app.app_context():
            print("🗑️ Iniciando limpeza dos dados...")
            
            # Ordem de remoção respeitando dependências
            tables_info = [
                (Document, "documentos"),
                (CaseActivity, "atividades"),
                (CaseComment, "comentários"),
                (CaseCompetence, "competências"),
                (CaseBenefit, "benefícios"),
                (CaseLawyer, "relações caso-advogado"),
                (FapReason, "motivos FAP"),
                (CaseTemplate, "templates de casos"),
                (Case, "casos"),
                (Lawyer, "advogados"),
                (Court, "varas judiciais"),
                (Client, "clientes"),
                (KnowledgeTag, "tags de conhecimento"),
                (KnowledgeCategory, "categorias de conhecimento"),
                (User, "usuários"),
                (LawFirm, "escritórios")
            ]
            
            total_deleted = 0
            
            for model, description in tables_info:
                count = delete_model_records(model)
                if count > 0:
                    total_deleted += count
                    print(f"✓ Removidos {count} {description}")
                else:
                    print(f"→ Nenhum registro em {description}")
            
            # Commit das remoções
            db.session.commit()
            
            print("\n" + "=" * 40)
            print(f"✅ LIMPEZA CONCLUÍDA!")
            print(f"Total de registros removidos: {total_deleted}")
            print("=" * 40)
            
    except Exception as e:
        print(f"❌ Erro durante a limpeza: {e}")
        with app.app_context():
            db.session.rollback()
        raise

def clear_specific_data(table_name):
    """Remove dados de uma tabela específica"""
    ensure_not_production()
    table_map = {
        'documents': (Document, "documentos"),
        'activities': (CaseActivity, "atividades"),
        'comments': (CaseComment, "comentários"),
        'competences': (CaseCompetence, "competências"),
        'benefits': (CaseBenefit, "benefícios"),
        'case_lawyers': (CaseLawyer, "relações caso-advogado"),
        'fap_reasons': (FapReason, "motivos FAP"),
        'templates': (CaseTemplate, "templates de casos"),
        'cases': (Case, "casos"),
        'lawyers': (Lawyer, "advogados"),
        'courts': (Court, "varas judiciais"),
        'clients': (Client, "clientes"),
        'knowledge_tags': (KnowledgeTag, "tags de conhecimento"),
        'knowledge_categories': (KnowledgeCategory, "categorias de conhecimento"),
        'users': (User, "usuários"),
        'law_firms': (LawFirm, "escritórios")
    }
    
    if table_name not in table_map:
        print(f"❌ Tabela '{table_name}' não encontrada.")
        print(f"Tabelas disponíveis: {', '.join(table_map.keys())}")
        return
    
    try:
        with app.app_context():
            model, description = table_map[table_name]
            count = delete_model_records(model)
            
            if count > 0:
                db.session.commit()
                print(f"✅ Removidos {count} {description}")
            else:
                print(f"→ Nenhum registro em {description}")
                
    except Exception as e:
        print(f"❌ Erro durante a limpeza de {table_name}: {e}")
        with app.app_context():
            db.session.rollback()
        raise

def show_data_summary():
    """Mostra resumo dos dados no banco"""
    try:
        ensure_not_production()
        with app.app_context():
            tables_info = [
                (LawFirm, "escritórios"),
                (User, "usuários"),
                (Client, "clientes"),
                (Court, "varas judiciais"),
                (Lawyer, "advogados"),
                (Case, "casos"),
                (CaseLawyer, "relações caso-advogado"),
                (CaseBenefit, "benefícios"),
                (CaseCompetence, "competências"),
                (CaseActivity, "atividades"),
                (CaseComment, "comentários"),
                (FapReason, "motivos FAP"),
                (CaseTemplate, "templates de casos"),
                (KnowledgeCategory, "categorias de conhecimento"),
                (KnowledgeTag, "tags de conhecimento"),
                (Document, "documentos")
            ]
            
            print("📊 RESUMO DOS DADOS ATUAIS:")
            print("=" * 40)
            
            total_records = 0
            for model, description in tables_info:
                count = model.query.count()
                total_records += count
                status = "📝" if count > 0 else "📄"
                print(f"{status} {count:3d} {description}")
            
            print("=" * 40)
            print(f"Total de registros: {total_records}")
            
    except Exception as e:
        print(f"❌ Erro ao consultar dados: {e}")

def main():
    """Função principal"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Script para limpar dados do sistema Intellexia"
    )
    parser.add_argument(
        '--table', 
        help='Limpar apenas uma tabela específica',
        choices=['documents', 'activities', 'comments', 'competences', 'benefits', 'case_lawyers',
             'fap_reasons', 'templates', 'cases', 'lawyers', 'courts', 'clients',
             'knowledge_tags', 'knowledge_categories', 'users', 'law_firms']
    )
    parser.add_argument(
        '--summary', 
        action='store_true',
        help='Mostrar apenas resumo dos dados sem limpar'
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Confirmar limpeza sem prompt interativo'
    )
    
    args = parser.parse_args()
    
    if args.summary:
        show_data_summary()
        return
    
    if args.table:
        if not args.confirm:
            response = input(f"⚠️ Confirma a remoção de todos os dados da tabela '{args.table}'? (s/N): ")
            if response.lower() not in ['s', 'sim', 'yes', 'y']:
                print("Operação cancelada.")
                return
        
        clear_specific_data(args.table)
    else:
        if not args.confirm:
            print("⚠️ Esta operação irá remover TODOS os dados do sistema!")
            response = input("Confirma a remoção completa? (s/N): ")
            if response.lower() not in ['s', 'sim', 'yes', 'y']:
                print("Operação cancelada.")
                return
        
        clear_all_data()

if __name__ == '__main__':
    main()