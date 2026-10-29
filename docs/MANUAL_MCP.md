# Manual do Usuário — Conectar sua IA ao IntellexIA (MCP)

> O IntellexIA pode ser acessado por assistentes de IA — como o :claude: **Claude** — por meio do protocolo **MCP** (Model Context Protocol). Depois de conectar, você conversa com a IA e ela consulta **os dados do seu escritório** no IntellexIA: base de conhecimento, painel FAP, contestações, processos, jurisprudência, monitoramento de publicações, **Diário Oficial da União** e mais — com **72 ferramentas** organizadas por área e **comandos prontos** para relatórios, recursos e e-mails.

---

## O que é a conexão MCP

O MCP é uma "ponte" segura entre um assistente de IA e o IntellexIA. Em vez de copiar e colar dados para o chat, você pergunta — e a IA busca a resposta diretamente no sistema, **com o seu usuário**, respeitando o seu escritório e as suas permissões de módulo.

> [!IA] **Segurança:** a autorização usa o **seu login do IntellexIA** (OAuth). Nenhuma senha ou chave é copiada para o assistente; você apenas aprova o acesso em uma tela do próprio sistema, e pode revogá-lo quando quiser.

### Exemplos do que você pode pedir

- "Quantos benefícios temos do BISTEK?" — respondido em segundos pelo resumo estatístico;
- "**Me mostra o painel do FAP do BISTEK**" — abre um painel visual, com cartões e gráficos, dentro da própria conversa;
- "Liste as contestações FAP da vigência 2023 que estão indeferidas";
- "Quais as 10 filiais do grupo Vale com mais benefícios na vigência 2026?" — o ranking de estabelecimentos em uma chamada;
- "**Algum cliente saiu no Diário Oficial esta semana?**" — os clientes citados e os resultados de recurso FAP publicados;
- "O que o Ministério da Previdência publicou ontem na Seção 1?" — o sumário da edição, órgão por órgão;
- "Saiu alguma portaria sobre o \"Fator Acidentário de Prevenção\" em agosto?" — pesquisa no acervo do Diário Oficial;
- "Qual foi o resultado da contestação de protocolo 10128.053144/2025-42?" — e, na sequência, "quais benefícios dela foram deferidos?";
- "O que temos na base de conhecimento sobre acidente de trajeto?";
- "Pesquise o NB 6320957810 nos documentos" — retorna os trechos com link para abrir o PDF;
- "Me traga todos os benefícios B91 de 2023 **em planilha**" — gera o Excel oficial do sistema com link de download;
- "O que mudou nas contestações esta semana?";
- "Quem é o CNPJ 59.104.422/0103-84?" — consulta pública da Receita;
- "Quais intimações chegaram esta semana e ainda não foram lidas?";
- "O que saiu no processo 5001181-56.2023.4.03.6100?" — a linha do tempo das publicações do processo;
- "Explica essa intimação: tem prazo?" — a IA diz o prazo, a providência e a urgência;
- "**Revise esta petição**" (com o arquivo anexado) — o Claude revisa na conversa com o manual e as regras do Revisor do escritório e, se você quiser, grava no histórico da petição;
- "O que a revisão da petição 4387120543 apontou?" — lê os achados de uma revisão que já existe, sem revisar de novo;
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

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `consultar_base_conhecimento` | Perguntar à Base de Conhecimento | Pergunta em linguagem natural com **resposta elaborada e fontes** (RAG) | IA |
| `pesquisar_base_conhecimento` | Pesquisar na Base de Conhecimento | Pesquisa Inteligente: retorna os **trechos/documentos** encontrados, com fonte, página, relevância e **link para abrir o arquivo** | IA |
| `ler_arquivo_base_conhecimento` | Ler arquivo da Base | Lê o **arquivo inteiro** de um resultado da pesquisa — útil quando o trecho não basta, como num resumo em `.md`. Markdown e texto vêm do arquivo original; PDF e DOCX, remontados dos trechos indexados. Documento grande vem em partes | Sistema |
| `buscar_por_numero_processo` | Tudo de um processo pelo número | Acha **tudo de um processo pelo número** — petições e documentos da Base de Conhecimento, decisões da Jurisprudência, peças-modelo e o processo no Painel —, com ou sem pontuação, completo ou só parte do número (mínimo 7 dígitos). Traz o link de cada item e, quando houver, o **original no Drive** | Sistema |

