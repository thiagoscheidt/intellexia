from app.agents.file_agent import FileAgent
from app.agents.agent_document_reader import AgentDocumentReader
from main import app
from flask import jsonify, render_template, session, request, redirect, url_for, flash
from app.models import db, Client, Court, Lawyer, Case, CaseLawyer, CaseBenefit, Document, CaseCompetence, Petition, User, LawFirm
import hashlib
import uuid
import re
from datetime import datetime, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename
from functools import wraps

# Helper function to get current law_firm_id
def get_current_law_firm_id():
    """Retorna o law_firm_id do usuário logado"""
    return session.get('law_firm_id')

# Helper function to extract text from DOCX
def _extract_text_from_docx(document):
    """Extrai texto completo de um documento DOCX"""
    text_parts = []
    
    # Extrair texto dos parágrafos
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)
    
    # Extrair texto das tabelas
    for table in document.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_text = ' '.join([p.text for p in cell.paragraphs if p.text.strip()])
                if cell_text:
                    row_text.append(cell_text)
            if row_text:
                text_parts.append(' | '.join(row_text))
    
    return '\n\n'.join(text_parts)

# Decorator to ensure law_firm context
def require_law_firm(f):
    """Decorator para garantir que o usuário tem um escritório associado"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Escritório não encontrado. Faça login novamente.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def check_session():
    # Allow access to authentication routes and static files
    public_endpoints = ['auth.login', 'auth.register', 'auth.forgot_password', 'static']
    if 'user_id' not in session and request.endpoint not in public_endpoints:
        if request.is_json:
            return jsonify({"error": "Unauthorized"}), 401
        else:
            return redirect(url_for('auth.login'))
    
    # Se está autenticado, atualizar última atividade
    if 'user_id' in session and request.endpoint not in public_endpoints:
        user = User.query.get(session['user_id'])
        if user:
            user.last_activity = datetime.utcnow()
            db.session.commit()

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint - unique route kept from legacy routes.py"""
    return jsonify({"status": "healthy"}), 200

@app.route('/ia/test')
def ia_test():
    """Rota de teste para funcionalidades de IA - kept for testing purposes"""
    file_agent = FileAgent()
    file_id = file_agent.upload_file(
        "https://emsportal.com.br/controle/includes/anexoProtocoloDownload.php?id=372094&anexo=2025-11/1c0a60f97ee2ab4a81ff18916d451091.pdf"
    )

    agent = AgentDocumentReader()
    result = agent.analyze_document(file_id)
    print(result)
    return jsonify(result)
