# API do IntellexIA + Biblioteca de IA — desenho

Data: 22/10/2026 · Situação: proposta, aguardando aprovação

## Por que

O escritório questionou a lógica de o IntellexIA construir uma tela para cada
necessidade, se os próprios usuários já montam o que precisam com IA (Claude
Code, Claude.ai). A resposta proposta é entregar **blocos de construção** em
vez de telas:

1. **API do IntellexIA**: a base do escritório (benefícios, contestações,
   segurados, base de conhecimento, jurisprudência, processos) acessível por
   token pessoal, para o usuário pedir ao Claude Code "monta uma tela que
   filtra os B91 indeferidos da Vale" e ele consumir a API.
2. **Biblioteca de IA**: cada pessoa guarda os próprios prompts e pode
   compartilhá-los com o escritório. Os prompts aparecem como **comandos
   prontos** no conector MCP, então um prompt bem escrito vira um "agente"
   reutilizável sem precisar de deploy nosso.

Os dois se completam: a API dá os dados para quem programa (ou pede ao Claude
Code), e a biblioteca dá o roteiro para quem só conversa.

O escritório não trouxe casos concretos. Os exemplos citados foram filtrar
benefícios, pesquisar na base de conhecimento, pesquisar por CPF e revelar o
nome do segurado: "quase as mesmas coisas que tem no MCP".

## Objetivos

- Token de API pessoal, criado e revogado pelo próprio usuário, numa tela e
  também pelo MCP.
- API REST só de **leitura** (fora a revelação de nome, que já existe no MCP),
  com os **mesmos dados e as mesmas regras** das ferramentas MCP.
- Documentação da API sempre igual ao código: gerada do mesmo registro que
  monta as rotas, legível por gente (página) e por IA (OpenAPI JSON).
- Biblioteca de IA com tela própria, prompts pessoais e do escritório, e
  uso direto no Claude como comando pronto.

## Fora do escopo (agora)

- Escrita pela API (criar processo, alterar benefício, disparar sincronização).
- Webhooks e notificações por API.
- Exportação Excel pela API (o usuário monta a partir do JSON).
- Agentes rodando no servidor ou agendados (fica para a conversa dos
  "comandos como agentes").

## O que não pode acontecer (anti-objetivos)

- **A API virar porta lateral.** Nada que a tela ou o MCP escondem de um
  usuário pode sair pela API: mesmo filtro de escritório, mesmos módulos, mesma
  regra de admin.
- **Duas implementações divergindo.** Se a API reescrever a query do MCP, em
  três meses os números não batem. A API chama os **mesmos handlers** do MCP.
- **Token vazado sem controle.** Token guardado em texto puro, sem validade,
  sem registro de uso ou que sobrevive ao usuário desativado.
- **Consulta paga em massa.** A API não pode virar um jeito de revelar 26 mil
  nomes num loop.

## Parte 1 — API

### Onde vive

No próprio app Flask (Gunicorn), blueprint novo `public_api`, prefixo
`/api/v1`. Sem serviço novo, sem porta nova, mesmo domínio
(`app_public_url()` + `/api/v1`).

O `check_session` (`app/middlewares.py`) hoje redireciona tudo sem sessão.
Requisição do blueprint `public_api` passa direto para a autenticação por
token (checar `request.blueprint`, não uma lista de endpoints). **A API nunca
aceita o cookie de sessão**: só `Authorization: Bearer`. Isso evita que uma
página qualquer aberta no navegador logado chame a API (CSRF).

### Token

| Item | Decisão |
|---|---|
| Formato | `itx_` + 40 caracteres aleatórios (`secrets.token_urlsafe(30)`) |
| Guardado como | SHA-256 do token. O token em si é mostrado **uma vez**, na criação |
| Identificação na tela | nome dado pelo usuário + os 4 últimos caracteres |
| Validade | escolhida na criação: 30, 90 (padrão), 180 dias ou sem validade |
| Dono | um usuário; o escritório vem do usuário, nunca de parâmetro |
| Permissões | as **atuais** do usuário, conferidas a cada requisição (usuário desativado, módulo retirado ou papel rebaixado valem na hora). Diferente do MCP, que guarda um retrato das permissões no token |
| Revogação | pelo dono ou por admin do escritório; usuário apagado leva os tokens (`ON DELETE CASCADE`) |
| Registro | `last_used_at` e `last_used_ip` no token |

