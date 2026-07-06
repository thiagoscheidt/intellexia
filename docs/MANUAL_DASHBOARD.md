# Manual do Usuário — Dashboard Principal

> Documentação funcional da tela inicial do IntellexIA. Explica **o que cada número/gráfico significa** e **de onde o dado vem**, em linguagem de negócio.

---

## O que é esta tela

O **Dashboard Principal** é a visão geral do escritório. Ele reúne, em uma única página, os principais indicadores de quatro frentes do sistema:

1. **Painel FAP** — contestações baixadas do portal FAP Web (Dataprev).
2. **Centro de Contestações** — benefícios e itens contestados extraídos dos relatórios de julgamento.
3. **Painel Judicial** — processos judiciais.
4. **Base de Conhecimento** — documentos do escritório.

### Regras que valem para a tela inteira

- **Tudo é do seu escritório.** Todos os números respeitam o escritório em que você está logado. Você nunca vê dados de outro escritório.
- **Se algo falhar ao carregar, os números aparecem zerados** e uma mensagem de erro é exibida. Zerado aqui significa "não consegui carregar", não necessariamente "não existe".

---

## 1. Painel FAP — Contestações FAP Web

Quatro cartões no topo desta seção:

| Cartão | O que significa | De onde vem |
|---|---|---|
| **Total de Contestações** | Quantas contestações foram baixadas do FAP Web para o seu escritório. | Contagem de todas as contestações sincronizadas. |
| **Com PDF Baixado** | Quantas dessas já tiveram o arquivo PDF baixado e guardado no sistema. O rodapé mostra o **% do total**. | Contestações que têm um arquivo local salvo. |
| **Sem PDF** | Quantas ainda não tiveram o PDF baixado. | É simplesmente *Total − Com PDF*. |
| **Vigências Cadastradas** | Quantos **anos de vigência FAP** distintos existem nas contestações. O rodapé mostra o ano mais recente. | ⚠️ **Mostra no máximo 5 anos** (os 5 mais recentes). Se houver mais de 5 anos, o número fica limitado a 5. |

### Gráficos FAP

| Gráfico | O que mostra | Observação importante |
|---|---|---|
| **Contestações por Situação** | Distribuição das contestações pela situação (rótulo textual vindo do FAP Web). | Sem situação → aparece como "Indefinida". |
| **Contestações por Ano de Vigência** | Quantas contestações por ano de vigência FAP. | ⚠️ Limitado aos **5 anos mais recentes**. |
| **Contestações por Status de Deferimento** | Deferido / Indeferido / Parcial / Sem julgamento. Tem um seletor para filtrar por empresa. | O status de deferimento vem do resultado do julgamento informado pelo FAP Web. Contestações ainda não julgadas caem em **"Sem julgamento"**. |
| **Contestações por Situação — por Empresa** | Mesma distribuição de situação, mas separada por empresa (CNPJ). | O nome da empresa só aparece se ela estiver cadastrada; senão aparece o CNPJ. |

---

## 2. Contestações FAP — recentes (painel com 3 abas) ⭐

Este é o painel que costuma gerar dúvida sobre **"a data da coluna da esquerda"**. Ele tem **três abas**, e **cada aba mostra uma data de natureza diferente**. Preste atenção ao título da coluna de data:

### Aba "Publicadas no D.O.U." (aba padrão)

> [!DOU] A data desta aba é a **Publicação no Diário Oficial da União** — quando o resultado da contestação foi (ou será) publicado. Vem do sistema FAP; geralmente já ocorreu, mas pode ser futura se a publicação foi programada.

- **Coluna de data: "Publicação D.O.U."**
- **O que é essa data:** é a data de **publicação do resultado da contestação no Diário Oficial da União (D.O.U.)**.
- **É passada ou futura?** ➜ **Normalmente é uma data passada** (o resultado já foi publicado), **mas pode ser futura** quando a publicação foi **programada** para uma data ainda por vir. Essa data vem do **sistema FAP**, que pode agendar a publicação no D.O.U. **Não é um prazo de ação.**
- **De onde vem:** é o campo `dataDOU`, informado pelo próprio **portal FAP Web**. O IntellexIA apenas copia essa data — não a calcula.
- A aba lista as contestações **da data de publicação mais recente para a mais antiga** (até 20 itens). Uma contestação ganha Data D.O.U. quando o resultado é publicado ou tem publicação programada.

