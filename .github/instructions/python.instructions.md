---
applyTo: "**/*.py"
---

# Instrucoes Python (Flask, SQLAlchemy, Agentes)

## Arquitetura

- Novas features web devem usar blueprints em `app/blueprints/`.
- Evite adicionar novas rotas no codigo legado `app/routes.py`.
- Ao criar modulo novo, registrar import/export de blueprint e registrar em `main.py`.

## Banco e models

- Preferir `db.Model` em `app/models.py` seguindo convencoes existentes.
- Toda entidade de negocio por escritorio deve conter `law_firm_id`.
- Queries de negocio devem filtrar por `law_firm_id`.
- Para mudancas de schema, criar script em `database/`.

Checklist minimo para migration script:

1. Arquivo em `database/` com nome descritivo (`add_*`, `alter_*`, `remove_*`).
2. Execucao via `with app.app_context()`.
3. Verificacao previa de existencia (coluna/tabela/indice) para idempotencia.
4. Mensagens claras de sucesso e erro.

## IA e agentes

- Preferir saida estruturada (Pydantic) para agentes.
- Aplicar fallback quando houver erro de execucao do agente.
- Reusar servicos existentes em `app/services/` antes de criar novo helper.
- Registrar uso de token/custo com servicos padrao quando fizer chamada LLM.
- No modulo FAP Review, manter revisor com perfil deterministico (temperatura baixa, geralmente 0.0).

## Seguranca e sessao

- Respeitar middlewares e decorators de autenticacao/autorizacao existentes.
- APIs devem retornar erro apropriado (ex.: 401) quando nao autenticado.
- Evitar expor dados de outro escritorio (tenant isolation estrito).

## Estilo de codigo

- Manter coerencia com padrao atual do arquivo.
- Evitar novas dependencias sem necessidade clara.
- Priorizar funcoes pequenas e reutilizaveis em vez de duplicacao.
