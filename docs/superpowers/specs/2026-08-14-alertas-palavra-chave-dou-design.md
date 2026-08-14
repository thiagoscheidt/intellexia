# Alertas por palavra-chave no Diário Oficial

**Data:** 2026-08-14
**Módulo:** `dou`
**Status:** aprovado

## Problema

O alerta de DOU hoje só dispara por **CNPJ de cliente cadastrado**. Fica de
fora justamente o que muda o jogo antes de virar processo: portaria que altera
a metodologia do FAP, pauta de julgamento do CRPS, revisão do NTEP, consulta
pública. Nada disso escreve o CNPJ de ninguém.

A demanda é uma tela onde o escritório configura o que quer vigiar por texto,
órgão ou seção.

## A dificuldade real não é casar palavra — é o volume

Casar texto é trivial: o acervo já está indexado no Meilisearch. O que decide
o desenho é impedir que a primeira regra criada vire uma mangueira de
incêndio. Se isso acontecer, a pessoa para de olhar a tela de alertas — e o
escritório perde junto o alerta de CNPJ, que hoje funciona.

É a mesma regra que o `CLAUDE.md` já fixou para os badges do header:
**pendência, nunca volume.**

### Medições (acervo de 7 dias: 21.038 matérias, 34,5 MB de texto, ~3.005/dia)

Alertas por dia que cada termo geraria:

| termo | alertas/dia |
|---|---|
| `CRPS` | 0,9 |
| `Fator Acidentário de Prevenção` (frase) | 1,0 |
| `FAP` | 1,7 |
| `aposentadoria` | 68 |
| `licitação` | 660 |

Para comparar: **a carteira inteira de clientes gera hoje ~6 alertas/dia**
(41 em 7 dias). Uma única regra mal formulada supera isso em 100×.

## Por que motor próprio, e não Meilisearch

O Meilisearch busca com tolerância a erro e trata termos como prefixo. Isso é
correto para uma caixa de busca e desastroso para um alerta:

| termo | Meilisearch | casamento por fronteira de palavra |
|---|---|---|
| `FAP` | **92** matérias | **12** |
| `Fator Acidentário de Prevenção` | **748** | **7** |

As 80 diferenças do `FAP` foram inspecionadas uma a uma: **FAPED (82×),
FAPEG (34×), FAPESP (11×), FAPEC, FAPEMIG, FAPERJ…** — fundações de amparo à
pesquisa. Nenhuma tem relação com Fator Acidentário de Prevenção.

O `748 vs 7` é o modo OU: sem aspas, o índice casa "Fator" e "Prevenção"
isoladamente. **107× as mesmas palavras.**

Decisão: **motor próprio, em memória**, com dois efeitos colaterais bons —
mais preciso, e o alerta deixa de depender do índice. Mantém o invariante já
documentado: *o índice serve à tela de busca; o alerta não pode depender dele.*

Descartada também a variante híbrida (Meili no teste, memória na colheita):
duas implementações do mesmo casamento divergem, e aí o teste vira mentira —
destruindo justamente a peça que resolve o problema do volume.

## Decisões tomadas com o usuário

| Pergunta | Decisão |
|---|---|
| O que vigiar | Temas jurídicos **+** nomes fora da carteira **+** órgão/publicador — os três na mesma regra, com campos opcionais |
| Dono da regra | **Do escritório, com dono registrado**; filtro "minhas regras" |
| Regra ruidosa | **Avisa e deixa salvar.** Não bloqueia, não limita colheita (buraco silencioso é pior que ruído) |

## Arquitetura

### Modelo de dados

**Tabela nova `dou_alert_rules`** (tem `law_firm_id` — a regra é do escritório,
diferente do acervo, que é catálogo público compartilhado):

