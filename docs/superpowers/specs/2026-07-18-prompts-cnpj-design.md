# Prompts de consulta por CNPJ

**Data:** 2026-07-18
**Status:** aprovado

## Objetivo

Dois comandos prontos (prompts MCP) que encurtam a consulta de CNPJ: um traz a
ficha cadastral da empresa, outro só o quadro societário. Ambos pedem o CNPJ ao
usuário antes de executar.

A motivação é conveniência, não capacidade nova: a tool `consultar_cnpj` já faz
tudo isso numa chamada. O ganho é não precisar redigir o pedido toda vez, e ter
a saída sempre no mesmo formato.

## O que já existe

- `consultar_cnpj(cnpj)` (`mcp_server/server.py:861`) → `consultar_cnpj_handler`
  (`mcp_server/tools/utilities.py:7`) → `OpenCNPJService`.
- Campos devolvidos: `cnpj`, `razao_social`, `nome_fantasia`,
  `situacao_cadastral`, `data_inicio_atividade`, `porte_empresa`,
  `natureza_juridica`, endereço (`logradouro`, `numero`, `complemento`,
  `bairro`, `municipio`, `uf`, `cep`), `email` e `qsa`.
- O handler acrescenta `cnpj_consultado` e `tipo_estabelecimento`
  (`"Matriz"` ou `"Filial"`, derivado do sufixo `0001`).
- Cada item de `qsa`: `nome_socio`, `cnpj_cpf_socio`, `qualificacao_socio`,
  `identificador_socio`.
- Em falha, o handler devolve `{"erro": ..., "status_code": ...}` — não levanta
  exceção.

**Nenhuma tool, query ou serviço é criado ou alterado neste trabalho.**

## Os dois prompts

Ambos em `mcp_server/server.py`, junto dos dez já existentes, seguindo o padrão
de `email_cliente`: função que recebe argumentos obrigatórios e devolve o texto
da instrução. O argumento obrigatório é o que faz o cliente pedir o CNPJ antes
de executar.

### `ficha_empresa(cnpj: str)`

Ficha cadastral completa: razão social, nome fantasia, situação cadastral,
início de atividade, porte, natureza jurídica, endereço, e-mail, e um resumo do
quadro societário (quantos sócios, quem administra).

### `socios_empresa(cnpj: str)`

Mesma chamada de tool, recorte apenas no `qsa`: nome, CPF/CNPJ, qualificação e
identificador de cada sócio, em tabela.

## Os três casos que a saída erra sozinha

O texto dos prompts precisa cobrir explicitamente:

1. **Filial.** Havendo `tipo_estabelecimento == "Filial"`, a resposta declara
   isso e avisa que o quadro societário é da matriz — não apresenta os dados
   como se fossem da empresa inteira.
2. **Sem sócios.** MEI e empresa individual vêm com `qsa` vazio. A resposta diz
   "não há sócios registrados" de forma explícita. Silenciar seria pior: lê como
   falha de consulta.
3. **CNPJ inválido ou não encontrado.** Vindo `erro`, a resposta reporta a falha
   com clareza e não inventa dados.

## Documentação

Duas linhas na tabela "Comandos prontos" de `docs/MANUAL_MCP.md` — fonte única
renderizada em `/docs/manuais` e lida pelo assistente do manual.

## Teste

`tests/test_mcp_prompts_cnpj.py`, script standalone no padrão do projeto:

1. Ambos os prompts estão registrados no servidor MCP.
2. O CNPJ recebido aparece no texto gerado.
3. O texto instrui a usar `consultar_cnpj` — pega renomeação de tool que
   quebraria o prompt em silêncio.
4. Os três casos de borda (filial, sem sócios, erro) estão mencionados no texto,
   para que a instrução não os perca numa edição futura.

## Fora de escopo

- Cruzar os sócios com a base de clientes ou processos do escritório. É mais
  útil, mas é outro projeto, com outras tools envolvidas.
- Corrigir o docstring de `consultar_cnpj`, que promete CNAE embora o
  serializador não devolva esse campo. Registrado como achado à parte.
