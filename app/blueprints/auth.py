from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from sqlalchemy import func
from app.models import db, User, LawFirm
from app.services.google_oauth import (google_client, google_login_enabled, google_redirect_uri,
                                       sanitize_picture_url)
from app.utils.permissions import get_landing_endpoint
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

CONTA_INATIVA_MSG = 'Sua conta está inativa. Entre em contato com o suporte.'
ESCRITORIO_INATIVO_MSG = 'O escritório está inativo. Entre em contato com o suporte.'

# Autocadastro desligado: contas são criadas pelo admin em Administração de
# Usuários. Para reabrir, basta voltar esta flag para True (a tela e as rotas
# continuam no lugar) e restaurar o link "Criar conta" em templates/login.html.
REGISTRATION_ENABLED = False
CADASTRO_FECHADO_MSG = (
    'O cadastro está fechado. Solicite acesso ao administrador do escritório.'
)

# Erros do login com Google chegam de volta como ?erro=<código>: a tela de login
# não renderiza flash messages, então a mensagem é resolvida aqui e exibida na
# caixa de alerta que a página já tem.
LOGIN_ERROR_MESSAGES = {
    'google_indisponivel': 'O login com Google não está configurado nesta instalação.',
    'google_falhou': 'Não foi possível concluir o login com Google. Tente novamente.',
    'google_email_nao_verificado': 'O Google não confirmou a verificação deste e-mail.',
    'google_nao_autorizado': (
        'Esta conta Google não está autorizada. '
        'Fale com o administrador do escritório.'
    ),
    'conta_inativa': CONTA_INATIVA_MSG,
    'escritorio_inativo': ESCRITORIO_INATIVO_MSG,
    'cadastro_fechado': CADASTRO_FECHADO_MSG,
}


def _safe_next_url(value):
    """Aceita apenas paths relativos do próprio site (evita open redirect)."""
    if value and value.startswith('/') and not value.startswith('//') and '\\' not in value:
        return value
    return None


def _start_user_session(user, remember=False, via_google=False):
    """Registra o acesso e popula a sessão. Devolve o endpoint de destino.

    Fonte única das chaves de sessão — usada pelo login por senha e pelo login
    com Google, para que as duas portas nunca divirjam. ``via_google`` alimenta
    os contadores de adoção mostrados na tela de Atividade de Usuários.
    """
    agora = datetime.now()
    user.last_login = agora
    user.last_activity = agora
    if via_google:
        user.google_last_login_at = agora
        user.google_login_count = (user.google_login_count or 0) + 1
    db.session.commit()

    session['user_id'] = user.id
    session['user_email'] = user.email
    session['user_name'] = user.name
    session['user_role'] = user.role
    session['user_module_permissions'] = user.get_module_permissions()
    # Vale também para o login por senha: a foto vem do banco, não do fluxo do Google.
    session['user_picture'] = user.google_picture_url
    session['law_firm_id'] = user.law_firm_id
    session['law_firm_name'] = user.law_firm.name

    if remember:
        session.permanent = True

    return get_landing_endpoint(user.role, user.module_permissions)


@auth_bp.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        next_url = _safe_next_url(request.args.get('next'))
        return redirect(next_url or url_for('dashboard.dashboard'))
    return render_template(
        'login.html',
        google_login_enabled=google_login_enabled(),
        next_url=_safe_next_url(request.args.get('next')),
        login_error=LOGIN_ERROR_MESSAGES.get(request.args.get('erro')),
    )

@auth_bp.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('email')
    password = request.form.get('password')
    remember = request.form.get('remember')
    
    if not email or not password:
        return jsonify({"success": False, "message": "Email e senha são obrigatórios"})
    
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return jsonify({"success": False, "message": "Email ou senha incorretos"})
    
    if not user.is_active:
        return jsonify({"success": False, "message": CONTA_INATIVA_MSG})

    if not user.law_firm.is_active:
        return jsonify({"success": False, "message": ESCRITORIO_INATIVO_MSG})

    if not user.check_password(password):
        return jsonify({"success": False, "message": "Email ou senha incorretos"})

    landing_endpoint = _start_user_session(user, remember=bool(remember))

    next_url = _safe_next_url(request.args.get('next'))

    return jsonify({
        "success": True,
        "redirect": next_url or url_for(landing_endpoint),
        "user": user.to_dict()
    })

@auth_bp.route('/login/google', methods=['GET'])
def google_login():
    """Inicia o fluxo OpenID Connect do Google (Authorization Code)."""
    client = google_client()
    if client is None:
        return redirect(url_for('auth.login', erro='google_indisponivel'))

    # O 'next' não sobrevive ao redirect do Google: guarda na sessão já validado.
    session['google_next_url'] = _safe_next_url(request.args.get('next'))

    try:
        return client.authorize_redirect(google_redirect_uri())
    except Exception:
        logger.exception('Falha ao iniciar o login com Google')
        return redirect(url_for('auth.login', erro='google_falhou'))


