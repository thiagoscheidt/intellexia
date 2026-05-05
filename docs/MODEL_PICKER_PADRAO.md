# Model Picker Padrão (Reutilizável)

Este guia define o padrão oficial para seleção de modelo de IA no IntellexIA.

Objetivo: evitar duplicação de HTML/CSS/JS, manter UX consistente e facilitar evolução futura em um único ponto.

---

## Arquivos do Componente

- Macro Jinja: `templates/partials/model_picker_modal.html`
- CSS compartilhado: `static/css/model-picker-modal.css`
- JS compartilhado: `static/js/model-picker-modal.js`

---

## Regra de Uso

Sempre que uma tela precisar selecionar modelo de IA:

1. Importar e renderizar o macro `model_picker_modal(...)`.
2. Incluir o CSS compartilhado.
3. Incluir o JS compartilhado.
4. Instanciar `new window.ModelPickerModal({...})` no JavaScript da página.

Nao duplicar o modal diretamente no template da feature.
Nao copiar a logica de busca/filtro/renderizacao para scripts locais.

---

## Exemplo Minimo (Template)

```jinja2
{% from "partials/model_picker_modal.html" import model_picker_modal %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/model-picker-modal.css') }}">
{% endblock %}

{% block content %}
{{ model_picker_modal(modal_id='modelPickerModal', title='Selecionar modelo de IA') }}
{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/model-picker-modal.js') }}"></script>
<script>
  const picker = new window.ModelPickerModal({
    modalId: 'modelPickerModal',
    models: availableModels,
    defaultModelId,
    getSelectedModelId: () => selectedModelInput.value || '',
    onSelect: (modelId, modelMeta) => {
      selectedModelInput.value = modelId || '';
      renderSelectedModel(modelMeta);
    },
  });
</script>
{% endblock %}
```

---

## Contrato de Dados

Cada item em `models` deve seguir, no minimo, o formato abaixo:

```json
{
  "id": "openai/gpt-4o-mini",
  "name": "GPT-4o mini",
  "description": "...",
  "context_length": 128000,
  "prompt_price": 0.000001,
  "completion_price": 0.000002,
  "release_timestamp": 1736380800
}
```

Observacoes:

- `release_timestamp` pode vir em segundos ou milissegundos; o componente normaliza automaticamente.
- Quando `id` e vazio, a opcao "Padrao do ambiente" e exibida no topo.

---

## Comportamentos Embutidos no Componente

- Busca por nome, id e descricao.
- Filtro por provider (OpenAI, Anthropic, Google, etc.) por heuristica de namespace.
- Ordenacao por data de lancamento (mais recente primeiro).
- Badge de lancamento com destaque visual.
- Callback de selecao via `onSelect(modelId, modelMeta)`.

---

## Regras de Evolucao

1. Melhorias visuais/funcionais devem ser feitas no componente compartilhado.
2. Alteracoes de contrato (campos esperados) devem atualizar este documento.
3. Evitar ajustes locais em cada tela para nao fragmentar UX.
4. Se uma tela precisar comportamento especial, preferir extensao por callback antes de fork do componente.

---

## Checklist para Novas Telas

- [ ] Importou macro `model_picker_modal`.
- [ ] Incluiu `static/css/model-picker-modal.css`.
- [ ] Incluiu `static/js/model-picker-modal.js`.
- [ ] Instanciou `window.ModelPickerModal` com callbacks.
- [ ] Nao duplicou HTML do modal na tela.
- [ ] Nao duplicou logica de filtros/ordenacao no script da tela.

---

## Tela de Referencia

Implementacao de referencia atual:

- `templates/disputes_center/classifier_prompt_settings.html`
