"""Configuração do banco lida do ambiente, sem carregar a aplicação.

Fonte única do `.env` e da URL do banco para o `main.py` e para os scripts que
consultam a fila antes de decidir se vale carregar a aplicação inteira
(`existe_na_fila`).

`import main` registra todos os blueprints e, com eles, LangChain, Docling,
transformers e torch: medido em 22/10/2026, ~10 s de CPU e ~1 GB de RAM local,
~40 s por processo no servidor. Os processadores de fila rodam no cron e, na
maioria das execuções, não há nada a processar — pagar o boot inteiro para
descobrir isso deixava um núcleo ocupado à toa. Este módulo só usa o
SQLAlchemy Core.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(env_path: Path | str = Path('.') / '.env') -> None:
    """Carrega o `.env` por cima do ambiente do processo (o `.env` vence)."""
    env_path = Path(env_path)
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.strip().split('=', 1)
                os.environ[key] = value  # Usar assignment ao invés de setdefault


def database_uri() -> str:
    """URL do banco conforme `ENVIRONMENT` / `DATABASE_TYPE`."""
    environment = os.environ.get('ENVIRONMENT', 'development')

    if environment == 'production' or os.environ.get('DATABASE_TYPE') == 'mysql':
        # MySQL para produção
        mysql_host = os.environ.get('MYSQL_HOST', 'localhost')
        mysql_port = os.environ.get('MYSQL_PORT', '3306')
        mysql_user = os.environ.get('MYSQL_USER', 'root')
        mysql_password = os.environ.get('MYSQL_PASSWORD', 'password')
        mysql_database = os.environ.get('MYSQL_DATABASE', 'intellexia')
        return f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_database}?charset=utf8mb4"

    # SQLite para desenvolvimento
    return 'sqlite:///intellexia.db'


def _engine_uri() -> str:
    """URL para um engine fora do Flask.

    O Flask-SQLAlchemy resolve SQLite relativo dentro de `instance/`; um engine
    criado direto resolveria pelo diretório atual e abriria (criando) outro
    arquivo vazio.
    """
    uri = database_uri()
    prefixo = 'sqlite:///'
    if uri.startswith(prefixo) and not uri.startswith(prefixo + '/'):
        return prefixo + str(PROJECT_ROOT / 'instance' / uri[len(prefixo):])
    return uri


def existe_na_fila(sql: str, **params) -> bool:
    """True se a consulta devolve alguma linha.

    Qualquer falha (banco fora, `.env` incompleto) devolve True: o script segue
    o caminho normal, que carrega a aplicação e mostra o erro de verdade — o
    pré-filtro nunca pode ser o motivo de a fila parar.
    """
    from sqlalchemy import bindparam, create_engine, text
    from sqlalchemy.pool import NullPool

    try:
        engine = create_engine(_engine_uri(), poolclass=NullPool)
        try:
            stmt = text(sql)
            listas = [nome for nome, valor in params.items() if isinstance(valor, (list, tuple))]
            if listas:
                stmt = stmt.bindparams(*(bindparam(nome, expanding=True) for nome in listas))
            with engine.connect() as conn:
                return conn.execute(stmt, params).first() is not None
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 — degrada para o caminho completo
        print(f"Pré-verificação da fila falhou ({exc.__class__.__name__}: {exc}); seguindo pelo caminho completo.")
        return True
