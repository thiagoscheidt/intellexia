# Painel FAP como MCP App

**Data:** 2026-07-18
**Status:** aprovado, aguardando plano de implementação

## Objetivo

Expor o resumo estatístico do FAP como interface visual dentro da conversa do
Claude, via a extensão MCP Apps do FastMCP, sem duplicar dado nem enfraquecer as
tools de texto existentes.

Hoje `resumo_fap` devolve um dicionário aninhado de agregações que o modelo
precisa narrar em texto corrido. Contagens por ano, situação, instância,
empresa, tipo, status de 1ª/2ª instância e tópico de contestação são
comparações — leem-se melhor como barras do que como prosa.

Este é um piloto de uso real, não um experimento descartável: precisa degradar
com elegância em cliente que não renderiza, e não pode derrubar o servidor MCP
se a dependência de UI quebrar.

## Contexto técnico verificado

- `fastmcp` 3.2.4 já instalado; o parâmetro `app` existe em `FastMCP.tool`.
- `prefab-ui` **não** está instalado — entra via `fastmcp[apps]`.
- A documentação do FastMCP avisa que Prefab está em desenvolvimento ativo com
  breaking changes frequentes, e recomenda pinar a versão.
- O servidor MCP roda em produção sob systemd (`intellexia-mcp.service`), com
  deploy por `deploy/deploy_mcp.sh`, que já executa `uv sync`.

## Arquitetura

Três peças, uma responsabilidade cada:

### `fap_summary_handler` — inalterado

`mcp_server/tools/fap.py:472`. Segue sendo a fonte única do dado agregado.
Nenhuma query nova é escrita neste trabalho. Tela, `resumo_fap` e o painel leem
do mesmo lugar, seguindo a regra de fonte única já aplicada em
`fap_review_service` e `fap_digest_service`.

### `mcp_server/apps/fap_panel.py` — novo

Único arquivo que importa Prefab. Contém a função que recebe o dicionário do
handler e devolve o componente de UI. Função pura: sem acesso a banco, sem
contexto Flask, sem sessão.

Essa fronteira é deliberada. O risco conhecido do projeto é o Prefab quebrar num
upgrade; isolá-lo num arquivo pequeno e puro faz a quebra acontecer em código
que se lê inteiro e que o teste cobre sem subir servidor.

### `painel_fap` — tool nova em `server.py`

Assinatura idêntica à de `resumo_fap` (`ano_vigencia`, `cnpj`, `empresa`), mesma
permissão `require_module("fap_panel")`, mesmo `with app.app_context()`.

`resumo_fap` **não é alterado**. Seu docstring instrui o modelo a preferi-la para
toda pergunta de contagem; mexer no seu formato de retorno arriscaria um
roteamento que hoje funciona.

## Conteúdo do painel

Tudo derivado do que o handler já retorna:

- **Cards de topo**: total de contestações, total de benefícios, total pago em
  BRL, benefícios com/sem CAT.
- **Contestações**: barras por situação, por ano de vigência, e top empresas.
- **Benefícios**: barras por tópico de contestação, e status de 1ª e 2ª
  instância.
- **Cabeçalho de filtros**: ano de vigência, CNPJ e empresa aplicados. Sem isso
  o usuário não sabe o recorte que está vendo.

Tópicos (~20 possíveis) e empresas são cortados nos **8 maiores**, seguidos de
uma faixa `outros (N)` **rotulada e visível**, onde N é a contagem somada dos
demais. Corte silencioso lê como cobertura completa — a convenção do projeto
exige anunciar o que foi omitido. As demais dimensões (situação, ano de
vigência, status de instância, tipo) têm cardinalidade baixa e vão inteiras.

## Degradação

Dois modos de falha, ambos resolvidos sem intervenção:

**Host que não renderiza MCP Apps.** A tool devolve o dicionário do handler como
conteúdo estruturado junto com o recurso de UI. Cliente sem suporte vê os
números; não vê erro nem resposta vazia.

**Prefab ausente ou quebrado.** O import de `mcp_server/apps/fap_panel.py` fica
isolado no registro da tool. Se falhar, `painel_fap` não é registrada, o
servidor sobe normalmente com um aviso em log, e `resumo_fap` e as demais tools
seguem intactas.

## Testes

`tests/test_mcp_fap_panel.py`, no padrão dos scripts standalone existentes
(`uv run python tests/...`, dados criados removidos ao final):

1. **Builder puro**: dicionário-fixture representando a saída do handler →
   componente; confere que serializa e que os totais e as barras batem com o
   fixture.
2. **Top-N**: fixture com mais tópicos que o limite; confere que a faixa
   `outros (N)` aparece e que a soma fecha com o total.
3. **Fixture vazio**: escritório sem dado não quebra o componente.
4. **Isolamento por escritório**: passada com dado real confirmando que o painel
   só enxerga o `law_firm_id` do chamador.

## Deploy

- `uv add "fastmcp[apps]"`, com `prefab-ui` pinado em versão exata (`==`) no
  `pyproject.toml`.
- `deploy/deploy_mcp.sh` já roda `uv sync` e reinicia `intellexia-mcp.service`;
  nenhuma mudança de infraestrutura é necessária.

## Fora de escopo

- Drill-down por clique (callbacks `FastMCPApp`). É o passo seguinte natural, e
  esta arquitetura o suporta sem refazer nada, mas depende da parte mais nova e
  instável do protocolo. Fica para depois do painel sobreviver a algumas semanas
  de uso real.
- Apps para listagem de benefícios, acompanhamento de contestações e
  distribuição de tópicos. Mesma razão: uma tool bem feita antes de quatro pela
  metade.
- Qualquer alteração em `resumo_fap` ou nas telas web do `/fap-panel`.
