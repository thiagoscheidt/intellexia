# Manual do Usuário — Painel FAP

> Documentação funcional do módulo **Painel FAP**. Explica cada tela, cada coluna e **de onde vêm os dados**, com destaque para o significado das datas (especialmente a **Data D.O.U.**).

---

## O que é o Painel FAP

O **Painel FAP** é a ponte entre o IntellexIA e o **portal FAP Web (Dataprev)**. Ele:

1. **Sincroniza** empresas, procurações e contestações direto do portal oficial;
2. **Guarda** esses dados no sistema (para você não depender do portal a cada consulta);
3. **Baixa os PDFs** das contestações em lote;
4. **Exibe** tudo em telas organizadas, com filtros e exportação para Excel.

> [!INFO] **Importante:** as telas do Painel FAP mostram o que **já foi sincronizado**. Elas leem do banco do IntellexIA, não do portal ao vivo (exceto a verificação de sessão e o download de um PDF específico). Se um dado novo apareceu no portal e você ainda não sincronizou, ele não estará aqui.

### Como a autenticação funciona

Para conversar com o portal, o sistema usa os **dados de sessão** (cookies) que você cola na tela de Sincronização. Se a sessão expirar, aparece o aviso "sessão expirada" e você precisa colar os dados novamente.

---

## Sincronização automática (rotina de madrugada)

O Painel FAP **se mantém atualizado sozinho**. Todas as madrugadas, uma **rotina automática** roda no servidor e sincroniza o sistema com o portal FAP Web — sem ninguém precisar clicar em nada. Quando o time chega de manhã, os dados já estão atualizados.

A rotina executa nesta ordem:

1. **Confere a sessão do FAP.** Se as credenciais de acesso ao portal estiverem expiradas, a rotina **para por aí** e nada é sincronizado (é preciso atualizar os dados de autenticação — veja a Tela de Sincronização).
2. **Empresas** — traz as novas e atualiza as existentes. Empresas que saíram do portal são removidas, **exceto** as que já têm contestações no sistema (para não perder histórico).
3. **Procurações** — cria as novas e atualiza as existentes.
4. **Contestações** — varre **todas as empresas, ano a ano** (por padrão de 2010 até o ano atual), criando as novas e atualizando as que mudaram. Toda mudança fica registrada no histórico (aba "Atualizadas").
5. **PDFs** — baixa automaticamente os arquivos das contestações que ainda não têm PDF salvo (pula os que já existem em disco).

> [!INFO] **O que esperar no dia a dia:** você **não precisa sincronizar manualmente** — a rotina noturna já cuida disso. A **Tela de Sincronização** (abaixo) serve para casos pontuais: rodar uma sincronização na hora ou **atualizar as credenciais** quando a sessão do portal expira. Uma sessão expirada é, na prática, a única coisa que trava a rotina automática — quando isso acontece, os dados param de atualizar até alguém colar novos dados de acesso.

---

## Tela 1 — Sincronização

É a porta de entrada do módulo. Organizada em passos:

- **Passo 1 — Dados de autenticação:** você cola o JSON com os cookies da sua sessão do portal FAP. Um alerta indica se a conexão está ativa ou expirada.
- **Passo 2 — Empresas:** sincroniza a lista de empresas a que o escritório tem acesso no portal: as que deram procuração **e** as vinculadas ao acesso do escritório no gov.br. O sistema **adiciona as novas** e **remove as que sumiram** do portal — menos as que já têm contestação sincronizada, que ficam com o histórico.
- **Passo 3 — Procurações:** sincroniza as procurações eletrônicas.
- **Passo 4 — Contestações:** você escolhe empresa e ano e sincroniza as contestações. Também é aqui que dispara o **download dos PDFs em lote**.

A tabela de resultado ("Contestações sincronizadas") mostra: Vigência, CNPJ, Instância, Situação, Protocolo e **Transmissão** (data em que a contestação foi transmitida).

---

## Tela 2 — Empresas

Lista as empresas a que o escritório tem acesso no portal FAP — as que deram procuração e as vinculadas ao acesso do escritório no gov.br.

