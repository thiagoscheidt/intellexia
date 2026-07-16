# Manual do Usuário — Conectar sua IA ao IntellexIA (MCP)

> O IntellexIA pode ser acessado por assistentes de IA — como o :claude: **Claude** — por meio do protocolo **MCP** (Model Context Protocol). Depois de conectar, você conversa com a IA e ela consulta **os dados do seu escritório** no IntellexIA: base de conhecimento, painel FAP, contestações, processos e mais — com **32 ferramentas** organizadas por área e **comandos prontos** para relatórios, recursos e e-mails.

---

## O que é a conexão MCP

O MCP é uma "ponte" segura entre um assistente de IA e o IntellexIA. Em vez de copiar e colar dados para o chat, você pergunta — e a IA busca a resposta diretamente no sistema, **com o seu usuário**, respeitando o seu escritório e as suas permissões de módulo.

> [!IA] **Segurança:** a autorização usa o **seu login do IntellexIA** (OAuth). Nenhuma senha ou chave é copiada para o assistente; você apenas aprova o acesso em uma tela do próprio sistema, e pode revogá-lo quando quiser.

### Exemplos do que você pode pedir

- "Quantos benefícios temos do BISTEK?" — respondido em segundos pelo resumo estatístico;
- "Liste as contestações FAP da vigência 2023 que estão indeferidas";
- "O que temos na base de conhecimento sobre acidente de trajeto?";
- "Pesquise o NB 6320957810 nos documentos" — retorna os trechos com link para abrir o PDF;
- "Me traga todos os benefícios B91 de 2023 **em planilha**" — gera o Excel oficial do sistema com link de download;
- "O que mudou nas contestações esta semana?";
- "Quem é o CNPJ 59.104.422/0103-84?" — consulta pública da Receita;
- "**Revise esta petição**" (colando o texto) — o agente revisor oficial aponta achados e documentos faltantes;
- "**Revise esta petição, identificador FAP-2024-013**" — a revisão entra no painel do Revisor, com histórico e custo;
- "O que a revisão da FAP-2024-013 apontou?" — lê os achados sem gastar outra rodada de IA;
- Comando pronto `/analise_empresa` — análise completa de uma empresa em um clique.

---

## Endereço do servidor

```
:url_mcp:
```

Use exatamente este endereço (sem barra no final) — é o endereço **desta** instalação do IntellexIA, já preenchido acima.

---

## :claude: Conectar no Claude Code

1. No terminal, adicione o servidor:

   ```
   claude mcp add --transport http intellexia :url_mcp:
   ```

2. Dentro do Claude Code, digite `/mcp`, selecione **intellexia** e escolha **Authenticate**.
3. O navegador abre no IntellexIA:
   - **Já logado?** Aparece a tela **"Autorizar acesso"** — clique em **Autorizar**.
   - **Não logado?** Faça login normalmente; a tela de autorização aparece em seguida.
4. Volte ao Claude Code — a conexão estará ativa e as ferramentas do IntellexIA disponíveis.

> [!INFO] Para conferir a conexão a qualquer momento: `claude mcp list` (deve mostrar `intellexia ... ✓ Connected`).

---

## :claude: Conectar no Claude Desktop / claude.ai

1. Abra **Settings → Connectors → Add custom connector**.
2. Informe a URL `:url_mcp:`.
3. Conclua a autorização no navegador (mesmo fluxo: login do IntellexIA + botão **Autorizar**).

---

## Ferramentas por categoria

### 📚 Base de Conhecimento

| Ferramenta | O que faz | Origem |
|---|---|---|
| `consultar_base_conhecimento` | Pergunta em linguagem natural com **resposta elaborada e fontes** (RAG) | IA |
| `pesquisar_base_conhecimento` | Pesquisa Inteligente: retorna os **trechos/documentos** encontrados, com fonte, página, relevância e **link para abrir o arquivo** | IA |

> [!IA] A pesquisa decide sozinha entre busca **semântica** (conceitos) e **textual** (termos exatos). Números de benefício, NIT, CPF e CNPJ são buscados de forma exata e determinística.

### 📋 Painel FAP — consultas

