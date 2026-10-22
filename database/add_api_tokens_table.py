"""
Migration: cria a tabela api_tokens e libera o módulo `api` a quem já existe.

Tokens pessoais da API do IntellexIA (``/api/v1``) — ver ``ApiToken`` e
``app/services/api_token_service.py``.

O módulo `api` entra nos padrões de todos os papéis, mas o padrão só vale para
quem tem ``module_permissions`` vazio: o usuário com lista gravada (qualquer
um que já passou pela Administração de Usuários) ficaria sem ele. Por isso a
migration acrescenta `api` a essas listas — **só na primeira execução** (quando
cria a tabela), para não desfazer depois a decisão de um admin que tirou o
módulo de alguém. Idempotente.

Executar:
    uv run python database/add_api_tokens_table.py
    uv run python database/add_api_tokens_table.py --aplicar-modulo   # libera de novo a quem não tem
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, ApiToken, User


def criar_tabela() -> bool:
    """Cria api_tokens se não existir. True se criou."""
    table = ApiToken.__table__
    if inspect(db.engine).has_table(table.name):
        print(f'[OK] Tabela {table.name} já existe.')
        return False
    try:
        table.create(db.engine)
    except Exception as e:
        print(f'[ERRO] Falha ao criar {table.name}: {e}')
        raise
    print(f'[OK] Tabela {table.name} criada ({db.engine.dialect.name}).')
    return True


def aplicar_modulo_api() -> int:
    """Acrescenta 'api' às listas de módulos gravadas sem ele. Devolve quantos mudaram."""
    alterados = 0
    for user in User.query.filter(User.module_permissions.isnot(None)).all():
        if str(user.role or '').strip().lower() == 'admin':
            continue  # admin tem todos os módulos sempre
        try:
            lista = json.loads(user.module_permissions)
        except (TypeError, ValueError):
            continue  # lista ilegível já cai nos padrões, que têm 'api'
        if not isinstance(lista, list) or 'api' in lista:
            continue
        user.set_module_permissions(lista + ['api'])
        alterados += 1
    db.session.commit()
    return alterados


def run(aplicar_modulo: bool | None = None):
    """Cria a tabela e, só na primeira vez, libera o módulo `api`.

    Rodar de novo não reconcede: um admin que tirou `api` de alguém depois não
    vê a decisão desfeita. Para forçar: ``--aplicar-modulo``.
    """
    with app.app_context():
        criou = criar_tabela()
        if aplicar_modulo is None:
            aplicar_modulo = criou or '--aplicar-modulo' in sys.argv[1:]
        if not aplicar_modulo:
            print('[OK] Módulo "API e integrações" já foi distribuído na criação da tabela — '
                  'nada a fazer (use --aplicar-modulo para liberar de novo a quem não tem).')
            return
        alterados = aplicar_modulo_api()
        print(f'[OK] Módulo "API e integrações" liberado para {alterados} usuário(s) com lista própria de módulos.')


if __name__ == '__main__':
    run()
