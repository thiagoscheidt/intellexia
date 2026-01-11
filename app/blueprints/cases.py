from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for
from app.models import db, Case, Client, CaseBenefit, Document, Petition, CaseLawyer, Lawyer, CaseCompetence
from datetime import datetime
from decimal import Decimal
from functools import wraps
from werkzeug.utils import secure_filename
import os

cases_bp = Blueprint('cases', __name__, url_prefix='/cases')

def get_current_law_firm_id():
    return session.get('law_firm_id')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@cases_bp.route('/')
@require_law_firm
def cases_list():
    law_firm_id = get_current_law_firm_id()
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    query = Case.query.filter_by(law_firm_id=law_firm_id).join(Client)
    
    client_id = request.args.get('client_id')
    if client_id:
        query = query.filter(Case.client_id == client_id)
    
    case_type = request.args.get('case_type')
    if case_type:
        query = query.filter(Case.case_type == case_type)
    
    status = request.args.get('status')
    if status:
        query = query.filter(Case.status == status)
    
    court_id = request.args.get('court_id')
    if court_id:
        query = query.filter(Case.court_id == court_id)
    
    fap_year = request.args.get('fap_year')
    if fap_year:
        try:
            year = int(fap_year)
            query = query.filter(
                db.or_(
                    Case.fap_start_year == year,
                    Case.fap_end_year == year,
                    db.and_(Case.fap_start_year <= year, Case.fap_end_year >= year)
                )
            )
        except ValueError:
            pass
    
    value_min = request.args.get('value_min')
    if value_min:
        try:
            min_val = float(value_min)
            query = query.filter(Case.value_cause >= min_val)
        except (ValueError, TypeError):
            pass
    
    value_max = request.args.get('value_max')
    if value_max:
        try:
            max_val = float(value_max)
            query = query.filter(Case.value_cause <= max_val)
        except (ValueError, TypeError):
            pass
    
    search_text = request.args.get('search')
    if search_text:
        search_pattern = f"%{search_text}%"
        query = query.filter(
            db.or_(
                Case.title.ilike(search_pattern),
                Case.facts_summary.ilike(search_pattern),
                Case.thesis_summary.ilike(search_pattern),
                Client.name.ilike(search_pattern)
            )
        )
    
    date_from = request.args.get('date_from')
    if date_from:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Case.filing_date >= date_obj)
        except ValueError:
            pass
    
    date_to = request.args.get('date_to')
    if date_to:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(Case.filing_date <= date_obj)
        except ValueError:
            pass
    
    cases = query.order_by(Case.created_at.desc()).all()
    
    return render_template('cases/list.html', cases=cases, clients=clients, courts=courts)