Tabela nova `api_tokens` (migration `database/add_api_tokens_table.py`):
`id, law_firm_id, user_id (CASCADE), name, token_hash (unique), last4,
expires_at (UTC, nullable), revoked_at, revoked_by_id (SET NULL),
created_at, last_used_at, last_used_ip`.

Serviço `app/services/api_token_service.py`, fonte única da tela, do MCP e da
autenticação: `criar(user, nome, dias)` → `(registro, token_em_claro)`,
`listar(user)`, `listar_do_escritorio(law_firm_id)` (admin), `revogar(...)`,
`autenticar(token_em_claro)` → usuário ou erro.

**Quem pode ter token**: módulo de permissão novo **`api`** ("API e
integrações"), liberado por padrão para todos os papéis; o admin pode retirar
por usuário na Administração de Usuários. Ter o módulo `api` não dá
acesso a dado nenhum sozinho: cada rota ainda exige o módulo da tela
correspondente.

### Formato das respostas

- JSON com as **mesmas chaves em português** que o MCP devolve (é o mesmo
  handler). Paginação igual: `limite`/`deslocamento` na query e o envelope com
  `total_encontrado`, `tem_mais`, `proximo_deslocamento`.
- Erros sempre `{"erro": "mensagem para gente"}` com o status certo:
  - 401 token ausente, inválido, revogado ou vencido;
  - 403 sem o módulo (mesma mensagem do MCP);
  - 400 parâmetro inválido (`ToolError` dos handlers vira 400);
  - 404 quando o handler devolve `{"erro": "... não encontrado ..."}` em
    rota de detalhe (os handlers de detalhe hoje devolvem `erro` em vez de
    levantar; a camada da API converte);
  - 429 limite excedido.
- CNPJ e CPF aceitos com ou sem pontuação, como no MCP.

### Rotas da primeira entrega

Cada rota é uma linha num **registro** (`app/blueprints/public_api/rotas.py`
ou equivalente): caminho, handler do MCP, módulo exigido, parâmetros com tipo
e descrição. Desse registro saem as rotas Flask, o OpenAPI e a página de
documentação. Teste compara o registro com as rotas montadas.

| Rota | Handler (MCP) | Módulo |
|---|---|---|
| `GET /api/v1/eu` | — (usuário, escritório, módulos, validade do token, consultas de nome restantes hoje) | `api` |
| `GET /fap/empresas` | `list_fap_companies_handler` | `fap_panel` |
| `GET /fap/contestacoes` · `/fap/contestacoes/{id}` | `list_fap_contestacoes_handler` · `get_contestacao_detail_handler` | `fap_panel` |
| `GET /fap/beneficios` · `/fap/beneficios/{id}` | `list_fap_benefits_handler` · `get_benefit_detail_handler` | `fap_panel` |
| `GET /fap/resumo` | `fap_summary_handler` | `fap_panel` |
| `GET /fap/filtros` | `fap_filter_values_handler` | `fap_panel` |
| `GET /fap/procuracoes` | `list_fap_procuracoes_handler` | `fap_panel` |
| `GET /fap/calculo/beneficios` · `/fap/calculo/resumo` | `listar_beneficios_calculo_fap_handler` · `resumo_beneficios_calculo_fap_handler` | `fap_panel` |
| `GET /segurados?cpf=&nit=&nome=` | `buscar_por_segurado_handler` | `fap_panel` |
| `POST /segurados/revelar-nome` | `revelar_nome_segurado_handler` | `fap_panel` |
| `GET /base-conhecimento/pesquisa` · `/base-conhecimento/arquivos/{id}` | `kb_search_handler` · `read_kb_file_handler` | `knowledge_base` |
| ~~`POST /base-conhecimento/perguntar`~~ | **Fora por ora** (revisão de 22/10): a busca do agente não filtra escritório; volta quando filtrar | — |
| `GET /jurisprudencia` · `/{id}` · `/panorama` · `/filtros` | handlers de `tools/jurisprudence.py` | `process_panel` |
| `GET /processos` · `/processos/{id}` | `list_processes_handler` · `get_process_detail_handler` | `process_panel` |
| `GET /numero-processo/{numero}` | `search_by_process_number_handler` | por base, como no MCP |

Segunda entrega (mesmo molde, só linhas novas no registro): CATs, massas,
vínculos, rotatividade, comunicações (DJEN), DOU, Revisor (leitura).

### Revelar nome e perguntar à base (o que custa dinheiro)

- **Revelar nome**: um CPF por chamada, só da base do escritório, com o mesmo
  `segurado_nome_service.revelar`. Nova `origem='api'`. **O limite diário por
  usuário (`CPF_NOME_LIMITE_DIARIO_MCP`) passa a contar MCP e API juntos**:
  são os dois caminhos automatizados, e separados dobrariam a cota de quem
  usa os dois. A resposta informa `consultas_restantes_hoje`. Nome já salvo
  não conta, como hoje.
- **Perguntar à base**: passa pelo `TokenUsageService` como qualquer chamada
  de IA (já passa, pelo handler) e tem limite próprio por usuário/dia
  (`API_LIMITE_PERGUNTAS_DIA`, padrão 200).

### Limite de requisições

Por token, 120 requisições por minuto (`API_LIMITE_POR_MINUTO`). Contador em
memória por processo do Gunicorn: com 4 workers o limite real fica entre 120 e
480/min, o que basta para conter um loop descontrolado sem trazer Redis nem
dependência nova. Se um dia precisar de limite exato, troca-se o contador sem
mexer nas rotas.

### Registro de uso

Reaproveita `user_mcp_calls`, com `kind='api'` e `name` = a rota do registro
(ex.: `GET /fap/beneficios`). Assim a tela de **Atividade de Usuários** mostra
o uso da API junto do MCP sem tabela nova, e o mesmo princípio vale: **sem
argumentos** (CPF, texto). A coluna MCP da tela ganha a contagem da API ao
lado; o modal "funções usadas" separa por tipo.

### Documentação

- `GET /api/v1/openapi.json`: OpenAPI 3.1 gerado do registro. Exige token
  (lista o que o escritório tem, não é segredo, mas não há motivo para ser
  público).
- **Página "API"** (`/api/docs`, logada): a documentação legível, gerada do
  mesmo registro, com rota, parâmetros, exemplo de `curl` e exemplo de
  resposta, mais uma seção "Usar no Claude Code" com o prompt de partida:

  > Use a API do IntellexIA (documentação em `<url>/api/v1/openapi.json`,
  > token na variável `INTELLEXIA_TOKEN`) para…

  Sem Swagger UI de CDN: a página segue o visual do app (AdminLTE), como o
  manual. Os endereços saem de `app_public_url()`, nunca domínio fixo.
- **Manual** `docs/MANUAL_API.md`, registrado em `_MANUALS` e
  `_MANUAL_FILES`: o que é, como pedir acesso, como criar o token, cuidados
  (não colar token em código versionado nem em página HTML pública), como usar
  com o Claude Code.

### Tela "Minha API"

Item novo no menu do usuário (perto de Perfil), visível com o módulo `api`:

- lista dos meus tokens (nome, final `…a3f9`, criado em, validade, último
  uso) com botão Revogar;
- botão **Criar token**: nome + validade → modal que mostra o token **uma
  vez**, com Copiar e o aviso de que não aparece de novo;
- atalhos para a documentação e o manual.

Admin vê também a aba **Tokens do escritório** (de quem, último uso,
revogar).

### MCP

Ferramentas novas (módulo `api`):

- `minha_api`: endereço da API, link da documentação, meus tokens (sem o
  segredo) e a cota de nomes restante.
- `criar_token_api(nome, validade_dias)`: cria e devolve o token **uma vez**,
  com a orientação de guardá-lo em variável de ambiente ou `.env` fora do git.
  A docstring proíbe a IA de repetir o token depois nem de gravá-lo em arquivo
  versionado.
- `revogar_token_api(token_id)`.
- `documentacao_api(secao)`: o OpenAPI resumido (rotas + parâmetros), para o
  Claude Code montar a integração sem sair da conversa.

Entram no `docs/MANUAL_MCP.md` (tabela + contagem "N ferramentas"), e o
`tests/test_mcp_catalogo.py` cobra isso.

## Parte 2 — Biblioteca de IA

Redesenhada em 22/10/2026, depois da conversa com o Thiago (modelo aprovado:
grade de cards "rica", `.superpowers/brainstorm/2_layout_v2.png`).

### O problema

Cada colaborador tem os próprios prompts, "agentes" e skills, espalhados na
conta do Claude de cada um. O que funciona para um não chega aos outros, e vai
embora quando a pessoa sai. O escritório usa o **Claude**, mas a biblioteca tem
de funcionar **independente** do plano do Claude: mora no IntellexIA e chega ao
Claude pelo conector MCP que todos já usam.

### O que o mercado faz (pesquisado em 22/10/2026)

- **Claude (Team/Enterprise)**: skills (`SKILL.md` + arquivos) compartilhadas
  entre colegas e provisionadas pelo admin; publicar não exige aprovação.
- **ChatGPT**: o mesmo formato de skill, abas "Compartilhadas comigo" / "Do
  workspace"; GPTs viraram "agentes do workspace".
- **Copilot**: Prompt Gallery com três abas — sugeridos, meus, do time.
- **Harvey / Legora**: biblioteca de workflows do escritório + os prontos do
  fornecedor; playbooks para revisão padronizada.

Padrão comum, e o que adotamos: três prateleiras (minhas / do escritório / do
fornecedor), compartilhar com um clique, e "agente" = roteiro de instruções
com acesso a ferramentas.

### O que é um item

Um tipo só por baixo, com uma etiqueta de **tipo** para a pessoa:

| Tipo | O que é | Exemplo |
|---|---|---|
| Prompt | Texto para colar, com ou sem campos | "E-mail ao cliente: deferimento" |
| Agente | Roteiro com papel, passos e ferramentas do IntellexIA | "Analista de sentença FAP" |
| Skill | Instruções + **anexos de texto** (modelo, checklist), no formato de skill do Claude | "Revisão de impugnação antes do protocolo" |

Campos: título, "quando usar" (descrição), texto (corpo), área (FAP,
Jurisprudência, Processos, Comunicação, Base de Conhecimento, Diário Oficial,
Geral), "usa dados do IntellexIA" (marca de que o roteiro chama ferramentas do
conector), visibilidade (**só eu** ou **escritório**) e anexos.

**Campos a preencher** são escritos como `{{empresa}}` no texto e lidos dele
(nunca guardados à parte). No Claude viram argumentos do comando; campo não
informado vira, no texto entregue, a instrução de perguntar ao usuário.

### Dados

Migration `database/add_prompt_library_tables.py`, todas com `law_firm_id`:

- `prompt_library_items`: `tipo`, `titulo`, `slug` (único por escritório; é o
  nome do comando), `descricao`, `corpo` (MEDIUMTEXT), `anexos_json`, `area`,
  `usa_intellexia`, `visibilidade`, `recomendado` + `recomendado_por_id`,
  `versao`, `usos`, `owner_id` (SET NULL), `arquivado_em`, datas em UTC.
- `prompt_library_versions`: uma linha por versão salva (título, descrição,
  corpo, anexos, quem editou, quando) — "Ver versões" e "Restaurar".
- `prompt_library_favorites`: (usuário, item).

### Regras

- Qualquer usuário logado usa a biblioteca (não é módulo: não expõe dado do
  escritório). Item **pessoal** só o dono vê — nem o admin (como no Claude).
- Editar, arquivar e mudar visibilidade: o dono; item do escritório também o
  admin. Item do escritório cujo dono saiu continua (dono `NULL`, só admin edita).
- **Recomendado pelo escritório**: só admin marca, só em item do escritório.
  Tornar o item pessoal tira o selo.
- **Compartilhar confere dados pessoais**: CPF ou CNPJ válido (DV) no texto ou
  nos anexos pede confirmação antes de publicar para o escritório.
- Duplicar cria uma cópia **pessoal** (de item do escritório ou do IntellexIA).
- Toda edição que muda título, descrição, texto ou anexos vira versão nova.
- O **comando no Claude** é escolhido no editor (vem do título enquanto a
  pessoa não mexe) e não muda quando o título muda; nome ocupado é erro.
- `usos` soma "Copiar"/"Abrir no Claude" na tela e o uso pelo conector.

### Tela `/prompts` — "Biblioteca de IA"

Item próprio no menu lateral. Faixa no topo com os números (meus, do
escritório, usos), o botão **+ Novo** (menu Prompt / Agente / Skill / Importar skill do Claude) e o
**Como usar** (modal). Nome na tela: **Biblioteca de IA** — "prompt" é um dos três tipos e não nomeia o todo; o endereço e os nomes internos seguem `prompt_library`. Antes: **Novo prompt** e **Importar skill do Claude**.
Abas **Meus / Do escritório / Do IntellexIA / Favoritos**, busca (título,
texto, área, autor), ordenação (mais usados, recentes, A–Z) e filtro lateral
por **tipo**, **área** e **selo** (recomendados, usa dados do IntellexIA). Na
aba do escritório, a seção **Recomendados pelo escritório** vem primeiro.

Card: ícone por área e tipo, título, estrela de favorito, selos (recomendado,
nº de campos, usa dados, versão, nº de anexos), começo do texto, autor com
foto, usos, o **comando no Claude** e as ações — **Copiar** (ou **Preencher e
copiar** quando há campos), **Abrir no Claude** e o menu ⋯ (editar, duplicar,
versões, compartilhar/tornar pessoal, recomendar, baixar como skill, arquivar).

"Abrir no Claude" copia o texto **e** abre `claude.ai/new?q=…`: o parâmetro não
é documentado para a web e já parou de preencher em 2025, então o texto copiado
é a garantia (o aviso diz para colar se não aparecer).

Editor em página própria (`/prompts/novo`, `/prompts/<id>/editar`) com prévia
dos campos detectados e anexos.

### Importar e baixar skill

- **Importar**: `.zip` exportado do Claude ou um `SKILL.md`. O frontmatter
  (`name`, `description`) vira título e "quando usar"; o corpo vira o texto;
  os demais arquivos **de texto** viram anexos. Scripts e binários ficam de
  fora (a skill compartilhada rodaria na máquina dos colegas) e a tela diz o
  que foi ignorado. Limites de tamanho e de número de arquivos; nada é gravado
  em disco.
- **Baixar como skill**: `.zip` com a pasta `<nome>/SKILL.md` (frontmatter no
  formato do Claude) e os anexos, pronto para subir no Claude.

### Do IntellexIA

Os comandos prontos do servidor MCP aparecem na aba, só leitura, com o texto
real: lidos do `mcp_server/server.py` por AST (sem subir o servidor), com cada
argumento trocado por `{{argumento}}`. "Duplicar" vira ponto de partida pessoal.

### Ferramentas do conector (aba "Do IntellexIA" e editor)

Para o usuário saber o que existe e montar agentes que chamam a ferramenta
certa: um modal em cards (ícone e cor da área, nome curto, nome técnico,
descrição), com busca e filtro por área, aberto por "Ferramentas do IntellexIA"
no topo da tela (cada card com "Usar num agente") e pelo "Inserir ferramenta" do
editor (clicar no card insere no cursor "Chame a ferramenta X do IntellexIA para ").
Com acesso primeiro; sem o módulo, em cinza no fim, com o motivo. O nome curto é a
coluna "Nome" das tabelas do `MANUAL_MCP.md` (fonte única). O editor lista as ferramentas citadas e os módulos que
elas exigem (quem não tiver recebe acesso negado). Citar uma ferramenta marca
"usa dados do IntellexIA"; o card mostra quantas o roteiro chama.

### No Claude (MCP)

- **Comandos prontos**: um middleware (`mcp_server/prompt_library.py`)
  acrescenta à lista de comandos de cada usuário os itens que ele vê —
  `meu_<tipo>_<slug>` (pessoais) e `escritorio_<tipo>_<slug>` (do escritório), com o tipo — prompt, agente ou skill — no nome para a lista do Claude já dizer o que é, — com os campos
  como argumentos, e responde esses nomes no `prompts/get`. O uso continua
  registrado pelo `UsoMcpMiddleware` (vem antes na cadeia).
- **Ferramentas**, porque nem todo cliente atualiza a lista de comandos no meio
  da conversa: `biblioteca_prompts` (lista com busca), `usar_prompt(nome,
  campos)` (devolve o texto pronto, e a IA segue) e `salvar_prompt(...)` (a
  pessoa transforma em item algo que acabou de funcionar na conversa; pessoal
  por padrão).

### Fora do escopo (agora)

- Scripts em skill; execução de agente no servidor ou agendada.
- Transferir os itens pessoais de quem saiu do escritório.
- Instalar a skill direto na conta Claude da pessoa (não há caminho oficial).

## Ordem de entrega

1. **Tokens + núcleo da API**: tabela, serviço, autenticação, envelope de
   erro, limite, registro de uso, `GET /eu` e as rotas de FAP e segurados.
2. **Resto da primeira leva de rotas** (base de conhecimento, jurisprudência,
   processos), OpenAPI, página de documentação, tela Minha API, ferramentas
   MCP de token e documentação, manual.
3. **Biblioteca de IA**: tabelas, tela, importar/baixar skill, ganchos e
   ferramentas no MCP, manual.
4. **Segunda leva de rotas** conforme o uso pedir.

Cada passo vai a homologação sozinho. As partes 1–2 e a 3 são independentes:
dá para inverter se o escritório preferir a biblioteca antes.

## Testes

Scripts em `tests/`, no padrão do projeto:

- `test_api_tokens.py`: token mostrado uma vez e guardado só o hash;
  vencido, revogado, de usuário inativo → 401; sem módulo → 403; módulo
  retirado depois da criação → 403 na hora; outro escritório nunca aparece.
- `test_api_rotas.py`: cada rota do registro responde igual ao handler do MCP
  com os mesmos parâmetros; registro × rotas montadas × OpenAPI batem;
  cookie de sessão sozinho não autentica.
- `test_api_revelar_nome.py`: cota compartilhada MCP + API; CPF fora da base
  recusado.
- `test_prompt_library.py`: visibilidade (pessoal de outro usuário nunca
  aparece, nem para admin; outro escritório nunca), campos, preenchimento,
  edição só por dono/admin, recomendado só admin, versões e restaurar, aviso de
  CPF/CNPJ ao compartilhar, importar/baixar skill (script ignorado), comandos do
  sistema lidos por AST, comandos e ferramentas no MCP.

## Decisões que tomei (confira)

- API dentro do Flask, `/api/v1`, só Bearer, sem cookie, CORS aberto.
- Permissões conferidas ao vivo a cada requisição.
- Cota de "revelar nome" compartilhada entre MCP e API.
- Uso registrado em `user_mcp_calls` com `kind='api'`, sem tabela nova.
- Limite por minuto em memória (aproximado), sem Redis.
- Documentação gerada do registro de rotas, no visual do app, sem Swagger de
  CDN.
- Biblioteca aberta a qualquer usuário logado; prompts entram como comandos no
  MCP com prefixo `meu_`/`escritorio_`.
- API primeiro, biblioteca depois.

## Decididos com o Thiago (22/10/2026)

O token é por usuário e o uso é interno ao escritório, então:

1. **Telas no navegador são permitidas.** A API libera CORS para qualquer
   origem, sem credenciais de cookie (`Access-Control-Allow-Origin: *`, só o
   header `Authorization`). Como a API só aceita Bearer, liberar a origem não
   abre CSRF; o risco que sobra é o token dentro da página, aceito. O manual
   recomenda ainda assim não publicar essa página fora do escritório.
2. **O MCP cria token** (`criar_token_api`), além de listar e revogar.
3. **Módulo `api` liberado por padrão** para todos os papéis (entra nos
   padrões de não-admin). O admin ainda pode retirar por usuário.
