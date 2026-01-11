from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, Lawyer
from datetime import datetime
from functools import wraps

lawyers_bp = Blueprint('lawyers', __name__, url_prefix='/lawyers')

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

@lawyers_bp.route('/')
@require_law_firm
def lawyers_list():
    law_firm_id = get_current_law_firm_id()
    lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).order_by(Lawyer.name).all()
    return render_template('lawyers/list.html', lawyers=lawyers)

@lawyers_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def lawyer_new():
    from app.form import LawyerForm
    form = LawyerForm()
    
    if form.validate_on_submit():
        lawyer = Lawyer(
            law_firm_id=get_current_law_firm_id(),
            name=form.name.data,
            oab_number=form.oab_number.data,
            email=form.email.data,
            phone=form.phone.data,
            is_default_for_publications=form.is_default_for_publications.data
        )
        
        db.session.add(lawyer)
        try:
            db.session.commit()
            flash('Advogado cadastrado com sucesso!', 'success')
            return redirect(url_for('lawyers.lawyers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar advogado: {str(e)}', 'danger')
    
    return render_template('lawyers/form.html', form=form, title='Novo Advogado')

@lawyers_bp.route('/<int:lawyer_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def lawyer_edit(lawyer_id):
    from app.form import LawyerForm
    law_firm_id = get_current_law_firm_id()
    lawyer = Lawyer.query.filter_by(id=lawyer_id, law_firm_id=law_firm_id).first_or_404()
    form = LawyerForm(obj=lawyer)
    
    if form.validate_on_submit():
        lawyer.name = form.name.data
        lawyer.oab_number = form.oab_number.data
        lawyer.email = form.email.data
        lawyer.phone = form.phone.data
        lawyer.is_default_for_publications = form.is_default_for_publications.data
        lawyer.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Advogado atualizado com sucesso!', 'success')
            return redirect(url_for('lawyers.lawyers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar advogado: {str(e)}', 'danger')
    
    return render_template('lawyers/form.html', form=form, title='Editar Advogado', lawyer_id=lawyer_id)

@lawyers_bp.route('/<int:lawyer_id>/delete', methods=['POST'])
def lawyer_delete(lawyer_id):
    lawyer = Lawyer.query.get_or_404(lawyer_id)
    
    if lawyer.case_lawyers:
        flash('Não é possível excluir advogado que possui casos associados.', 'warning')
        return redirect(url_for('lawyers.lawyers_list'))
    
    try:
        db.session.delete(lawyer)
        db.session.commit()
        flash('Advogado excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir advogado: {str(e)}', 'danger')
    
    return redirect(url_for('lawyers.lawyers_list'))
