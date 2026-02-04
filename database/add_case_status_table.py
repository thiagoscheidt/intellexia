#!/usr/bin/env python3
"""
Script para criar tabela de situações de caso e adicionar campo case_status_id na tabela cases
"""
import sys
sys.path.insert(0, '/c/Users/thiago/projetos/intellexia')

from app import create_app, db

app = create_app()

with app.app_context():
    # SQL para criar a tabela case_status
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS case_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status_name VARCHAR(100) NOT NULL UNIQUE,
        status_order INTEGER NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # SQL para inserir as situações
    insert_status_sql = """
    INSERT INTO case_status (status_name, status_order, description) VALUES
    ('Novo caso recebido', 1, 'Novo caso foi recebido'),
    ('Em análise jurídica inicial', 2, 'Análise jurídica inicial em progresso'),
    ('Aguardando documentos do cliente', 3, 'Aguardando documentos do cliente'),
    ('Documentos recebidos', 4, 'Documentos do cliente foram recebidos'),
    ('Petição em elaboração', 5, 'Petição está sendo elaborada'),
    ('Petição em revisão', 6, 'Petição em fase de revisão'),
    ('Petição finalizada', 7, 'Petição foi finalizada'),
    ('Aguardando protocolo', 8, 'Aguardando protocolo da petição'),
    ('Petição protocolada', 9, 'Petição foi protocolada'),
    ('Número do processo recebido', 10, 'Número do processo foi recebido'),
    ('Aguardando despacho inicial do juiz', 11, 'Aguardando despacho inicial do juiz'),
    ('Em andamento', 12, 'Processo em andamento'),
    ('Prazo em aberto', 13, 'Prazo em aberto para ação'),
    ('Caso suspenso', 14, 'Caso foi suspenso'),
    ('Caso encerrado / arquivado', 15, 'Caso foi encerrado ou arquivado');
    """
    
    # SQL para adicionar coluna case_status_id
    add_column_sql = """
    ALTER TABLE cases ADD COLUMN case_status_id INTEGER DEFAULT 1;
    """
    
    # SQL para adicionar FK
    add_fk_sql = """
    ALTER TABLE cases ADD CONSTRAINT fk_cases_case_status 
    FOREIGN KEY (case_status_id) REFERENCES case_status(id);
    """
    
    try:
        # Criar tabela
        db.session.execute(create_table_sql)
        print("✓ Tabela case_status criada com sucesso")
        
        # Inserir dados
        db.session.execute(insert_status_sql)
        print("✓ Situações de caso inseridas com sucesso")
        
        # Adicionar coluna
        db.session.execute(add_column_sql)
        print("✓ Coluna case_status_id adicionada com sucesso")
        
        # Commit
        db.session.commit()
        print("✓ Migração concluída com sucesso!")
        
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {str(e)}")
        if "already exists" in str(e) or "duplicate column" in str(e):
            print("  (A tabela ou coluna pode já existir)")
