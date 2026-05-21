# Copilot Instructions for IntellexIA

## Contexto do projeto

IntellexIA e uma plataforma juridica para automacao de casos trabalhistas e previdenciarios, com foco em FAP.

- Backend: Flask + Flask-SQLAlchemy
- Banco: SQLite (dev) e MySQL (prod)
- IA: LangChain + OpenAI/OpenRouter, com agentes especializados
- Busca: Qdrant (semantica) e Meilisearch (termos exatos)
- Frontend: Jinja2 + AdminLTE 4 + Bootstrap 5
- Dependencias Python: usar `uv` (nao usar `pip` diretamente)

## Fontes de verdade no codigo

- Entrada da aplicacao e registro de blueprints: `main.py`
- Blueprints ativos: `app/blueprints/`
- Modelos SQLAlchemy: `app/models.py`
- Middlewares de sessao/autenticacao: `app/middlewares.py`

Arquivos legados existem e nao devem ser referencia primaria para novas features:

- `app/routes.py` (legado, manter alteracoes minimas)
- `app/routes_backup.py`, `old/`, `agent_document_generator.py`

## Regras obrigatorias de implementacao

1. Multi-tenant e obrigatorio.
Toda listagem, busca e operacao de negocio deve filtrar por `law_firm_id`.

2. Timezone da aplicacao e Sao Paulo.
Para datas no backend, preferir utilitarios existentes e padroes da aplicacao.

3. Novas rotas devem entrar em blueprint modular.
Registrar no pacote `app/blueprints` e no `main.py`.

4. Chamadas de IA devem seguir padrao de resiliencia.
Preferir saida estruturada (Pydantic) e fallback em caso de falha.

5. Rastrear custo/tokens em fluxos de IA quando aplicavel.
Reutilizar servicos ja existentes ao inves de logica duplicada.

6. Migrations nao usam Alembic.
Criar script standalone em `database/` com verificacao idempotente antes de alterar schema.

7. Nao duplicar componente de seletor de modelo.
Usar os artefatos compartilhados:
- `templates/partials/model_picker_modal.html`
- `static/css/model-picker-modal.css`
- `static/js/model-picker-modal.js`

## Comandos e fluxo de trabalho

- Instalar dependencias: `uv sync`
- Rodar app (dev): `uv run python main.py`
- Rodar com flask: `uv run flask run`
- Rodar script de migration: `uv run python database/<script>.py`
- Rodar scripts de teste: `uv run python tests/<script>.py`

## Boas praticas de alteracao

- Fazer mudancas pequenas, focadas e consistentes com o estilo local.
- Evitar refatoracao ampla sem necessidade funcional.
- Preservar compatibilidade com fluxo atual baseado em blueprints.
- Em duvida entre doc antiga e codigo atual, prevalece o codigo atual.
