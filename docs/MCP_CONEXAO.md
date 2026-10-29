# Conectando ao Servidor MCP do IntellexIA

O IntellexIA expõe um servidor **MCP (Model Context Protocol)** que permite a assistentes de IA
(Claude Code, Claude Desktop, etc.) consultar a base de conhecimento, o painel FAP e as
contestações do seu escritório — com autenticação **OAuth 2.1 na sua conta do IntellexIA**.

- **URL do servidor:** `https://SEU-DOMINIO/mcp` — o domínio desta instalação do IntellexIA
  (ex.: `https://rs-dev.intellexia.com.br/mcp` no ambiente de desenvolvimento). A URL exata
  aparece pronta para copiar no sistema: menu do topo → ícone do Claude, ou em
  *Manuais → Conectar sua IA (MCP)*.
- **Autenticação:** OAuth no navegador, reusando o login do IntellexIA (sem chaves ou tokens manuais)
- **Isolamento:** todo acesso é restrito ao escritório do usuário autenticado e respeita as
  permissões de módulo configuradas em *Administração de Usuários*

---

## Pré-requisitos

1. Ter uma conta ativa no IntellexIA.
2. Usuário e escritório ativos.
3. Permissão nos módulos que pretende usar (veja [Permissões](#permissões-por-ferramenta)).

---

## Claude Code (CLI / VS Code)

### 1. Adicionar o servidor

```bash
claude mcp add --transport http intellexia https://SEU-DOMINIO/mcp
```

> Use `--scope user` para disponibilizar em todos os projetos, ou rode dentro de um projeto
> para escopo local.

### 2. Autenticar

Dentro do Claude Code:

1. Digite `/mcp`
2. Selecione **intellexia** → **Authenticate**
3. O navegador abre no IntellexIA:
   - **Já logado no IntellexIA?** Aparece direto a tela "Autorizar acesso" — clique em **Autorizar**.
   - **Não logado?** Faça login normalmente; você volta automaticamente para a tela de autorização.
4. Pronto — o Claude Code confirma a conexão e as ferramentas ficam disponíveis.

### 3. Verificar

```bash
claude mcp list
```

Deve mostrar `intellexia: ... - ✓ Connected`.

---

## Claude Desktop / claude.ai

Em **Settings → Connectors → Add custom connector**, informe a URL
`https://SEU-DOMINIO/mcp` e conclua a autorização no navegador
(mesmo fluxo de login do IntellexIA).

---

## Ferramentas disponíveis

| Ferramenta | O que faz |
|---|---|
| `consultar_base_conhecimento` | Pergunta em linguagem natural à base de conhecimento (RAG com fontes) |
| `pesquisar_base_conhecimento` | Pesquisa Inteligente: trechos ranqueados com fonte/página (roteador LLM escolhe semântica vs. textual) |
| `listar_empresas_fap` | Lista empresas FAP sincronizadas do escritório |
| `listar_contestacoes_fap` | Lista contestações FAP (filtros: CNPJ, raiz, vigência, situação, instância) |
| `detalhar_contestacao` | Contestação completa + benefícios vinculados + alterações recentes |
| `valores_de_filtro_fap` | Códigos/valores válidos para os filtros (situações, instâncias, tópicos...) |
| `listar_cats_fap` | CATs das contestações (módulo Painel de Contestações) |
| `listar_massas_salariais_fap` | Folha de pagamento contestada por competência |
| `listar_vinculos_fap` | Vínculos empregatícios contestados por competência |
| `listar_rotatividade_fap` | Taxas de rotatividade contestadas |
| `listar_beneficios_fap` | Lista benefícios (filtros: CNPJ, segurado, NIT, CPF, nº benefício, tópico, vigência, status na 1ª/2ª instância) |
| `detalhar_beneficio` | Detalhes completos de um benefício |
| `conferir_dados_beneficios` | Lista de benefícios (número + o que a petição/planilha diz: CPF, NIT, espécie, DIB, DCB, nascimento, CNPJ, vigência, nome, CAT) contra a Central e o cálculo FAP, sem IA e sem gravar a entrada — `conferencia_beneficios_service`. Divergências campo a campo + alertas da base (excluído do cálculo, fora do cálculo sincronizado, não contestado, deferido, indeferido nas duas). Mesmo handler da rota `POST /api/v1/fap/beneficios/conferir` |
| `listar_beneficios_calculo_fap` | Benefícios e CATs do cálculo FAP (contestados ou não), com CPF inteiro e filtro por situação e contestado |
| `resumo_beneficios_calculo_fap` | Contagens do cálculo FAP: por tipo, excluídos, não contestados e cruzamento |
| `resumo_fap` | Estatísticas agregadas de contestações e benefícios, com cruzamento tipo × status por instância |
| `prazos_e_alertas` | Contestações aguardando resultado, decisões recentes e processos por fase |
| `comparar_vigencias` | Compara resultados de benefícios entre vigências FAP |
| `buscar_por_segurado` | Visão 360º de um segurado (benefícios, CATs, processos), por NIT, CPF ou nome já revelado |
| `revelar_nome_segurado` | Nome de um segurado pelo CPF — consulta paga, só a pedido explícito, com limite diário por usuário (`CPF_NOME_LIMITE_DIARIO_MCP`) |
| `alteracoes_recentes_fap` | Mudanças detectadas nas sincronizações com o FAP Web |
| `listar_procuracoes_fap` | Procurações eletrônicas sincronizadas |
| `exportar_beneficios_excel` | Planilha XLSX dos benefícios filtrados (link assinado, 1 h de validade) |
| `exportar_contestacoes_excel` | Planilha XLSX das contestações filtradas (link assinado, 1 h de validade) |
| `listar_processos` | Processos judiciais com fase atual |
| `detalhar_processo` | Processo completo: fases, benefícios, teses e decisões |
| `pesquisar_jurisprudencia` | Base de Jurisprudência: busca com sinônimos (modo `campos`) ou no inteiro teor (`inteiro_teor`), filtros por tese original/do catálogo, resultado, tribunal, instância, UF, vigência e período; sem termo é a listagem completa (paginada) |
| `detalhar_decisao` | Decisão completa: motivo, ementa (transcrição ou resumo), fundamentos, argumentos, precedentes (com id quando estão na base), teses e trilha do processo |
| `panorama_jurisprudencia` | Resultados por tribunal e instância, viradas no acórdão e favoráveis recentes de um recorte |
| `valores_de_filtro_jurisprudencia` | Teses do catálogo e originais, tribunais, instâncias, resultados, UFs e vigências existentes, com contagem |
| `decisoes_parecidas` | Decisões semanticamente próximas de uma decisão (índice próprio da jurisprudência) |
| `exportar_jurisprudencia_excel` | Planilha XLSX das decisões filtradas (link assinado, 1 h de validade) |
| `consultar_cnpj` | Dados cadastrais públicos de um CNPJ (OpenCNPJ/Receita) — qualquer usuário logado |
| `revisar_peticao_inicial` | Instruções do FapPetitionReviewerAgent (prompt de sistema e mensagem da tarefa montados pelo mesmo código do agente, com os prompts, o manual e os pontos de atenção ativos; os casos de referência ficam sob consulta por `ler_manual_revisor`) em partes de até 40 mil caracteres, com o formato do JSON repetido no fim, para o Claude revisar o anexo na conversa. Id Wrike/`peticao_id` opcionais (`fap_review_claude_service`) |
| `conferir_revisao_peticao` | Confere o JSON do Claude contra o contrato de saída e passa o mesmo parse/saneador do agente (`montar_resultado`); grava rascunho em `fap_review_drafts` (24 h) e devolve os achados para exibir |
| `conferir_planilha_beneficios` | Devolve o script da checagem da planilha de benefícios — o módulo `app/utils/planilha_beneficios.py` da tela, compactado, + a chamada — para o Claude rodar no ambiente dele com a planilha (.xlsx/.csv) e a petição anexadas. O resultado vai em `conferir_revisao_peticao(planilha_beneficios=...)`, aceito só com a `script_versao` atual (hash do código), e é gravado como `benefits_spreadsheet_review` |
| `gravar_revisao_peticao` | Grava o rascunho como `FapReviewExecution` concluída com `review_origin='claude'` (fora da pontuação, sem aprovação); cria a petição pelo Id Wrike se for nova |
| `mudar_status_peticao` | Muda o `workflow_status` da petição pelo `fap_review_service.change_petition_status` — o mesmo da rota da tela (aprovar/devolver/reabrir só admin; última revisão do Claude não vai para aprovação por não-admin). Papel relido do banco a cada chamada, não do token |
| `listar_peticoes_revisao` | Petições do Revisor com workflow_status, nº de revisões e última revisão (paginada) |
| `detalhar_revisao` | Achados de uma revisão existente: gravidade, localização, correção, referência do manual, documentos faltantes e teses |
| `historico_revisoes_peticao` | Evolução entre revisões da mesma petição: novos, reincidentes e resolvidos |
| `comparar_versoes_peticao` | Como `revisar_peticao_inicial`, com as instruções da revisão comparativa (original × revisada) |
| `ler_manual_revisor` | Lê a referência ativa (manual_fap, casos_referencia, project_instructions) por seção ou termo |
| `versoes_manual_revisor` | Versões das referências: ativa, autor, data, tamanho |
| `auditoria_revisor` | Trilha de auditoria do módulo (paginada) |
| `estatisticas_revisor` | Score/retrabalho/reincidência por advogado — **exige papel de admin** (`require_admin`) |

Prompts MCP (comandos prontos): `relatorio_semanal_fap`, `analise_empresa`, `agenda_do_dia`, `minuta_recurso`, `resumir_decisao`, `email_cliente`, `analise_risco_empresa`, `corrigir_peticao`, `pronto_para_protocolo`, `devolutiva_ao_advogado`.

### Paginação das listagens

As tools `listar_*` e `alteracoes_recentes_fap` devolvem uma página por vez:

| Campo da resposta | Significado |
|---|---|
| `total_encontrado` | Quantos registros o filtro encontrou (não quantos vieram) |
| `retornados` / `deslocamento` | Tamanho e início desta página |
| `tem_mais` | `true` = resposta parcial |
| `proximo_deslocamento` | Valor a repassar em `deslocamento` para a próxima página |

Parâmetros: `limite` (teto de 200 por página — acima disso a resposta só enche o
contexto) e `deslocamento` (padrão 0). Chamadas sem `deslocamento` se comportam
como antes.

> **Ordenação estável:** todo `order_by` paginado termina no `id`. Os dados vêm de
> carga em lote e centenas de registros compartilham o mesmo `created_at`; sem o
> desempate, `LIMIT/OFFSET` repetiria linhas e pularia outras silenciosamente
> (medido: 168 benefícios perdidos numa varredura de 2.899). Ao criar uma nova
> listagem, use `mcp_server/tools/pagination.py` e mantenha essa regra.

Para volume, prefira `exportar_*_excel` (até 50 mil linhas); para contagens,
`resumo_fap`.

Exemplos de uso no Claude:

> "Liste as contestações FAP da vigência 2023 que estão indeferidas"
> "Consulte na base de conhecimento o que temos sobre acidente de trajeto"
> "Traga os detalhes do benefício 123"

### Permissões por ferramenta

| Ferramenta | Módulo exigido no IntellexIA |
|---|---|
| `consultar_base_conhecimento`, `pesquisar_base_conhecimento` | Base de Conhecimento |
| `listar_empresas_fap`, `listar_contestacoes_fap`, `detalhar_contestacao`, `listar_beneficios_fap`, `detalhar_beneficio`, `conferir_dados_beneficios`, `listar_beneficios_calculo_fap`, `resumo_beneficios_calculo_fap`, `resumo_fap`, `alteracoes_recentes_fap`, `listar_procuracoes_fap`, `valores_de_filtro_fap`, `exportar_beneficios_excel`, `exportar_contestacoes_excel`, `buscar_por_segurado`, `revelar_nome_segurado` | Painel FAP |
| `listar_cats_fap`, `listar_massas_salariais_fap`, `listar_vinculos_fap`, `listar_rotatividade_fap` | Painel de Contestações |
| `listar_processos`, `detalhar_processo`, `pesquisar_jurisprudencia`, `detalhar_decisao`, `panorama_jurisprudencia`, `valores_de_filtro_jurisprudencia`, `decisoes_parecidas`, `exportar_jurisprudencia_excel` | Painel de Processos |
| `revisar_peticao_inicial`, `conferir_revisao_peticao`, `conferir_planilha_beneficios`, `gravar_revisao_peticao`, `mudar_status_peticao`, `listar_peticoes_revisao`, `detalhar_revisao`, `historico_revisoes_peticao`, `comparar_versoes_peticao`, `ler_manual_revisor`, `versoes_manual_revisor`, `auditoria_revisor` | Revisor de Petições |
| `estatisticas_revisor` | Revisor de Petições **+ papel de administrador** (espelha o `require_admin_user` da tela) |

Sem o módulo liberado, a ferramenta retorna um erro de permissão claro. Permissões são
reavaliadas automaticamente a cada renovação de token (no máximo 1 hora).

---

## Sessão e revogação

- **Access token:** 1 hora (renovado automaticamente pelo cliente via refresh token).
- **Refresh token:** 30 dias — depois disso é preciso autorizar de novo.
- **Revogar acesso:** remova o servidor no cliente (`claude mcp remove intellexia`) ou
  desative o usuário no IntellexIA — usuários/escritórios inativos perdem o acesso na
  próxima renovação de token.

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `401 invalid_token` | Token expirado/revogado | `/mcp` → **Authenticate** novamente |
| Navegador abre no login e não volta | Sessão do IntellexIA expirada | Faça login e o fluxo continua sozinho |
| "Acesso negado: ... módulo" | Usuário sem o módulo liberado | Peça a um administrador em *Administração de Usuários* |
| "Solicitação expirada" na tela de autorização | Demorou mais de 10 min para autorizar | Reinicie a conexão no cliente |
| `Protected resource ... does not match` | Cliente configurado com URL divergente | Use exatamente a URL mostrada no sistema, **sem barra final** |
| Falha geral de conexão | Serviço fora do ar | No servidor: `systemctl status intellexia-mcp` |

---

## Desenvolvimento local

```bash
# Sobe o servidor MCP local (porta 8001), apontando para o app Flask local
MCP_PUBLIC_URL=http://localhost:8001 uv run python mcp_server/server.py

# Conectar o Claude Code ao ambiente local
claude mcp add --transport http intellexia-dev http://localhost:8001

# Teste ponta a ponta do fluxo OAuth (sem rede)
uv run python tests/test_mcp_oauth.py
```

> No modo local o consentimento redireciona o login para a raiz do próprio
> `MCP_PUBLIC_URL`; para reusar a sessão do Flask local, defina também
> `APP_PUBLIC_URL=http://localhost:5051` (ou a porta onde o app roda).

## Domínio da instalação

O domínio **não** se define na linha de comando nem no serviço systemd: sai do `.env`
daquela instalação, o mesmo arquivo que configura o resto do sistema.

```bash
# .env — única variável de domínio necessária
APP_PUBLIC_URL=https://seu-dominio.com.br
# MCP_PUBLIC_URL só quando o MCP vive em outro domínio/subdomínio que o app
```

Ordem de resolução no servidor MCP: `MCP_PUBLIC_URL` → `APP_PUBLIC_URL` + `/mcp` →
domínio de desenvolvimento (com aviso no log). O `main.py` carrega o `.env` por cima do
ambiente do processo, então o `.env` vence inclusive o systemd — por isso a unit não
declara domínio nenhum.

> **Por que aqui não vale "usar o domínio que o usuário está acessando"**, como no modal
> e no manual: o OAuth fixa `issuer` e `resource` dentro dos handlers quando o processo
> sobe, antes de existir requisição (verificado: uma requisição em outro Host continua
> recebendo o endereço configurado no start). Além disso, um issuer que mudasse por
> requisição quebraria clientes que já cachearam a metadata — o erro
> `Protected resource ... does not match`.

## Deploy (servidor)

```bash
sudo bash deploy/deploy_mcp.sh
```

O script descobre o domínio nesta ordem: `MCP_DOMAIN` (override) → `APP_PUBLIC_URL` ou
`MCP_PUBLIC_URL` do `.env` → detecção pelo site do nginx que faz proxy para a aplicação →
falha com instrução (melhor do que publicar o domínio errado). Depois atualiza o código em
`/sites/intellexia`, roda as migrations (OAuth e notificações), instala/reinicia o serviço
systemd `intellexia-mcp` (porta 8001), garante os `location` de `/mcp` e do discovery OAuth
no nginx e, ao final, confere se o endereço anunciado bate com o esperado.

Arquitetura e decisões de design: [superpowers/specs/2026-07-15-mcp-oauth-design.md](superpowers/specs/2026-07-15-mcp-oauth-design.md).
