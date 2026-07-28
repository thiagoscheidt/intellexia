# Redesign das Referências de Impugnação — busca por tribunal/vara/juiz e seções

**Data:** 2026-07-28
**Módulos afetados:** `impugnacao_references`, `process_panel` (geração), `app/agents/legal_drafting/`

## Objetivo

Fazer a geração de impugnação priorizar peças-modelo do mesmo contexto do processo
(mesmo juiz > mesma vara > mesmo TRF > geral) e tornar as seções de tese das peças
pesquisáveis — tanto na geração quanto na tela de referências.

## Decisões de design (tomadas com o usuário)

1. **Metadados por IA**: tribunal/vara/juiz/nº CNJ de cada peça-modelo são extraídos
   do próprio documento pelo agente de metadados, com edição manual na tela.
   Não há vínculo obrigatório com um `JudicialProcess`.
2. **Seções livres por peça**: os títulos de seção detectados são gravados por
   documento (`sections_json`) e indexados no Qdrant. **Não** haverá catálogo
   canônico de títulos de seção no `JudicialLegalThesis`.
3. **Boost em camadas** na busca de referências: filtro obrigatório por
   tese/`section_kind`, priorização cumulativa juiz > vara > TRF, nunca retorna
   vazio (fallback para acervo geral).
4. **Meilisearch só na busca da tela**: índice dedicado para busca textual do
   advogado. O retrieval da geração continua 100% Qdrant.

---

## Bloco 1 — Correções de base (pré-requisito)

Bugs que impedem o funcionamento do que já existe:

1. `app/agents/legal_drafting/agent_generated_document.py:1197` lê
   `process.court.name` — atributo inexistente em `Court` (campos reais:
   `tribunal`, `secao_judiciaria`, `subsecao_judiciaria`, `orgao_julgador`).
   Corrigir para usar os campos reais / property `JudicialProcess.tribunal_name`.
2. `app/blueprints/process_panel.py:3448` passa `getattr(process, 'trf_region', None)`
   ao `ImpugnacaoEnrichmentAgent` — `JudicialProcess` não tem esse campo, então o
   boost regional nunca recebe TRF. Corrigir derivando o TRF do número CNJ via
   `app/utils/cnj.tribunal_sigla_from_cnj` (helper novo `trf_region_from_process`
   centralizado, reutilizado nos dois pontos).
3. **Semântica do `should` no Qdrant**: em filtro Qdrant, `should` é condição
   "ao menos uma deve casar", não boost de score. Verificar o comportamento atual
   de `_build_filter` em `impugnacao_reference_retriever.py:60-107` (o `trf_region`
   em `should` provavelmente age como filtro rígido ou é ignorado). A correção
   definitiva é o Bloco 4 (camadas no cliente); este item documenta e remove o
   uso incorreto de `should`.

## Bloco 2 — Metadados das peças-modelo via IA

**Agente** (`impugnacao_reference_metadata_agent.py`): ampliar o schema Pydantic
para extrair também:

- `process_number` — número CNJ do processo de origem da peça (quando presente);
- `orgao_julgador` — vara/órgão julgador citado na peça;
- `judge_name` — magistrado, quando citado/assinado (campo frequentemente ausente:
  o agente deve retornar `null` sem inventar).

Derivação de TRF: com `process_number` extraído, o `trf_region` passa a ser
derivado do CNJ (fonte determinística); a extração textual + regex atual vira
fallback quando não há número CNJ.

**Modelo** (`ImpugnacaoReferenceModel`): novas colunas

| Coluna | Tipo | Observação |
|---|---|---|
| `process_number` | String(30) | número CNJ normalizado |
| `orgao_julgador` | String(255) | vara/órgão julgador |
| `judge_name` | String(255) | pode ser NULL |
| `sections_json` | JSON | ver Bloco 3 |

**Migration**: script standalone `database/add_impugnacao_reference_context_fields.py`
seguindo o checklist do projeto (app_context, idempotência por verificação de
coluna existente, mensagens claras).

**Tela**: campos exibidos e editáveis no detalhe (`detail.html`) via POST de
edição de metadados; listagem ganha colunas Tribunal e Vara. A edição de
`process_number` re-deriva o `trf_region`.

## Bloco 3 — Seções por peça

**`sections_json`** no `ImpugnacaoReferenceModel`, preenchido na ingestão:

```json
[
  {
    "titulo": "6. AUXÍLIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94) – APURAÇÃO...",
    "titulo_normalizado": "AUXILIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94) – APURACAO...",
    "section_kind": "merit_by_thesis",
    "teses": ["apuracao_indice_custo"],
    "qtd_chunks": 4
  }
]
```

Normalização do título: mesma regra já usada no gerador
(`_normalize_section_label_for_prompt` — remove numeração inicial) + caixa alta
sem acentos, extraída para helper compartilhado (evitar duplicação).

**Payload Qdrant dos chunks** (`impugnacao_reference_ingestor.py`): adicionar
`section_normalized`, `orgao_julgador`, `judge_name`, `process_number` ao payload
já existente. Reindexação (fluxo existente) recalcula tudo.

