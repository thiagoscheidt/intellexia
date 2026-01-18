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

# Importar e registrar blueprints
from app.blueprints import (
    auth_bp, dashboard_bp, cases_bp, clients_bp, 
    lawyers_bp, courts_bp, benefits_bp, documents_bp,
    petitions_bp, assistant_bp, tools_bp, settings_bp,
    knowledge_base_bp, admin_users_bp
)
from app.blueprints.case_comments import case_comments_bp

# Registrar todos os blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(cases_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(lawyers_bp)
app.register_blueprint(courts_bp)
app.register_blueprint(benefits_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(petitions_bp)
app.register_blueprint(assistant_bp)
app.register_blueprint(tools_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(admin_users_bp)
app.register_blueprint(knowledge_base_bp)
app.register_blueprint(case_comments_bp)

# Importar middlewares e contexto (mantém funcionalidade anterior)
from app.middlewares import init_app_middlewares
init_app_middlewares(app)

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
