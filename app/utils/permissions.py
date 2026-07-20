import json
from typing import Iterable

MODULE_PERMISSIONS = {
    'dashboard': 'Dashboard',
    'fap_panel': 'Painel FAP',
    'disputes_center': 'Painel de Contestacoes',
    'fap_review': 'Revisor de Peticoes',
    'process_panel': 'Painel de Processos',
    'cases': 'Casos',
    'knowledge_base': 'Base de Conhecimento',
    'tools': 'Ferramentas',
    'clients': 'Clientes',
    'lawyers': 'Advogados',
    'courts': 'Varas Judiciais',
    'settings': 'Configuracoes',
    'admin_users': 'Administracao de Usuarios',
}

ALL_MODULE_PERMISSION_KEYS = tuple(MODULE_PERMISSIONS.keys())

ROLE_DEFAULT_MODULE_PERMISSIONS = {
    'admin': list(ALL_MODULE_PERMISSION_KEYS),
    'lawyer': [k for k in ALL_MODULE_PERMISSION_KEYS if k != 'admin_users'],
    'assistant': [k for k in ALL_MODULE_PERMISSION_KEYS if k != 'admin_users'],
    'user': [k for k in ALL_MODULE_PERMISSION_KEYS if k != 'admin_users'],
}

ENDPOINT_MODULE_MAP = {
    'dashboard.': 'dashboard',
    'fap_panel.': 'fap_panel',
    'disputes_center.': 'disputes_center',
    'fap_review.': 'fap_review',
    'process_panel.': 'process_panel',
    'impugnacao_references.': 'process_panel',
    'cases.': 'cases',
    'benefits.': 'cases',
    'documents.': 'cases',
    'petitions.': 'cases',
    'fap_reasons.': 'cases',
    'case_comments.': 'cases',
    'knowledge_base.': 'knowledge_base',
    'tools.': 'tools',
    'assistant.': 'tools',
    'clients.': 'clients',
    'lawyers.': 'lawyers',
    'courts.': 'courts',
    'settings.': 'settings',
    'admin_users.': 'admin_users',
    'access_audit.': 'admin_users',
}

EXACT_ENDPOINT_MODULE_MAP = {
    'process_panel.manage_judicial_phases': 'settings',
    'process_panel.manage_document_types': 'settings',
    'process_panel.manage_defendants': 'settings',
    'process_panel.manage_legal_theses': 'settings',
}

PRIORITY_ENDPOINT_PREFIX_MAP = {
    'knowledge_base.categories': 'settings',
    'knowledge_base.tags': 'settings',
}

PUBLIC_ENDPOINT_PREFIXES = ('auth.', 'static')

LANDING_ENDPOINT_BY_MODULE = {
    'dashboard': 'dashboard.dashboard',
    'fap_panel': 'fap_panel.contestacoes_page',
    'disputes_center': 'disputes_center.list_disputes_center',
    'fap_review': 'fap_review.index',
    'process_panel': 'process_panel.list_processes',
    'cases': 'cases.cases_list',
    'knowledge_base': 'knowledge_base.intelligent_search',
    'tools': 'tools.tools_document_summary_list',
    'clients': 'clients.clients_list',
    'lawyers': 'lawyers.lawyers_list',
    'courts': 'courts.courts_list',
    'settings': 'process_panel.manage_judicial_phases',
    'admin_users': 'admin_users.list_users',
}


def normalize_role(role: str | None) -> str:
    normalized = str(role or '').strip().lower()
    return normalized or 'user'


def get_default_module_permissions(role: str | None) -> list[str]:
    normalized_role = normalize_role(role)
    defaults = ROLE_DEFAULT_MODULE_PERMISSIONS.get(normalized_role)
    if defaults is None:
        defaults = ROLE_DEFAULT_MODULE_PERMISSIONS['user']
    return list(defaults)


def normalize_module_permissions(raw_permissions: Iterable[str] | None, role: str | None) -> list[str]:
    role_name = normalize_role(role)
    if role_name == 'admin':
        return list(ALL_MODULE_PERMISSION_KEYS)

    if raw_permissions is None:
        return get_default_module_permissions(role_name)

    allowed = {item for item in ALL_MODULE_PERMISSION_KEYS}
    cleaned = []
    for permission in raw_permissions:
        key = str(permission or '').strip()
        if key and key in allowed and key not in cleaned:
            cleaned.append(key)
    return cleaned


def parse_module_permissions(raw_permissions: str | list[str] | tuple[str, ...] | None, role: str | None) -> list[str]:
    if isinstance(raw_permissions, (list, tuple)):
        return normalize_module_permissions(raw_permissions, role)

    if not raw_permissions:
        return normalize_module_permissions(None, role)

    try:
        payload = json.loads(raw_permissions)
        if isinstance(payload, list):
            return normalize_module_permissions(payload, role)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    return normalize_module_permissions(None, role)


def dump_module_permissions(permissions: Iterable[str] | None, role: str | None) -> str:
    normalized = normalize_module_permissions(permissions, role)
    ordered = [item for item in ALL_MODULE_PERMISSION_KEYS if item in normalized]
    return json.dumps(ordered, ensure_ascii=True)


def has_module_permission(
    module_key: str,
    role: str | None,
    module_permissions: str | list[str] | tuple[str, ...] | None,
) -> bool:
    return module_key in parse_module_permissions(module_permissions, role)


def get_module_from_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None

    for public_prefix in PUBLIC_ENDPOINT_PREFIXES:
        if endpoint == public_prefix or endpoint.startswith(public_prefix):
            return None

    if endpoint in EXACT_ENDPOINT_MODULE_MAP:
        return EXACT_ENDPOINT_MODULE_MAP[endpoint]

    for prefix, module_key in PRIORITY_ENDPOINT_PREFIX_MAP.items():
        if endpoint.startswith(prefix):
            return module_key

    for prefix, module_key in ENDPOINT_MODULE_MAP.items():
        if endpoint.startswith(prefix):
            return module_key

    return None


def can_access_endpoint(
    endpoint: str | None,
    role: str | None,
    module_permissions: str | list[str] | tuple[str, ...] | None,
) -> bool:
    module_key = get_module_from_endpoint(endpoint)
    if not module_key:
        return True
    return has_module_permission(module_key, role, module_permissions)


def get_landing_endpoint(role: str | None, module_permissions: str | list[str] | tuple[str, ...] | None) -> str:
    ordered_modules = [
        'dashboard',
        'cases',
        'process_panel',
        'fap_panel',
        'disputes_center',
        'fap_review',
        'knowledge_base',
        'tools',
        'clients',
        'lawyers',
        'courts',
        'settings',
        'admin_users',
    ]

    for module_key in ordered_modules:
        if has_module_permission(module_key, role, module_permissions):
            endpoint = LANDING_ENDPOINT_BY_MODULE.get(module_key)
            if endpoint:
                return endpoint

    return 'auth.logout'
