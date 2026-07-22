"""
Teste das restrições de acesso por papel (módulos admin-only).

Regras:
- 'settings' e 'admin_users' são admin-only DUROS: mesmo concedidos a um
  não-admin, são removidos na normalização.
- Cadastros (clients, lawyers, courts) saem dos defaults de não-admin, mas
  podem ser concedidos individualmente pela tela de usuários.
- O perfil do próprio usuário (settings.profile*) fica fora do módulo settings
  — qualquer usuário logado acessa.
- Dashboard de Tokens é tela admin-only dentro do módulo dashboard.

Uso: uv run python tests/test_module_permissions_admin.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.utils.permissions import (  # noqa: E402
    ADMIN_ONLY_MODULES,
    can_access_endpoint,
    get_default_module_permissions,
    get_module_from_endpoint,
    normalize_module_permissions,
)

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def run():
    print("[1] Módulos admin-only duros")
    check("settings e admin_users no conjunto duro", ADMIN_ONLY_MODULES == {'settings', 'admin_users'})
    granted = ['dashboard', 'settings', 'admin_users', 'cases']
    check("não-admin com settings concedido → removido",
          'settings' not in normalize_module_permissions(granted, 'lawyer'))
    check("não-admin com admin_users concedido → removido",
          'admin_users' not in normalize_module_permissions(granted, 'lawyer'))
    check("módulos comuns concedidos permanecem",
          set(normalize_module_permissions(granted, 'lawyer')) == {'dashboard', 'cases'})
    check("admin mantém tudo", 'settings' in normalize_module_permissions(granted, 'admin'))

    print("[2] Defaults por papel sem cadastros/settings")
    for role in ('lawyer', 'assistant', 'user'):
        defaults = set(get_default_module_permissions(role))
        check(f"{role}: sem settings/admin_users", not ({'settings', 'admin_users'} & defaults))
        check(f"{role}: sem cadastros por default", not ({'clients', 'lawyers', 'courts'} & defaults))
        check(f"{role}: mantém módulos operacionais",
              {'dashboard', 'fap_review', 'cases'} <= defaults)
    check("admin: tudo", 'settings' in get_default_module_permissions('admin')
          and 'clients' in get_default_module_permissions('admin'))

    print("[3] Cadastros concedíveis individualmente")
    check("lawyer com clients concedido mantém acesso",
          'clients' in normalize_module_permissions(['clients'], 'lawyer'))

    print("[4] Perfil próprio fora do módulo settings")
    check("settings.profile sem módulo", get_module_from_endpoint('settings.profile') is None)
    check("settings.profile_post sem módulo", get_module_from_endpoint('settings.profile_post') is None)
    check("settings.law_firm_settings continua no módulo",
          get_module_from_endpoint('settings.law_firm_settings') == 'settings')
    check("lawyer acessa o próprio perfil", can_access_endpoint('settings.profile', 'lawyer', None))
    check("lawyer não acessa dados do escritório",
          not can_access_endpoint('settings.law_firm_settings', 'lawyer', None))


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
