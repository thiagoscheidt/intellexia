#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de migração: Adiciona coluna fap_vigencia_years à tabela case_benefits
Armazena os anos de vigência FAP selecionados (comma-separated)
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app, db
from app.models import CaseBenefit

def migrate():
    """Executa a migração"""
    app = create_app()
    
    with app.app_context():
        try:
            # Verificar se a coluna já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('case_benefits')]
            
            if 'fap_vigencia_years' in columns:
                print("✅ Coluna 'fap_vigencia_years' já existe em 'case_benefits'")
                return
            
            # Executar SQL para adicionar a coluna
            db.engine.execute('''
                ALTER TABLE case_benefits 
                ADD COLUMN fap_vigencia_years VARCHAR(500) NULL 
                COMMENT 'Anos de vigência FAP (comma-separated, ex: "2019,2020,2021")'
            ''')
            
            print("✅ Coluna 'fap_vigencia_years' adicionada com sucesso!")
            print("   - Tipo: VARCHAR(500)")
            print("   - Permite: NULL")
            print("   - Uso: Armazenar anos FAP separados por vírgula")
            
        except Exception as e:
            print(f"❌ Erro ao executar migração: {e}")
            return False
    
    return True

if __name__ == '__main__':
    print("\n🔄 Iniciando migração: add_fap_vigencia_years.py")
    print("=" * 60)
    
    success = migrate()
    
    if success:
        print("\n✅ Migração concluída com sucesso!")
        print("   A coluna 'fap_vigencia_years' está pronta para uso.")
    else:
        print("\n❌ Migração falhou!")
        sys.exit(1)
