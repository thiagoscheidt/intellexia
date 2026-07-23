"""Modelo de IA por agente e por escritório (ai_model_settings).

Fonte única da tela "Configurações de IA" do Painel de Processos e da
resolução de modelo dos agentes configuráveis. Sem configuração salva vale o
padrão do sistema (env/config) — comportamento idêntico ao anterior à tela.

Novo agente configurável = nova entrada em AGENT_REGISTRY (sem schema novo):
informe key, grupo, rótulo, descrição e a função que resolve o padrão atual.
"""
import os

from app.agents import config as agents_config
from app.models import db, AiModelSetting

GROUP_READING = 'Leitura de documentos'
GROUP_GENERATION = 'Geração de documentos'

AGENT_REGISTRY = [
    {
        'key': 'judicial_document_extractor',
        'group': GROUP_READING,
        'label': 'Extração de dados',
        'description': 'Lê cada documento enviado ao processo e extrai número, partes, vara, '
                       'tipo documental e fase.',
        'default': lambda: agents_config.DEFAULT_MODEL_MINI,
    },
    {
        'key': 'judicial_document_summary',
        'group': GROUP_READING,
        'label': 'Resumo do documento',
        'description': 'Gera o resumo exibido no botão "Ver resumo da IA" da aba Documentos.',
        'default': lambda: os.getenv('JUDICIAL_DOCUMENT_SUMMARY_MODEL') or agents_config.DEFAULT_MODEL,
    },
    {
        'key': 'judicial_contestation_analysis',
        'group': GROUP_READING,
        'label': 'Análise de contestação',
        'description': 'Analisa contestações da União e vincula benefícios e teses ao processo.',
        'default': lambda: os.getenv('JUDICIAL_CONTESTATION_ANALYSIS_MODEL') or agents_config.DEFAULT_MODEL_ROBUST,
    },
    {
        'key': 'generated_document',
        'group': GROUP_GENERATION,
        'label': 'Gerador de documentos',
        'description': 'Modelo padrão da geração de peças (ex.: impugnação de contestação). '
                       'Pode ser trocado pontualmente na própria tela de Gerar Documento.',
        'default': lambda: agents_config.DEFAULT_MODEL_LEGAL_DRAFTING,
    },
    {
        'key': 'impugnacao_enrichment',
        'group': GROUP_GENERATION,
        'label': 'Enriquecimento da impugnação',
        'description': 'Subagente que cruza jurisprudências e peças-modelo do escritório '
                       'durante a geração da impugnação.',
        'default': lambda: os.getenv('IMPUGNACAO_ENRICHMENT_MODEL') or agents_config.DEFAULT_MODEL_ROBUST,
    },
]

_REGISTRY_BY_KEY = {entry['key']: entry for entry in AGENT_REGISTRY}


def get_model(law_firm_id, agent_key):
    """Modelo efetivo do agente: configuração do escritório ou padrão do sistema."""
    if law_firm_id:
        row = AiModelSetting.query.filter_by(
            law_firm_id=law_firm_id, agent_key=agent_key).first()
        if row and row.model_name:
            return row.model_name
    entry = _REGISTRY_BY_KEY.get(agent_key)
    return entry['default']() if entry else None


def list_for_screen(law_firm_id):
    """Grupos + agentes com padrão, configurado e efetivo — para a tela de configurações."""
    configured = {
        row.agent_key: row.model_name
        for row in AiModelSetting.query.filter_by(law_firm_id=law_firm_id).all()
    }
    groups = {}
    for entry in AGENT_REGISTRY:
        agent = {
            'key': entry['key'],
            'label': entry['label'],
            'description': entry['description'],
            'default': entry['default'](),
            'configured': configured.get(entry['key']),
        }
        groups.setdefault(entry['group'], []).append(agent)
    return [{'group': name, 'agents': agents} for name, agents in groups.items()]


def set_model(law_firm_id, agent_key, model_name, user_id=None):
    """Grava (ou limpa, com model_name vazio → volta ao padrão) o modelo do agente."""
    if agent_key not in _REGISTRY_BY_KEY:
        raise ValueError(f'Agente desconhecido: {agent_key}')

    row = AiModelSetting.query.filter_by(
        law_firm_id=law_firm_id, agent_key=agent_key).first()
    model_name = (model_name or '').strip()

    if not model_name:
        if row:
            db.session.delete(row)
        return

    if row:
        row.model_name = model_name
        row.updated_by_user_id = user_id
    else:
        db.session.add(AiModelSetting(
            law_firm_id=law_firm_id,
            agent_key=agent_key,
            model_name=model_name,
            updated_by_user_id=user_id,
        ))


def save_all(law_firm_id, selections, user_id=None):
    """Aplica um dict {agent_key: model_name} de uma vez (vazio = volta ao padrão)."""
    for entry in AGENT_REGISTRY:
        if entry['key'] in selections:
            set_model(law_firm_id, entry['key'], selections[entry['key']], user_id=user_id)
    db.session.commit()
