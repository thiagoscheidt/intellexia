"""Tokens pessoais da API do IntellexIA — fonte única da tela, do MCP e da autenticação.

O token é ``itx_`` + texto aleatório e só existe em claro no momento da
criação: o banco guarda o SHA-256 (para achar) e os 4 últimos caracteres (para
a pessoa reconhecer na tela). Quem chama a API é o **usuário dono**, com o
escritório e as permissões que ele tem **agora** — usuário desativado ou com
módulo retirado perde o acesso na requisição seguinte, sem esperar o token
vencer.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.models import ApiToken, User, db

PREFIXO = 'itx_'
VALIDADES_DIAS = (30, 90, 180, None)
VALIDADE_PADRAO = 90


class TokenInvalido(Exception):
    """Token ausente, desconhecido, vencido, revogado ou de usuário inativo."""

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def situacao(t: ApiToken) -> str:
    if t.revoked_at:
        return 'revogado'
    if t.expires_at and t.expires_at <= _utcnow():
        return 'vencido'
    return 'ativo'


def criar(user: User, nome: str, dias: int | None = VALIDADE_PADRAO) -> tuple[ApiToken, str]:
    """Cria o token e devolve (registro, token em claro). O texto não é guardado."""
    if dias not in VALIDADES_DIAS:
        raise ValueError(f'Validade inválida: {dias}. Use 30, 90, 180 dias ou sem validade.')
    nome = (nome or '').strip()[:100] or 'Token de API'
    texto = PREFIXO + secrets.token_urlsafe(30)
    agora = _utcnow()
    reg = ApiToken(
        law_firm_id=user.law_firm_id,
        user_id=user.id,
        name=nome,
        token_hash=_hash(texto),
        last4=texto[-4:],
        expires_at=agora + timedelta(days=dias) if dias else None,
        created_at=agora,
    )
    db.session.add(reg)
    db.session.commit()
    return reg, texto


def listar(user: User) -> list[ApiToken]:
    return (ApiToken.query.filter_by(user_id=user.id, law_firm_id=user.law_firm_id)
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc()).all())


def listar_do_escritorio(law_firm_id: int) -> list[ApiToken]:
    return (ApiToken.query.filter_by(law_firm_id=law_firm_id)
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc()).all())


def revogar(token_id: int, por: User) -> ApiToken:
    """Revoga o token. Só o dono ou um admin do mesmo escritório; revogar de novo não muda nada."""
    reg = db.session.get(ApiToken, token_id)
    if not reg or reg.law_firm_id != por.law_firm_id:
        raise PermissionError('Token não encontrado.')
    eh_admin = str(por.role or '').strip().lower() == 'admin'
    if reg.user_id != por.id and not eh_admin:
        raise PermissionError('Só o dono do token ou um administrador pode revogá-lo.')
    if not reg.revoked_at:
        reg.revoked_at = _utcnow()
        reg.revoked_by_id = por.id
        db.session.commit()
    return reg


def autenticar(token_em_claro: str | None, ip: str | None = None) -> User:
    """Usuário dono do token, ou ``TokenInvalido``. Marca o último uso (sem commit)."""
    texto = (token_em_claro or '').strip()
    if not texto.startswith(PREFIXO):
        raise TokenInvalido('Token de API inválido.')
    h = _hash(texto)
    reg = ApiToken.query.filter_by(token_hash=h).first()
    if not reg or not hmac.compare_digest(reg.token_hash, h):
        raise TokenInvalido('Token de API inválido.')
    estado = situacao(reg)
    if estado == 'revogado':
        raise TokenInvalido('Token de API revogado. Crie outro em Minha API.')
    if estado == 'vencido':
        raise TokenInvalido('Token de API vencido. Crie outro em Minha API.')
    user = db.session.get(User, reg.user_id)
    if not user or not user.is_active or user.law_firm_id != reg.law_firm_id:
        raise TokenInvalido('O usuário deste token não está ativo.')
    if not user.law_firm or not user.law_firm.is_active:
        # Mesma regra do login e do OAuth do MCP: escritório suspenso não entra.
        raise TokenInvalido('O escritório deste token não está ativo.')
    reg.last_used_at = _utcnow()
    reg.last_used_ip = (ip or '')[:45] or None
    return user


def token_da_requisicao(token_em_claro: str) -> ApiToken | None:
    """Registro do token em claro (para a resposta de /eu e o limite por token)."""
    return ApiToken.query.filter_by(token_hash=_hash((token_em_claro or '').strip())).first()


def serializar(t: ApiToken) -> dict:
    """O que a tela e o MCP mostram — nunca o hash."""
    def iso(v):
        return v.replace(tzinfo=timezone.utc).isoformat() if v else None

    return {
        'id': t.id,
        'nome': t.name,
        'final': t.last4,
        'usuario_id': t.user_id,
        'criado_em': iso(t.created_at),
        'expira_em': iso(t.expires_at),
        'ultimo_uso': iso(t.last_used_at),
        'situacao': situacao(t),
    }
