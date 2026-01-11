from flask import Blueprint, render_template, session, redirect, url_for, jsonify, flash, request
from app.models import db, LawFirm, User
from datetime import datetime
from functools import wraps

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('law_firm_id'):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@settings_bp.route('/law-firm', methods=['GET'])
@require_law_firm
def law_firm_settings():
    """Página de configurações do escritório (apenas admin)"""
    if session.get('user_role') != 'admin':
        flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    law_firm = LawFirm.query.get(law_firm_id)
    if not law_firm:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    return render_template('settings/law_firm.html', law_firm=law_firm)

@settings_bp.route('/law-firm', methods=['POST'])
@require_law_firm
def law_firm_settings_post():
    """Atualizar dados do escritório (apenas admin)"""
    if session.get('user_role') != 'admin':
        return jsonify({"success": False, "message": "Acesso negado"}), 403
    
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return jsonify({"success": False, "message": "Escritório não encontrado"}), 404
    
    law_firm = LawFirm.query.get(law_firm_id)
    if not law_firm:
        return jsonify({"success": False, "message": "Escritório não encontrado"}), 404
    
    try:
        law_firm.name = request.form.get('name', law_firm.name)
        law_firm.trade_name = request.form.get('trade_name', law_firm.trade_name)
        law_firm.cnpj = request.form.get('cnpj', law_firm.cnpj)
        
        law_firm.street = request.form.get('street', law_firm.street)
        law_firm.number = request.form.get('number', law_firm.number)
        law_firm.complement = request.form.get('complement', law_firm.complement)
        law_firm.district = request.form.get('district', law_firm.district)
        law_firm.city = request.form.get('city', law_firm.city)
        law_firm.state = request.form.get('state', law_firm.state)
        law_firm.zip_code = request.form.get('zip_code', law_firm.zip_code)
        
        law_firm.phone = request.form.get('phone', law_firm.phone)
        law_firm.email = request.form.get('email', law_firm.email)
        law_firm.website = request.form.get('website', law_firm.website)
        
        law_firm.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        session['law_firm_name'] = law_firm.name
        
        return jsonify({
            "success": True, 
            "message": "Dados do escritório atualizados com sucesso!"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False, 
            "message": f"Erro ao atualizar dados: {str(e)}"
        }), 500
