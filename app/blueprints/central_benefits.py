from datetime import datetime
from functools import wraps
import os

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.models import Benefit, Client, FapContestationJudgmentReport, db


central_benefits_bp = Blueprint('central_benefits', __name__, url_prefix='/central-benefits')


def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


@central_benefits_bp.route('/')
@require_law_firm
def list_central_benefits():
    law_firm_id = get_current_law_firm_id()
    benefits = (
        Benefit.query.filter_by(law_firm_id=law_firm_id)
        .order_by(Benefit.created_at.desc())
        .all()
    )

    def extract_cnpj_root(cnpj):
        digits = ''.join(ch for ch in (cnpj or '') if ch.isdigit())
        return digits[:8] if len(digits) >= 8 else ''

    def extract_cnpj_branch(cnpj):
        digits = ''.join(ch for ch in (cnpj or '') if ch.isdigit())
        return digits[8:12] if len(digits) >= 12 else ''

    clients_data = (
        Client.query.with_entities(Client.cnpj, Client.name)
        .filter_by(law_firm_id=law_firm_id)
        .all()
    )

    roots_map = {}
    for cnpj, name in clients_data:
        root = extract_cnpj_root(cnpj)
        if not root:
            continue

        branch = extract_cnpj_branch(cnpj)
        clean_name = (name or '').strip()

        if root not in roots_map:
            roots_map[root] = {'root': root, 'company_name': '', 'is_main': False}

        current = roots_map[root]
        if branch == '0001' and clean_name:
            current['company_name'] = clean_name
            current['is_main'] = True
            continue

        if not current['is_main'] and clean_name and not current['company_name']:
            current['company_name'] = clean_name

    cnpj_roots = [
        {'root': item['root'], 'company_name': item['company_name']}
        for _, item in sorted(roots_map.items(), key=lambda entry: entry[0])
    ]

    return render_template('central_benefits/list.html', benefits=benefits, cnpj_roots=cnpj_roots)


