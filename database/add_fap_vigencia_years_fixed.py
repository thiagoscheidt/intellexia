#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de migração: Adiciona coluna fap_vigencia_years à tabela case_benefits
Armazena os anos de vigência FAP selecionados (comma-separated)
"""

import sys
import sqlite3
from pathlib import Path

def migrate():
    """Executa a migração via SQLite direto, sem importar o app"""
    try:
        db_path = Path(__file__).parent.parent / "instance" / "intellexia.db"

        if not db_path.exists():
            print(f"❌ Banco não encontrado: {db_path}")
            return False

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Verificar se a coluna já existe
        cursor.execute("PRAGMA table_info(case_benefits);")
        columns = [row[1] for row in cursor.fetchall()]

        if 'fap_vigencia_years' in columns:
            print("✅ Coluna 'fap_vigencia_years' já existe em 'case_benefits'")
            conn.close()
            return True

        cursor.execute("ALTER TABLE case_benefits ADD COLUMN fap_vigencia_years VARCHAR(500);")
        conn.commit()
        conn.close()

        print("✅ Coluna 'fap_vigencia_years' adicionada com sucesso!")
        print("   - Tipo: VARCHAR(500)")
        print("   - Permite: NULL")
        print("   - Uso: Armazenar anos FAP separados por vírgula")
        return True

    except Exception as e:
        print(f"❌ Erro ao executar migração: {e}")
        return False

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
