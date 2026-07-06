# Manual do Usuário — Painel de Contestações (Centro de Contestações)

> Documentação funcional do módulo **Centro de Contestações**. Explica cada tela, cada coluna e **de onde vêm os dados**, em linguagem de negócio.

---

## O que é o Painel de Contestações

O **Centro de Contestações** organiza tudo que foi **contestado no FAP** e já teve **relatório de julgamento** analisado. Diferente do Painel FAP (que conversa com o portal ao vivo), aqui os dados vêm de outra fonte:

> [!INFO] **De onde vêm os dados deste módulo:** de **PDFs de "Relatório de Julgamento de Contestação do FAP"**. Esses PDFs são enviados na tela de **Relatórios** (ou trazidos pela **Importação Automática**) e uma **IA extrai** deles os benefícios, CATs, massas salariais, vínculos e taxas de rotatividade. Ou seja: o conteúdo que você vê nas listas foi **lido automaticamente dos relatórios**, não digitado à mão (embora tudo possa ser editado manualmente depois).

Todos os dados são do **seu escritório** — você nunca vê dados de outro.

---

## Como o status funciona (vale para todas as telas)

Cada item contestado tem **status em duas instâncias**: 1ª e 2ª. O sistema padroniza os textos dos relatórios em quatro situações:

| Status | Significado |
|---|---|
| **Deferido** | A contestação foi aceita. |
| **Indeferido** | A contestação foi negada. |
| **Em análise** | Ainda sendo analisada. |
| **Pendente** | Sem decisão registrada ainda. |

- O **"Status geral"** de um item prioriza a **2ª instância**; se não houver decisão de 2ª, usa a **1ª**; se não houver nenhuma, fica **Pendente**.
- Abaixo do status padronizado, o sistema costuma mostrar o **texto original do relatório**, para você conferir a fonte.

---

## Tela 1 — Benefícios

A tela principal. Lista os **benefícios contestados** (auxílios que entraram na conta do FAP).

### Cartões de estatística

Há dois conjuntos de cartões:

- **Painel geral** — considera **toda a base** do escritório (ignora filtros).
- **Painel filtrado** — recalcula os mesmos números **conforme os filtros aplicados**.

Em ambos: Total, Deferidos, Indeferidos, Em análise, Pendentes, Categorizados e Sem categoria. Os cartões de Deferidos/Indeferidos trazem um detalhamento por 1ª e 2ª instância.

### Colunas da tabela

| Coluna | O que significa | De onde vem |
|---|---|---|
| **ID** | Identificador interno do benefício. | Sistema |
| **Número / NIT / Tipo** | Nº do benefício, **NIT** do segurado e **tipo** (B91, B94 etc.). | Relatório |
| **Segurado** | Nome, CPF e data de nascimento do segurado. | Relatório |
| **CNPJ Empregador** | CNPJ e nome da empresa empregadora. | Relatório |
| **Status 1ª instância** | Deferido/Indeferido/Em análise/Pendente + texto original abaixo. | Relatório |
| **Status 2ª instância** | Mesmo esquema, para o recurso. | Relatório |
| **Vigência FAP** | Ano(s) de vigência FAP afetados por esse benefício. | Relatório |
| **Categoria FAP** | Categoria/tópico da contestação, atribuída pela **IA** (ex.: "Erro de Estabelecimento"). Se vazio, aparece o botão **Classificar**; se preenchido, **Reclassificar**. | IA |
| **DIB / DCB** | **DIB** = Data de Início do Benefício; **DCB** = Data de Cessação do Benefício (datas passadas). | Relatório |
| **Ações** | Ver decisões, editar, excluir, ver linha do tempo. | — |

> **Sobre DIB e DCB:** são datas do próprio benefício (quando começou e quando cessou). São sempre **datas passadas** — não são prazos.

### Filtros

Por texto em vários campos, por Cliente, por CNPJ (raiz ou completo), por Status geral e por Categoria FAP (todos / com categoria / sem categoria).

### Modais úteis

- **Decisões do Benefício** — um mesmo benefício pode ter **várias decisões** (por exemplo, uma para a CAT e outra para "nexo técnico sem CAT"). Aqui você vê cada decisão com sua instância, status, justificativa e parecer.
- **Linha do tempo de arquivos** — histórico de todos os documentos e edições daquele benefício. As datas aqui são de **transmissão** e **publicação** dos documentos (eventos passados).

---

## Tela 2 — Vigências

Agrupa as contestações por **vigência** (combinação de CNPJ do empregador + ano) e vincula cada uma ao **cliente** correspondente.

| Coluna | O que mostra |
|---|---|
| **Vigência** | Ano de vigência FAP. |
| **Benefícios / CATs / Massas / Vínculos / Taxa Rot.** | Quantos itens de cada tipo existem naquela vigência. |
| **Status 1ª instância** | Resumo (deferido/indeferido/em análise/pendente) dos benefícios daquela vigência na 1ª instância. |
| **Status 2ª instância** | Mesmo resumo para a 2ª instância. |
| **Ações** | Atalhos para cada lista (benefícios, CATs etc.) já filtrada por aquela vigência. |

