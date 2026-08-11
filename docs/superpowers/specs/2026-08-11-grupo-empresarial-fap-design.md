# Filtro "Grupo Empresarial" no módulo FAP

**Data:** 2026-08-11
**Status:** aprovado (abordagem A)

## Problema

O filtro "Grupo Empresarial" já existe no Disputes Center, mas o que ele chama de
"grupo" é **uma empresa outorgante** — um CNPJ raiz. O próprio código admite
(`app/blueprints/disputes_center.py:562-570`): *"cada empresa é gravada pela raiz
do CNPJ (8 dígitos) + nome. Por isso o filtro se comporta como o de CNPJ raiz"*.

O cliente trabalha com grupos empresariais reais: ADSERVI reúne ~15 CNPJs raiz
distintos (5 Estrelas, Fiel Vigilância, Liberdade Segurança, Tecnoguarda…). Hoje
é impossível ver o grupo inteiro numa consulta — é preciso filtrar raiz por raiz.

O cliente forneceu uma planilha com todas as empresas de que tem ou já teve
procuração de acesso ao FAP: **CNPJ Raiz Outorgante | Grupo | Razão Social**.
Regra dele: toda empresa tem correspondência na coluna Grupo — se não pertence a
um grupo, o valor é o próprio nome ou apelido. *"A coluna B é a chave para Grupo."*

## Decisões tomadas

| Questão | Decisão |
|---|---|
| Semântica do filtro existente | **Redefinir**: "Grupo Empresarial" passa a significar o grupo real, alcançando todas as raízes dele. Quem quer uma empresa só usa o filtro de CNPJ raiz, que continua ao lado. |
| Conflito planilha × edição manual | **Planilha vence, mas avisa antes**: a tela de conferência mostra o de-para e só grava após confirmação. |
| Alcance da 1ª entrega | Disputes Center (6 telas) + Painel FAP (Contestações, pending-list e 2 exports). |
| Onde o grupo mora | Tabela de mapeamento própria, chaveada por CNPJ raiz (abordagem A). |

### Por que não uma coluna em `FapCompany`

Duas das três sincronizações de empresas (`app/blueprints/fap_panel.py:280-284` e
`app/blueprints/disputes_center.py:4230-4236`) fazem `.delete()` em toda empresa
que não voltou da API, sem a proteção de FK que o cron tem. Procuração vencida →
empresa apagada → grupo junto. Além disso a planilha inclui empresas de que o
escritório *já teve* procuração, que nem existem mais em `fap_companies`.

Chavear por `cnpj_raiz`, sem FK, faz o mapeamento sobreviver a isso.

### Por que não uma entidade Grupo + associação (2 tabelas)

O grupo hoje é só um rótulo: não tem atributo próprio nem ciclo de vida. Duas
tabelas seriam a estrutura de uma entidade sem conteúdo. Se um dia o grupo ganhar
dados próprios (advogado responsável, etc.), migrar é um `INSERT ... SELECT DISTINCT`.

## Modelo de dados

```
fap_company_groups
  id                    PK
  law_firm_id           FK law_firms, NOT NULL     ← multi-tenant
  cnpj_raiz             String(8),  NOT NULL
  grupo_nome            String(255), NOT NULL      "ADSERVI"   (exibição)
  grupo_chave           String(255), NOT NULL      "ADSERVI"   (normalizado)
  origem                String(20),  NOT NULL      'planilha' | 'manual'
  razao_social_origem   String(500), NULL          o que a planilha dizia
  created_at, updated_at

  UNIQUE (law_firm_id, cnpj_raiz)          uma empresa pertence a um grupo só
  INDEX  (law_firm_id, grupo_chave)        grupo → raízes, a consulta do filtro
```

`grupo_chave` existe porque a coluna B é texto digitado: sem normalizar,
"ÁGUIA SISTEMAS" e "Águia Sistemas" viram dois grupos. Normalização = maiúsculas,
sem acentos, espaços colapsados. `grupo_nome` preserva o texto original.

Sem FK para `fap_companies`, pelo motivo acima.

## Serviço — `app/services/fap_group_service.py`

Fonte única. Inclui **extrair** `_build_fap_group_options` e `_apply_grupo_filter`
de dentro de `disputes_center` (hoje privados lá), já que o Painel FAP passa a
precisar dos mesmos — evitando a terceira cópia colada da mesma lógica.

```
normalize_group_key(nome)                  → chave normalizada
group_options(law_firm_id)                 → [{chave, nome, total_empresas}]
roots_for_group(law_firm_id, chave)        → ['11312620', '11312655', ...]
apply_group_filter(query, law_firm_id, chave, coluna, *, coluna_e_raiz)
assign_group(law_firm_id, raiz, nome, origem)
preview_import(law_firm_id, caminho)       → diff, sem gravar
apply_import(law_firm_id, caminho)         → grava
```

`apply_group_filter` é o único lugar que conhece os dois formatos de CNPJ do
banco: `cnpj_raiz` (8 dígitos limpos, indexado → `IN`) e `employer_cnpj`
(`'60.701.190/0001-04'` → `REPLACE`+`LIKE` com N raízes em `OR`, como já é hoje).
Nenhuma tela precisa saber dessa diferença.

## Importação da planilha

