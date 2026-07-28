# Cobertura de referências por tese

**Data:** 2026-07-28 · **Módulos:** `legal_drafting` (retriever + gerador), `process_panel` (worker + preview + wizard)

## Requisito (do usuário)

A unidade de cobertura é a **tese**, não a peça:

1. Toda tese dos benefícios selecionados precisa de modelo de referência, para a
   argumentação sair "encorpada".
2. A busca prioriza **local** (juiz → vara → tribunal), porque a tese que vinga
   muda conforme quem julga.
3. Buscar **mais de um exemplo por tese** quando existir — exemplos são **peças
   distintas**, não trechos da mesma peça.
4. Não achou no local → desce para outras fontes; a busca não para na primeira
   camada vazia.
5. Tese sem nenhum modelo no acervo → **avisar nominalmente**: "não foi
   encontrado modelo de referência para a tese X". Nunca falhar em silêncio.

## Falhas atuais (verificadas no código)

- **Teses descartadas em silêncio**: `_build_style_references_block` gasta o teto
  global (22.000 chars) por ordem de chegada — 4 seções × 2.200 e depois 4.500
  por tese — e faz `break` ao estourar. Com blocos cheios cabem ~2-3 teses; as
  demais ficam sem referência e nada é reportado.
- **Sem garantia de peças distintas**: o plano por tese aceita até 6 trechos que
  podem vir todos da mesma peça.
- **Sem aviso de tese descoberta** em qualquer lugar da interface.

## Design

### 1. Camada compartilhada

`chunk_match_layer(chunk, context) -> 'juiz'|'vara'|'trf'|'geral'` e
`LAYER_ORDER`/`LAYER_LABELS` migram para `impugnacao_process_context.py` (fonte
única). O preview passa a importar de lá em vez de manter cópia privada.

### 2. Retriever: parar por peças distintas

`fetch_style_references(..., min_distinct_references: Optional[int] = None)`.
Quando informado, o laço de camadas **continua descendo** mesmo após cumprir a
cota do kind, aceitando apenas trechos de `reference_id` ainda não visto, até
juntar N peças distintas ou esgotar as camadas. Teto rígido
`top_k + min_distinct_references` por kind, e os caps globais seguem valendo.

### 3. Módulo de cobertura

`app/agents/legal_drafting/impugnacao_thesis_coverage.py`:

```
search_thesis_references(retriever, *, law_firm_id, thesis_label, thesis_key,
                         query_text, context, kind_plan, max_chunks, max_chars,
                         allowed_reference_ids, min_distinct=2)
    -> (chunks, coverage)
```

`coverage` (contrato consumido por gerador, worker, preview e tela):

```json
{
  "tese": "Apuração do Índice de Custo",
  "tese_key": "apuracao_do_indice_de_custo",
  "exemplos": [{"reference_id": 12, "camada": "vara"},
               {"reference_id": 7,  "camada": "trf"}],
  "camada": "vara",
  "qtd_exemplos": 2,
  "sem_modelo": false
}
```

`exemplos` ordenado pela melhor camada; `camada` = melhor camada entre eles;
`sem_modelo=true` quando a busca não retornou nenhum trecho.

### 4. Gerador: cota por tese antes de qualquer extra

Substitui a alocação por ordem de chegada:

```
MIN_THESIS_CHARS = 1200
n              = nº de teses
sections_reserve = min(4 * max_section_chars, 40% de max_total_chars)
thesis_pool      = max_total_chars - sections_reserve
per_thesis       = clamp(thesis_pool // n, MIN_THESIS_CHARS, max_thesis_chars)
sections_pool    = max_total_chars - (per_thesis * n)
per_section      = min(max_section_chars, sections_pool // 4)
```

Os blocos por tese são montados **primeiro** e **todos** (sem `break`); as seções
consomem o que sobrar (puladas quando `per_section` fica irrisório). A ordem no
prompt final permanece seções → teses. A cobertura de todas as teses fica em
`self.last_reference_coverage`, no padrão dos demais agentes
(`last_sections_summary` do ingestor).

### 5. Worker: aviso nas notas internas

Após `dispatch`, teses com `sem_modelo=true` viram itens de checklist nas
observações internas da versão:

```
- [ ] Não foi encontrado modelo de referência para a tese "X" — redigida sem peça-modelo do acervo; revisar fundamentação e citações.
```

A expressão "sem peça-modelo" é palavra-chave de alerta no renderizador de notas
da tela de detalhe, então o item já sai destacado em vermelho.

### 6. Preview e wizard

O preview ganha `cobertura_teses` (mesma estrutura), calculada com o mesmo
módulo. No passo Documentos, bloco "Cobertura por tese" acima das peças:

- verde: `2 exemplos · mesma vara`
- âmbar: `1 exemplo · acervo geral`
- vermelho: `Nenhum modelo de referência no acervo`

A cobertura é **recalculada ao vivo** conforme o usuário marca/desmarca peças —
desmarcar a única peça que cobre uma tese muda a linha para vermelho na hora,
porque a geração usará apenas as peças confirmadas.

## Fora de escopo

Peça-espelho composta (usa este mesmo mapa de cobertura, mas é feature
separada); mudanças no chunking; validadores de citação/vazamento.

## Testes

- Retriever: `min_distinct_references` desce camadas e traz peças distintas;
  respeita teto; sem o parâmetro o comportamento é o de hoje.
- Cobertura: agregação de exemplos, melhor camada, `sem_modelo`.
- Cota: com N teses, todas recebem bloco; nenhuma é descartada.