@auth_bp.route('/login/google/callback', methods=['GET'])
def google_callback():
    """Retorno do Google: autentica e libera só quem já existe na base.

    O Google prova a posse do e-mail; a autorização continua sendo nossa —
    usuário inexistente nunca é criado aqui.
    """
    client = google_client()
    if client is None:
        return redirect(url_for('auth.login', erro='google_indisponivel'))

    next_url = _safe_next_url(session.pop('google_next_url', None))

    try:
        # Valida assinatura (JWKS do Google), iss, aud, exp e nonce do id_token.
        token = client.authorize_access_token()
        claims = token.get('userinfo') or client.userinfo(token=token) or {}
    except Exception:
        logger.exception('Falha ao concluir o login com Google')
        return redirect(url_for('auth.login', erro='google_falhou'))

    email = (claims.get('email') or '').strip().lower()
    google_sub = (claims.get('sub') or '').strip()
    email_verificado = str(claims.get('email_verified')).strip().lower() in ('true', '1')

    if not email or not google_sub or not email_verificado:
        return redirect(url_for('auth.login', erro='google_email_nao_verificado'))

    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        # Mensagem neutra: não revela se o e-mail existe na base.
        logger.info('Login com Google recusado: e-mail sem usuário correspondente')
        return redirect(url_for('auth.login', erro='google_nao_autorizado'))

    if not user.is_active:
        return redirect(url_for('auth.login', erro='conta_inativa'))

    if not user.law_firm or not user.law_firm.is_active:
        return redirect(url_for('auth.login', erro='escritorio_inativo'))

    _link_google_account(user, google_sub)
    # Reescrita a cada login: se a pessoa trocou ou removeu a foto no Google, segue.
    user.google_picture_url = sanitize_picture_url(claims.get('picture'))

    landing_endpoint = _start_user_session(user, via_google=True)
    return redirect(next_url or url_for(landing_endpoint))


def _link_google_account(user, google_sub):
    """Vincula (ou revincula) a conta Google ao usuário.

    A revinculação é automática: se o e-mail bate e o Google o confirmou como
    verificado, um 'sub' novo (conta recriada, migração para o Workspace)
    substitui o anterior. Um mesmo 'sub' não pode ficar em dois usuários — o
    vínculo antigo é limpo antes, senão o índice único bloquearia o login.
    """
    if user.google_sub == google_sub:
        return

    User.query.filter(
        User.google_sub == google_sub, User.id != user.id
    ).update({'google_sub': None, 'google_linked_at': None}, synchronize_session=False)

    user.google_sub = google_sub
    user.google_linked_at = datetime.now()
    db.session.flush()


@auth_bp.route('/register', methods=['GET'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    if not REGISTRATION_ENABLED:
        return redirect(url_for('auth.login', erro='cadastro_fechado'))
    return render_template('register.html')

@auth_bp.route('/register', methods=['POST'])
def register_post():
    if not REGISTRATION_ENABLED:
        return jsonify({"success": False, "message": CADASTRO_FECHADO_MSG})

    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    password_confirm = request.form.get('password_confirm')
    terms = request.form.get('terms')
    law_firm_name = request.form.get('law_firm_name')
    law_firm_cnpj = request.form.get('law_firm_cnpj')
    oab_number = request.form.get('oab_number')
    
    if not all([full_name, email, password, password_confirm, law_firm_name, law_firm_cnpj]):
        return jsonify({"success": False, "message": "Todos os campos obrigatórios devem ser preenchidos"})
    
    if password != password_confirm:
        return jsonify({"success": False, "message": "As senhas não coincidem"})
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "A senha deve ter pelo menos 6 caracteres"})
    
    if not terms:
        return jsonify({"success": False, "message": "Você deve aceitar os termos de uso"})
    
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Este email já está cadastrado"})
    
    if LawFirm.query.filter_by(cnpj=law_firm_cnpj).first():
        return jsonify({"success": False, "message": "Este CNPJ já está cadastrado"})
    
    try:
        law_firm = LawFirm(
            name=law_firm_name,
            cnpj=law_firm_cnpj,
            is_active=True,
            subscription_plan='trial'
        )
        db.session.add(law_firm)
        db.session.flush()
        
        user = User(
            law_firm_id=law_firm.id,
            name=full_name,
            email=email,
            role='admin',
            oab_number=oab_number,
            is_active=True,
            is_verified=False
        )
        user.set_password(password)
        user.set_module_permissions(None)
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "Conta criada com sucesso! Faça login para continuar."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False, 
            "message": f"Erro ao criar conta: {str(e)}"
        })

@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password():
    return render_template('forgot_password.html')

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password_post():
    email = request.form.get('email')
    
    if not email:
        return jsonify({"success": False, "message": "Email é obrigatório"})
    
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    return jsonify({"success": True, "message": "Se o email existir em nosso sistema, você receberá as instruções para redefinir sua senha."})

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema com sucesso.', 'info')
    return redirect(url_for('auth.login'))