| Coluna | O que significa | De onde vem |
|---|---|---|
| **Empresa** | Razão social (com a raiz do CNPJ como subtítulo). | Portal FAP Web. |
| **CNPJ** | CNPJ formatado. | Portal FAP Web. |
| **Tipo de Procuração** | Tipo da procuração eletrônica. Mostra **Vinculada pelo e-gov** (com a data, "desde 28/02/2019") quando a empresa não tem procuração no FAP e o acesso vem de ela ter vinculado no gov.br o CPF de quem faz o login — caso do grupo Vale. Esse acesso depende do certificado usado no login: entrando com outro CPF, a empresa some da lista. | Portal FAP Web. |
| **Contestações** | Quantas contestações essa empresa tem no sistema. | Contagem no IntellexIA. |
| **Última Sync** | Quando as empresas foram sincronizadas pela última vez. | Registro interno. |
| **Ações** | Atalhos para os benefícios e para as contestações da empresa. | — |

O filtro **Acesso** separa as empresas pela origem do acesso: **Procuração no FAP** ou **Vinculada pelo e-gov**.

---

## Tela 3 — Contestações ⭐ (tela principal)

Esta é a tela mais rica do módulo. **Ela só mostra dados quando há pelo menos um filtro ativo** — sem filtro, aparece vazia. Isso evita carregar tudo de uma vez.

### Cartões de estatística (calculados sobre TODO o resultado filtrado)

- **Total** — total de contestações no filtro.
- **Inst. em Andamento (1ª/2ª)** e **Inst. Transmitidas (1ª/2ª)** — separam por instância e por situação.
- **Recursos** — contestações de 2ª instância.
- **Arq. Local / Sem Arq. Local** — quantas já têm (ou não) o PDF baixado.
- **Barra de benefícios processados/pendentes** — quantas contestações já foram transformadas em benefícios no Centro de Contestações.

### Filtros disponíveis

Vigência (ano), CNPJ Raiz, Estabelecimento (CNPJ completo), Instância, Situação, Protocolo, e **Ordenar por**. A ordenação pode ser por: Publicação D.O.U. (mais recente), Transmissão, Cadastro ou Última atualização.

### Como a tabela é organizada

A tabela é **agrupada por Vigência × Estabelecimento (CNPJ)**. Cada linha reúne as contestações daquela empresa naquele ano, separadas em **quatro quadrantes**:

| Quadrante | O que reúne |
|---|---|
| **1ª Instância — Em Andamento** | Contestação de 1ª instância ainda em tramitação. |
| **1ª Instância — Transmitidas** | Contestação de 1ª instância já transmitida/concluída. |
| **2ª Instância — Em Andamento** | Recurso (2ª instância) ainda em tramitação. |
| **2ª Instância — Transmitidos** | Recurso (2ª instância) já transmitido/concluído. |

> **Como o sistema decide "Em Andamento" vs "Transmitida":** ele lê o texto da situação vindo do portal. Situações que falam em "andamento" ou "prazo" (e não em "transmitido", "resultado" ou "divulgado") são tratadas como **em andamento**. É uma leitura automática do texto do próprio portal.

### O que aparece em cada contestação (dentro do quadrante)

- **Protocolo** — número do protocolo da contestação (do portal).
- **Situação** — texto da situação (do portal).
- **Data D.O.U.** (ícone de jornal) — ver seção destacada abaixo.
- **Deferimento** — resultado do julgamento (ex.: "Deferimento Parcial"), quando já houve.
- **Badge "Local"** — indica que o PDF já está salvo no sistema.
- **Ações** — visualizar/baixar o PDF, ver histórico e ver detalhes.

### Modal de Detalhes — o "raio-x" da contestação

Ao abrir os detalhes, você vê todos os campos que o portal fornece, incluindo várias datas. **Aqui é onde fica clara a diferença entre datas passadas e futuras:**

| Campo | O que é | Passado ou futuro |
|---|---|---|
| **Data Inicial** | Início da contestação. | Passado |
| **Data Transmissão** | Quando a contestação foi transmitida. | Passado |
| **Publicação D.O.U.** | Publicação do resultado no Diário Oficial. | Passado ou futuro (se programado) |
| **Fim Prazo 1ª Instância** | Prazo final para agir na 1ª instância. | **Futuro** (é um prazo) |
| **Fim Prazo 2ª Instância** | Prazo final para agir na 2ª instância. | **Futuro** (é um prazo) |
| **Liberação de Análise** | Quando a análise foi liberada. | Passado |