@central_benefits_bp.route('/fap-contestation-reports', methods=['GET', 'POST'])
@require_law_firm
def fap_contestation_reports():
    from app.form import FapContestationJudgmentReportForm

    law_firm_id = get_current_law_firm_id()
    form = FapContestationJudgmentReportForm()

    if form.validate_on_submit():
        file = form.file.data
        if file:
            try:
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_filename = f'{timestamp}_{filename}'

                upload_dir = os.path.join('uploads', 'fap_contestation_reports')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, unique_filename)
                file.save(file_path)

                file_size = os.path.getsize(file_path)
                file_extension = os.path.splitext(filename)[1].lower().replace('.', '')

                report = FapContestationJudgmentReport(
                    user_id=session.get('user_id'),
                    law_firm_id=law_firm_id,
                    original_filename=filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_extension.upper(),
                    status='pending',
                )

                db.session.add(report)
                db.session.commit()
                flash('Relatório enviado com sucesso! Ele ficará pendente até processamento via script.', 'success')
                return redirect(url_for('central_benefits.fap_contestation_reports'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao enviar relatório: {str(e)}', 'danger')

    reports = (
        FapContestationJudgmentReport.query.filter_by(law_firm_id=law_firm_id)
        .order_by(FapContestationJudgmentReport.uploaded_at.desc())
        .all()
    )

    return render_template('central_benefits/fap_contestation_reports.html', form=form, reports=reports)


@central_benefits_bp.route('/fap-contestation-reports/<int:report_id>/delete', methods=['POST'])
@require_law_firm
def delete_fap_contestation_report(report_id):
    law_firm_id = get_current_law_firm_id()
    report = FapContestationJudgmentReport.query.filter_by(id=report_id, law_firm_id=law_firm_id).first_or_404()

    try:
        if report.file_path and os.path.exists(report.file_path):
            os.remove(report.file_path)
        db.session.delete(report)
        db.session.commit()
        flash('Relatório excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir relatório: {str(e)}', 'danger')

    return redirect(url_for('central_benefits.fap_contestation_reports'))


@central_benefits_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def new_central_benefit():
    from app.form import CentralBenefitForm

    law_firm_id = get_current_law_firm_id()
    form = CentralBenefitForm()

    clients = (
        Client.query.filter_by(law_firm_id=law_firm_id)
        .order_by(Client.name.asc())
        .all()
    )
    form.client_id.choices = [('', 'Sem cliente vinculado')] + [(c.id, c.name) for c in clients]

    if form.validate_on_submit():
        benefit = Benefit(
            law_firm_id=law_firm_id,
            client_id=form.client_id.data,
            benefit_number=form.benefit_number.data,
            benefit_type=form.benefit_type.data,
            insured_name=form.insured_name.data,
            insured_nit=form.insured_nit.data,
            insured_cpf=form.insured_cpf.data,
            insured_date_of_birth=form.insured_date_of_birth.data,
            employer_cnpj=form.employer_cnpj.data,
            employer_name=form.employer_name.data,
            benefit_start_date=form.benefit_start_date.data,
            benefit_end_date=form.benefit_end_date.data,
            initial_monthly_benefit=form.initial_monthly_benefit.data,
            total_paid=form.total_paid.data,
            accident_date=form.accident_date.data,
            accident_company_name=form.accident_company_name.data,
            accident_summary=form.accident_summary.data,
            cat_number=form.cat_number.data,
            bo_number=form.bo_number.data,
            fap_vigencia_years=form.fap_vigencia_years.data,
            request_type=form.request_type.data or None,
            status=form.status.data,
            justification=form.justification.data,
            opinion=form.opinion.data,
            notes=form.notes.data,
        )

        db.session.add(benefit)
        try:
            db.session.commit()
            flash('Benefício centralizado cadastrado com sucesso!', 'success')
            return redirect(url_for('central_benefits.list_central_benefits'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar benefício: {str(e)}', 'danger')

    return render_template('central_benefits/form.html', form=form, title='Novo Benefício Centralizado')


@central_benefits_bp.route('/<int:benefit_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def edit_central_benefit(benefit_id):
    from app.form import CentralBenefitForm

    law_firm_id = get_current_law_firm_id()
    benefit = Benefit.query.filter_by(id=benefit_id, law_firm_id=law_firm_id).first_or_404()
    form = CentralBenefitForm(obj=benefit)

    clients = (
        Client.query.filter_by(law_firm_id=law_firm_id)
        .order_by(Client.name.asc())
        .all()
    )
    form.client_id.choices = [('', 'Sem cliente vinculado')] + [(c.id, c.name) for c in clients]

    if request.method == 'GET':
        form.client_id.data = benefit.client_id

    if form.validate_on_submit():
        benefit.client_id = form.client_id.data
        benefit.benefit_number = form.benefit_number.data
        benefit.benefit_type = form.benefit_type.data
        benefit.insured_name = form.insured_name.data
        benefit.insured_nit = form.insured_nit.data
        benefit.insured_cpf = form.insured_cpf.data
        benefit.insured_date_of_birth = form.insured_date_of_birth.data
        benefit.employer_cnpj = form.employer_cnpj.data
        benefit.employer_name = form.employer_name.data
        benefit.benefit_start_date = form.benefit_start_date.data
        benefit.benefit_end_date = form.benefit_end_date.data
        benefit.initial_monthly_benefit = form.initial_monthly_benefit.data
        benefit.total_paid = form.total_paid.data
        benefit.accident_date = form.accident_date.data
        benefit.accident_company_name = form.accident_company_name.data
        benefit.accident_summary = form.accident_summary.data
        benefit.cat_number = form.cat_number.data
        benefit.bo_number = form.bo_number.data
        benefit.fap_vigencia_years = form.fap_vigencia_years.data
        benefit.request_type = form.request_type.data or None
        benefit.status = form.status.data
        benefit.justification = form.justification.data
        benefit.opinion = form.opinion.data
        benefit.notes = form.notes.data
        benefit.updated_at = datetime.utcnow()

        try:
            db.session.commit()
            flash('Benefício centralizado atualizado com sucesso!', 'success')
            return redirect(url_for('central_benefits.list_central_benefits'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar benefício: {str(e)}', 'danger')

    return render_template(
        'central_benefits/form.html',
        form=form,
        title='Editar Benefício Centralizado',
        benefit_id=benefit_id,
    )


@central_benefits_bp.route('/<int:benefit_id>/delete', methods=['POST'])
@require_law_firm
def delete_central_benefit(benefit_id):
    law_firm_id = get_current_law_firm_id()
    benefit = Benefit.query.filter_by(id=benefit_id, law_firm_id=law_firm_id).first_or_404()

    try:
        db.session.delete(benefit)
        db.session.commit()
        flash('Benefício centralizado excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir benefício: {str(e)}', 'danger')

    return redirect(url_for('central_benefits.list_central_benefits'))
