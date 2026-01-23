from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, CaseBenefit, Case
from datetime import datetime
from functools import wraps

benefits_bp = Blueprint('benefits', __name__, url_prefix='/benefits')

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

@benefits_bp.route('/')
def benefits_list():
    """Lista todos os benefícios do sistema para visualização geral"""
    benefits = CaseBenefit.query.join(Case).order_by(CaseBenefit.created_at.desc()).all()
    return render_template('benefits/list.html', benefits=benefits)

@benefits_bp.route('/<int:benefit_id>')
def benefit_detail(benefit_id):
    """Visualiza detalhes de um benefício específico"""
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    related_cases = Case.query.filter(
        Case.benefits.any(CaseBenefit.id == benefit_id)
    ).order_by(Case.created_at.desc()).all()
    
    from app.models import Document
    related_documents = Document.query.filter_by(related_benefit_id=benefit_id).all()
    
    return render_template('benefits/detail.html', 
                         benefit=benefit, 
                         related_cases=related_cases,
                         documents=related_documents)

@benefits_bp.route('/case/<int:case_id>')
def case_benefits_list(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    return render_template('cases/benefits_list.html', case=case, benefits=benefits)

@benefits_bp.route('/case/<int:case_id>/new', methods=['GET', 'POST'])
def case_benefit_new(case_id):
    from app.form import CaseBenefitContextForm
    case = Case.query.get_or_404(case_id)
    form = CaseBenefitContextForm()
    
    if form.validate_on_submit():
        benefit = CaseBenefit(
            case_id=case_id,
            benefit_number=form.benefit_number.data,
            benefit_type=form.benefit_type.data,
            insured_name=form.insured_name.data,
            insured_nit=form.insured_nit.data,
            numero_cat=form.numero_cat.data,
            numero_bo=form.numero_bo.data,
            data_inicio_beneficio=form.data_inicio_beneficio.data,
            data_fim_beneficio=form.data_fim_beneficio.data,
            accident_date=form.accident_date.data,
            accident_company_name=form.accident_company_name.data,
            error_reason=form.error_reason.data,
            notes=form.notes.data
        )
        
        db.session.add(benefit)
        try:
            db.session.commit()
            flash('Benefício cadastrado com sucesso!', 'success')
            return redirect(url_for('benefits.case_benefits_list', case_id=case_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar benefício: {str(e)}', 'danger')
    
    return render_template('cases/benefit_form.html', form=form, case=case, title='Novo Benefício')

@benefits_bp.route('/case/<int:case_id>/<int:benefit_id>/edit', methods=['GET', 'POST'])
def case_benefit_edit(case_id, benefit_id):
    from app.form import CaseBenefitContextForm
    case = Case.query.get_or_404(case_id)
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    if benefit.case_id != case_id:
        flash('Benefício não encontrado neste caso.', 'error')
        return redirect(url_for('benefits.case_benefits_list', case_id=case_id))
    
    form = CaseBenefitContextForm(obj=benefit)
    
    if form.validate_on_submit():
        benefit.benefit_number = form.benefit_number.data
        benefit.benefit_type = form.benefit_type.data
        benefit.insured_name = form.insured_name.data
        benefit.insured_nit = form.insured_nit.data
        benefit.numero_cat = form.numero_cat.data
        benefit.numero_bo = form.numero_bo.data
        benefit.data_inicio_beneficio = form.data_inicio_beneficio.data
        benefit.data_fim_beneficio = form.data_fim_beneficio.data
        benefit.accident_date = form.accident_date.data
        benefit.accident_company_name = form.accident_company_name.data
        benefit.error_reason = form.error_reason.data
        benefit.notes = form.notes.data
        benefit.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Benefício atualizado com sucesso!', 'success')
            return redirect(url_for('benefits.case_benefits_list', case_id=case_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar benefício: {str(e)}', 'danger')
    
    return render_template('cases/benefit_form.html', form=form, case=case, title='Editar Benefício', benefit_id=benefit_id)

@benefits_bp.route('/case/<int:case_id>/<int:benefit_id>/delete', methods=['POST'])
def case_benefit_delete(case_id, benefit_id):
    case = Case.query.get_or_404(case_id)
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    if benefit.case_id != case_id:
        flash('Benefício não encontrado neste caso.', 'error')
        return redirect(url_for('benefits.case_benefits_list', case_id=case_id))
    
    try:
        db.session.delete(benefit)
        db.session.commit()
        flash('Benefício excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir benefício: {str(e)}', 'danger')
    
    return redirect(url_for('benefits.case_benefits_list', case_id=case_id))