@cases_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def case_new():
    from app.form import CaseForm
    form = CaseForm()
    
    law_firm_id = get_current_law_firm_id()
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] if courts else [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        case = Case(
            law_firm_id=get_current_law_firm_id(),
            client_id=form.client_id.data if form.client_id.data != 0 else None,
            court_id=form.court_id.data if form.court_id.data != 0 else None,
            title=form.title.data,
            case_type=form.case_type.data,
            fap_reason=form.fap_reason.data if form.fap_reason.data else None,
            fap_start_year=form.fap_start_year.data,
            fap_end_year=form.fap_end_year.data,
            facts_summary=form.facts_summary.data,
            thesis_summary=form.thesis_summary.data,
            prescription_summary=form.prescription_summary.data,
            value_cause=form.value_cause.data,
            status=form.status.data,
            filing_date=form.filing_date.data
        )
        
        db.session.add(case)
        try:
            db.session.commit()
            from flask import flash
            flash('Caso cadastrado com sucesso!', 'success')
            return redirect(url_for('cases.cases_list'))
        except Exception as e:
            db.session.rollback()
            from flask import flash
            flash(f'Erro ao cadastrar caso: {str(e)}', 'danger')
    
    return render_template('cases/form.html', form=form, title='Novo Caso')

@cases_bp.route('/<int:case_id>')
def case_detail(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    competences = CaseCompetence.query.filter_by(case_id=case_id).all()
    petitions = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).all()
    case_lawyers = CaseLawyer.query.filter_by(case_id=case_id).all()
    all_lawyers = Lawyer.query.order_by(Lawyer.name).all()
    return render_template('cases/detail.html', case=case, case_id=case_id, benefits=benefits, documents=documents, competences=competences, petitions=petitions, case_lawyers=case_lawyers, all_lawyers=all_lawyers)

@cases_bp.route('/<int:case_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def case_edit(case_id):
    from app.form import CaseForm
    law_firm_id = get_current_law_firm_id()
    case = Case.query.filter_by(id=case_id, law_firm_id=law_firm_id).first_or_404()
    form = CaseForm(obj=case)
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] if courts else [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        case.client_id = form.client_id.data if form.client_id.data != 0 else None
        case.court_id = form.court_id.data if form.court_id.data != 0 else None
        case.title = form.title.data
        case.case_type = form.case_type.data
        case.fap_reason = form.fap_reason.data if form.fap_reason.data else None
        case.fap_start_year = form.fap_start_year.data
        case.fap_end_year = form.fap_end_year.data
        case.facts_summary = form.facts_summary.data
        case.thesis_summary = form.thesis_summary.data
        case.prescription_summary = form.prescription_summary.data
        case.value_cause = form.value_cause.data
        case.status = form.status.data
        case.filing_date = form.filing_date.data
        case.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            from flask import flash
            flash('Caso atualizado com sucesso!', 'success')
            return redirect(url_for('cases.cases_list'))
        except Exception as e:
            db.session.rollback()
            from flask import flash
            flash(f'Erro ao atualizar caso: {str(e)}', 'danger')
        
    return render_template('cases/form.html', form=form, title='Editar Caso', case_id=case_id)

@cases_bp.route('/<int:case_id>/delete', methods=['POST'])
def case_delete(case_id):
    case = Case.query.get_or_404(case_id)
    
    try:
        db.session.delete(case)
        db.session.commit()
        from flask import flash
        flash('Caso excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao excluir caso: {str(e)}', 'danger')
    
    return redirect(url_for('cases.cases_list'))

@cases_bp.route('/<int:case_id>/lawyers/add', methods=['POST'])
def case_lawyer_add(case_id):
    case = Case.query.get_or_404(case_id)
    
    lawyer_id = request.form.get('lawyer_id')
    role = request.form.get('role', '')
    
    if not lawyer_id:
        from flask import flash
        flash('Selecione um advogado.', 'warning')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    lawyer = Lawyer.query.get_or_404(int(lawyer_id))
    
    existing = CaseLawyer.query.filter_by(case_id=case_id, lawyer_id=lawyer_id).first()
    if existing:
        from flask import flash
        flash('Este advogado já está vinculado ao caso.', 'warning')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    case_lawyer = CaseLawyer(
        case_id=case_id,
        lawyer_id=lawyer_id,
        role=role
    )
    
    db.session.add(case_lawyer)
    try:
        db.session.commit()
        from flask import flash
        flash(f'Advogado {lawyer.name} vinculado ao caso com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao vincular advogado: {str(e)}', 'danger')
    
    return redirect(url_for('cases.case_detail', case_id=case_id))

@cases_bp.route('/<int:case_id>/lawyers/<int:case_lawyer_id>/remove', methods=['POST'])
def case_lawyer_remove(case_id, case_lawyer_id):
    case_lawyer = CaseLawyer.query.get_or_404(case_lawyer_id)
    
    if case_lawyer.case_id != case_id:
        from flask import flash
        flash('Vínculo não pertence a este caso.', 'danger')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    lawyer_name = case_lawyer.lawyer.name
    
    try:
        db.session.delete(case_lawyer)
        db.session.commit()
        from flask import flash
        flash(f'Advogado {lawyer_name} removido do caso.', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao remover advogado: {str(e)}', 'danger')
    
    return redirect(url_for('cases.case_detail', case_id=case_id))
