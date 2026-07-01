# Múltiplas decisões de contestação por benefício (FAP)

**Data:** 2026-07-01
**Status:** Aprovado (design) — pronto para plano de implementação
**Área:** FAP / disputes_center / ingestão de relatórios de julgamento

---

## 1. Contexto e problema

Os relatórios de julgamento de contestação do FAP (PDFs baixados do portal, com milhares de
páginas) listam o **mesmo benefício (NB) em mais de um lugar** do documento, em páginas distantes.
Investigando um caso real (NB `6125797817`, contestação 28660, páginas ~1943 e 3183), confirmamos
que **não são o mesmo bloco repetido nem artefato de parsing**: são **análises jurídicas distintas**
do mesmo benefício, porque um único evento gera **múltiplos "insumos"** no cálculo do FAP
(ex.: a **CAT** e o **"Nexo Técnico Previdenciário sem CAT vinculada"**). A empresa contesta cada
insumo, e o relatório traz uma análise separada para cada um — com **justificativa, parecer e
consulta DATAPREV diferentes**, ainda que na mesma instância (ambas "1ª instância").

Hoje o modelo `Benefit` tem **campos planos** para decisão: `first_instance_status`,
`first_instance_justification`, `first_instance_opinion`, `second_instance_*` — ou seja, **espaço
para uma única análise por instância**. Durante a ingestão (`_upsert_benefits_from_report`), a
deduplicação por `(benefit_number, vigência)` mantém corretamente **1 benefício = 1 linha**, mas
**descarta a segunda análise**: a segunda ocorrência do mesmo NB cai em `should_apply_update = False`
(mesmo relatório → mesma data de referência) e não é gravada. No caso analisado, isso equivale a
1789 blocos extraídos → 971 benefícios, com ~815 "duplicados" que na verdade eram **análises
distintas jogadas fora**.

### Decisão de produto

- **Manter 1 benefício = 1 linha** (identidade correta — mesma pessoa/NB/vigência).
- **Passar a salvar cada análise de contestação separadamente**, exibi-las no modal "Decisões do
  Benefício" e **classificar cada uma** no classificador de tópicos FAP (os tópicos do benefício
  passam a ser a **união** dos tópicos das análises).

---

## 2. Objetivo e escopo

**Objetivo:** preservar, exibir e classificar todas as análises de contestação de um benefício,
sem inflar a identidade do benefício.

**Fora de escopo (decisão do usuário):**
- **Testes automatizados** e **reprocessamento de validação** — o usuário vai **apagar a base e
  reprocessar os scripts do zero**; validação será manual pós-processamento.
- **Migração de dados existentes** — produção ainda não tem benefícios; a base é recriada por
  truncate/`recreate_database.py`, então a tabela nova nasce do model.
- Captura de campos hoje não persistidos (`Total Pago`, `Data de Óbito`, `RMI` na decisão) —
  evolução futura, não faz parte deste escopo.

---

## 3. Modelo de dados

### Nova tabela `BenefitContestationDecision` (`benefit_contestation_decisions`)

Uma linha por **análise/insumo** de contestação.

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | Integer PK | |
| `law_firm_id` | FK → `law_firms.id`, NOT NULL, index | Tenant — filtro obrigatório |
| `benefit_id` | FK → `benefits.id`, NOT NULL, index | `cascade delete` |
| `report_id` | FK → `fap_contestation_judgment_reports.id`, nullable, index | Origem |
| `instancia` | SmallInteger, NOT NULL | `1` ou `2` |
| `sequence` | Integer, NOT NULL, default 0 | Ordem das sub-abas dentro de `(benefit, instancia)` |
| `status` | String(30), index | Normalizado (Deferido/Indeferido/…) |
| `status_raw` | String(255) | Texto original do status |
| `justification` | Text | Justificativa da empresa |
| `opinion` | Text | Parecer do órgão |
| `source_page` | Integer, nullable | Página do PDF (best-effort, do "Página N de M") |
| `fingerprint` | String(64), NOT NULL | `sha256(instancia + justificativa_norm + parecer_norm)` |
| `fap_contestation_topics_json` | Text, nullable | Tópicos classificados **desta** análise (lista JSON) |
| `created_at` / `updated_at` | DateTime | Auditoria |

**Constraints/índices:**
- `UNIQUE (law_firm_id, benefit_id, fingerprint)` — chave de idempotência.
- Índice `(law_firm_id, benefit_id, instancia, sequence)` para leitura do modal.

**Idempotência:** o `fingerprint` identifica uma análise pelo conteúdo (instância + justificativa +
parecer normalizados). No reprocesso/`--force_reimport`, análise igual → **UPDATE**; análise nova →
**nova linha**. Elimina a re-duplicação.

### Alterações em `Benefit`

- Nova relação: `contestation_decisions = db.relationship('BenefitContestationDecision',
  back_populates='benefit', cascade='all, delete-orphan', order_by='BenefitContestationDecision.instancia, BenefitContestationDecision.sequence')`.
- **Campos planos mantidos** (`first/second_instance_*`) como **espelho da análise principal**
  (a `sequence = 0` de cada instância, do relatório mais recente). Garante compatibilidade com o
  modal atual, o classificador e o disputes_center — a tabela filha é a fonte completa; os campos
  planos são um resumo da principal.
- `fap_contestation_topics_json` passa a ser a **união** dos tópicos de todas as decisões do
  benefício (dedup preservando ordem). O campo legado `fap_contestation_topic` continua sendo o
  primeiro tópico.

