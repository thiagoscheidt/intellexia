# Melhorias nas Configurações do Revisor FAP (prompts e referências)

**Data:** 2026-07-21
**Módulo:** `fap_review` — Configurações/versionamento
**Origem:** itens 1, 2, 3, 5, 6 e 8 da avaliação aprovados pelo usuário (4 e 7 ficaram de fora).

## 1. Numeração de versões sem duplicar

Nos POSTs de `edit_prompt` e `edit_reference`, o número da nova versão passa a ser `max(version_number) + 1` do tipo (via `func.max`), não `versão_da_página + 1` — elimina versões duplicadas ao salvar duas vezes ou salvar a partir de versão antiga.

## 2. Fluxo salvar/ativar coerente

- POST aceita `{content, change_note, activate}`. Com `activate=true`, a nova versão já nasce ativa (desativando as demais na mesma transação, com auditoria de criação e ativação).
- Resposta traz `redirect_url`; o JS navega para a página da **nova** versão (o botão "Usar Esta Versão" da página antiga deixa de ser armadilha).
- O auto-redirect de GET "versão inativa → ativa" é **removido** dos editores por id (ele quebrava o link "abrir versão" da sidebar); em seu lugar, banner visual "Você está vendo uma versão inativa". A navegação por tipo (`edit_*_by_type`) continua abrindo a ativa.
- Botões: **Salvar Rascunho** (outline) e **Salvar e Ativar** (primário).

## 3. Diff entre versões

- Rotas GET `/settings/prompts/<id>/diff/<other_id>` e `/settings/references/<id>/diff/<other_id>` (admin-only, mesmo escritório e mesmo tipo), retornando JSON com as linhas de `difflib.unified_diff`.
- Guarda: conteúdo acima de 2 MB responde erro amigável (diff de referência gigante não trava o worker).
- UI: botão "comparar" em cada versão da sidebar → modal com diff colorido (adições verdes, remoções vermelhas, contexto neutro). JS/CSS locais, sem libs novas.

## 4. (item 5 da avaliação) Versões usadas em cada execução

- Coluna `used_versions_json` (Text) em `fap_review_executions`.
- Helper no serviço `collect_active_versions(law_firm_id)` → `{tipo: {id, version}}` para os 3 prompts do revisor e as 3 referências — fonte única para tela e MCP.
- Blueprint `_execute_reviewer_agent` grava na execução ao rodar; `record_text_review` (MCP) ganha parâmetro opcional com o mesmo dado.
- Exibição: linha compacta na tela de resultado da revisão ("Executada com: revisor_identity v3 · manual_fap v2 …").

## 5. (item 6) Descrição da mudança (`change_note`)

- Coluna `change_note` (String 255) em `fap_review_prompt_versions` e `fap_review_reference_versions`.
- Campo de texto no editor ("O que mudou nesta versão?" — opcional); exibido na sidebar de versões e incluído na descrição do audit log.

## 6. (item 8) Importar referência de arquivo

- No editor de referências: botão "Importar de arquivo" (`.md`, `.txt`, `.docx`, máx. 10 MB) → POST multipart `/settings/references/import-file` extrai o texto (`_extract_text_from_document`, pipeline existente) e devolve JSON `{content}`; o JS preenche o editor para o admin revisar e salvar como nova versão. O upload em si não grava nada.

## Migration

Uma migration standalone `database/add_fap_review_versioning_metadata.py` (idempotente): `change_note` nas duas tabelas de versão + `used_versions_json` em `fap_review_executions`.

## Fora de escopo

Dry-run de prompt (item 4), diff da proposta de treinamento (item 7).

## Verificação

Script standalone novo `tests/test_fap_review_settings_versioning.py` cobrindo: numeração max+1 (dois saves seguidos), salvar-e-ativar, diff endpoint, change_note persistida e `used_versions_json` no registro via serviço. Screenshots dos editores via Playwright (porta 5051).