Também há campos de responsável, e-mail, observação, efeito suspensivo e indicadores de prazo aberto.

---

## ⭐ A Data D.O.U. — explicada em detalhe

Esta é a data que gera mais dúvidas, então vale um destaque.

> [!DOU] **Data D.O.U. = data de publicação do resultado no Diário Oficial da União.** Vem do sistema FAP. **Geralmente já ocorreu, mas pode ser futura** quando a publicação foi programada. Nunca é um prazo de ação.

- **O que é:** **Data de Publicação no Diário Oficial da União (D.O.U.)**. É o dia em que o **resultado/julgamento da contestação é publicado oficialmente**.
- **De onde vem:** é o campo `dataDOU`, informado pelo **próprio portal/sistema FAP**. O IntellexIA apenas copia — não inventa nem calcula essa data.
- **É passada ou futura?** ➜ **Geralmente passada, mas pode ser futura.** Na maioria das vezes marca uma publicação que **já ocorreu**; porém, quando o sistema FAP **programa** a publicação para uma data ainda por vir, a Data D.O.U. aponta para o **futuro**. Em nenhum caso é um prazo de ação.
- **Quando ela existe:** quando o resultado é publicado ou tem publicação programada. Enquanto a contestação está em andamento e sem previsão de publicação, ela **não tem** Data D.O.U.

> [!ALERTA] **Não confundir:**
> - **Data D.O.U.** = quando o resultado *é publicado* no Diário Oficial (já ocorrida ou programada).
> - **Fim de Prazo (1ª/2ª instância)** = até quando você *pode agir* (prazo futuro).
> - **Data Transmissão** = quando a contestação *foi enviada* (passado).

---

## Tela 4 — Procurações

Lista as procurações eletrônicas sincronizadas, uma linha por procuração.

### Cartões

Total, Deferidas, Excluídas, Indeferidas, **"Vencem em 30 dias"** (procurações deferidas cuja vigência termina nos próximos 30 dias) **"Empresas sem procuração vigente"** e **"Vinculadas pelo e-gov"** (empresas acessadas só pelo vínculo gov.br, sem procuração no FAP). Os dois últimos são clicáveis e filtram a tela.

### Colunas

| Coluna | O que significa |
|---|---|
| **Protocolo** | Protocolo da procuração. |
| **Tipo** | Tipo da procuração. |
| **Situação** | Deferida / Indeferida / Excluída (com cor). |
| **Empresa outorgante** | Empresa que concede a procuração (com CNPJ raiz). |
| **Outorgado** | Quem recebe a procuração (CPF ou CNPJ). |
| **Vigência início / fim** | Período de validade. A data de fim ganha alerta de cor quando está vencida ou perto de vencer. |
| **Data cadastro** | Quando a procuração foi cadastrada no portal. |

### Empresas sem procuração vigente

Além das procurações, a tela mostra as **empresas da Tela 2 que hoje não têm nenhuma procuração valendo** — isto é, nenhuma procuração Deferida dentro do período de vigência. Cada empresa aparece em **uma linha destacada**, e a situação separa dois casos:

- **Vinculada pelo e-gov** (linha azul) — a empresa não tem procuração, mas o escritório tem acesso pelo vínculo gov.br do CPF do login, como o grupo Vale. A coluna **Vigência início** mostra a data em que a empresa fez o vínculo, e **Vigência fim** aparece como "não informada": o gov.br não divulga a validade do vínculo — só a própria empresa vê, entrando com o e-CNPJ dela.
- **Sem procuração vigente** (linha laranja) — a empresa não tem procuração valendo nem vínculo e-gov. Logo abaixo, o motivo:

- **Nunca teve procuração** — a empresa está no Painel FAP sem nunca ter dado procuração.
- **Última: Expirada / Excluída** — a empresa já teve procuração; as colunas de vigência mostram as datas da última.

Onde elas aparecem:

