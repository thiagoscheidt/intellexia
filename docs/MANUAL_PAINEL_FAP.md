# Manual do Usuário — Painel FAP

> Documentação funcional do módulo **Painel FAP**. Explica cada tela, cada coluna e **de onde vêm os dados**, com destaque para o significado das datas (especialmente a **Data D.O.U.**).

---

## O que é o Painel FAP

O **Painel FAP** é a ponte entre o IntellexIA e o **portal FAP Web (Dataprev)**. Ele:

1. **Sincroniza** empresas, procurações e contestações direto do portal oficial;
2. **Guarda** esses dados no sistema (para você não depender do portal a cada consulta);
3. **Baixa os PDFs** das contestações em lote;
4. **Exibe** tudo em telas organizadas, com filtros e exportação para Excel.

> **Importante:** as telas do Painel FAP mostram o que **já foi sincronizado**. Elas leem do banco do IntellexIA, não do portal ao vivo (exceto a verificação de sessão e o download de um PDF específico). Se um dado novo apareceu no portal e você ainda não sincronizou, ele não estará aqui.

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

> **O que esperar no dia a dia:** você **não precisa sincronizar manualmente** — a rotina noturna já cuida disso. A **Tela de Sincronização** (abaixo) serve para casos pontuais: rodar uma sincronização na hora ou **atualizar as credenciais** quando a sessão do portal expira. Uma sessão expirada é, na prática, a única coisa que trava a rotina automática — quando isso acontece, os dados param de atualizar até alguém colar novos dados de acesso.

---

## Tela 1 — Sincronização

É a porta de entrada do módulo. Organizada em passos:

- **Passo 1 — Dados de autenticação:** você cola o JSON com os cookies da sua sessão do portal FAP. Um alerta indica se a conexão está ativa ou expirada.
- **Passo 2 — Empresas:** sincroniza a lista de empresas com procuração. O sistema **adiciona as novas** e **remove as que sumiram** do portal.
- **Passo 3 — Procurações:** sincroniza as procurações eletrônicas.
- **Passo 4 — Contestações:** você escolhe empresa e ano e sincroniza as contestações. Também é aqui que dispara o **download dos PDFs em lote**.

A tabela de resultado ("Contestações sincronizadas") mostra: Vigência, CNPJ, Instância, Situação, Protocolo e **Transmissão** (data em que a contestação foi transmitida).

---

## Tela 2 — Empresas

Lista as empresas com procuração cadastrada.

| Coluna | O que significa | De onde vem |
|---|---|---|
| **Empresa** | Razão social (com a raiz do CNPJ como subtítulo). | Portal FAP Web. |
| **CNPJ** | CNPJ formatado. | Portal FAP Web. |
| **Tipo de Procuração** | Tipo da procuração eletrônica. | Portal FAP Web. |
| **Contestações** | Quantas contestações essa empresa tem no sistema. | Contagem no IntellexIA. |
| **Última Sync** | Quando as empresas foram sincronizadas pela última vez. | Registro interno. |
| **Ações** | Atalhos para os benefícios e para as contestações da empresa. | — |

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

- **O que é:** **Data de Publicação no Diário Oficial da União (D.O.U.)**. É o dia em que o **resultado/julgamento da contestação é publicado oficialmente**.
- **De onde vem:** é o campo `dataDOU`, informado pelo **próprio portal/sistema FAP**. O IntellexIA apenas copia — não inventa nem calcula essa data.
- **É passada ou futura?** ➜ **Geralmente passada, mas pode ser futura.** Na maioria das vezes marca uma publicação que **já ocorreu**; porém, quando o sistema FAP **programa** a publicação para uma data ainda por vir, a Data D.O.U. aponta para o **futuro**. Em nenhum caso é um prazo de ação.
- **Quando ela existe:** quando o resultado é publicado ou tem publicação programada. Enquanto a contestação está em andamento e sem previsão de publicação, ela **não tem** Data D.O.U.

> **Não confundir:**
> - **Data D.O.U.** = quando o resultado *é publicado* no Diário Oficial (já ocorrida ou programada).
> - **Fim de Prazo (1ª/2ª instância)** = até quando você *pode agir* (prazo futuro).
> - **Data Transmissão** = quando a contestação *foi enviada* (passado).

---

## Tela 4 — Procurações

Lista as procurações eletrônicas sincronizadas.

### Cartões

Total, Deferidas, Excluídas, Indeferidas e **"Vencem em 30 dias"** (procurações deferidas cuja vigência termina nos próximos 30 dias).

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