| Ferramenta | O que faz | Origem |
|---|---|---|
| `listar_empresas_fap` | Empresas sincronizadas — busca por **parte do nome**, CNPJ ou tipo de procuração | FAP Web |
| `listar_contestacoes_fap` | Contestações com filtros (CNPJ, raiz, vigência, situação, instância), nome da empresa e status do PDF | FAP Web |
| `detalhar_contestacao` | Contestação completa + **benefícios vinculados** + alterações recentes + **link do PDF** | FAP Web |
| `listar_beneficios_fap` | Benefícios com filtros ricos (**empresa por nome**, CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência...) | FAP Web |
| `detalhar_beneficio` | Todos os campos de um benefício, incluindo justificativas, pareceres e decisões de julgamento | Sistema |
| `listar_procuracoes_fap` | Procurações eletrônicas com situação e vigência | FAP Web |
| `valores_de_filtro_fap` | Códigos e valores válidos para filtros (situações, instâncias, tópicos, motivos) — a IA consulta antes de filtrar | Sistema |

### 📊 Painel FAP — análises e acompanhamento

| Ferramenta | O que faz | Origem |
|---|---|---|
| `resumo_fap` | Contagens agregadas em uma chamada: contestações por vigência/situação/instância/**empresa**; benefícios por tipo/status/tópico + **financeiro** (total pago) | Cálculo |
| `alteracoes_recentes_fap` | O que mudou nas sincronizações com o portal ("o que mudou essa semana?") | FAP Web |
| `prazos_e_alertas` | O que pede atenção: contestações aguardando resultado, decisões recentes (janela de recurso) e processos por fase | Cálculo |
| `comparar_vigencias` | Compara resultados entre vigências (ex: 2023 vs 2024): deferidos/indeferidos, tópicos e financeiro | Cálculo |
| `buscar_por_segurado` | Visão 360º de uma pessoa: benefícios + CATs + processos (por NIT, CPF ou nome) | Sistema |

> [!INFO] Para perguntas de **quantidade** ("quantos benefícios da empresa X?"), a IA usa o `resumo_fap` — resposta em segundos, sem listar registro por registro.

> [!IA] **Listas grandes:** as consultas trazem uma página por vez (e dizem quantos registros existem no total). Havendo mais, a IA busca as páginas seguintes sozinha quando fizer sentido — mas para *todos* os registros o caminho certo é pedir a **planilha em Excel**, e para números agregados, o resumo.

### 📑 Relatórios em Excel

| Ferramenta | O que faz | Origem |
|---|---|---|
| `exportar_beneficios_excel` | Planilha **idêntica à do sistema** (33 colunas) com os benefícios filtrados, até 50 mil linhas | Relatório |
| `exportar_contestacoes_excel` | Planilha oficial das contestações, com links dos PDFs | Relatório |

> [!ALERTA] O link de download expira em **1 hora**. Peça a exportação de novo se o link vencer.

### ⚖️ Painel de Contestações

| Ferramenta | O que faz | Origem |
|---|---|---|
| `listar_cats_fap` | CATs das contestações com datas e status por instância | Relatório |
| `listar_massas_salariais_fap` | Folha de pagamento contestada por competência, com valores pleiteados | Relatório |
| `listar_vinculos_fap` | Vínculos empregatícios contestados por competência | Relatório |
| `listar_rotatividade_fap` | Taxas de rotatividade contestadas (admissões, rescisões, vínculos) | Relatório |

### 🏛️ Processos Judiciais

| Ferramenta | O que faz | Origem |
|---|---|---|
| `listar_processos` | Processos com fase atual, partes e valor da causa | Sistema |
| `detalhar_processo` | Processo completo: histórico de fases, benefícios vinculados, teses e decisões | Sistema |

### 🧰 Utilidades

| Ferramenta | O que faz | Origem |
|---|---|---|
| `consultar_cnpj` | Dados cadastrais públicos de um CNPJ (Receita Federal): razão social, situação, endereço, sócios e **matriz/filial** | Sistema |

### ✍️ Revisão de Petições

| Ferramenta | O que faz | Origem |
|---|---|---|
| `revisar_peticao_inicial` | Revisa o texto de uma petição com o **agente revisor oficial** do escritório (mesmos prompts, manual FAP e casos de referência do módulo Revisor): achados com severidade, documentos faltantes, teses e resumo executivo | IA |
| `listar_peticoes_revisao` | Petições do Revisor com o estágio de cada uma, nº de revisões e data da última — "o que está aguardando ajuste?" | Sistema |
| `detalhar_revisao` | Os achados de uma revisão **já feita**: gravidade, localização, correção sugerida e referência do manual | Sistema |
| `historico_revisoes_peticao` | Evolução entre as revisões da mesma petição: o que foi resolvido, o que **reincidiu** e o que é novo | Sistema |
| `comparar_versoes_peticao` | Revisa **duas versões juntas** (original × revisada) com o agente oficial — "a v2 corrigiu o que foi apontado?" | IA |
| `ler_manual_revisor` | Lê o **manual FAP do escritório** (e casos de referência) por seção ou termo — é o que permite explicar um achado citando a régua real | Sistema |
| `versoes_manual_revisor` | Versões do manual e das referências: qual está ativa, quem criou e quando | Sistema |
| `auditoria_revisor` | Quem fez o quê e quando no módulo | Sistema |
| `estatisticas_revisor` | Score, retrabalho e reincidência por advogado — **só para administradores** | Cálculo |

> [!IA] A revisão usa as configurações do módulo **Revisor de Petições** (modelo, manual e prompts ativos do escritório) e pode levar cerca de 1 minuto em petições longas.

> [!ALERTA] **Para a revisão entrar no sistema, informe o identificador do documento** (ex.: "revise esta petição, identificador FAP-2024-013"). Com ele, a revisão vira uma revisão da petição como qualquer outra: aparece no painel, conta no histórico e no custo. Sem ele, a IA responde a análise mas **nada fica salvo**.

> [!INFO] Pedir para *ler* uma revisão que já existe (`detalhar_revisao`) é instantâneo e não gasta IA — prefira isso a mandar revisar de novo.

> [!ALERTA] As **estatísticas por advogado** seguem a mesma regra da tela: só administradores. Um usuário comum recebe acesso negado, mesmo tendo o módulo liberado.

---

## Comandos prontos

Além das ferramentas, o IntellexIA publica **comandos prontos** (prompts MCP) que aparecem
no menu do assistente — no Claude Code, digite `/` e procure por `intellexia`:

| Comando | O que faz |
|---|---|
| `relatorio_semanal_fap` | Relatório semanal completo: panorama geral + o que mudou na semana + pontos de atenção |
| `analise_empresa` | Análise completa de uma empresa no FAP: benefícios, resultados por instância, impacto financeiro e recomendações |
| `agenda_do_dia` | O que precisa de atenção hoje: prazos, decisões recentes e processos, por prioridade |
| `minuta_recurso` | Esqueleto de recurso para um benefício indeferido, com fundamentos da base de conhecimento |
| `resumir_decisao` | Resume uma decisão/parecer FAP: resultado, fundamentação, efeito no FAP e próximos passos |
| `email_cliente` | Redige um e-mail ao cliente explicando o resultado do FAP em linguagem simples |
| `analise_risco_empresa` | Onde concentrar esforço: tópicos com mais chance de deferimento para uma empresa |
| `corrigir_peticao` | Pega a revisão já feita e devolve, achado a achado, o trecho reescrito pronto para colar |
| `pronto_para_protocolo` | Veredito objetivo: a petição pode ser protocolada? (críticos em aberto + documentos faltantes) |
| `devolutiva_ao_advogado` | Transforma os achados em uma devolutiva construtiva para quem redigiu |

---

## Permissões

O acesso da IA **espelha as suas permissões** no IntellexIA:

| Para usar... | Você precisa do módulo... |
|---|---|
| Base de Conhecimento (consulta e pesquisa) | Base de Conhecimento |
| Painel FAP (consultas, análises e relatórios Excel) | Painel FAP |
| CATs, folha de pagamento, vínculos e rotatividade | Painel de Contestações |
| Processos judiciais | Painel de Processos |
| Revisor de petições | Revisor de Petições |
| Consulta de CNPJ | Qualquer usuário logado (dados públicos) |

Sem o módulo liberado, a IA recebe uma mensagem clara de acesso negado. Permissões alteradas por um administrador passam a valer em **até 1 hora** (na renovação automática da sessão da IA).

> [!ALERTA] A IA **nunca** enxerga dados de outro escritório: o isolamento é feito pelo servidor a partir do usuário autorizado, não pela IA.

---

## Duração do acesso e revogação

- A autorização se renova sozinha por até **30 dias**; depois disso, basta autorizar de novo.
- Para **revogar**: remova o servidor no assistente (ex.: `claude mcp remove intellexia`).
- Usuários ou escritórios **desativados** perdem o acesso automaticamente em até 1 hora.

---

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Pedido para autenticar de novo | Autorização expirou (30 dias) ou foi revogada | `/mcp` → **Authenticate** |
| Navegador abre na tela de login | Sua sessão do IntellexIA expirou | Faça login; o fluxo continua sozinho |
| "Acesso negado: ... módulo" | Seu usuário não tem o módulo liberado | Peça a um administrador do escritório |
| "Solicitação expirada" | A tela de autorização ficou aberta mais de 10 minutos | Reinicie a conexão no assistente |
| Link de planilha não abre | Download expirado (1 hora) | Peça a exportação novamente |
| Erro de conexão | Serviço temporariamente indisponível | Tente novamente em instantes; persistindo, avise o suporte |