### Botão "Marcar 1ª instância como deferido"

Aparece quando a vigência **já tem movimentação em 2ª instância** e ainda há benefícios de 1ª instância sem decisão. Ele marca, **de uma vez**, esses benefícios como deferidos em 1ª instância (registrando no histórico que foi uma ação manual). Serve para agilizar quando o caso já subiu de instância.

---

## Telas 3 a 6 — CATs, Massa Salarial, Vínculos e Rotatividade

São quatro listas com a **mesma estrutura** (status 1ª/2ª instância, filtros, edição e exportação Excel). Todas vêm da extração dos relatórios de julgamento. O que muda são as colunas específicas de cada tipo:

### CATs (Comunicações de Acidente de Trabalho)

| Coluna | O que significa |
|---|---|
| **CAT** | Número da Comunicação de Acidente de Trabalho. |
| **Vigência** | Ano de vigência FAP. |
| **Empregador** | CNPJ da CAT e o CNPJ do empregador atribuído. |
| **NIT Segurado** | Número de Identificação do Trabalhador. |
| **Data Acidente / CAT** | Data do acidente e data de registro da CAT (passadas). |
| **Bloqueio** | Indica se há bloqueio (Sim/Não). |

### Massa Salarial

| Coluna | O que significa |
|---|---|
| **CNPJ Empregador** | Empresa. |
| **Competência** | Mês/ano de referência (ex.: 11/2023). |
| **Total Remunerações** | Valor total de remunerações. |
| **Valor Solicitado (1ª)** | Valor de massa salarial pedido na contestação de 1ª instância. |

### Número Médio de Vínculos

| Coluna | O que significa |
|---|---|
| **Competência** | Mês/ano de referência. |
| **Quantidade Original** | Número de vínculos original. |
| **Qtd Solicitada (1ª)** | Número de vínculos pedido na contestação de 1ª instância. |

### Taxa Média de Rotatividade

| Coluna | O que significa |
|---|---|
| **Ano** | Ano de referência. |
| **Taxa Rot. (%)** | Taxa de rotatividade. |
| **Admissões** | Nº de admissões (o formulário de edição também tem rescisões e vínculos no início do ano). |

---

## Tela 7 — Relatórios de Contestação FAP (upload)

É a tela onde tudo começa: você **envia os PDFs** dos relatórios de julgamento. Formatos aceitos: PDF, DOC, DOCX, TXT, XLSX, XLS.

| Coluna | O que mostra |
|---|---|
| **Arquivo** | Nome do arquivo enviado. |
| **Status** | Pendente → Na fila → Processando → Concluído (ou Erro). |
| **Upload** | Quando foi enviado. |

Ao processar, a IA extrai os benefícios, CATs, massas, vínculos e taxas — que passam a aparecer nas telas anteriores. O sistema também **evita duplicar** o mesmo arquivo (reconhece arquivos idênticos já enviados).

---

## Tela 8 — Importação Automática FAP

Atalho que conversa com o **portal FAP Web ao vivo** para trazer contestações sem precisar baixar o PDF manualmente.

- **Empresas** — lista CNPJ raiz, razão social e tipo de procuração.
- **Contestações e Recursos** — separadas em: Contestações em Andamento, Contestações Transmitidas, Recursos em Andamento, Recursos Transmitidos. Cada célula mostra a situação e o protocolo vindos do portal.
- Ao **importar** uma contestação, o sistema baixa o PDF e cria automaticamente um relatório de julgamento — que segue o mesmo fluxo da tela de Relatórios.

---

## A Categoria FAP e a classificação por IA

A coluna **Categoria FAP** (na tela de Benefícios) é preenchida por uma **IA classificadora**.

- A IA escolhe uma ou mais categorias de uma **lista fechada** (cerca de 20 tópicos), como "Erro de Estabelecimento", "Pré-FAP", "Nexo Afastado", "Restabelecimento de Benefício – B91 60 dias", entre outros.
- **Regra de confiança:** a IA só atribui uma categoria quando tem **confiança de pelo menos 80%**. Se ficar abaixo disso, o benefício permanece **sem categoria** (para não classificar errado).
- Um mesmo benefício pode receber **mais de uma categoria**.
- A categoria pode ser gerada pelo botão **Classificar** e refeita com **Reclassificar**.

> **Configuração avançada (apenas administradores):** o texto do prompt da IA, o material de referência jurídica e o modelo usado são **configuráveis por escritório**, com histórico de versões. Isso permite ajustar a classificação sem mexer no sistema.

---

## Glossário rápido

| Termo | Significado |
|---|---|
| **Benefício B91** | Auxílio-doença acidentário. |
| **Benefício B94** | Auxílio-acidente. |
| **NIT** | Número de Identificação do Trabalhador. |
| **CAT** | Comunicação de Acidente de Trabalho. |
| **DIB / DCB** | Data de Início / de Cessação do Benefício. |
| **Vigência** | Ano de referência do FAP contestado. |
| **1ª / 2ª Instância** | Fases da contestação (2ª = recurso). |
| **Categoria FAP** | Tópico jurídico da contestação, atribuído pela IA. |
