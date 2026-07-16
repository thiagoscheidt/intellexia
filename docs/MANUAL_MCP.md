# Manual do Usuário — Conectar sua IA ao IntellexIA (MCP)

> O IntellexIA pode ser acessado por assistentes de IA — como o **Claude** — por meio do protocolo **MCP** (Model Context Protocol). Depois de conectar, você conversa com a IA e ela consulta **os dados do seu escritório** no IntellexIA: base de conhecimento, painel FAP, contestações, processos e mais — com **18 ferramentas** organizadas por área.

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
- "Quem é o CNPJ 59.104.422/0103-84?" — consulta pública da Receita.

---

## Endereço do servidor

```
https://rs-dev.intellexia.com.br/mcp
```

Use exatamente este endereço (sem barra no final).

---

## Conectar no Claude Code

1. No terminal, adicione o servidor:

   ```
   claude mcp add --transport http intellexia https://rs-dev.intellexia.com.br/mcp
   ```

2. Dentro do Claude Code, digite `/mcp`, selecione **intellexia** e escolha **Authenticate**.
3. O navegador abre no IntellexIA:
   - **Já logado?** Aparece a tela **"Autorizar acesso"** — clique em **Autorizar**.
   - **Não logado?** Faça login normalmente; a tela de autorização aparece em seguida.
4. Volte ao Claude Code — a conexão estará ativa e as ferramentas do IntellexIA disponíveis.

> [!INFO] Para conferir a conexão a qualquer momento: `claude mcp list` (deve mostrar `intellexia ... ✓ Connected`).

---

## Conectar no Claude Desktop / claude.ai

1. Abra **Settings → Connectors → Add custom connector**.
2. Informe a URL `https://rs-dev.intellexia.com.br/mcp`.
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
| `detalhar_contestacao` | Contestação completa + **benefícios vinculados** + alterações recentes | FAP Web |
| `listar_beneficios_fap` | Benefícios com filtros ricos (**empresa por nome**, CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência...) | FAP Web |
| `detalhar_beneficio` | Todos os campos de um benefício, incluindo justificativas, pareceres e decisões de julgamento | Sistema |
| `listar_procuracoes_fap` | Procurações eletrônicas com situação e vigência | FAP Web |
| `valores_de_filtro_fap` | Códigos e valores válidos para filtros (situações, instâncias, tópicos, motivos) — a IA consulta antes de filtrar | Sistema |

### 📊 Painel FAP — análises e acompanhamento

| Ferramenta | O que faz | Origem |
|---|---|---|
| `resumo_fap` | Contagens agregadas em uma chamada: contestações por vigência/situação/instância/**empresa**; benefícios por tipo/status/tópico + **financeiro** (total pago) | Cálculo |
| `alteracoes_recentes_fap` | O que mudou nas sincronizações com o portal ("o que mudou essa semana?") | FAP Web |

> [!INFO] Para perguntas de **quantidade** ("quantos benefícios da empresa X?"), a IA usa o `resumo_fap` — resposta em segundos, sem listar registro por registro.

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

### 🏛️ Processos Judiciais

| Ferramenta | O que faz | Origem |
|---|---|---|
| `listar_processos` | Processos com fase atual, partes e valor da causa | Sistema |
| `detalhar_processo` | Processo completo: histórico de fases, benefícios vinculados, teses e decisões | Sistema |

### 🧰 Utilidades

| Ferramenta | O que faz | Origem |
|---|---|---|
| `consultar_cnpj` | Dados cadastrais públicos de um CNPJ (Receita Federal): razão social, situação, endereço, sócios e **matriz/filial** | Sistema |

### 🚧 Em desenvolvimento

| Ferramenta | O que faz | Origem |
|---|---|---|
| `revisar_peticao_inicial` | Revisor de petições iniciais | IA |

---

## Permissões

O acesso da IA **espelha as suas permissões** no IntellexIA:

| Para usar... | Você precisa do módulo... |
|---|---|
| Base de Conhecimento (consulta e pesquisa) | Base de Conhecimento |
| Painel FAP (consultas, análises e relatórios Excel) | Painel FAP |
| CATs das contestações | Painel de Contestações |
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
