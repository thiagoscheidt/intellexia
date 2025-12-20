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
    db, Client, Court, Lawyer, Case, CaseLawyer, 
    CaseCompetence, CaseBenefit, Document
)

def clear_all_data():
    """Remove todos os dados do banco de dados"""
    try:
        with app.app_context():
            print("🗑️ Iniciando limpeza dos dados...")
            
            # Ordem de remoção respeitando dependências
            tables_info = [
                (Document, "documentos"),
                (CaseCompetence, "competências"),
                (CaseBenefit, "benefícios"),
                (CaseLawyer, "relações caso-advogado"),
                (Case, "casos"),
                (Lawyer, "advogados"),
                (Court, "varas judiciais"),
                (Client, "clientes")
            ]
            
            total_deleted = 0
            
            for model, description in tables_info:
                count = model.query.count()
                if count > 0:
                    model.query.delete()
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
        db.session.rollback()
        raise

def clear_specific_data(table_name):
    """Remove dados de uma tabela específica"""
    table_map = {
        'documents': (Document, "documentos"),
        'competences': (CaseCompetence, "competências"),
        'benefits': (CaseBenefit, "benefícios"),
        'case_lawyers': (CaseLawyer, "relações caso-advogado"),
        'cases': (Case, "casos"),
        'lawyers': (Lawyer, "advogados"),
        'courts': (Court, "varas judiciais"),
        'clients': (Client, "clientes")
    }
    
    if table_name not in table_map:
        print(f"❌ Tabela '{table_name}' não encontrada.")
        print(f"Tabelas disponíveis: {', '.join(table_map.keys())}")
        return
    
    try:
        with app.app_context():
            model, description = table_map[table_name]
            count = model.query.count()
            
            if count > 0:
                model.query.delete()
                db.session.commit()
                print(f"✅ Removidos {count} {description}")
            else:
                print(f"→ Nenhum registro em {description}")
                
    except Exception as e:
        print(f"❌ Erro durante a limpeza de {table_name}: {e}")
        db.session.rollback()
        raise

def show_data_summary():
    """Mostra resumo dos dados no banco"""
    try:
        with app.app_context():
            tables_info = [
                (Client, "clientes"),
                (Court, "varas judiciais"),
                (Lawyer, "advogados"),
                (Case, "casos"),
                (CaseLawyer, "relações caso-advogado"),
                (CaseBenefit, "benefícios"),
                (CaseCompetence, "competências"),
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
        choices=['documents', 'competences', 'benefits', 'case_lawyers', 
                'cases', 'lawyers', 'courts', 'clients']
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