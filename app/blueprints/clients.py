from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, Client
from datetime import datetime
from functools import wraps

clients_bp = Blueprint('clients', __name__, url_prefix='/clients')

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

@clients_bp.route('/')
@require_law_firm
def clients_list():
    law_firm_id = get_current_law_firm_id()
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.created_at.desc()).all()
    return render_template('clients/list.html', clients=clients)

@clients_bp.route('/<int:client_id>')
@require_law_firm
def client_detail(client_id):
    from app.models import Case
    from decimal import Decimal
    
    law_firm_id = get_current_law_firm_id()
    client = Client.query.filter_by(id=client_id, law_firm_id=law_firm_id).first_or_404()
    
    client_cases = Case.query.filter_by(client_id=client_id, law_firm_id=law_firm_id).order_by(Case.created_at.desc()).all()
    
    active_cases_count = len([case for case in client_cases if case.status == 'active'])
    
    total_benefits_count = 0
    for case in client_cases:
        total_benefits_count += len(case.benefits)
    
    total_case_value = sum([case.value_cause or Decimal('0') for case in client_cases])
    
    case_types_summary = {}
    for case in client_cases:
        case_type = case.case_type
        if case_type in case_types_summary:
            case_types_summary[case_type] += 1
        else:
            case_types_summary[case_type] = 1
    
    return render_template('clients/detail.html', 
                         client=client,
                         client_cases=client_cases,
                         active_cases_count=active_cases_count,
                         total_benefits_count=total_benefits_count,
                         total_case_value=total_case_value,
                         case_types_summary=case_types_summary)

@clients_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def client_new():
    from app.form import ClientForm
    form = ClientForm()
    
    if form.validate_on_submit():
        client = Client(
            law_firm_id=get_current_law_firm_id(),
            name=form.name.data,
            cnpj=form.cnpj.data,
            street=form.street.data,
            number=form.number.data,
            district=form.district.data,
            city=form.city.data,
            state=form.state.data,
            zip_code=form.zip_code.data,
            has_branches=form.has_branches.data,
            branches_description=form.branches_description.data
        )
        
        db.session.add(client)
        try:
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('clients.clients_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar cliente: {str(e)}', 'danger')
    
    return render_template('clients/form.html', form=form, title='Novo Cliente')

@clients_bp.route('/<int:client_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def client_edit(client_id):
    from app.form import ClientForm
    law_firm_id = get_current_law_firm_id()
    client = Client.query.filter_by(id=client_id, law_firm_id=law_firm_id).first_or_404()
    form = ClientForm(obj=client)
    
    if form.validate_on_submit():
        client.name = form.name.data
        client.cnpj = form.cnpj.data
        client.street = form.street.data
        client.number = form.number.data
        client.district = form.district.data
        client.city = form.city.data
        client.state = form.state.data
        client.zip_code = form.zip_code.data
        client.has_branches = form.has_branches.data
        client.branches_description = form.branches_description.data
        client.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('clients.clients_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar cliente: {str(e)}', 'danger')
    
    return render_template('clients/form.html', form=form, title='Editar Cliente', client_id=client_id)

@clients_bp.route('/<int:client_id>/delete', methods=['POST'])
@require_law_firm
def client_delete(client_id):
    law_firm_id = get_current_law_firm_id()
    client = Client.query.filter_by(id=client_id, law_firm_id=law_firm_id).first_or_404()
    
    if client.cases:
        flash('Não é possível excluir cliente que possui casos associados.', 'warning')
        return redirect(url_for('clients.clients_list'))
    
    try:
        db.session.delete(client)
        db.session.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')
    
    return redirect(url_for('clients.clients_list'))
