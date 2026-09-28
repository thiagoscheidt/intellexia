# Manual do Usuário — Conectar sua IA ao IntellexIA (MCP)

> O IntellexIA pode ser acessado por assistentes de IA — como o :claude: **Claude** — por meio do protocolo **MCP** (Model Context Protocol). Depois de conectar, você conversa com a IA e ela consulta **os dados do seu escritório** no IntellexIA: base de conhecimento, painel FAP, contestações, processos, jurisprudência, monitoramento de publicações e mais — com **44 ferramentas** organizadas por área e **comandos prontos** para relatórios, recursos e e-mails.

---

## O que é a conexão MCP

O MCP é uma "ponte" segura entre um assistente de IA e o IntellexIA. Em vez de copiar e colar dados para o chat, você pergunta — e a IA busca a resposta diretamente no sistema, **com o seu usuário**, respeitando o seu escritório e as suas permissões de módulo.

> [!IA] **Segurança:** a autorização usa o **seu login do IntellexIA** (OAuth). Nenhuma senha ou chave é copiada para o assistente; você apenas aprova o acesso em uma tela do próprio sistema, e pode revogá-lo quando quiser.

### Exemplos do que você pode pedir

- "Quantos benefícios temos do BISTEK?" — respondido em segundos pelo resumo estatístico;
- "**Me mostra o painel do FAP do BISTEK**" — abre um painel visual, com cartões e gráficos, dentro da própria conversa;
- "Liste as contestações FAP da vigência 2023 que estão indeferidas";
- "Qual foi o resultado da contestação de protocolo 10128.053144/2025-42?" — e, na sequência, "quais benefícios dela foram deferidos?";
- "O que temos na base de conhecimento sobre acidente de trajeto?";
- "Pesquise o NB 6320957810 nos documentos" — retorna os trechos com link para abrir o PDF;
- "Me traga todos os benefícios B91 de 2023 **em planilha**" — gera o Excel oficial do sistema com link de download;
- "O que mudou nas contestações esta semana?";
- "Quem é o CNPJ 59.104.422/0103-84?" — consulta pública da Receita;
- "Quais intimações chegaram esta semana e ainda não foram lidas?";
- "O que saiu no processo 5001181-56.2023.4.03.6100?" — a linha do tempo das publicações do processo;
- "Explica essa intimação: tem prazo?" — a IA diz o prazo, a providência e a urgência;
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

1. Abra **Personalizar → Conectores → Adicionar conector personalizado** (em inglês: *Customize → Connectors → Add custom connector*).
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
| `listar_contestacoes_fap` | Contestações com filtros (**protocolo**, CNPJ, raiz, vigência, situação, instância), com resultado do deferimento, nome da empresa e status do PDF | FAP Web |
| `detalhar_contestacao` | Contestação completa + **benefícios vinculados** + alterações recentes + **link do PDF** | FAP Web |
| `listar_beneficios_fap` | Benefícios com filtros ricos (**empresa por nome**, **protocolo da contestação**, CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência...) e o status em cada instância | FAP Web |
| `detalhar_beneficio` | Todos os campos de um benefício, incluindo justificativas, pareceres e decisões de julgamento | Sistema |
| `listar_procuracoes_fap` | Procurações eletrônicas com situação e vigência | FAP Web |
| `valores_de_filtro_fap` | Códigos e valores válidos para filtros (situações, instâncias, tópicos, motivos) — a IA consulta antes de filtrar | Sistema |

### 📊 Painel FAP — análises e acompanhamento

