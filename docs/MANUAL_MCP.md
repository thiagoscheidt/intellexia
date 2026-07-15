# Manual do Usuário — Conectar sua IA ao IntellexIA (MCP)

> O IntellexIA pode ser acessado por assistentes de IA — como o **Claude** — por meio do protocolo **MCP** (Model Context Protocol). Depois de conectar, você conversa com a IA e ela consulta **os dados do seu escritório** no IntellexIA: base de conhecimento, contestações FAP, benefícios e mais.

---

## O que é a conexão MCP

O MCP é uma "ponte" segura entre um assistente de IA e o IntellexIA. Com ela, você pode pedir coisas como:

- "Liste as contestações FAP da vigência 2023 que estão indeferidas";
- "O que temos na base de conhecimento sobre acidente de trajeto?";
- "Traga os detalhes do benefício 123".

A IA busca a resposta diretamente no sistema, **com o seu usuário** — respeitando o seu escritório e as suas permissões de módulo.

> [!IA] **Segurança:** a autorização usa o **seu login do IntellexIA** (OAuth). Nenhuma senha ou chave é copiada para o assistente; você apenas aprova o acesso em uma tela do próprio sistema, e pode revogá-lo quando quiser.

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

## O que a IA consegue fazer

| Ferramenta | O que faz | Origem |
|---|---|---|
| `consultar_base_conhecimento` | Pergunta em linguagem natural, resposta com fontes | IA |
| `pesquisar_base_conhecimento` | Pesquisa Inteligente: retorna os trechos/documentos encontrados, com fonte, página e relevância (roteador decide busca semântica ou textual) | IA |
| `listar_empresas_fap` | Empresas sincronizadas do escritório | Sistema |
| `listar_contestacoes_fap` | Contestações com filtros (CNPJ, raiz, vigência, situação, instância) e status do PDF | FAP Web |
| `detalhar_contestacao` | Contestação completa com benefícios vinculados e alterações recentes | FAP Web |
| `valores_de_filtro_fap` | Códigos e valores válidos para filtros (situações, instâncias, tópicos, motivos) | Sistema |
| `listar_cats_fap` | CATs das contestações com status por instância | Relatório |
| `listar_beneficios_fap` | Benefícios com filtros (CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência...) | FAP Web |
| `detalhar_beneficio` | Todos os campos de um benefício específico | Sistema |
| `resumo_fap` | Contagens agregadas: contestações por vigência/situação/instância, benefícios por tipo/status/tópico | Cálculo |
| `alteracoes_recentes_fap` | O que mudou nas últimas sincronizações com o portal ("o que mudou essa semana?") | FAP Web |
| `listar_procuracoes_fap` | Procurações eletrônicas com situação e vigência | FAP Web |
| `exportar_beneficios_excel` | Gera planilha Excel dos benefícios filtrados (até 50 mil linhas) com link de download | Sistema |
| `exportar_contestacoes_excel` | Gera planilha Excel das contestações filtradas com link de download | Sistema |
| `listar_processos` | Processos judiciais com fase atual, partes e valor da causa | Sistema |
| `detalhar_processo` | Processo completo: fases, benefícios vinculados, teses e decisões | Sistema |
| `revisar_peticao_inicial` | Em desenvolvimento | IA |

---

## Permissões

O acesso da IA **espelha as suas permissões** no IntellexIA:

| Para usar... | Você precisa do módulo... |
|---|---|
| Consulta à base de conhecimento | Base de Conhecimento |
| Empresas, contestações, benefícios, resumo, alterações, procurações e filtros FAP | Painel FAP |
| CATs das contestações | Painel de Contestações |
| Processos judiciais | Painel de Processos |
| Revisor de petições | Revisor de Petições |

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
| Erro de conexão | Serviço temporariamente indisponível | Tente novamente em instantes; persistindo, avise o suporte |