| coluna | tipo | nota |
|---|---|---|
| `law_firm_id` | FK, index | tenant |
| `nome` | String(120) | rótulo na tela e no chip do alerta |
| `termo` | String(200), nulo | nulo = regra só de órgão/seção |
| `modo` | String(10) | `frase` \| `palavras` |
| `secoes` | String(60), nulo | CSV `DO1,DO3`; nulo = todas |
| `orgao_raiz` | String(255), nulo | recorte pela raiz da hierarquia |
| `ativo` | Boolean, index | desligar sem perder histórico |
| `created_by_id` | FK users | o dono registrado |
| `last_match_at` | DateTime | responde "essa regra não pega nada há 40 dias" |

Invariante validado no serviço e no form: **pelo menos um entre `termo` e
`orgao_raiz`**. Regra sem nenhum dos dois casaria a edição inteira.

**Tabela filha `dou_alert_rule_hits`** — `(alert_id, rule_id, law_firm_id)`,
unique `(alert_id, rule_id)`, ambas as FK com `ON DELETE CASCADE`.

Filha, e não coluna no alerta: **a unidade do alerta continua sendo a
matéria.** Uma portaria pode disparar três regras; por par (regra, matéria)
ela viraria três linhas na tela e três no e-mail. É a mesma lição que já rendeu
41 alertas em vez de 1.333 (32×) no alerta de CNPJ.

**Em `dou_client_alerts`, duas mudanças:**

- `+ tem_regra` Boolean, index — denormalizado pelo mesmo motivo que
  `tem_resultado` e `pub_date` já são: filtro e badge sem abrir a filha.
- `match_type` passa a **nullable**. Hoje é `nullable=False, default='exato'`,
  e um alerta só de palavra-chave não tem casamento de CNPJ nenhum.

A tabela **não é renomeada**, embora passe a guardar alerta que não é de
cliente: renomear em MySQL de produção, com FK apontando para ela, mais modelo,
serviço, testes e a filha `dou_client_alert_matches`, é risco sem ganho
visível. Fica documentado no docstring.

### Motor — `app/services/dou_rule_service.py` (novo)

Módulo à parte porque `dou_alert_service` já tem ~750 linhas e é dono do
*registro* de alerta (criar, listar, triar, digest). Casamento de regra é outro
assunto, e o módulo novo **não sabe o que é alerta**: recebe regras e matérias,
devolve `{article_id: [rule_id]}`. Quem grava continua sendo um só.

```python
normalizar(texto)          # NFKD, sem combinantes, minúsculo
sonda(termo)               # maior corrida sem acento — a peneira SQL
compilar(regra)            # frase → \btermo\b ; palavras → todas, com fronteira
corpus_do_artigo(artigo)   # identifica + ementa + texto
casar(regras, artigos)     # → {article_id: [rule_id]}
testar(regra, dias)        # → total, por_dia, exemplos[] — mesmo `casar`
```

**Não existe modo OU.** É ele o 107×. Quem quiser OU cria duas regras — e aí vê
o volume de cada uma separado, que é melhor de qualquer forma.

**Não existe "procurar só no título".** Foi medido: `titulo` está vazio em
**100%** do acervo e `ementa` em **98%** — o DOU põe o cabeçalho em
`identifica` e todo o resto em `texto`. O corpus é `identifica + ementa +
texto`, sem knob.

Seção e órgão-raiz recortam **no SQL, antes** de carregar texto.

### A peneira SQL

Varrer 7 dias em Python custa 9,1 s de carga + 3,0 s de normalização = ~12 s.
Inaceitável num botão que a pessoa aperta várias vezes ajustando a regra.

Solução: um `LIKE` no banco usando a **maior corrida de caracteres sem acento**
do termo, e a regex exata só no que sobrou.

- `licitação` → sonda `licita`
- `Fator Acidentário de Prevenção` → sonda `fator acident`
- `contribuição previdenciária` → sonda `o previdenci`

Esse pedaço está **literalmente** no texto, então o `LIKE` é superconjunto
seguro: todo texto que contém `\bfap\b` contém `fap`. A peneira nunca muda a
resposta — é só o que ela evita carregar.