| Ferramenta | O que faz | Origem |
|---|---|---|
| `resumo_fap` | Contagens agregadas em uma chamada: contestações por vigência/situação/instância/**empresa**; benefícios por tipo/status/tópico + **financeiro** (total pago) | Cálculo |
| `painel_fap` | Os **mesmos números** do `resumo_fap`, só que como **painel visual** na conversa: cartões de totais e gráficos de barras por situação, vigência, empresa, tópico e instância | Cálculo |
| `alteracoes_recentes_fap` | O que mudou nas sincronizações com o portal ("o que mudou essa semana?") | FAP Web |
| `prazos_e_alertas` | O que pede atenção: contestações aguardando resultado, decisões recentes (janela de recurso) e processos por fase | Cálculo |
| `comparar_vigencias` | Compara resultados entre vigências (ex: 2023 vs 2024): deferidos/indeferidos, tópicos e financeiro | Cálculo |
| `buscar_por_segurado` | Visão 360º de uma pessoa: benefícios + CATs + processos (por NIT, CPF ou nome) | Sistema |

> [!INFO] Para perguntas de **quantidade** ("quantos benefícios da empresa X?"), a IA usa o `resumo_fap` — resposta em segundos, sem listar registro por registro. Quando você pede para **ver** o panorama ("me mostra o painel", "faz um gráfico disso"), ela usa o `painel_fap`, que traz os mesmos números em forma visual.

> [!IA] **O painel funciona em qualquer assistente.** Onde o aplicativo sabe desenhar painéis, você vê os cartões e gráficos; onde não sabe, a mesma resposta chega em texto, com os totais e as principais dimensões. Você nunca fica sem o número por causa do aplicativo que está usando.

> [!ALERTA] **O painel diz o que está deixando de fora.** Em dimensões com muitos valores — tópicos de contestação e empresas — ele mostra os **8 maiores** e agrupa o restante numa faixa `outros (N)` visível. E no cartão de tópicos aparece a cobertura real da classificação (por exemplo, "206 de 2899 benefícios têm tópico classificado"), para que a leitura não sugira que todos os benefícios foram classificados.

> [!INFO] **Pelo protocolo:** o número pode ir com ou sem pontuação (`10128.053144/2025-42` ou `10128053144202542`), completo ou só um trecho. As contestações de 1ª e de 2ª instância têm o mesmo protocolo, então as duas voltam juntas. Os benefícios de um protocolo são os da mesma empresa (CNPJ) e vigência da contestação — o **mesmo critério** do filtro "Protocolo administrativo" da tela de Benefícios, então a IA e a tela dão o mesmo número.

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

### 📖 Base de Jurisprudência

As decisões FAP do escritório (sentenças, acórdãos e embargos) — as mesmas da **Base de Conhecimento** do Painel de Processos.

| Ferramenta | O que faz | Origem |
|---|---|---|
| `pesquisar_jurisprudencia` | Pesquisa por palavras (com sinônimos), expressão entre aspas ou **número do processo**, com filtros de tese, tribunal, resultado e instância; traz a **citação pronta** e o trecho encontrado. Também busca no **inteiro teor** | Sistema |
| `detalhar_decisao` | Tudo de uma decisão: motivo, ementa, fundamentos, argumentos acolhidos e rejeitados, precedentes e as outras peças do mesmo processo | Sistema |
| `panorama_jurisprudencia` | "Qual a chance da tese X no TRF4?": resultados por tribunal e instância, processos que **viraram no acórdão** e as favoráveis mais recentes | Cálculo |
| `decisoes_parecidas` | Decisões que discutem o mesmo ponto com outras palavras, por semelhança de conteúdo | IA |
| `valores_de_filtro_jurisprudencia` | Teses, tribunais, instâncias e resultados que existem na base, com contagem — a IA consulta antes de filtrar | Sistema |
| `exportar_jurisprudencia_excel` | Planilha com as decisões filtradas (teses, resultado, fundamentos, ementa, citação e link), até 50 mil linhas | Relatório |

> [!ALERTA] Quando a ementa foi **resumida** pela IA na leitura do PDF, a decisão avisa: resumo não pode ser citado entre aspas como se fosse transcrição.

> [!INFO] **Duas teses por decisão, dois filtros.** A **tese original** é a que veio escrita na decisão — grafias que só diferem em acento ou maiúsculas contam juntas. A **tese do catálogo** é a padronizada do escritório, a mesma usada na geração da peça. Pode pedir pelas duas: "decisões com a tese original *acidente de trajeto*" ou "decisões da tese do catálogo *Trajeto - B91*".

> [!IA] **Sem termo, é a listagem completa**, paginada, com os filtros que você pedir ("todas as decisões do TRF4 de 2025"). Para a base inteira de uma vez, peça a **planilha**. A busca no **inteiro teor** só alcança as decisões com PDF no sistema — a resposta diz quantas são — e nela valem só os filtros de tribunal, resultado e instância.

Exemplos:

- "Qual a chance da tese de trajeto no TRF4?" — o panorama, com as viradas no acórdão;
- "Me traz as decisões favoráveis de 2025 sobre rotatividade, com a citação pronta";
- "O que diz o acórdão do processo 5083928-14.2021.4.04.7100?";
- "Tem decisão parecida com essa?";
- "Exporta todas as sentenças do TRF3 em planilha".

### 📡 Monitoramento de Processos

As publicações (intimações, citações, editais) que o radar captura no Diário de Justiça Eletrônico pelas OABs do escritório — as mesmas da tela **Monitoramento de Processos**.

| Ferramenta | O que faz | Origem |
|---|---|---|
| `listar_comunicacoes` | Publicações com os filtros da tela: tribunal, tipo, advogado, **número do processo**, período e **só as não lidas** | Sistema |
| `detalhar_comunicacao` | O **inteiro teor** de uma publicação, com processo, órgão, destinatários, advogados intimados e link do documento original | Sistema |
| `explicar_comunicacao` | Explica a publicação em linguagem clara: **prazo**, providência exigida e **urgência** | IA |
| `comunicacoes_do_processo` | **Linha do tempo** das publicações de um processo e se ele está no Painel de Processos; opcionalmente consulta o Diário de Justiça **ao vivo**, para processo fora do radar | Sistema |
| `resumo_monitoramento` | Visão geral do período: total, não lidas, distribuição por tribunal e tipo, advogados monitorados e os que estão **fora do radar** | Cálculo |

> [!IA] A explicação é gerada **uma vez** por publicação e fica guardada: pedir de novo é instantâneo e não gasta IA. É apoio à triagem — confira sempre prazo e teor no processo oficial.

> [!INFO] A consulta **ao vivo** mostra o que o Diário de Justiça tem sobre o processo, mas **não grava** nada no sistema: o radar só guarda o que pertence às OABs monitoradas. Ela exige o número completo (20 dígitos).

### 🔢 Como informar o número do processo

Em todas as ferramentas que buscam por processo (`listar_processos`, `listar_comunicacoes`, `comunicacoes_do_processo`), o número pode ser digitado **de qualquer jeito**:

| Você digita | Encontra |
|---|---|
| `5001181-56.2023.4.03.6100` | o processo |
| `50011815620234036100` | o mesmo processo |
| `5001181` | os processos com esse trecho — basta o número sequencial |

> [!ALERTA] São necessários **pelo menos 7 dígitos**. Um pedaço menor, como o ano `2023`, casaria com boa parte da base — a IA recebe o aviso e pede o número completo.

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

Além das ferramentas, o IntellexIA publica **comandos prontos** (prompts MCP): roteiros
completos que você dispara em um clique, sem precisar escrever o pedido. No Claude Code,
digite `/` e procure por `intellexia`; no Claude Desktop / claude.ai, eles ficam no botão
**+** da conversa, no item do conector IntellexIA:

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
| `ficha_empresa` | Ficha cadastral de uma empresa pelo CNPJ: razão social, situação, endereço, porte e resumo dos sócios |
| `socios_empresa` | Só o quadro societário de um CNPJ: nome, CPF/CNPJ e qualificação de cada sócio |

> [!INFO] Os dois comandos acima **pedem o CNPJ** antes de executar, e consultam dados públicos da Receita. Sendo um CNPJ de **filial**, a resposta avisa — o quadro societário é sempre o da matriz. Em MEI e empresa individual, a resposta diz que não há sócios registrados, em vez de vir vazia.

---

## Permissões

O acesso da IA **espelha as suas permissões** no IntellexIA:

| Para usar... | Você precisa do módulo... |
|---|---|
| Base de Conhecimento (consulta e pesquisa) | Base de Conhecimento |
| Painel FAP (consultas, análises e relatórios Excel) | Painel FAP |
| CATs, folha de pagamento, vínculos e rotatividade | Painel de Contestações |
| Processos judiciais e Base de Jurisprudência | Painel de Processos |
| Publicações do Diário de Justiça (monitoramento) | Monitoramento de Processos |
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