> [!IA] A pesquisa decide sozinha entre busca **semântica** (conceitos) e **textual** (termos exatos). Números de benefício, NIT, CPF e CNPJ são buscados de forma exata e determinística.

### 📋 Painel FAP — consultas

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `listar_empresas_fap` | Empresas do FAP | Empresas sincronizadas — busca por **parte do nome**, CNPJ ou tipo de procuração | FAP Web |
| `listar_contestacoes_fap` | Contestações FAP | Contestações com filtros (**protocolo**, CNPJ, raiz, vigência, situação, instância), com resultado do deferimento, nome da empresa e status do PDF | FAP Web |
| `detalhar_contestacao` | Detalhe de uma contestação | Contestação completa + **benefícios vinculados** + alterações recentes + **link do PDF** | FAP Web |
| `listar_beneficios_fap` | Benefícios contestados | Benefícios com filtros ricos (**empresa por nome**, **grupo empresarial**, **protocolo da contestação**, **resultado na 1ª e na 2ª instância**, CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência...) e o status em cada instância | FAP Web |
| `detalhar_beneficio` | Detalhe de um benefício | Todos os campos de um benefício, incluindo justificativas, pareceres e decisões de julgamento | Sistema |
| `conferir_dados_beneficios` | Conferir dados de benefícios | Confere **vários benefícios de uma vez** (os de uma petição, planilha ou e-mail) contra a Central e o cálculo FAP: CPF, NIT, espécie, DIB, DCB, nascimento, CNPJ, vigência, nome e CAT, com qualquer pontuação; aponta **divergências** e **alertas** — já excluído do cálculo, fora do cálculo, não contestado, deferido, indeferido nas duas instâncias. Sem IA; nada fica salvo | Sistema |
| `listar_beneficios_calculo_fap` | Benefícios do cálculo FAP | Benefícios (B91–B94) e CATs do **cálculo do FAP**, contestados ou não, com CPF e nascimento inteiros; filtros por vigência, empresa, grupo, CNPJ, CPF, NIT, número, tipo, situação (**conta** ou **excluído** do cálculo) e **contestado** (por vigência) | FAP Web |
| `resumo_beneficios_calculo_fap` | Resumo do cálculo FAP | Contagens do cálculo em uma chamada: total, por tipo, excluídos, não contestados e o cruzamento tipo × situação × contestado | FAP Web |
| `listar_procuracoes_fap` | Procurações eletrônicas | Procurações eletrônicas com situação e vigência | FAP Web |
| `valores_de_filtro_fap` | Filtros do FAP | Códigos e valores válidos para filtros (**grupos empresariais**, situações, instâncias, tópicos, motivos) — a IA consulta antes de filtrar | Sistema |