---

## 4. Ingestão (`_upsert_benefits_from_report`)

Para **cada bloco extraído** do mesmo NB:

1. **Identidade (inalterado):** acha/cria o `Benefit` por `(benefit_number, vigência)`.
2. **Decisões (novo):** o `parse_block` já devolve `first_instance_*` e `second_instance_*` do
   bloco. Para cada instância **presente** no bloco (tem justificativa OU status OU parecer),
   montar uma decisão:
   - Campos: `instancia`, `status`, `status_raw`, `justification`, `opinion`, `source_page`
     (extraído do texto "Página N de M" do bloco), `report_id`, `fingerprint`.
   - **Upsert por `(law_firm_id, benefit_id, fingerprint)`**: existe → UPDATE (`report_id`,
     `source_page`, `updated_at`); não existe → INSERT com `sequence` = próximo dentro de
     `(benefit, instancia)`.
3. **Espelho:** atualizar os campos planos `first/second_instance_*` do `Benefit` com a análise
   **principal** (`sequence = 0`) de cada instância, respeitando `should_apply_update` (só o
   espelho usa a regra de data de referência).
4. **Histórico:** `BenefitFapSourceHistory` permanece igual (1 linha por relatório que tocou o
   benefício).

**Detalhamento (log):** o diagnóstico atual (`blocos/distintos/duplicados/…`) passa a reportar
`decisões criadas` / `decisões atualizadas` em vez de tratar as repetições como "duplicados
descartados".

---

## 5. Classificação (uma por análise)

- `classify_benefits_contestation_topics` passa a **iterar as decisões** (em vez dos campos planos):
  monta o texto de cada decisão, chama o `FAPContestationClassifierAgent`, e grava os tópicos em
  `decision.fap_contestation_topics_json`.
- `Benefit.fap_contestation_topics_json` = **união** dos tópicos de todas as suas decisões (dedup,
  ordem preservada); `fap_contestation_topic` = primeiro tópico.
- `_build_benefit_classification_text` ganha uma variante que recebe uma **decisão** (reaproveitando
  `_clean_classification_text_block` e o cabeçalho de contexto já existentes).
- Concorrência/limiar (`temperature=0.0`, `MIN_CONFIDENCE=0.80`, `parallel_workers`) inalterados.

---

## 6. API + Modal (frontend — `disputes_center`)

Hoje o modal recebe as decisões via `data-*` no botão da tabela (justificativas embutidas em todas
as ~971 linhas) — pesado e não escala para N decisões.

- **Novo endpoint:** `GET /disputes-center/benefits/<benefit_id>/decisions`
  - Filtra por `law_firm_id` da sessão (multi-tenant).
  - Retorna `{ benefit_number, insured_name, decisions: [ {instancia, sequence, status,
    status_raw, justification, opinion, source_page, topics} ] }`.
- **Botão da tabela:** deixa de carregar justificativas nos `data-*`; carrega só `data-benefit-id`
  (+ número/nome para o cabeçalho). **Ganho colateral:** tira KBs de texto do DOM de cada linha →
  tabela mais leve.
- **Modal (`benefitDecisionModal`):** mantém as colunas **1ª / 2ª instância**. Ao abrir, o JS faz
  **fetch** das decisões e agrupa por `instancia`:
  - 1 decisão na instância → exibe direto (comportamento atual).
  - N decisões → **sub-abas** (`nav-tabs`) dentro da coluna (`Análise 1`, `Análise 2`… + status;
    página no rodapé).
  - Estados de **carregando / vazio / erro** tratados; **fallback** para os campos planos (espelho)
    se o fetch falhar (degradação graciosa, padrão do projeto).
- Reutilizar componentes/estilos existentes do modal; JS nativo no padrão atual (sem novos frameworks).

---

## 7. Migration

- Script standalone `database/add_benefit_contestation_decisions_table.py` no padrão do projeto
  (dentro de `with app.app_context()`, idempotente via inspector, cria tabela + índices + unique).
- **Opcional no fluxo atual:** como o usuário recria a base do zero (`recreate_database.py` / criação
  automática em dev a partir dos models), a tabela nasce do model. O script fica como conveniência
  para ambientes que não recriam.

---

## 8. Componentes afetados (resumo)

| Componente | Mudança |
|---|---|
| `app/models.py` | Nova classe `BenefitContestationDecision`; relação em `Benefit` |
| `app/services/fap_contestation_judgment_report_service.py` | Ingestão cria/atualiza decisões; espelho; classificação por decisão; detalhamento do log |
| `app/blueprints/disputes_center.py` | Novo endpoint `GET .../benefits/<id>/decisions` |
| `templates/disputes_center/list.html` | Botão passa a usar `data-benefit-id`; modal com fetch + sub-abas |
| `database/add_benefit_contestation_decisions_table.py` | Migration standalone (opcional) |

---

## 9. Riscos e mitigação

- **Pareamento 1ª↔2ª de um mesmo insumo é ambíguo no PDF** → não pareamos: agrupamos apenas por
  `instancia`; cada análise é uma sub-aba independente. Sem suposição frágil.
- **Fingerprint instável** (variação de espaço/pontuação) geraria duplicatas → normalização de texto
  reaproveitando `_text_fingerprint`/`_clean_classification_text_block`.
- **Compatibilidade** → campos planos mantidos como espelho; nada que lê o `Benefit` hoje quebra.
