#!/usr/bin/env python3
"""
Script para adicionar tabelas de comentários ao banco de dados
"""

import os
from pathlib import Path
import sys

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

# Carregar variáveis de ambiente
env_path = Path('.') / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

from flask import Flask
from app.models import db, CaseActivity, CaseComment

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key')

def build_database_uri() -> str:
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return database_url

    mysql_database = os.environ.get('MYSQL_DATABASE')
    if mysql_database:
        mysql_host = os.environ.get('MYSQL_HOST', 'localhost')
        mysql_port = os.environ.get('MYSQL_PORT', '3306')
        mysql_user = os.environ.get('MYSQL_USER', 'root')
        mysql_password = os.environ.get('MYSQL_PASSWORD', 'password')
        return f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_database}?charset=utf8mb4"

    return 'sqlite:///intellexia.db'


app.config['SQLALCHEMY_DATABASE_URI'] = build_database_uri()

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def create_tables():
    """Cria as tabelas de comentários se não existirem"""
    with app.app_context():
        try:
            # Criar apenas as novas tabelas
            db.create_all()
            
            print("✓ Tabelas de comentários criadas com sucesso!")
            print("  - case_activities")
            print("  - case_comments")
            
        except Exception as e:
            print(f"✗ Erro ao criar tabelas: {e}")
            return False
    
    return True

if __name__ == '__main__':
    success = create_tables()
    sys.exit(0 if success else 1)
