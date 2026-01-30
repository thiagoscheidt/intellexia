from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash
from app.models import db, FapReason, CaseTemplate
from datetime import datetime
from functools import wraps

fap_reasons_bp = Blueprint('fap_reasons', __name__, url_prefix='/cases/fap-reasons')

def get_current_law_firm_id():
    return session.get('law_firm_id')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Escritório não identificado na sessão.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@fap_reasons_bp.route('/')
@require_law_firm
def list():
    """Lista todos os motivos FAP"""
    law_firm_id = get_current_law_firm_id()
    
    # Filtros
    search = request.args.get('search', '').strip()
    status = request.args.get('status')
    
    query = FapReason.query.filter_by(law_firm_id=law_firm_id)
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                FapReason.display_name.ilike(search_pattern),
                FapReason.description.ilike(search_pattern)
            )
        )
    
    if status == 'active':
        query = query.filter_by(is_active=True)
    elif status == 'inactive':
        query = query.filter_by(is_active=False)
    
    fap_reasons = query.order_by(FapReason.display_name).all()
    
    # Estatísticas
    total_reasons = FapReason.query.filter_by(law_firm_id=law_firm_id).count()
    active_reasons = FapReason.query.filter_by(law_firm_id=law_firm_id, is_active=True).count()
    
    return render_template(
        'fap_reasons/list.html',
        fap_reasons=fap_reasons,
        total_reasons=total_reasons,
        active_reasons=active_reasons,
        search=search,
        current_status=status
    )


@fap_reasons_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def new():
    """Criar novo motivo FAP"""
    law_firm_id = get_current_law_firm_id()
    
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        description = request.form.get('description', '').strip()
        template_id = request.form.get('template_id')
        
        if not display_name:
            flash('Nome de exibição é obrigatório.', 'danger')
            return redirect(url_for('fap_reasons.new'))
        
        # Converter template_id vazio para None
        template_id = int(template_id) if template_id and template_id != '0' else None
        
        fap_reason = FapReason(
            law_firm_id=law_firm_id,
            display_name=display_name,
            description=description,
            template_id=template_id,
            is_active=True
        )
        
        try:
            db.session.add(fap_reason)
            db.session.commit()
            flash(f'Motivo FAP "{display_name}" criado com sucesso!', 'success')
            return redirect(url_for('fap_reasons.list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar motivo FAP: {str(e)}', 'danger')
    
    # Buscar templates disponíveis
    templates = CaseTemplate.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(CaseTemplate.template_name).all()
    
    return render_template('fap_reasons/form.html', templates=templates, title='Novo Motivo FAP')


@fap_reasons_bp.route('/<int:reason_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def edit(reason_id):
    """Editar motivo FAP"""
    law_firm_id = get_current_law_firm_id()
    
    fap_reason = FapReason.query.filter_by(
        id=reason_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        description = request.form.get('description', '').strip()
        template_id = request.form.get('template_id')
        
        if not display_name:
            flash('Nome de exibição é obrigatório.', 'danger')
            return redirect(url_for('fap_reasons.edit', reason_id=reason_id))
        
        # Converter template_id vazio para None
        template_id = int(template_id) if template_id and template_id != '0' else None
        
        fap_reason.display_name = display_name
        fap_reason.description = description
        fap_reason.template_id = template_id
        fap_reason.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash(f'Motivo FAP "{display_name}" atualizado com sucesso!', 'success')
            return redirect(url_for('fap_reasons.list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar motivo FAP: {str(e)}', 'danger')
    
    # Buscar templates disponíveis
    templates = CaseTemplate.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(CaseTemplate.template_name).all()
    
    return render_template(
        'fap_reasons/form.html',
        fap_reason=fap_reason,
        templates=templates,
        title='Editar Motivo FAP'
    )


@fap_reasons_bp.route('/<int:reason_id>/toggle', methods=['POST'])
@require_law_firm
def toggle(reason_id):
    """Ativar/Desativar motivo FAP"""
    law_firm_id = get_current_law_firm_id()
    
    fap_reason = FapReason.query.filter_by(
        id=reason_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    fap_reason.is_active = not fap_reason.is_active
    fap_reason.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        status = 'ativado' if fap_reason.is_active else 'desativado'
        flash(f'Motivo FAP "{fap_reason.display_name}" {status} com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar status: {str(e)}', 'danger')
    
    return redirect(url_for('fap_reasons.list'))


@fap_reasons_bp.route('/<int:reason_id>/delete', methods=['POST'])
@require_law_firm
def delete(reason_id):
    """Deletar motivo FAP"""
    law_firm_id = get_current_law_firm_id()
    
    fap_reason = FapReason.query.filter_by(
        id=reason_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    display_name = fap_reason.display_name
    
    try:
        db.session.delete(fap_reason)
        db.session.commit()
        flash(f'Motivo FAP "{display_name}" excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir motivo FAP: {str(e)}', 'danger')
    
    return redirect(url_for('fap_reasons.list'))