### Aba "Cadastradas"

- **Coluna de data: "Cadastrada em"**
- **O que é:** a data em que **o registro foi trazido para dentro do IntellexIA** (quando você sincronizou e ele entrou no sistema). É uma data de controle interno, **não** tem relação com o D.O.U.

### Aba "Atualizadas"

- **Coluna de data: "Atualizada em"** + coluna extra **"Alterou"**
- **O que é a data:** a última vez que uma sincronização detectou **mudança real** naquela contestação (ex.: mudou a situação, saiu o resultado, etc.).
- **Coluna "Alterou":** mostra, em linguagem amigável, **o que mudou** na última atualização (ex.: "Situação", "Publicação D.O.U.").

### Colunas comuns às três abas

Empresa/CNPJ, Protocolo, Instância (1ª ou 2ª), Situação, Vigência e um botão **Ações** que leva ao Painel FAP já filtrado por aquela vigência e empresa.

---

## 3. Centro de Contestações — Benefícios Contestados

Quatro cartões sobre os **benefícios** extraídos dos relatórios de julgamento:

| Cartão | O que significa |
|---|---|
| **Total de Benefícios** | Quantos benefícios contestados existem no escritório. |
| **Classificados por IA** | Quantos benefícios já receberam a **categoria FAP** atribuída pela IA. O rodapé mostra o % classificado. |
| **1ª Instância — Deferidos** | Benefícios cuja 1ª instância foi deferida. |
| **1ª Instância — Indeferidos** | Benefícios cuja 1ª instância foi indeferida. |

---

## 4. Contadores de outras categorias contestadas

Quatro cartões, cada um é a **contagem** de itens daquela categoria no escritório:

| Cartão | O que conta |
|---|---|
| **CATs** | Comunicações de Acidente de Trabalho contestadas. |
| **Massas Salariais** | Massas salariais contestadas. |
| **Vínculos Médios** | Número médio de vínculos contestado. |
| **Taxas de Rotatividade** | Taxas de rotatividade contestadas. |

---

## 5. Gráficos de Benefícios

| Gráfico | O que mostra |
|---|---|
| **Benefícios por Categoria FAP** | Quantos benefícios em cada categoria/tópico FAP (ex.: "Erro de Estabelecimento", "Pré-FAP"). Sem categoria → "Não classificado". |
| **Status por Instância** | Compara 1ª e 2ª instância nos status Deferidos / Indeferidos / Em análise / Pendentes. |

---

## 6. Painel Judicial — Processos Judiciais

| Cartão | O que conta |
|---|---|
| **Total de Processos** | Todos os processos judiciais do escritório. |
| **Ativos** | Processos com status "ativo". |
| **Suspensos** | Processos com status "suspenso". |
| **Encerrados** | Processos com status "encerrado". |

Os rodapés são atalhos que abrem o Painel de Processos já filtrado por aquele status.

---

## 7. Base de Conhecimento do Escritório

| Métrica | O que significa |
|---|---|
| **Documentos** | Documentos ativos na base de conhecimento. |
| **Categorias** | Categorias ativas cadastradas. |
| **Tags únicas** | Quantidade de tags distintas usadas nos documentos. |

---

## Guia rápido de datas (para não confundir)

| Onde aparece | Nome | O que é | Passado ou futuro |
|---|---|---|---|
| Aba "Publicadas no D.O.U." | **Publicação D.O.U.** | Publicação do resultado no Diário Oficial. | Passado (ou futuro, se programado) |
| Aba "Cadastradas" | **Cadastrada em** | Quando entrou no IntellexIA. | Passado |
| Aba "Atualizadas" | **Atualizada em** | Última mudança detectada na sincronização. | Passado |

A maioria das datas do dashboard é de **eventos que já ocorreram**. A exceção é a **Publicação D.O.U.**, que pode apontar para o **futuro** quando a publicação foi programada. As datas de **prazo de ação** (Fim de Prazo de 1ª/2ª instância) aparecem no **Painel FAP**, nos detalhes de cada contestação.