- **Na lista geral**, entram só as empresas que **nunca tiveram** procuração. As demais já estão na lista pelas próprias procurações expiradas.
- Clicando no cartão **"Empresas sem procuração vigente"** (ou escolhendo essa opção no filtro **Situação**), a tela passa a mostrar **uma linha por empresa**, com todas as que estão sem procuração vigente — é a lista de quem precisa renovar. As vinculadas pelo e-gov não entram aqui: elas têm acesso.
- Clicando no cartão **"Vinculadas pelo e-gov"** (ou escolhendo **Vinculada pelo e-gov** no filtro **Situação**), aparecem só as empresas acessadas pelo vínculo gov.br — como o grupo Vale —, com a data em que cada uma fez o vínculo.

> [!ALERTA]
> Quando a procuração expira e a empresa não tem vínculo no gov.br, o portal deixa de liberar as contestações dela: os dados já sincronizados continuam no sistema, mas param de ser atualizados.

A exportação para Excel acompanha o que está na tela, incluindo essas linhas.

---

## Tela 5 — Benefícios do cálculo FAP

Lista **todos os benefícios (B91, B92, B93 e B94) e CATs que o portal usou nos cálculos FAP** das empresas do Painel FAP — de todas as vigências e estabelecimentos, uma linha por item. É o retrato do cálculo do portal, não das contestações: aqui aparece também o que o escritório nunca contestou.

### Filtros

**Vigência**, **Grupo**, **Empresa** (CNPJ raiz), **Estabelecimento** (CNPJ de 14 dígitos), uma busca por **CPF, NIT, NB ou número da CAT** (com ou sem pontuação), os botões de **Tipo** (B91, B92, B93, B94, CAT), **No cálculo atual** e **Contestado**. A tela só pesquisa ao clicar em :btn-primary[Pesquisar].

### Cartões

Total de itens do filtro, quantidade por espécie de benefício, CATs, **excluídos no recálculo** e **não contestados**. Os cartões acompanham os filtros escolhidos.

### Colunas

| Coluna | O que significa |
|---|---|
| **Vig.** | Vigência do cálculo. O mesmo número em vigências diferentes é uma linha para cada. |
| **Estabelecimento** | CNPJ de 14 dígitos e nome da empresa. |
| **Tipo** | B91, B92, B93, B94 ou CAT. |
| **NB / nº CAT** | Número do benefício ou da CAT. |
| **NIT · CPF** | Identificação do segurado, mostrada inteira. |
| **Nasc., RMI, Total pago** | Nascimento, renda mensal inicial e total pago no benefício (nas CATs não se aplicam). |
| **Início → Cessação** | Período do benefício; na CAT, a data do acidente. |
| **No cálculo atual** | **Conta** (o portal usa o item no cálculo) ou **Excluído** (veja abaixo). |
| **Contestado** | **Sim** quando o item já está na Central de Contestações, com o link **ver** para o benefício. |

Clicando na seta ao fim da linha, a linha se expande e mostra o restante: despacho, período de contabilização, bloqueio e o cálculo de origem; para a CAT, data de cadastro, data de óbito, CNPJ original e atribuído e o recibo do eSocial.

> [!INFO]
> **Excluído** quer dizer que o próprio portal tirou o item do cálculo no recálculo — em geral porque uma contestação foi acatada. O item continua listado aqui para não se perder o histórico.

> [!INFO]
> **Contestado** significa que o **mesmo número** existe na Central de Contestações **na mesma vigência**. O mesmo NB em outra vigência não conta: ele aparece como **Não** até ser contestado naquela vigência.

---

## Exportações para Excel

A tela de Contestações permite exportar:

- **Por Contestação** — uma linha por contestação, com os campos principais e a Data de Transmissão.
- **Conforme a Listagem (Agrupado)** — espelha a tabela agrupada por Vigência × Estabelecimento, com as quantidades de cada quadrante.

---

## Glossário rápido

| Termo | Significado |
|---|---|
| **FAP** | Fator Acidentário de Prevenção — índice que ajusta a alíquota previdenciária da empresa. |
| **Vigência** | Ano de referência do FAP contestado. |
| **1ª / 2ª Instância** | Fases da contestação. 2ª instância = recurso. |
| **D.O.U.** | Diário Oficial da União (onde o resultado é publicado). |
| **Deferimento** | Resultado do julgamento (deferido, indeferido, parcial). |
| **Procuração** | Autorização eletrônica para o escritório atuar em nome da empresa. |
