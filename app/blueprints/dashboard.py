from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from app.models import db, Case, User
from datetime import datetime
from functools import wraps
from decimal import Decimal

dashboard_bp = Blueprint('dashboard', __name__)

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

def get_current_law_firm_id():
    return session.get('law_firm_id')

@dashboard_bp.route('/')
def index():
    """Redireciona para o dashboard principal"""
    user = User.query.get(session.get('user_id'))
    law_firm = user.law_firm if user else None
    
    message = request.args.get('message')
    if message:
        from flask import flash
        flash(message)
    return redirect(url_for('dashboard.dashboard'))

@dashboard_bp.route('/dashboard')
@require_law_firm
def dashboard():
    """Dashboard principal com estatísticas do sistema"""
    try:
        user = User.query.get(session.get('user_id'))
        law_firm = user.law_firm if user else None
        law_firm_id = get_current_law_firm_id()
        
        from app.models import Client, CaseBenefit, Lawyer, Document
        
        total_cases = Case.query.filter_by(law_firm_id=law_firm_id).count()
        active_cases = Case.query.filter_by(law_firm_id=law_firm_id, status='active').count()
        draft_cases = Case.query.filter_by(law_firm_id=law_firm_id, status='draft').count()
        filed_cases = Case.query.filter_by(law_firm_id=law_firm_id).filter(Case.filing_date.isnot(None)).count()
        
        total_clients = Client.query.filter_by(law_firm_id=law_firm_id).count()
        clients_with_branches = Client.query.filter_by(law_firm_id=law_firm_id, has_branches=True).count()
        
        total_benefits = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id).count()
        benefits_b91 = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id, CaseBenefit.benefit_type == 'B91').count()
        benefits_b94 = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id, CaseBenefit.benefit_type == 'B94').count()
        
        total_lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).count()
        
        total_documents = Document.query.join(Case).filter(Case.law_firm_id == law_firm_id).count()
        documents_for_ai = Document.query.join(Case).filter(Case.law_firm_id == law_firm_id, Document.use_in_ai == True).count()
        
        recent_cases = Case.query.filter_by(law_firm_id=law_firm_id).order_by(Case.created_at.desc()).limit(5).all()
        
        total_cause_value = db.session.query(db.func.sum(Case.value_cause)).filter(Case.law_firm_id == law_firm_id).scalar() or Decimal('0')
        
        cases_by_type_result = db.session.query(
            Case.case_type, 
            db.func.count(Case.id).label('count')
        ).filter(Case.law_firm_id == law_firm_id).group_by(Case.case_type).all()
        cases_by_type = {case_type: count for case_type, count in cases_by_type_result}
        
        cases_by_status_result = db.session.query(
            Case.status,
            db.func.count(Case.id).label('count')
        ).filter(Case.law_firm_id == law_firm_id).group_by(Case.status).all()
        cases_by_status = {status: count for status, count in cases_by_status_result}

        # Casos abertos por mês (usando created_at) – processado em Python para portabilidade entre bancos
        from collections import defaultdict
        cases_by_month_raw = Case.query.with_entities(Case.created_at).filter(
            Case.law_firm_id == law_firm_id,
            Case.created_at.isnot(None)
        ).all()
        cases_by_month_map = defaultdict(int)
        for (created_at,) in cases_by_month_raw:
            try:
                label = created_at.strftime('%b/%Y')  # Ex.: Jan/2026
                cases_by_month_map[label] += 1
            except Exception:
                continue
        # ordenar cronologicamente pela chave AAAA-MM, mantendo label amigável
        cases_by_month = {k: v for k, v in sorted(cases_by_month_map.items(), key=lambda kv: datetime.strptime(kv[0], '%b/%Y'))}
        
        total_users = User.query.filter_by(law_firm_id=law_firm_id).count()
        
        from app.models import Court
        total_courts = Court.query.filter_by(law_firm_id=law_firm_id).count()
        
        return render_template('dashboard.html',
            total_cases=total_cases,
            active_cases=active_cases,
            draft_cases=draft_cases,
            filed_cases=filed_cases,
            total_clients=total_clients,
            clients_with_branches=clients_with_branches,
            total_benefits=total_benefits,
            benefits_b91=benefits_b91,
            benefits_b94=benefits_b94,
            total_lawyers=total_lawyers,
            total_documents=total_documents,
            documents_for_ai=documents_for_ai,
            recent_cases=recent_cases,
            total_cause_value=total_cause_value,
            cases_by_type=cases_by_type,
            cases_by_status=cases_by_status,
            total_users=total_users,
            total_courts=total_courts,
            cases_by_month=cases_by_month,
            user=user,
            law_firm=law_firm
        )
    except Exception as e:
        print(f"Erro no dashboard: {str(e)}")
        from flask import flash
        flash(f'Erro ao carregar dashboard: {str(e)}', 'danger')
        return render_template('dashboard.html',
            total_cases=0,
            active_cases=0,
            draft_cases=0,
            filed_cases=0,
            total_clients=0,
            total_benefits=0,
            total_lawyers=0,
            total_documents=0,
            recent_cases=[],
            total_cause_value=0,
            cases_by_type={},
            cases_by_status={},
            cases_by_month={},
            user=user if 'user' in locals() else None,
            law_firm=law_firm if 'law_firm' in locals() else None
        )

@dashboard_bp.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200
