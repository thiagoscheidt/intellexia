# Busca no acervo do Diário Oficial

**Data:** 2026-08-10
**Estado:** design aprovado, pronto para plano de implementação
**Escopo:** Fase 2 do módulo Diário Oficial — busca por termo no acervo capturado.
**Depende de:** `2026-08-10-acervo-dou-inlabs-design.md` (fase 1, implementada)

---

## 1. Objetivo

Uma tela que responde "isso apareceu no Diário?" sobre todo o acervo capturado —
termos jurídicos, CNPJ de cliente, número de processo e nome de pessoa — com
refinamento por facetas e trecho destacado nos resultados.

### O que esta fase NÃO faz

- **Salvar busca**, **alertar por e-mail** e **varredura automática de
  clientes**. Isso é a fase 3 (watchlist): precisa de agendamento e de controle
  de "o que já foi visto", que é um problema diferente de indexar e consultar.
- Busca semântica (Qdrant). O corpus é jurídico-administrativo e as consultas
  são por termo e por identificador, não por similaridade conceitual.

---

## 2. Restrições medidas

### 2.1 Escala

Medido em 2026-08-10, com 6 dias capturados:

| | |
|---|---|
| Matérias | 20.682 |
| Texto total | 32,2 MB |
| Média por matéria | 1.630 caracteres |
| **Projeção — backfill de 4 meses** | **~293 mil matérias, 456 MB** |
| **Projeção — 1 ano** | **~862 mil matérias, 1,3 GB** |

Isso descarta busca em SQL: `LIKE '%termo%'` em 862 mil linhas de LONGTEXT é
varredura de tabela, e o full-text do MySQL não tem stemming de português.
Meilisearch já está no stack, no ar, e é o que o CLAUDE.md indica para "busca
por termos exatos".

### 2.2 Identificadores são quase metade do corpus

Amostra de 4.000 matérias:

- **1.245 (31%)** contêm CNPJ formatado (`19.630.496/0001-05`)
- **1.973 (49%)** contêm número de processo administrativo (`00000.000000/0000-00`)
- 56 (1,4%) contêm CNPJ só em dígitos

O Meilisearch tokeniza separando em `.`, `/` e `-`. Quem digitar
`19630496000105` **não acha nada**. Ver §4 — é o ponto que decide se a busca
serve.

---

## 3. Arquitetura

Segue o molde de `app/services/impugnacao_reference_search.py`, que já resolve
este mesmo problema para outro domínio.

```
app/services/dou_search_service.py     dono do índice Meilisearch "dou_articles"
  ├─ index_articles(articles)          chamado pela ingestão, após o commit
  ├─ search(...)                       consumido pela tela
  ├─ reindex_all(desde=None)           reconstrução a partir do banco
  └─ is_available()                    o Meilisearch responde?

app/blueprints/dou.py                  rota GET /dou/busca
templates/dou/busca.html               a tela
scripts/reindex_dou.py                 CLI de reindexação
```

**O banco é a fonte da verdade; o índice é descartável.** Se o Meilisearch
corromper ou a máquina mudar, `reindex_all()` reconstrói do MySQL. Daí duas
regras:

1. **Indexar nunca derruba a captura.** Falha ao indexar é registrada em log e
   o dia segue capturado — a fase 1 não pode passar a depender da fase 2.
2. **Buscar nunca derruba a tela.** Meilisearch fora do ar → a busca informa
   indisponibilidade; o acervo continua navegável.

---

## 4. Identificadores: extração e consulta

O ponto central do design.

### 4.1 Na indexação

De cada matéria, extrair por regex e **normalizar para só dígitos**:

- **CNPJ** — `\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}` → campo `cnpjs` (lista)
- **Processo administrativo** — `\d{5}\.\d{6}/\d{4}-\d{2}` → campo `processos` (lista)

A matéria com `CNPJ nº 19.630.496/0001-05` passa a carregar
`cnpjs: ["19630496000105"]`.

Também indexar CNPJs que já venham só em dígitos (`(?<!\d)\d{14}(?!\d)`), para
o campo cobrir as duas grafias.

### 4.2 Na consulta