Vale igual no SQLite do dev e no MySQL da produção, **sem depender de
collation** (o MySQL ignoraria acento sozinho; o SQLite não, e a sonda sem
acento remove a diferença).

Sonda com menos de 3 caracteres úteis → varredura completa (raro; termos assim
são ruins de qualquer jeito). Regra **sem termo** (só órgão/seção) não tem
sonda nem regex: o recorte no SQL já é a resposta inteira, e nenhum texto
precisa ser carregado.

Medido:

| termo | peneira | casam | tempo |
|---|---|---|---|
| `Fator Acidentário de Prevenção` | 7 | 7 | 0,53 s |
| `CRPS` | 7 | 6 | 0,72 s |
| `FAP` | 135 | 12 | 1,39 s |
| `licitação` | 6.324 | 4.626 | **1,91 s** |

Pior caso **1,9 s**. Cabe num botão.

### Gancho na ingestão

Em `dou_ingestion_service.ingest_date`, **depois do commit da edição**, ao lado
do `gerar_para_edicao` do CNPJ: mesmo lugar, mesma regra de tratar a própria
falha — alerta é derivado da captura e nunca dono dela.

Custo: **~1,3 s para o dia inteiro + ~0,1 s por regra ativa.**

### Tela de regras — `/dou/regras`

Rotas: lista, `nova`, `<id>/editar`, `<id>/excluir`, `<id>/ativar`,
`POST /dou/regras/testar` (JSON). Link no cabeçalho de `/dou/alertas`.

Permissão: módulo `dou` para ver e criar; **editar/excluir só o dono ou
admin** — é o que dá sentido a "dono registrado".

A lista mostra por regra: nome, o que casa (chips de termo/modo/seção/órgão),
dono, alertas nos últimos 30 dias, último casamento, toggle de ativo.

O formulário tem o **teste antes de salvar**, que é a peça central:

```
Nome     [ Julgamentos do CRPS                       ]
Termo    [ Conselho de Recursos da Previdência Social]
Modo     (•) frase exata   ( ) todas as palavras
Seções   [DO1] [DO2] [DO3]  ▸ vazio = todas
Órgão    [ Ministério da Previdência Social       ▾ ]
                                      [ Testar regra ]
─────────────────────────────────────────────────────
● 6 matérias em 7 dias — cerca de 1 por dia
  14/08 DO1 p.42 · PORTARIA Nº 1.234, DE 13 DE AGOSTO
  13/08 DO3 p.11 · EDITAL DE PAUTA DE JULGAMENTO
  …                                         [ Salvar ]
```

Faixa de veredito, ancorada no volume real da carteira (~6/dia), não em número
inventado:

| por dia | cor | mensagem |
|---|---|---|
| `= 0` | cinza | "não pegaria nada nos últimos 7 dias — confira o termo" |
| `0 < n ≤ 5` | verde | — |
| `5 < n ≤ 20` | âmbar | "volume alto — considere restringir por seção ou órgão" |
| `n > 20` | vermelho | "essa regra sozinha traria N× o que a carteira inteira traz" |

Os dois cortes são uma constante só no serviço, fácil de recalibrar quando
houver mais acervo. Salvar segue habilitado sempre (decisão do usuário: avisar,
não bloquear); acima do vermelho pede confirmação explícita.

**Retroatividade:** ao salvar, gera os alertas dos **últimos 7 dias** — a mesma
janela do teste, para o que foi visto ser o que aparece. Vale também quando a
pessoa salva **sem** ter testado: a janela é do desenho, não do clique. O
acervo inteiro fica num botão à parte na tela da regra, também mostrando o
número antes.

### Onde os alertas aparecem — `/dou/alertas` (a mesma tela)

Uma portaria que cita o CNPJ do cliente **e** casa a regra "FAP" é **um**
alerta com dois motivos; em telas separadas apareceria duas vezes.

Mudanças:

- filtro novo de **origem**: todos / cliente / palavra-chave
- filtro por **regra** específica (só as que já casaram)
- na linha, chips de regra ao lado dos chips de cliente; **o vermelho continua
  exclusivo do FAP**
