---
applyTo: "templates/**/*.html,static/**/*.js,static/**/*.css"
---

# Instrucoes Frontend (Jinja2 + AdminLTE + Bootstrap)

## Base visual e estrutura

- Seguir padrao de templates existente com `layout/base.html`.
- Reusar componentes compartilhados em `templates/partials/`.
- Manter compatibilidade com Bootstrap 5 e classes utilitarias ja usadas no projeto.

## Componentes compartilhados obrigatorios

- Para escolha de modelo de IA, usar componente padrao:
  - `templates/partials/model_picker_modal.html`
  - `static/css/model-picker-modal.css`
  - `static/js/model-picker-modal.js`
- Nao duplicar modal de model picker por pagina.

## Convencoes de telas

- Quando a tela ja usa `page_hero`, manter esse padrao.
- Preservar breadcrumbs, mensagens flash e estados de carregamento/erro.
- Garantir responsividade (desktop e mobile) sem quebrar layout existente.

## JavaScript

- Evitar frameworks novos; priorizar JS nativo no padrao atual.
- Reutilizar helpers existentes antes de criar utilitarios paralelos.
- Tratar estados vazios e falhas de API com mensagens claras para usuario.

## CSS

- Preferir estilos locais da pagina apenas quando necessario.
- Evitar colisao com estilos globais e manter nomenclatura clara.
- Preservar consistencia visual entre modulos (cards, badges, formularios, tabelas).