Se o termo digitado, depois de remover tudo que não é dígito, tiver:

- **14 dígitos** → consulta o campo `cnpjs` (`19.630.496/0001-05` → `19630496000105`)
- **17 dígitos** → consulta o campo `processos` (`15414.630210/2026-80` → `15414630210202680`)
- caso contrário → busca normal nos campos de texto

Contagens conferidas contra o acervo real, não presumidas.

Nas duas primeiras, a **tolerância a erro de digitação fica desligada**: no
Meilisearch isso é configuração de índice, não de consulta — `update_typo_tolerance`
com `disable_on_attributes=['cnpjs', 'processos']`. Número aproximado é número
errado, e sem isso `19630496000105` casaria com CNPJs de outras empresas que
diferem por um dígito.

Assim o mesmo campo aceita `19.630.496/0001-05`, `19630496000105` e
`Fator Acidentário`, e cada um segue o caminho certo.

### 4.3 Atalho "buscar por cliente"

Um seletor ao lado do campo lista os clientes do escritório
(`Client.query.filter_by(law_firm_id=...)`). Escolher um preenche a busca com o
CNPJ normalizado e cai no caminho de §4.2.

**Nota de tenancy:** o acervo continua global e sem `law_firm_id` (ver §5.1 do
spec da fase 1). Só a *lista de clientes* do seletor filtra por escritório. A
busca em si não é filtrada por tenant — o DOU é público.

---

## 5. O documento indexado

Um documento por matéria, `id` = `DouArticle.id`.

| Papel | Campos | Nota |
|---|---|---|
| **Pesquisável** (ordem = peso) | `identifica`, `ementa`, `titulo`, `orgao_hierarquia`, `texto`, `cnpjs`, `processos` | a ordem da lista é a ordem de relevância no Meilisearch |
| **Filtrável** (viram faceta) | `pub_name`, `pub_date_ts`, `art_type`, `orgao_raiz`, `edicao` | |
| **Ordenável** | `pub_date_ts` | para "mais recentes primeiro" |
| **Exibição** | `pagina`, `pagina_num`, `pdf_page`, `data_br`, `edition_id` | não pesquisáveis |

Dois campos derivados, e por quê:

- **`orgao_raiz`** — o primeiro nível de `orgao_hierarquia`
  (`Ministério da Previdência Social`, de
  `Ministério da Previdência Social/INSS/...`). A hierarquia completa tem
  centenas de valores distintos e não vira faceta usável; a raiz tem dezenas e
  é o corte que se usa na prática.
- **`pub_date_ts`** — a data como timestamp inteiro. O Meilisearch filtra e
  ordena por faixa numérica, não por tipo data.

O campo `texto` é indexado inteiro. Indexar só ementa e título deixaria de fora
o nome de um cliente citado no corpo de uma licitação, que é justamente uma das
buscas pedidas.

---

## 6. A tela `/dou/busca`

```
┌─ Buscar no Diário Oficial ──────────────────────────────┐
│ [ fator acidentário de prevenção      ] [Cliente ▾] 🔍  │
└─────────────────────────────────────────────────────────┘
 3.240 matérias · 0,04 s              Ordenar: relevância ▾

┌─ REFINAR ──────┐ ┌─ RESULTADOS ────────────────────────┐
│ SEÇÃO          │ │ PORTARIA Nº 1.234 · 10/08 · S1 p.42 │
│ ☐ Seção 1  412 │ │ …aprovado o [Fator Acidentário de   │
│ ☐ Seção 3 2.1k │ │ Prevenção] para o exercício de…     │
│                │ │ Ministério da Previdência/INSS      │
│ ÓRGÃO          │ ├─────────────────────────────────────┤
│ ☐ Previd…  412 │ │ RESOLUÇÃO CNPS Nº 1.3… · 07/08 · S1 │
│ ☐ Fazenda   88 │ │ …metodologia do [FAP] será revista… │
│                │ │ Ministério da Previdência/CNPS      │
│ PERÍODO        │ └─────────────────────────────────────┘
│ [__] a [__]    │
└────────────────┘
```

- **Facetas com contagem** à esquerda: Seção, Órgão (raiz), Tipo de ato,
  Período. É o que transforma "3.240 resultados" em algo navegável.
