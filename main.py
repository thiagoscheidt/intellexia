from flask import Flask
import os
from pathlib import Path

# Carregar variáveis do .env se existir
env_path = Path('.') / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.strip().split('=', 1)
                os.environ[key] = value  # Usar assignment ao invés de setdefault

# Criar aplicação Flask
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Configuração do banco de dados baseada no ambiente
environment = os.environ.get('ENVIRONMENT', 'development')

if environment == 'production':
    # MySQL para produção
    mysql_host = os.environ.get('MYSQL_HOST', 'localhost')
    mysql_port = os.environ.get('MYSQL_PORT', '3306')
    mysql_user = os.environ.get('MYSQL_USER', 'root')
    mysql_password = os.environ.get('MYSQL_PASSWORD', 'password')
    mysql_database = os.environ.get('MYSQL_DATABASE', 'intellexia')
    
    app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_database}?charset=utf8mb4"
else:
    # SQLite para desenvolvimento
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///intellexia.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar SQLAlchemy
from app.models import db
db.init_app(app)

# Importar rotas
from app.routes import *

if __name__ == '__main__':
    # Criar tabelas apenas quando executando diretamente
    with app.app_context():
        try:
            db.create_all()
            print("✓ Banco de dados conectado e tabelas criadas/verificadas!")
        except Exception as e:
            print(f"⚠️ Erro ao conectar com banco: {e}")
            print("Configure o MySQL e tente novamente.")
    
    app.run(debug=True)
