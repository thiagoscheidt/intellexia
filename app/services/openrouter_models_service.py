import logging
import os

import requests


logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = os.getenv('OPENROUTER_MODELS_URL', 'https://openrouter.ai/api/v1/models')
OPENROUTER_MODELS_TIMEOUT_SECONDS = int(os.getenv('OPENROUTER_MODELS_TIMEOUT_SECONDS', '15'))


def _safe_release_timestamp(raw_value) -> int | None:
    if raw_value in (None, ''):
        return None

    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        return None

    # Se vier em milissegundos, converte para segundos.
    if value > 10_000_000_000:
        value = int(value / 1000)

    return value if value > 0 else None


def _build_fallback_options(
    selected_model: str | None,
    fallback_model: str | None,
) -> list[dict[str, object]]:
    fallback_options: list[dict[str, object]] = []
    for model_id in [selected_model, fallback_model]:
        normalized_model_id = (model_id or '').strip()
        if normalized_model_id and normalized_model_id not in {item['id'] for item in fallback_options}:
            fallback_options.append(
                {
                    'id': normalized_model_id,
                    'name': normalized_model_id,
                    'description': 'Modelo disponível por fallback (não carregado da OpenRouter no momento).',
                    'context_length': None,
                    'prompt_price': None,
                    'completion_price': None,
                    'release_timestamp': None,
                }
            )
    return fallback_options


def fetch_openrouter_text_models_for_info(
    *,
    selected_model: str | None = None,
    fallback_model: str | None = None,
) -> tuple[list[dict[str, object]], str | None]:
    """Busca modelos text-only da OpenRouter para uso informativo em telas de configuração/UI."""

    api_key = os.getenv('OPENAI_API_KEY') or os.getenv('OPENROUTER_API_KEY')
    fallback_options = _build_fallback_options(selected_model, fallback_model)

    if not api_key:
        return fallback_options, 'OPENAI_API_KEY não configurada para carregar os modelos da OpenRouter.'

    try:
        response = requests.get(
            OPENROUTER_MODELS_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            params={'output_modalities': 'text'},
            timeout=OPENROUTER_MODELS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json() or {}
    except Exception as exc:
        logger.warning('Falha ao carregar modelos da OpenRouter (informativo): %s', exc)
        return fallback_options, 'Não foi possível carregar a lista de modelos da OpenRouter agora.'

    items: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for item in payload.get('data') or []:
        if not isinstance(item, dict):
            continue

        model_id = str(item.get('id') or '').strip()
        if not model_id or model_id in seen_ids:
            continue

        architecture = item.get('architecture') or {}
        output_modalities = architecture.get('output_modalities') or []
        modality = str(architecture.get('modality') or '')
        if output_modalities and 'text' not in output_modalities:
            continue
        if modality and 'text' not in modality:
            continue

        pricing = item.get('pricing') or {}
        top_provider = item.get('top_provider') or {}
        release_timestamp = (
            _safe_release_timestamp(item.get('created'))
            or _safe_release_timestamp(item.get('created_at'))
            or _safe_release_timestamp(item.get('published_at'))
            or _safe_release_timestamp(top_provider.get('created'))
            or _safe_release_timestamp(top_provider.get('created_at'))
        )

        context_length = item.get('context_length') or top_provider.get('context_length')
        try:
            context_length = int(context_length) if context_length is not None else None
        except (TypeError, ValueError):
            context_length = None

        items.append(
            {
                'id': model_id,
                'name': str(item.get('name') or model_id).strip() or model_id,
                'description': str(item.get('description') or '').strip(),
                'context_length': context_length,
                'prompt_price': str(pricing.get('prompt') or '').strip() or None,
                'completion_price': str(pricing.get('completion') or '').strip() or None,
                'release_timestamp': release_timestamp,
            }
        )
        seen_ids.add(model_id)

    items.sort(
        key=lambda model: (
            -(int(model.get('release_timestamp') or 0)),
            str(model.get('name') or '').lower(),
        )
    )

    for extra_model in fallback_options:
        if extra_model['id'] not in seen_ids:
            items.insert(0, extra_model)
            seen_ids.add(extra_model['id'])

    return items, None
