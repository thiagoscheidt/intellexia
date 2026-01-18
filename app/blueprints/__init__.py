"""
Blueprints para organização modular das rotas
"""
from app.blueprints.auth import auth_bp
from app.blueprints.dashboard import dashboard_bp
from app.blueprints.cases import cases_bp
from app.blueprints.clients import clients_bp
from app.blueprints.lawyers import lawyers_bp
from app.blueprints.courts import courts_bp
from app.blueprints.benefits import benefits_bp
from app.blueprints.documents import documents_bp
from app.blueprints.petitions import petitions_bp
from app.blueprints.assistant import assistant_bp
from app.blueprints.tools import tools_bp
from app.blueprints.settings import settings_bp
from app.blueprints.knowledge_base import knowledge_base_bp
from app.blueprints.admin_users import admin_users_bp

__all__ = [
    'auth_bp',
    'dashboard_bp',
    'cases_bp',
    'clients_bp',
    'lawyers_bp',
    'courts_bp',
    'benefits_bp',
    'documents_bp',
    'petitions_bp',
    'assistant_bp',
    'tools_bp',
    'settings_bp',
    'knowledge_base_bp',
    'admin_users_bp'
]
