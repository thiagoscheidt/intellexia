from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, CaseBenefit, Case, FapReason
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
    
    # Populate fap_reason_id choices
    fap_reasons = FapReason.query.filter_by(
        law_firm_id=case.law_firm_id,
        is_active=True
    ).order_by(FapReason.display_name).all()
    fap_reason_choices = [('', 'Nenhum motivo selecionado')] + [(str(r.id), r.display_name) for r in fap_reasons]
    form.fap_reason_id.choices = fap_reason_choices
    
    # Populate fap_vigencia_years choices based on case dates
    if case.fap_start_year and case.fap_end_year:
        years = [str(year) for year in range(case.fap_start_year, case.fap_end_year + 1)]
        form.fap_vigencia_years.choices = [(year, year) for year in years]
    else:
        form.fap_vigencia_years.choices = []
    
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
            fap_reason_id=int(form.fap_reason_id.data) if form.fap_reason_id.data else None,
            fap_vigencia_years=','.join(form.fap_vigencia_years.data) if form.fap_vigencia_years.data else None,
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
    
    # Populate fap_reason_id choices FIRST
    fap_reasons = FapReason.query.filter_by(
        law_firm_id=case.law_firm_id,
        is_active=True
    ).order_by(FapReason.display_name).all()
    fap_reason_choices = [('', 'Nenhum motivo selecionado')] + [(str(r.id), r.display_name) for r in fap_reasons]
    
    # Populate fap_vigencia_years choices based on case dates
    fap_vigencia_choices = []
    if case.fap_start_year and case.fap_end_year:
        years = [str(year) for year in range(case.fap_start_year, case.fap_end_year + 1)]
        fap_vigencia_choices = [(year, year) for year in years]
    
    # Now create the form with object data
    form = CaseBenefitContextForm(obj=benefit)
    
    # Set the choices after creating the form
    form.fap_reason_id.choices = fap_reason_choices
    form.fap_vigencia_years.choices = fap_vigencia_choices
    
    # Pre-fill fap_vigencia_years with existing values
    if benefit.fap_vigencia_years:
        form.fap_vigencia_years.data = benefit.fap_vigencia_years.split(',')
    
    # Ensure fap_reason_id is properly set as string
    if benefit.fap_reason_id:
        form.fap_reason_id.data = str(benefit.fap_reason_id)
    
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
        benefit.fap_reason_id = int(form.fap_reason_id.data) if form.fap_reason_id.data else None
        benefit.fap_vigencia_years = ','.join(form.fap_vigencia_years.data) if form.fap_vigencia_years.data else None
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