**Tela de detalhe**: bloco "Seções detectadas" renderizando `sections_json`
(título, kind, teses, nº de chunks) para auditoria da segmentação.

## Bloco 4 — Retrieval em camadas na geração

**Contexto do processo** montado na geração (helper único, reutilizado pelo
gerador e pelo enrichment):

- teses do caso (já existe);
- TRF: derivado do número CNJ do processo;
- vara: snapshot DataJud (`orgao_julgador` normalizado) → fallback
  `Court.orgao_julgador` / `JudicialProcess.section`;
- juiz: `JudicialProcess.judge_name` (pode estar vazio — camada é pulada).

**Retriever** (`impugnacao_reference_retriever.py`): para cada consulta
(tese/`section_kind` do `kind_plan` atual), executar até 4 buscas Qdrant com
filtros progressivamente mais amplos e cotas por camada:

1. mesmo `judge_name` (match normalizado, camada pulada se processo sem juiz);
2. mesmo `orgao_julgador` (match normalizado);
3. mesmo `trf_region`;
4. sem filtro de contexto (geral).

Merge no cliente com deduplicação por `qdrant_point_id`, respeitando ordem de
camada; dentro da camada, ordena por score semântico com `quality_score` como
desempate. Caps atuais (`MAX_CHUNKS`, `MAX_CHARS`, orçamentos por seção/tese)
preservados. Curto-circuito: se as camadas específicas já preencherem a cota,
não consulta as amplas.

Comparação de vara/juiz usa normalização (caixa alta, sem acentos, colapso de
espaços) — não igualdade crua de strings.

**Enrichment** (`ImpugnacaoEnrichmentAgent` / jurisprudência): mesma priorização
em camadas, usando o mesmo helper de contexto.

## Bloco 5 — Tela (escopo contido)

- **Listagem**: colunas Tribunal (TRF) e Vara; filtros por TRF, vara e tese;
  campo de busca textual (Bloco 6). Contagens movidas do template para a rota.
- **Detalhe**: metadados editáveis (Bloco 2) + bloco de seções (Bloco 3).
- **Upload**: inalterado (arquivo + notas; IA infere o resto).
- Sem telas novas.

## Bloco 6 — Meilisearch na busca da tela

Índice dedicado `impugnacao_references` (nome via env, padrão do projeto):

- **Documentos**: um por chunk — `id` (= chunk id), `law_firm_id`,
  `reference_id`, `reference_title`, `trf_region`, `orgao_julgador`,
  `judge_name`, `process_number`, `section`, `section_normalized`,
  `section_kind`, `thesis_catalog_id`, `status`, `text` (full_text).
- **Filterable**: `law_firm_id`, `status`, `trf_region`, `section_kind`,
  `thesis_catalog_id`, `reference_id`. **Searchable**: `text`, `section`,
  `reference_title`, `judge_name`, `orgao_julgador`, `process_number`.
- **Filtro de tenant obrigatório** em toda query (`law_firm_id`), como nas
  demais integrações.
- **Pontos de sincronização** (os mesmos onde o Qdrant já é tocado hoje):
  ingestão, reindexação, arquivar/reativar (atualiza `status`), exclusão.
  Falha no Meilisearch não pode abortar a ingestão (degradação graciosa com
  log, padrão do projeto) — o Qdrant é a fonte crítica.
- **Uso**: endpoint de busca da listagem consulta Meilisearch e agrega
  resultados por peça (título + trechos com highlight).
- A geração **não** consulta Meilisearch.

## Fora de escopo

- Catálogo canônico de títulos de seção no `JudicialLegalThesis`.
- Extração de juiz via DataJud (a API pública não expõe magistrado).
- Mudanças no chunking (permanece por página/heading com overlap).
- Mudanças no fluxo de upload.
- Backfill automático de metadados das peças já cadastradas — a reindexação
  manual peça a peça (botão existente) passa a preencher os campos novos;
  script de backfill em lote pode ser adicionado depois se necessário.

## Tratamento de erros

- Agente de metadados falhou → peça é criada sem os campos novos (comportamento
  atual preservado), editável na tela.
- Processo sem juiz/vara/TRF → camadas correspondentes são puladas; geração
  funciona como hoje (acervo geral).
- Meilisearch fora do ar → busca da tela mostra aviso e cai para filtros SQL;
  ingestão segue (log de erro).

## Testes

Padrão do projeto (scripts standalone, sem framework):

- `scripts/tests/test_impugnacao_reference_metadata.py` — extração de metadados
  sobre peça de exemplo (CNJ → TRF, vara, juiz nulo quando ausente).
- `scripts/tests/test_impugnacao_layered_retrieval.py` — monta acervo sintético
  no Qdrant e verifica ordem de camadas, dedup e fallback para geral.
- `scripts/tests/test_impugnacao_meilisearch_sync.py` — ingestão/arquivamento/
  exclusão refletidos no índice; filtro de tenant.
- Teste manual guiado: reindexar peça existente e conferir `sections_json` e
  campos novos na tela.
