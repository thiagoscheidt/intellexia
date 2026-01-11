from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, Court
from datetime import datetime
from functools import wraps

courts_bp = Blueprint('courts', __name__, url_prefix='/courts')

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

@courts_bp.route('/')
@require_law_firm
def courts_list():
    law_firm_id = get_current_law_firm_id()
    courts = Court.query.filter_by(law_firm_id=law_firm_id).order_by(Court.vara_name).all()
    return render_template('courts/list.html', courts=courts)

@courts_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def court_new():
    from app.form import CourtForm
    form = CourtForm()
    
    if form.validate_on_submit():
        court = Court(
            law_firm_id=get_current_law_firm_id(),
            section=form.section.data,
            vara_name=form.vara_name.data,
            city=form.city.data,
            state=form.state.data
        )
        
        db.session.add(court)
        try:
            db.session.commit()
            flash('Vara cadastrada com sucesso!', 'success')
            return redirect(url_for('courts.courts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar vara: {str(e)}', 'danger')
    
    return render_template('courts/form.html', form=form, title='Nova Vara')

@courts_bp.route('/<int:court_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def court_edit(court_id):
    from app.form import CourtForm
    law_firm_id = get_current_law_firm_id()
    court = Court.query.filter_by(id=court_id, law_firm_id=law_firm_id).first_or_404()
    form = CourtForm(obj=court)
    
    if form.validate_on_submit():
        court.section = form.section.data
        court.vara_name = form.vara_name.data
        court.city = form.city.data
        court.state = form.state.data
        court.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Vara atualizada com sucesso!', 'success')
            return redirect(url_for('courts.courts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar vara: {str(e)}', 'danger')
    
    return render_template('courts/form.html', form=form, title='Editar Vara', court_id=court_id)

@courts_bp.route('/<int:court_id>/delete', methods=['POST'])
@require_law_firm
def court_delete(court_id):
    law_firm_id = get_current_law_firm_id()
    court = Court.query.filter_by(id=court_id, law_firm_id=law_firm_id).first_or_404()
    
    if court.cases:
        flash('Não é possível excluir vara que possui casos associados.', 'warning')
        return redirect(url_for('courts.courts_list'))
    
    try:
        db.session.delete(court)
        db.session.commit()
        flash('Vara excluída com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir vara: {str(e)}', 'danger')
    
    return redirect(url_for('courts.courts_list'))