Fluxo em duas etapas, **sem tabelas de job/item**: o arquivo salvo em disco é a
fonte da verdade, e o confirm reprocessa o mesmo arquivo. Mais leve que o padrão
de `impugnacao_import_service` e suficiente, porque a planilha é pequena e o
processamento é instantâneo.

1. **Upload** — `.xlsx` (openpyxl, já é dependência direta), salvo em
   `uploads/fap_groups/{law_firm_id}/`.
2. **Conferência** — parse + diff contra o que já existe, mostrando:
   - **Novos**: CNPJ raiz que ainda não tinha grupo
   - **Alterados**: de-para explícito (`ADSERVI → ADSERVI GRUPO`), destacando os
     que hoje são `origem='manual'` — é o aviso que a decisão de conflito exige
   - **Inalterados**: contagem apenas
   - **Erros por linha**, com o número da linha da planilha
   - **Aviso**: CNPJ que não existe em `fap_companies` é aceito (é o caso das
     procurações vencidas), mas listado para conferência
3. **Confirmar** — aplica. Reimportar a mesma planilha resulta em zero alterações.

Cabeçalho localizado por varredura das primeiras linhas (padrão de
`impugnacao_import_service._find_header`), não por posição fixa. Colunas
reconhecidas por nome normalizado: `CNPJ Raiz Outorgante`, `Grupo`, `Razão Social`.

O CNPJ vem como `60.659.463/` na planilha — reduzir a dígitos e tomar os 8
primeiros.

### Erros e casos de borda

| Situação | Comportamento |
|---|---|
| CNPJ raiz ilegível (< 8 dígitos) | erro na linha, com número |
| Coluna Grupo vazia | erro na linha (a regra é que toda empresa tem grupo) |
| Mesmo CNPJ raiz em 2+ linhas com grupos diferentes | erro, apontando as linhas conflitantes |
| Mesmo CNPJ raiz repetido com o mesmo grupo | aceito, contado uma vez |
| CNPJ sem empresa correspondente | aceito, listado como aviso |
| Planilha corrompida / não-xlsx | erro amigável em PT-BR, sem stacktrace |

## Botão manual

Na tela **Empresas Sincronizadas (FAP)** (`/fap-panel/empresas`), que hoje é
100% read-only:

- Nova coluna **Grupo** na tabela, com `—` para quem não tem
- Botão de editar por linha → modal com campo de texto + `datalist` dos grupos
  já existentes (autocompletar evita criar "ADSERVI " duplicado por espaço)
- Botão **Importar planilha de grupos** no cabeçalho da tela
- Salvar grava `origem='manual'`

A tela ganha também filtro por grupo e um atalho "sem grupo", para achar quem
falta cadastrar depois de uma sincronização trazer empresas novas.

## Filtros nas telas

Em **todas** as barras de filtro, a lista de grupos termina com uma opção
**"— Sem grupo —"**, que recorta as empresas ainda não mapeadas. Sem ela, uma
sincronização que traga empresas novas as tornaria invisíveis a qualquer recorte
por grupo, e ninguém perceberia que falta cadastrar. Ela filtra pelo complemento:
CNPJs raiz que não aparecem em `fap_company_groups`.

**Disputes Center** (6 telas: list, vigencias, cats, payroll_masses,
employment_links, turnover_rates) — já têm o `<select>` e o wiring. Muda:
- as opções passam a vir de `group_options()` (grupos, não empresas)
- o valor do parâmetro passa a ser a **chave do grupo**, não a raiz de 8 dígitos
- `_apply_grupo_filter` delega ao serviço

**Painel FAP** — ganha o filtro:
- `_build_contestacoes_filters` (`fap_panel.py:1016`) — cobre `/contestacoes` e
  `/contestacoes/pending-list` de uma vez
- os **dois exports** (`fap_panel.py:1628` e `:1682`), que duplicam a lógica de
  filtro em vez de chamar o helper
- `has_active_filters`, e os dicts `_qs` e `_pqb` do template (senão o filtro se
  perde na paginação e nos links de export)
- `<select>` novo em `templates/fap_panel/contestacoes.html`, com Select2 como os
  vizinhos

**Fora de escopo, com motivo:**
- `fap_review` — não existe vínculo petição→empresa; exigiria criá-lo antes
- `benefits` (CaseBenefit) — o modelo não tem coluna de CNPJ
- MCP — adiado para uma segunda entrega

## Testes

Scripts standalone, no padrão do projeto (`tests/`, `scripts/tests/`):

1. **Parser** (função pura, sem Flask): CNPJ com máscara e com barra solta,
   cabeçalho em linha variável, linha vazia, grupo vazio, CNPJ duplicado
   conflitante, arquivo corrompido.
2. **Normalização de chave**: acento, caixa, espaços múltiplos → mesma chave.
3. **Import**: preview não grava; apply grava; reimportar dá zero alterações;
   o de-para marca corretamente o que era manual.
4. **Filtro**: grupo com N raízes devolve exatamente as linhas das N raízes, nas
   duas famílias de coluna (`cnpj_raiz` limpo e `employer_cnpj` pontuado).
5. **Multi-tenancy**: grupo de um escritório nunca aparece nem filtra no outro.

## Migration

`database/add_fap_company_groups_table.py`, no padrão dos `add_*`: idempotente,
dentro de `with app.app_context():`, verificando existência antes de criar. Sem
backfill — a tabela nasce vazia e é populada pela primeira importação.
