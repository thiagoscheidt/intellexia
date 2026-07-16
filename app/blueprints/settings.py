import re

from flask import Blueprint, render_template, session, redirect, url_for, jsonify, flash, request
from app.models import db, LawFirm, NotificationSetting, User
from app.services import email_service, notification_service
from datetime import datetime
from functools import wraps

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
MIN_PASSWORD_LENGTH = 6

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
        
        law_firm.updated_at = datetime.now()
        
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


@settings_bp.route('/notifications', methods=['GET'])
@require_law_firm
def notifications():
    """Página de notificações por e-mail (apenas admin)."""
    if session.get('user_role') != 'admin':
        flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    fap_digest = notification_service.get_or_create_setting(
        session.get('law_firm_id'), NotificationSetting.TYPE_FAP_DIGEST
    )

    return render_template(
        'settings/notifications.html',
        fap_digest=fap_digest,
        smtp_configured=email_service.is_configured(),
        smtp_config=email_service.get_config(),
        weekday_labels=notification_service.WEEKDAY_LABELS,
        user_email=session.get('user_email'),
    )


@settings_bp.route('/notifications/fap-digest', methods=['POST'])
@require_law_firm
def notifications_fap_digest_post():
    """Salvar a configuração do Resumo FAP (apenas admin)."""
    if session.get('user_role') != 'admin':
        return jsonify({"success": False, "message": "Acesso negado"}), 403

    setting = notification_service.get_or_create_setting(
        session.get('law_firm_id'), NotificationSetting.TYPE_FAP_DIGEST
    )

    frequency = (request.form.get('frequency') or '').strip()
    if frequency not in (NotificationSetting.FREQUENCY_DAILY, NotificationSetting.FREQUENCY_WEEKLY):
        return jsonify({"success": False, "message": "Frequência inválida"}), 400

    send_hour = _parse_int_in_range(request.form.get('send_hour'), 0, 23)
    if send_hour is None:
        return jsonify({"success": False, "message": "Horário inválido"}), 400

    send_weekday = _parse_int_in_range(request.form.get('send_weekday'), 0, 6)
    if send_weekday is None:
        return jsonify({"success": False, "message": "Dia da semana inválido"}), 400

    raw_recipients = request.form.get('recipients') or ''
    recipients = email_service.normalize_recipients(raw_recipients)
    informed = [r for r in re.split(r'[,;\s]+', raw_recipients) if r.strip()]
    invalid = [r for r in informed if not email_service.is_valid_email(r)]
    if invalid:
        return jsonify({
            "success": False,
            "message": f"E-mail(s) inválido(s): {', '.join(invalid[:3])}",
        }), 400

    is_enabled = (request.form.get('is_enabled') or '').lower() in ('1', 'true', 'on', 'yes')
    if is_enabled and not recipients:
        return jsonify({
            "success": False,
            "message": "Informe ao menos um destinatário para ativar o envio",
        }), 400

    try:
        setting.is_enabled = is_enabled
        setting.frequency = frequency
        setting.send_hour = send_hour
        setting.send_weekday = send_weekday
        setting.set_recipients(recipients)
        setting.updated_at = datetime.now()

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Configuração de notificação salva com sucesso!",
            "recipients": recipients,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao salvar: {str(e)}"}), 500


@settings_bp.route('/notifications/fap-digest/send-now', methods=['POST'])
@require_law_firm
def notifications_fap_digest_send_now():
    """Envia o Resumo FAP de teste para o próprio admin logado.

    Nunca dispara para a lista de destinatários (evita envio acidental a clientes)
    e não altera ``last_sent_at``.
    """
    if session.get('user_role') != 'admin':
        return jsonify({"success": False, "message": "Acesso negado"}), 403

    user = _get_logged_user()
    if not user or not user.email:
        return jsonify({"success": False, "message": "Usuário sem e-mail cadastrado"}), 400

    if not email_service.is_configured():
        return jsonify({
            "success": False,
            "message": "SMTP não configurado. Defina SMTP_HOST e SMTP_FROM_EMAIL no .env do servidor.",
        }), 400

    try:
        result = notification_service.send_fap_digest(
            session.get('law_firm_id'), force=True, override_recipients=[user.email]
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao enviar: {str(e)}"}), 500

    if result.get('status') != 'sent':
        return jsonify({"success": False, "message": result.get('message', 'Falha no envio')}), 500

    return jsonify({"success": True, "message": f"E-mail de teste enviado para {user.email}."})


def _parse_int_in_range(raw, minimum, maximum):
    """Int dentro do intervalo, ou None se inválido."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if minimum <= value <= maximum else None


def _get_logged_user():
    """Usuário da sessão. Nunca aceita id vindo da requisição."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)


@settings_bp.route('/profile', methods=['GET'])
@require_law_firm
def profile():
    """Página de perfil do usuário logado"""
    user = _get_logged_user()
    if not user:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('auth.login'))

    return render_template('settings/profile.html', user=user)


@settings_bp.route('/profile', methods=['POST'])
@require_law_firm
def profile_post():
    """Atualizar dados pessoais do usuário logado"""
    user = _get_logged_user()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado"}), 404

    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not name or not email:
        return jsonify({"success": False, "message": "Nome e e-mail são obrigatórios"}), 400

    if not EMAIL_PATTERN.match(email):
        return jsonify({"success": False, "message": "E-mail inválido"}), 400

    email_owner = User.query.filter(User.email == email, User.id != user.id).first()
    if email_owner:
        return jsonify({"success": False, "message": "Este e-mail já está em uso por outro usuário"}), 400

    try:
        # role, law_firm_id e is_active não são editáveis aqui, mesmo que venham no form.
        user.name = name
        user.email = email
        user.phone = (request.form.get('phone') or '').strip() or None
        user.oab_number = (request.form.get('oab_number') or '').strip() or None
        user.updated_at = datetime.now()

        db.session.commit()

        session['user_name'] = user.name
        session['user_email'] = user.email

        return jsonify({"success": True, "message": "Perfil atualizado com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao atualizar perfil: {str(e)}"}), 500


@settings_bp.route('/profile/password', methods=['POST'])
@require_law_firm
def profile_password_post():
    """Alterar a senha do usuário logado"""
    user = _get_logged_user()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado"}), 404

    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not all([current_password, new_password, confirm_password]):
        return jsonify({"success": False, "message": "Preencha todos os campos de senha"}), 400

    if not user.check_password(current_password):
        return jsonify({"success": False, "message": "A senha atual está incorreta"}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "message": "A nova senha e a confirmação não coincidem"}), 400

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": f"A nova senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres",
        }), 400

    if new_password == current_password:
        return jsonify({"success": False, "message": "A nova senha deve ser diferente da atual"}), 400

    try:
        user.set_password(new_password)
        user.updated_at = datetime.now()
        db.session.commit()

        return jsonify({"success": True, "message": "Senha alterada com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao alterar senha: {str(e)}"}), 500
