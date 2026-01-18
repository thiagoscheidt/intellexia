from flask import Blueprint, request, jsonify, session
from app.models import db, Case, CaseComment, CaseActivity, User
from datetime import datetime
from functools import wraps
from sqlalchemy.orm import joinedload

case_comments_bp = Blueprint('case_comments', __name__, url_prefix='/cases/<int:case_id>/comments')

def check_case_access(f):
    """Verifica se o usuário tem acesso ao caso"""
    @wraps(f)
    def decorated_function(case_id, *args, **kwargs):
        case = Case.query.get_or_404(case_id)
        if case.law_firm_id != session.get('law_firm_id'):
            return {'error': 'Acesso negado'}, 403
        return f(case_id, *args, **kwargs)
    return decorated_function


@case_comments_bp.route('/', methods=['GET'])
@check_case_access
def list_comments(case_id):
    """Lista comentários principais (paginado)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    comments = CaseComment.query.filter_by(
        case_id=case_id,
        parent_comment_id=None  # Apenas comentários principais
    ).options(joinedload(CaseComment.user), joinedload(CaseComment.replies)).order_by(
        CaseComment.is_pinned.desc(),
        CaseComment.created_at.desc()
    ).paginate(page=page, per_page=per_page)
    
    return jsonify({
        'comments': [{
            'id': c.id,
            'user': c.user.name,
            'user_id': c.user_id,
            'avatar': f"https://ui-avatars.com/api/?name={c.user.name}&background=random",
            'title': c.title,
            'content': c.content,
            'created_at': c.created_at.isoformat(),
            'updated_at': c.updated_at.isoformat(),
            'is_pinned': c.is_pinned,
            'is_resolved': c.is_resolved,
            'resolved_by': c.resolved_by.name if c.resolved_by else None,
            'reply_count': CaseComment.query.filter_by(parent_comment_id=c.id).count(),
            'mentions': c.mentions or [],
            'can_edit': session.get('user_id') == c.user_id,
            'can_delete': session.get('user_id') == c.user_id or session.get('user_role') == 'admin'
        } for c in comments.items],
        'total': comments.total,
        'pages': comments.pages,
        'current_page': page
    })


@case_comments_bp.route('/<int:comment_id>/replies', methods=['GET'])
@check_case_access
def get_replies(case_id, comment_id):
    """Obtém respostas de um comentário"""
    parent = CaseComment.query.get_or_404(comment_id)
    
    if parent.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    replies = CaseComment.query.filter_by(
        parent_comment_id=comment_id
    ).order_by(CaseComment.created_at.asc()).all()
    
    return jsonify({
        'replies': [{
            'id': r.id,
            'user': r.user.name,
            'user_id': r.user_id,
            'avatar': f"https://ui-avatars.com/api/?name={r.user.name}&background=random",
            'content': r.content,
            'created_at': r.created_at.isoformat(),
            'updated_at': r.updated_at.isoformat(),
            'can_edit': session.get('user_id') == r.user_id,
            'can_delete': session.get('user_id') == r.user_id or session.get('user_role') == 'admin'
        } for r in replies]
    })


@case_comments_bp.route('/', methods=['POST'])
@check_case_access
def add_comment(case_id):
    """Adiciona novo comentário"""
    case = Case.query.get_or_404(case_id)
    
    if case.law_firm_id != session.get('law_firm_id'):
        return {'error': 'Acesso negado'}, 403
    
    data = request.get_json()
    
    if not data.get('content'):
        return {'error': 'Comentário vazio'}, 400
    
    comment = CaseComment(
        case_id=case_id,
        user_id=session.get('user_id'),
        title=data.get('title', ''),
        content=data.get('content'),
        comment_type=data.get('type', 'internal'),
        mentions=data.get('mentions', [])
    )
    
    db.session.add(comment)
    
    # Registrar atividade
    activity = CaseActivity(
        case_id=case_id,
        user_id=session.get('user_id'),
        activity_type='comment',
        title=f'Novo comentário: {data.get("title", "Sem título")}',
        related_id=comment.id
    )
    db.session.add(activity)
    db.session.commit()
    
    return jsonify({
        'id': comment.id,
        'created_at': comment.created_at.isoformat()
    }), 201


@case_comments_bp.route('/<int:comment_id>/reply', methods=['POST'])
@check_case_access
def reply_comment(case_id, comment_id):
    """Adiciona resposta a um comentário"""
    parent = CaseComment.query.get_or_404(comment_id)
    
    if parent.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    data = request.get_json()
    
    if not data.get('content'):
        return {'error': 'Resposta vazia'}, 400
    
    reply = CaseComment(
        case_id=case_id,
        user_id=session.get('user_id'),
        content=data.get('content'),
        parent_comment_id=comment_id,
        mentions=data.get('mentions', [])
    )
    
    db.session.add(reply)
    
    activity = CaseActivity(
        case_id=case_id,
        user_id=session.get('user_id'),
        activity_type='comment_reply',
        title=f'Resposta em comentário de {parent.user.name}',
        related_id=reply.id
    )
    db.session.add(activity)
    db.session.commit()
    
    return jsonify({
        'id': reply.id,
        'created_at': reply.created_at.isoformat()
    }), 201


@case_comments_bp.route('/<int:comment_id>', methods=['PUT'])
@check_case_access
def update_comment(case_id, comment_id):
    """Atualiza um comentário"""
    comment = CaseComment.query.get_or_404(comment_id)
    
    if comment.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    if comment.user_id != session.get('user_id') and session.get('user_role') != 'admin':
        return {'error': 'Sem permissão'}, 403
    
    data = request.get_json()
    
    if 'content' in data:
        comment.content = data.get('content')
    if 'title' in data:
        comment.title = data.get('title')
    if 'mentions' in data:
        comment.mentions = data.get('mentions', [])
    
    comment.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'updated': True})


@case_comments_bp.route('/<int:comment_id>', methods=['DELETE'])
@check_case_access
def delete_comment(case_id, comment_id):
    """Deleta um comentário e suas respostas"""
    comment = CaseComment.query.get_or_404(comment_id)
    
    if comment.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    if comment.user_id != session.get('user_id') and session.get('user_role') != 'admin':
        return {'error': 'Sem permissão'}, 403
    
    # Deletar respostas também
    CaseComment.query.filter_by(parent_comment_id=comment_id).delete()
    db.session.delete(comment)
    db.session.commit()
    
    return jsonify({'deleted': True})


@case_comments_bp.route('/<int:comment_id>/pin', methods=['POST'])
@check_case_access
def pin_comment(case_id, comment_id):
    """Fixar/desafixar comentário importante"""
    comment = CaseComment.query.get_or_404(comment_id)
    
    if comment.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    if session.get('user_role') != 'admin' and comment.user_id != session.get('user_id'):
        return {'error': 'Sem permissão'}, 403
    
    comment.is_pinned = not comment.is_pinned
    db.session.commit()
    
    return jsonify({'pinned': comment.is_pinned})


@case_comments_bp.route('/<int:comment_id>/resolve', methods=['POST'])
@check_case_access
def resolve_comment(case_id, comment_id):
    """Marcar/desmarcar comentário como resolvido"""
    comment = CaseComment.query.get_or_404(comment_id)
    
    if comment.case_id != case_id:
        return {'error': 'Comentário não pertence a este caso'}, 400
    
    if session.get('user_role') != 'admin':
        return {'error': 'Sem permissão'}, 403
    
    if comment.is_resolved:
        comment.is_resolved = False
        comment.resolved_by_id = None
        comment.resolved_at = None
    else:
        comment.is_resolved = True
        comment.resolved_by_id = session.get('user_id')
        comment.resolved_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'resolved': comment.is_resolved})


@case_comments_bp.route('/timeline', methods=['GET'])
@check_case_access
def case_timeline(case_id):
    """Obtém timeline de atividades do caso"""
    limit = request.args.get('limit', 20, type=int)
    
    activities = CaseActivity.query.filter_by(case_id=case_id).order_by(
        CaseActivity.created_at.desc()
    ).limit(limit).all()
    
    return jsonify({
        'activities': [{
            'id': a.id,
            'type': a.activity_type,
            'title': a.title,
            'description': a.description,
            'user': a.user.name,
            'created_at': a.created_at.isoformat(),
            'icon': get_activity_icon(a.activity_type)
        } for a in activities]
    })


def get_activity_icon(activity_type):
    """Retorna ícone apropriado para cada tipo de atividade"""
    icons = {
        'comment': 'bi-chat-left-text',
        'comment_reply': 'bi-reply',
        'status_change': 'bi-arrow-repeat',
        'document_added': 'bi-file-earmark-plus',
        'lawyer_added': 'bi-person-plus',
        'benefit_added': 'bi-plus-circle'
    }
    return icons.get(activity_type, 'bi-info-circle')