- "Ver trecho" reaproveita `trechos_do_alerta` inteiro — muda só **o que se
  grifa**: hoje o CNPJ, agora o termo. `sanitizar_html` e `grifar_html` seguem
  iguais
- o contador do header (`dou_alertas_nao_lidos`) já soma não-lidos e passa a
  incluir os novos sem tocar em nada

### E-mail

Mesmo tipo `dou_digest`, **um e-mail por manhã, não dois**. Bloco novo
"Palavras-chave" abaixo do de empresas: uma linha por regra, contagem e até 3
exemplos, mesma janela de 3 edições publicadas e mesmo selo NOVO.

Se não houver desfecho FAP mas houver regra com novidade, o assunto passa a
levar a regra — a lógica de "o assunto leva o desfecho, não a contagem"
continua valendo.

## Tratamento de erro

- **Regra inválida** (sem termo e sem órgão, termo só de pontuação): recusada
  no serviço e no form, com mensagem.
- **Falha do motor durante a ingestão**: capturada e logada, com rollback só do
  bloco de alertas — a captura da edição já commitada não é desfeita. Mesmo
  padrão do gancho de CNPJ e do índice.
- **Teste que estoura tempo**: a peneira limita o pior caso a ~2 s; ainda
  assim o endpoint devolve JSON de erro legível em vez de 500.
- **Regra excluída**: `ON DELETE CASCADE` remove os hits. O alerta sobrevive se
  ainda tiver cliente ou outra regra; se ficar sem motivo nenhum, é removido
  na mesma transação.

## Testes — `tests/test_dou_regras.py`

Cada item tranca uma descoberta da medição, não uma linha de código:

1. **`FAP` não casa `FAPESP`/`FAPED`/`FAPEG`** — os 80 falsos positivos
2. **não existe modo OU** — `Fator Acidentário de Prevenção` casa 7, nunca 748
3. **a peneira é superconjunto** — para cada termo, o conjunto do `LIKE` contém
   o da regex; é a propriedade que autoriza a otimização
4. acento e caixa são indiferentes (`ACIDENTÁRIO` = `acidentario`)
5. uma matéria + duas regras = **um** alerta com dois hits
6. alerta só de regra tem `match_type` nulo e `clients_count` 0
7. matéria que casa cliente **e** regra continua sendo um alerta só
8. recorte por seção e por órgão-raiz
9. reprocessar não duplica hits nem apaga a triagem (`status`)
10. regra de um escritório não vaza para outro
11. regra sem termo e sem órgão é recusada
12. regra inativa não colhe

## Entregáveis

- `app/models.py` — `DouAlertRule`, `DouAlertRuleHit`, `+ tem_regra`,
  `match_type` nullable
- `app/services/dou_rule_service.py` — novo
- `app/services/dou_alert_service.py` — grava os hits, filtros de origem/regra,
  grifo por termo, bloco do digest
- `app/services/dou_ingestion_service.py` — gancho
- `app/blueprints/dou.py` — rotas de regra + filtros novos
- `templates/dou/regras.html`, `regra_form.html`; ajustes em `alertas.html`,
  `_alerta_trecho.html`, `emails/dou_digest.html`
- `static/css/dou.css` — chips de regra, faixa de veredito
- `database/add_dou_alert_rules_tables.py`,
  `database/alter_dou_alerts_for_rules.py`
- `scripts/gerar_alertas_dou.py` — flag de backfill de regras
- `tests/test_dou_regras.py`; ajustes em `test_dou_alertas.py`,
  `test_dou_routes.py`
- `CLAUDE.md` — seção de alertas por palavra-chave

## Fora de escopo

- Alerta por usuário (a decisão foi regra do escritório)
- Bloqueio ou teto de colheita para regra ruidosa
- Sugestão automática de termo por IA
- Alerta por CPF ou por número de processo (o motor serve, mas não foi pedido)