### 📊 Painel FAP — análises e acompanhamento

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `resumo_fap` | Números do FAP | Contagens agregadas em uma chamada: contestações por vigência/situação/instância/**empresa**; benefícios por tipo/status/tópico, **tipo × resultado em cada instância** ("quantos B91 indeferidos na 1ª?" numa chamada), **ranking de filiais** (os estabelecimentos com mais benefícios) + **financeiro** (total pago). Filtra por empresa, CNPJ, vigência, **grupo empresarial**, tipo de benefício e resultado por instância | Cálculo |
| `painel_fap` | Painel visual do FAP | Os **mesmos números** do `resumo_fap`, só que como **painel visual** na conversa: cartões de totais e gráficos de barras por situação, vigência, empresa, tópico e instância | Cálculo |
| `alteracoes_recentes_fap` | O que mudou no FAP | O que mudou nas sincronizações com o portal ("o que mudou essa semana?") | FAP Web |
| `prazos_e_alertas` | Prazos e alertas | O que pede atenção: contestações aguardando resultado, decisões recentes (janela de recurso) e processos por fase | Cálculo |
| `comparar_vigencias` | Comparar vigências | Compara resultados entre vigências (ex: 2023 vs 2024): deferidos/indeferidos, tópicos e financeiro | Cálculo |
| `buscar_por_segurado` | Visão 360º do segurado | Visão 360º de uma pessoa: benefícios + CATs + processos (por NIT, CPF ou nome) | Sistema |
| `revelar_nome_segurado` | Revelar nome do segurado | Revela o **nome** de um segurado pelo CPF (o FAP não informa nome) — a mesma consulta paga do botão **Revelar nome** das telas. Só quando você pede o nome de uma pessoa específica, com limite diário por usuário; o nome fica salvo para todos | Sistema |
| `consultar_cpf` | Consulta completa de CPF | Consulta **paga** de **qualquer CPF válido** (com ou sem pontuação) e devolve **tudo o que o serviço traz**: nome, nascimento, sexo, nome da mãe. Nada fica salvo; entra no mesmo limite diário do revelar nome. Também em tela, em **Ferramentas → Consulta de CPF**. Para só o nome de um segurado da base, prefira `revelar_nome_segurado` | Sistema |

> [!INFO] **Nome do segurado.** O relatório e o portal do FAP **não informam o nome** — só CPF, NIT e nascimento. O nome aparece nas respostas quando alguém já o revelou (botão :btn-outline-primary[Revelar nome] nas telas de Benefícios, ou pedindo à IA), e a busca por nome acha esses segurados. Para revelar um nome novo, peça explicitamente ("qual o nome do segurado do CPF …?"): é uma consulta paga, feita uma vez por CPF, com limite diário por usuário — a IA não revela nomes em lote nem por conta própria. Cada benefício traz também o link gratuito da **consulta de CPF na Receita**, já preenchido (falta só o captcha).

> [!INFO] **Empresa ou grupo?** O filtro por **empresa** procura pelo nome, e um pedaço de nome pode pegar mais de uma empresa — "vale" também encontra a "Cooperativa Vale do Itajaí". Quando isso acontece, a resposta lista as empresas que entraram na conta e a IA avisa antes de dar o número. Para um grupo econômico inteiro, e só ele, peça pelo **grupo** ("do grupo Vale"): é o mesmo cadastro de grupos das telas do Painel FAP.

> [!INFO] Para perguntas de **quantidade** ("quantos benefícios da empresa X?"), a IA usa o `resumo_fap` — resposta em segundos, sem listar registro por registro. Quando você pede para **ver** o panorama ("me mostra o painel", "faz um gráfico disso"), ela usa o `painel_fap`, que traz os mesmos números em forma visual.

> [!IA] **O painel funciona em qualquer assistente.** Onde o aplicativo sabe desenhar painéis, você vê os cartões e gráficos; onde não sabe, a mesma resposta chega em texto, com os totais e as principais dimensões. Você nunca fica sem o número por causa do aplicativo que está usando.

> [!ALERTA] **O painel diz o que está deixando de fora.** Em dimensões com muitos valores — tópicos de contestação e empresas — ele mostra os **8 maiores** e agrupa o restante numa faixa `outros (N)` visível. E no cartão de tópicos aparece a cobertura real da classificação (por exemplo, "206 de 2899 benefícios têm tópico classificado"), para que a leitura não sugira que todos os benefícios foram classificados.

> [!INFO] **Pelo protocolo:** o número pode ir com ou sem pontuação (`10128.053144/2025-42` ou `10128053144202542`), completo ou só um trecho. As contestações de 1ª e de 2ª instância têm o mesmo protocolo, então as duas voltam juntas. Os benefícios de um protocolo são os da mesma empresa (CNPJ) e vigência da contestação — o **mesmo critério** do filtro "Protocolo administrativo" da tela de Benefícios, então a IA e a tela dão o mesmo número.

> [!IA] **Listas grandes:** as consultas trazem uma página por vez (e dizem quantos registros existem no total). Havendo mais, a IA busca as páginas seguintes sozinha quando fizer sentido — mas para *todos* os registros o caminho certo é pedir a **planilha em Excel**, e para números agregados, o resumo.

### 📑 Relatórios em Excel

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `exportar_beneficios_excel` | Benefícios em Excel | Planilha **idêntica à do sistema** (33 colunas) com os benefícios filtrados, até 50 mil linhas | Relatório |
| `exportar_contestacoes_excel` | Contestações em Excel | Planilha oficial das contestações, com links dos PDFs | Relatório |

> [!ALERTA] O link de download expira em **1 hora**. Peça a exportação de novo se o link vencer.

### ⚖️ Painel de Contestações

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `listar_cats_fap` | CATs contestadas | CATs das contestações com datas e status por instância | Relatório |
| `listar_massas_salariais_fap` | Massa salarial contestada | Folha de pagamento contestada por competência, com valores pleiteados | Relatório |
| `listar_vinculos_fap` | Vínculos contestados | Vínculos empregatícios contestados por competência | Relatório |
| `listar_rotatividade_fap` | Rotatividade contestada | Taxas de rotatividade contestadas (admissões, rescisões, vínculos) | Relatório |

### 🏛️ Processos Judiciais

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `listar_processos` | Processos judiciais | Processos com fase atual, partes e valor da causa | Sistema |
| `detalhar_processo` | Detalhe de um processo | Processo completo: histórico de fases, benefícios vinculados, teses e decisões | Sistema |

### 📖 Base de Jurisprudência

As decisões FAP do escritório (sentenças, acórdãos e embargos) — as mesmas da **Base de Conhecimento** do Painel de Processos.

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `pesquisar_jurisprudencia` | Pesquisar jurisprudência | Pesquisa por palavras (com sinônimos), expressão entre aspas ou **número do processo**, com filtros de tese, tribunal, resultado e instância; traz a **citação pronta** e o trecho encontrado. Também busca no **inteiro teor** | Sistema |
| `detalhar_decisao` | Detalhe de uma decisão | Tudo de uma decisão: motivo, ementa, fundamentos, argumentos acolhidos e rejeitados, precedentes e as outras peças do mesmo processo | Sistema |
| `panorama_jurisprudencia` | Chance de êxito por tese | "Qual a chance da tese X no TRF4?": resultados por tribunal e instância, processos que **viraram no acórdão** e as favoráveis mais recentes | Cálculo |
| `decisoes_parecidas` | Decisões parecidas | Decisões que discutem o mesmo ponto com outras palavras, por semelhança de conteúdo | IA |
| `valores_de_filtro_jurisprudencia` | Filtros da jurisprudência | Teses, tribunais, instâncias e resultados que existem na base, com contagem — a IA consulta antes de filtrar | Sistema |
| `exportar_jurisprudencia_excel` | Jurisprudência em Excel | Planilha com as decisões filtradas (teses, resultado, fundamentos, ementa, citação e link), até 50 mil linhas | Relatório |

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

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `listar_comunicacoes` | Publicações (DJEN) | Publicações com os filtros da tela: tribunal, tipo, advogado, **número do processo**, período e **só as não lidas** | Sistema |
| `detalhar_comunicacao` | Inteiro teor da publicação | O **inteiro teor** de uma publicação, com processo, órgão, destinatários, advogados intimados e link do documento original | Sistema |
| `explicar_comunicacao` | Explicar uma publicação | Explica a publicação em linguagem clara: **prazo**, providência exigida e **urgência** | IA |
| `comunicacoes_do_processo` | Publicações de um processo | **Linha do tempo** das publicações de um processo e se ele está no Painel de Processos; opcionalmente consulta o Diário de Justiça **ao vivo**, para processo fora do radar | Sistema |
| `resumo_monitoramento` | Resumo do monitoramento | Visão geral do período: total, não lidas, distribuição por tribunal e tipo, advogados monitorados e os que estão **fora do radar** | Cálculo |

> [!IA] A explicação é gerada **uma vez** por publicação e fica guardada: pedir de novo é instantâneo e não gasta IA. É apoio à triagem — confira sempre prazo e teor no processo oficial.

> [!INFO] A consulta **ao vivo** mostra o que o Diário de Justiça tem sobre o processo, mas **não grava** nada no sistema: o radar só guarda o que pertence às OABs monitoradas. Ela exige o número completo (20 dígitos).

### 📰 Diário Oficial da União

O Diário Oficial capturado todo dia pelo sistema (tela **Diário Oficial**): a pesquisa em todo o acervo, as edições e o sumário do dia, e o que é do escritório — os **clientes citados**, os **resultados de recurso FAP** publicados pelo CRPS e o que casou com as regras de **"O que vigiar"**.

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `pesquisar_dou` | Pesquisar no Diário Oficial | Pesquisa no acervo por texto, **CNPJ** ou **número de processo** (reconhecidos sozinhos, com ou sem pontuação), com filtros de seção, órgão, tipo de ato e período. Traz o trecho encontrado, o total real e a distribuição por seção, órgão e tipo | Sistema |
| `ler_materia_dou` | Ler uma matéria do DOU | O **inteiro teor** de uma matéria, com CNPJs e processos citados e os links: no sistema, na **folha do PDF assinado** e no portal da Imprensa Nacional. Se a matéria gerou alerta para o escritório, diz para quais clientes | Sistema |
| `valores_de_filtro_dou` | Filtros do Diário Oficial | Seções, órgãos e tipos de ato que existem no acervo, e o período coberto — a IA consulta antes de filtrar | Sistema |
| `ultimas_edicoes_dou` | Últimas edições do DOU | As últimas edições capturadas: matérias por seção, edições extras, PDF assinado e a **situação da captura** | Sistema |
| `sumario_edicao_dou` | Sumário da edição do dia | O **sumário da edição** de um dia, como o do portal da Imprensa Nacional: órgãos na ordem das páginas, com quantas matérias cada um publicou; com um órgão, as matérias dele no dia | Sistema |
| `resumo_dou_escritorio` | DOU para o escritório | O que o Diário Oficial trouxe **para o escritório** nas últimas edições — o mesmo conteúdo do e-mail diário: clientes citados, recursos FAP julgados e regras que casaram | Cálculo |
| `alertas_dou` | Alertas do Diário Oficial | Os alertas do escritório com os filtros da tela: lidos ou não, cliente, **resultado FAP** (deferimento, indeferimento), origem, seção, regra e período | Sistema |
| `detalhar_alerta_dou` | Detalhe de um alerta do DOU | Um alerta por inteiro: cada estabelecimento citado com o resultado FAP e as **linhas do edital** (processo, CNPJ, instância, resultado) | Sistema |
| `regras_dou` | Regras de "O que vigiar" | As regras de "O que vigiar": termo, órgão, seções, quem criou, quantos alertas cada uma gerou e quando casou pela última vez | Sistema |
| `testar_termo_dou` | Testar termo de vigilância | Quantos alertas por dia um termo geraria **antes** de virar regra, com exemplos — o mesmo teste da tela. Só consulta: a regra se cria na tela | Cálculo |

> [!DOU] **Use aspas para expressão ou sigla.** Sem aspas, a pesquisa procura as palavras soltas: "fator acidentário de prevenção" encontra **748** matérias; entre aspas, **7**. E "FAP" sem aspas traz também FAPESP, FAPEMIG e outras fundações. A IA é orientada a usar aspas, e a resposta avisa quando faltaram.

> [!ALERTA] **"Não saiu nada" pode ser captura atrasada.** A pesquisa só enxerga as edições que o sistema já capturou. A IA consulta `ultimas_edicoes_dou` e avisa quando a captura está parada ou com falha, em vez de concluir que nada foi publicado.

> [!INFO] O acervo do Diário Oficial é público e igual para todos; **alertas e regras são do escritório** e a IA só vê os do seu. Deferimento é ganho de causa (o FAP da empresa cai); indeferimento abre prazo para recorrer.

### 🔢 Como informar o número do processo

Em todas as ferramentas que buscam por processo (`listar_processos`, `listar_comunicacoes`, `comunicacoes_do_processo`), o número pode ser digitado **de qualquer jeito**:

| Você digita | Encontra |
|---|---|
| `5001181-56.2023.4.03.6100` | o processo |
| `50011815620234036100` | o mesmo processo |
| `5001181` | os processos com esse trecho — basta o número sequencial |

> [!ALERTA] São necessários **pelo menos 7 dígitos**. Um pedaço menor, como o ano `2023`, casaria com boa parte da base — a IA recebe o aviso e pede o número completo.

### 🧰 Utilidades

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `consultar_cnpj` | Consultar CNPJ na Receita | Dados cadastrais públicos de um CNPJ (Receita Federal): razão social, situação, endereço, sócios e **matriz/filial** | Sistema |

### 🔑 API do IntellexIA

Os mesmos dados destas ferramentas em formato de API, para montar telas, planilhas e scripts (por exemplo, no Claude Code). Veja o manual **API do IntellexIA**.

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `minha_api` | Minha API | Endereço da API, link da documentação e os **seus tokens** (só o final de cada um, situação, validade e último uso) | Sistema |
| `criar_token_api` | Criar token da API | Cria um **token pessoal** da API. Ele aparece uma vez só, na resposta: guarde numa variável de ambiente ou num `.env` fora do git | Sistema |
| `revogar_token_api` | Revogar token da API | Revoga um token seu: ele para de funcionar na hora | Sistema |
| `documentacao_api` | Documentação da API | As **rotas da API** com os parâmetros, uma por linha, e o endereço da documentação completa (OpenAPI) — para o Claude montar a integração sem sair da conversa | Sistema |

### 💬 Biblioteca de IA

Os prompts, agentes e skills que você e o escritório guardam na **Biblioteca de IA** do IntellexIA. Além destas ferramentas, cada item aparece como **comando pronto** (veja abaixo). Veja o manual **Biblioteca de IA**.

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `biblioteca_prompts` | Itens da Biblioteca de IA | Lista os **seus prompts e os do escritório** (recomendados primeiro), com busca — "tem algum prompt de resumo de sentença?" | Sistema |
| `usar_prompt` | Usar item da biblioteca | Entrega o texto pronto de um item da biblioteca com os **campos preenchidos**, e o Claude segue o roteiro | Sistema |
| `salvar_prompt` | Salvar na biblioteca | **Guarda na sua biblioteca** um prompt que acabou de funcionar na conversa ("salva isso como prompt"). Fica só para você, a menos que peça para compartilhar | Sistema |

### ✍️ Revisão de Petições

| Ferramenta | Nome | O que faz | Origem |
|---|---|---|---|
| `revisar_peticao_inicial` | Revisar petição inicial | Entrega ao Claude as **instruções do Revisor do escritório** (regras, manual FAP, casos de referência, pontos de atenção da última revisão) para ele **revisar a petição anexada ali na conversa**. A petição não vai para o IntellexIA; o Id Wrike é opcional | Sistema |
| `conferir_revisao_peticao` | Conferir revisão feita no Claude | Confere o resultado da revisão feita na conversa com o **mesmo saneador da tela** (tira duplicado, corrige contagem de dias, marca o que já foi descartado) e devolve os achados para o Claude mostrar. Guarda como rascunho por 24 h, fora do histórico, junto com a tabela dos **dados dos benefícios** conferidos com a base | Sistema |
| `conferir_planilha_beneficios` | Conferir planilha de benefícios | Confere se os benefícios da **planilha (.xlsx ou .csv)** foram citados na petição — a **mesma checagem da tela**, sem IA. O Claude recebe o script e roda com os arquivos anexados na conversa; numa revisão, o resultado vai junto na conferência e aparece na tela ao gravar | Sistema |
| `gravar_revisao_peticao` | Gravar revisão no histórico | Grava no histórico da petição a revisão conferida — **só se você disser que sim** —, com o selo **"Feita no Claude"**. Para petição nova, pede o Id Wrike. Depois, anexa os arquivos à revisão (ou mostra um link para você soltá-los) | Sistema |
| `mudar_status_peticao` | Mudar status da petição | Muda o status de uma petição do Revisor **quando você pede** (o Claude confirma antes), com as **mesmas regras da tela**: aprovar, devolver e reabrir só para administrador, e revisão "Feita no Claude" não vai para aprovação por quem não é admin | Sistema |
| `listar_peticoes_revisao` | Petições no Revisor | Petições do Revisor com o estágio de cada uma, nº de revisões e data da última — "o que está aguardando ajuste?" | Sistema |
| `detalhar_revisao` | Achados de uma revisão | Os achados de uma revisão **já feita**: gravidade, localização, correção sugerida e referência do manual. Enquanto processa, diz há quanto tempo | Sistema |
| `historico_revisoes_peticao` | Histórico de revisões | Evolução entre as revisões da mesma petição: o que foi resolvido, o que **reincidiu** e o que é novo | Sistema |
| `comparar_versoes_peticao` | Comparar versões da petição | Como `revisar_peticao_inicial`, para **duas versões anexadas** (original × revisada) — "a v2 corrigiu o que foi apontado?" | Sistema |
| `ler_manual_revisor` | Manual FAP do escritório | Lê o **manual FAP do escritório** (e casos de referência) por seção ou termo — é o que permite explicar um achado citando a régua real | Sistema |
| `versoes_manual_revisor` | Versões do manual do Revisor | Versões do manual e das referências: qual está ativa, quem criou e quando | Sistema |
| `auditoria_revisor` | Auditoria do Revisor | Quem fez o quê e quando no módulo | Sistema |
| `estatisticas_revisor` | Desempenho por advogado | Score, retrabalho e reincidência por advogado — **só para administradores** | Cálculo |

> [!IA] **Quem revisa é o Claude da sua conversa**, com as instruções do Revisor do escritório (manual e prompts ativos). Leva alguns minutos e gasta o limite do **seu plano do Claude**, não o do IntellexIA. A qualidade acompanha o modelo escolhido na conversa: prefira Sonnet ou Opus, e uma revisão por conversa.

> [!ALERTA] A revisão gravada pelo Claude leva o selo **"Feita no Claude"**: aparece no histórico da petição, mas **fica fora da pontuação dos advogados e não envia a petição para aprovação**. Para aprovar, a última revisão tem de ser feita pela tela do Revisor.

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
| `dou_do_dia` | O Diário Oficial de hoje para o escritório: recursos FAP julgados (com processo e CNPJ dos indeferidos), clientes citados, regras que casaram e os atos de previdência e trabalho da Seção 1 |
| `radar_regulatorio_fap` | O que mudou nas regras do FAP, NTEP e RAT no período (padrão 30 dias): normas, pautas de julgamento do CRPS e o que acompanhar, com o link da folha do PDF assinado |

**Os prompts da sua Biblioteca também viram comandos**: `meu_<tipo>_<nome>` para os seus e `escritorio_<tipo>_<nome>` para os compartilhados com o escritório (ex.: `escritorio_agente_triagem_publicacoes`), com os campos (`{{empresa}}`) como argumentos. Se um prompt novo não aparecer na lista, reconecte o conector ou peça ao Claude para usar a ferramenta `biblioteca_prompts`.

> [!INFO] `ficha_empresa` e `socios_empresa` **pedem o CNPJ** antes de executar, e consultam dados públicos da Receita. Sendo um CNPJ de **filial**, a resposta avisa — o quadro societário é sempre o da matriz. Em MEI e empresa individual, a resposta diz que não há sócios registrados, em vez de vir vazia.

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
| Diário Oficial da União (pesquisa, edições, alertas e "O que vigiar") | Diário Oficial |
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
