from flask import Flask
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.utils.database_config import database_uri, load_env_file

# Carregar variáveis do .env se existir
load_env_file()

# Timezone padrão da aplicação (São Paulo)
APP_TIMEZONE_NAME = 'America/Sao_Paulo'
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
os.environ.setdefault('TZ', APP_TIMEZONE_NAME)
if hasattr(time, 'tzset'):
    time.tzset()

# Criar aplicação Flask
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['APP_TIMEZONE'] = APP_TIMEZONE_NAME

# Configuração do banco de dados baseada no ambiente
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri()

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar SQLAlchemy
from app.models import db
db.init_app(app)

# Importar e registrar blueprints
from app.blueprints import (
    auth_bp, dashboard_bp, cases_bp, clients_bp, 
    lawyers_bp, courts_bp, benefits_bp, documents_bp,
    petitions_bp, assistant_bp, tools_bp, settings_bp,
    knowledge_base_bp, admin_users_bp, access_audit_bp, process_panel_bp,
    disputes_center_bp, fap_panel_bp, fap_review_bp,
    impugnacao_references_bp, jurisprudence_bp, fap_calculo_bp, process_knowledge_bp, docs_bp, communications_bp, dou_bp, public_api_bp, minha_api_bp, prompt_library_bp,
)
from app.blueprints.case_comments import case_comments_bp
from app.blueprints.fap_reasons import fap_reasons_bp

# Registrar todos os blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(cases_bp)
app.register_blueprint(fap_reasons_bp)
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
app.register_blueprint(access_audit_bp)
app.register_blueprint(knowledge_base_bp)
app.register_blueprint(case_comments_bp)
app.register_blueprint(process_panel_bp)
app.register_blueprint(disputes_center_bp)
app.register_blueprint(fap_panel_bp)
app.register_blueprint(fap_review_bp)
app.register_blueprint(impugnacao_references_bp)
app.register_blueprint(jurisprudence_bp)
app.register_blueprint(fap_calculo_bp)
app.register_blueprint(process_knowledge_bp)
app.register_blueprint(docs_bp)
app.register_blueprint(communications_bp)
app.register_blueprint(dou_bp)
app.register_blueprint(public_api_bp)
app.register_blueprint(minha_api_bp)
app.register_blueprint(prompt_library_bp)


@app.route('/favicon.ico')
def favicon():
    """Serve o favicon na raiz, sem exigir login.

    Navegadores e clientes MCP (conectores do Claude) buscam ``/favicon.ico``
    na raiz do domínio. Sem esta rota, o ``check_session`` redirecionava para
    a tela de login e o pedido devolvia um HTML de login no lugar do ícone.
    """
    from flask import send_from_directory
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon',
    )


# Importar middlewares e contexto (mantém funcionalidade anterior)
from app.middlewares import init_app_middlewares
init_app_middlewares(app)


# Login com Google (opcional): só habilita se houver credenciais no .env
from app.services.google_oauth import init_google_oauth
init_google_oauth(app)


# Registrar filtro Jinja para converter JSON
@app.template_filter('from_json')
def from_json_filter(value):
    """Converte string JSON para objeto Python"""
    if not value:
        return {}
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        return {}


# Registrar filtro Jinja para extrair basename de caminho
@app.template_filter('basename')
def basename_filter(value):
    """Extrai o nome do arquivo de um caminho completo"""
    if not value:
        return ''
    return os.path.basename(value)


@app.template_filter('sem_estilos')
def sem_estilos_filter(value):
    """Remove blocos <style>/<script> antes de um |striptags.

    O teor de alguns tribunais (ex.: TJSC) vem em HTML completo; striptags
    sozinho preserva o conteúdo interno dos blocos de estilo como texto.
    A limpeza completa (tags + entidades) vive em document_utils.strip_html_text,
    compartilhada com o MCP.
    """
    import re
    if not value:
        return ''
    return re.sub(r'(?is)<(style|script)[^>]*>.*?</\1>', ' ', str(value))


# Filtros de timezone (America/Sao_Paulo)
from app.utils.timezone import format_datetime_sp, format_date_sp

app.add_template_filter(format_datetime_sp, name='datetime_sp')
app.add_template_filter(format_date_sp, name='date_sp')

# CNPJ raiz e CPF chegam do portal FAP como número e perdem o zero à esquerda;
# os filtros devolvem os zeros e aplicam a máscara.
from app.utils.cnpj import formatar_cnpj, formatar_cnpj_raiz, formatar_cpf
app.add_template_filter(formatar_cnpj_raiz, name='cnpj_raiz')
app.add_template_filter(formatar_cpf, name='cpf')
app.add_template_filter(formatar_cnpj, name='cnpj')

# Prioridade de correção do Revisor: separa o nível do plano de ação (fonte
# única em fap_review_service, usada pelo resultado e pelo detalhe da petição)
from app.services.fap_review_service import split_correction_priority

app.add_template_filter(split_correction_priority, name='correction_priority')




if __name__ == '__main__':
    # Criar tabelas apenas quando executando diretamente
    with app.app_context():
        try:
            db.create_all()
            print("✓ Banco de dados conectado e tabelas criadas/verificadas!")
        except Exception as e:
            print(f"⚠️ Erro ao conectar com banco: {e}")
            print("Configure o MySQL e tente novamente.")
    
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