- **Trecho destacado** em cada resultado (`attributes_to_crop` + tags de
  destaque), para decidir sem abrir.
- **Ordenação** por relevância (padrão) ou data decrescente.
- **Clique** leva à matéria (`dou.materia`), que já existe.
- **Estado inicial** (antes da primeira busca): convite a agir, com exemplos de
  consulta — não uma tabela vazia.
- **Estado vazio** (busca sem resultado): informa o que foi buscado e sugere
  remover filtros.
- **Meilisearch fora do ar**: aviso de indisponibilidade e link para o acervo.

Reaproveita o CSS do módulo (`static/css/dou.css`) e o `page_hero`, como as
demais telas.

---

## 7. Sincronia do índice

| Momento | O que acontece |
|---|---|
| Captura de uma `(data, seção)` | Após o commit, as matérias inseridas e atualizadas são indexadas em lote |
| Republicação | Mesma matéria, mesmo `id` → o documento é substituído, sem duplicar |
| Carga inicial / reconstrução | `uv run python scripts/reindex_dou.py [--desde YYYY-MM-DD]`, em lotes |
| Meilisearch indisponível na captura | Log de erro; o dia fica capturado e a matéria entra no índice na próxima reindexação |

A indexação em lote usa `add_documents` em blocos (1.000 documentos), no padrão
já usado pelo `knowledge_ingestion_agent`.

---

## 8. Tratamento de erro

| Situação | Comportamento |
|---|---|
| Meilisearch fora do ar durante a busca | Tela informa indisponibilidade e oferece o acervo; nunca 500 |
| Meilisearch fora do ar durante a captura | Log de erro; captura conclui normalmente |
| Índice inexistente na primeira busca | `get_or_create_index` cria vazio; a tela mostra "nenhum resultado" com aviso para rodar a reindexação |
| Termo vazio | Não busca; mostra o estado inicial |
| Filtro com valor inválido | Ignorado, sem erro — facetas são geradas a partir do próprio índice |

---

## 9. Testes

- **`tests/test_dou_search.py`** — o mais valioso e o que não precisa de rede:
  extração e normalização de CNPJ e processo a partir de texto real, e a
  decisão de roteamento da consulta (14 dígitos → `cnpjs`; 20 → `processos`;
  resto → texto). Função pura, testável sem Meilisearch.
- **Indexação e busca ponta a ponta** — contra o Meilisearch local, num índice
  de teste com nome próprio (`dou_articles_test`), apagado ao final. **Nunca
  usar o índice de produção**: já houve um teste neste módulo que apagou dados
  reais por usar a mesma chave que o dado verdadeiro.
- **Rotas** — `/dou/busca` responde 200, exige login, e degrada quando o
  Meilisearch não responde.

---

## 10. Variáveis de ambiente novas

```bash
DOU_MEILI_INDEX=dou_articles     # nome do índice (padrão: dou_articles)
```

`MEILISEARCH_HOST` e `MEILISEARCH_API_KEY` já existem e são reutilizados.

---

## 11. Decisões registradas

| Decisão | Escolha | Razão |
|---|---|---|
| Motor de busca | Meilisearch | Já no stack e no ar; SQL não escala para 862 mil linhas de LONGTEXT |
| Identificadores | Campos normalizados só com dígitos | O tokenizador quebra CNPJ na pontuação; sem isso, 31% do acervo fica inalcançável por CNPJ |
| Tolerância a erro | Desligada para CNPJ e processo | Número aproximado é número errado |
| Refinamento | Facetas com contagem | Com ~293 mil matérias, filtro sem contagem é filtrar às cegas |
| Faceta de órgão | Só a raiz da hierarquia | A hierarquia completa tem centenas de valores e não vira faceta usável |
| Clientes | Atalho que preenche o CNPJ | Resolve a consulta mais frequente em dois cliques; varredura automática é fase 3 |
| Fonte da verdade | MySQL; índice é descartável | Permite reconstruir e torna a falha do índice não-crítica |
| Escopo | Sem salvar busca nem alertar | Fase 3 — exige agendamento e controle de "já visto" |
