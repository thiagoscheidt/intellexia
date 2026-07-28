# Passo "Documentos" no wizard de geração — confirmação dos insumos

**Data:** 2026-07-28 · **Módulo:** `process_panel` (wizard de documentos gerados)

## Objetivo

Tornar visível e confirmável o conjunto de documentos que alimenta a geração da
impugnação. Hoje três fontes entram no agente: (1) contestação da União (PDF +
resumo estruturado — obrigatórios), (2) anexos ativos e descritos dos benefícios
selecionados (automáticos), (3) peças-modelo recuperadas do Qdrant pelo retriever
em camadas (invisíveis ao usuário). O usuário passa a ver as três e a confirmar
anexos e peças-modelo antes de gerar.

## Decisões (aprovadas pelo usuário)

1. **Granularidade por peça inteira**: checkbox por peça-modelo; confirmada →
   todos os seus trechos ficam elegíveis. Sem seleção por trecho.
2. **Escopo "tudo visível"**: contestação informativa (sem desmarcar), anexos por
   benefício com checkbox, peças-modelo com checkbox. Tudo pré-marcado.
3. **Wizard vira 4 passos**: Tipo → Benefícios → **Documentos** → Revisão. O
   passo Documentos roda o preview ao ser aberto (depende das teses do passo 2).
4. **Auditoria**: os ids confirmados ficam gravados na versão gerada.

## Modelo de dados

Coluna nova em `judicial_process_generated_document_versions`:

- `confirmed_documents_json` (JSON, nullable) —
  `{"reference_ids": [int], "attachment_ids": [int]}`.
  `NULL` = fluxo legado (sem restrição — comportamento atual). Lista de
  `reference_ids` vazia = gerar **sem** bloco de referências e **sem**
  enriquecimento jurisprudencial.

Migration aditiva standalone no padrão do projeto
(`database/add_generated_document_confirmed_documents.py`).

## Preview (backend)

Serviço novo `app/services/generated_document_preview_service.py`:

`build_documents_preview(process, law_firm_id, document_type, parsed_selections)`
→ dict:

- `contestacao`: `{aplicavel: bool, pdf_encontrado: bool, pdf_nome: str|None,
  resumo_encontrado: bool}` — via `_resolve_latest_contestation_pdf_path` e
  `_resolve_latest_contestation_summary_payload` (helpers existentes do
  blueprint, movidos/importados sem duplicação). Aplicável só para
  `impugnacao_contestacao`.
- `beneficios`: lista `{benefit_id, nb, segurado, anexos: [{id, arquivo,
  titulo}]}` — mesmo filtro do worker (ativo + descrição preenchida).
- `referencias` (só para `impugnacao_contestacao`): peças candidatas agregadas
  dos trechos retornados pelo retriever em camadas — para cada tese distinta das
  seleções e para os 4 planos de seção, com caps generosos. Por peça:
  `{reference_id, titulo, trf_region, orgao_julgador, judge_name,
  quality_score, camada ('juiz'|'vara'|'trf'|'geral'), teses: [keys],
  trechos: int}`. Metadados autoritativos vêm do banco
  (`ImpugnacaoReferenceModel`, filtrado por law_firm) — o payload do Qdrant só
  define o conjunto e a camada.
- Falha de Qdrant/embeddings → `referencias: null` + flag `referencias_erro`
  (a tela avisa e deixa seguir sem referências).

Rota nova `POST /process-panel/<id>/documentos-gerados/preview-documentos`
(JSON: `{document_type, selections: ["benefit_id:thesis_id", ...]}`), com
validação de tenant/processo igual à rota de criação.

Para a agregação, `_hit_to_item` do retriever passa a expor também
`reference_id`, `judge_name_norm`, `orgao_julgador_norm` e
`orgao_julgador_origem_norm` (a camada é derivada comparando com o contexto).

## Geração restrita ao confirmado

- `fetch_style_references(..., allowed_reference_ids=None)`: quando lista não
  vazia, `_build_filter` adiciona `FieldCondition(key='reference_id',
  match=MatchAny(any=[...]))`. Lista vazia → retorna `[]` sem consultar.
- `AgentGeneratedDocument.dispatch(...)/generate_impugnacao_contestacao(...)` e
  `_build_style_references_block(...)` ganham `allowed_reference_ids=None` e
  repassam ao retriever; lista vazia → bloco de referências vira `""`.
- `ImpugnacaoEnrichmentAgent.enrich(..., allowed_reference_ids=None)` idem;
  no worker, lista vazia → enriquecimento é pulado.
- Worker `_run_generated_document_generation` lê `version.confirmed_documents_json`:
  `attachment_ids` presentes → anexos filtrados por id; `reference_ids`
  presentes → repassados a dispatch/enrichment. `NULL` → comportamento atual.
- Rota `generated_document_create`: lê `confirmed_reference_ids[]` e
  `confirmed_attachment_ids[]` do form **somente** quando o form traz
  `documents_confirmed=1` (evita que um POST legado/sem JS restrinja tudo);
  valida ints e grava na version antes do spawn.

## Wizard (template `generated_document_new.html`)

- Indicadores passam a 4 (Tipo, Benefícios, Documentos, Revisão); painel antigo
  de Revisão vira `panel-4`; `goToStep` atualizado (validações: 1→2 tipo, 2→3
  benefícios; ao entrar no 3 dispara o preview; ao entrar no 4 `buildSummary`).
- Painel Documentos: estado de carregamento (spinner), erro amigável com
  "tentar novamente", e três blocos: card da contestação (ok/alerta se faltar
  PDF ou resumo — só para impugnação), anexos agrupados por benefício
  (checkboxes `confirmed_attachment_ids[]`, pré-marcados), peças-modelo
  (checkboxes `confirmed_reference_ids[]`, pré-marcados, com badge da camada —
  "Mesmo juiz", "Mesma vara", "Mesmo TRF", "Acervo geral" —, teses, ★ e nº de
  trechos). Hidden `documents_confirmed=1` no form.
- Nenhuma peça marcada → aviso âmbar no próprio passo ("será gerado sem
  referências de estilo"), mas deixa prosseguir.
- Revisão ganha uma linha-resumo "Documentos confirmados: X peças-modelo ·
  Y anexos" com link "Alterar" para o passo 3.
- Preview re-executa se o usuário voltar ao passo 2 e mudar a seleção
  (invalidação simples: refetch sempre que entrar no passo 3 com seleção
  diferente da última consultada).

## Fora de escopo

- Seleção por trecho; mudanças no chunking/retrieval além do filtro por id;
  edição de anexos/peças dentro do wizard (links para as telas próprias);
  outros tipos de documento continuam sem bloco de referências (o passo mostra
  contestação n/a e anexos normalmente).

## Tratamento de erros

- Preview: Qdrant/embeddings fora → seção de referências mostra aviso e o passo
  segue utilizável (equivale a gerar sem referências, como o fluxo atual em
  falha). Contestação ausente → alerta vermelho no card (a geração falharia).
- Worker: `confirmed_documents_json` malformado → tratar como `NULL` (log).

## Testes

- `scripts/tests/test_impugnacao_layered_retrieval.py`: casos novos com
  `allowed_reference_ids` (filtra; lista vazia → `[]`).
- `scripts/tests/test_generated_document_preview.py`: agregação por peça e
  cálculo de camada com retriever stubado (sem serviços externos).
- Verificação manual: wizard completo em rs-dev após restart.
