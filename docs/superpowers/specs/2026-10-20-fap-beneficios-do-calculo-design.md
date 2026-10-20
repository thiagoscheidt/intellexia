# Benefícios do cálculo FAP — sincronização, tela e MCP

Data: 20/10/2026 · Origem: retornos E02 e E04 da Remessa R09 (MCP) e conversa com o Thiago.

## Por que

A Central de Contestações só conhece os benefícios que vieram nos **relatórios de
julgamento** importados — e esse relatório não traz CPF do segurado, e o parser não
lê RMI nem total pago. Resultado medido na homologação: `insured_cpf` vazio em todos
os benefícios (E02), `total_paid` vazio em todos e `request_type` vazio em 100% (E04).

O portal FAP Web tem tudo isso na **Consulta do FAP**: para cada estabelecimento e
vigência, o cálculo do FAP e a lista de cada benefício e CAT que entrou nele, com CPF,
nascimento, RMI e total pago. Mais: no recálculo, o portal marca cada item como
`ORIGINAL` ou `EXCLUIDO` — o próprio portal diz o que a contestação conseguiu tirar.
Hoje o sistema não lê nada disso.

O que se quer:

1. trazer para uma base própria **todos** os benefícios e CATs do cálculo FAP, de
   **todas as vigências, todas as empresas, todos os estabelecimentos**;
2. com ela, **completar** os benefícios que já temos (CPF, nascimento, RMI, total pago);
3. uma **tela nova no Painel FAP** listando tudo, com filtros — inclusive o que foi e o
   que não foi contestado;
4. o **MCP** consultando essa base (achar segurado por CPF mesmo sem contestação).

## Como o portal entrega (medido em 20/10/2026)

Tudo JSON, pelo mesmo cookie de sessão do `FAP_AUTH_JSON` que o `fap_sync_cron` usa, e
funciona pelo `FapWebService._get` atual (urllib, sem navegador). Base
`https://fap-mps.dataprev.gov.br/gateway/fap/v1`:

| Chamada | Devolve |
|---|---|
| `GET /vigencias/anos` | anos disponíveis — hoje `2010..2027` |
| `GET /vigencias/{ano}/empresa/{raiz8}/estabelecimentos` | lista de CNPJs (números, sem zero à esquerda) |
| `GET /vigencias/{ano}/empresa/{cnpj14}/calculos` | histórico: eventos (sem `id`) e cálculos (com `id`), **mais recente primeiro** — `tipoProcessamento` (`CALCULO_ORIGINAL`, `RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA`, `RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA`, …), `dataProcessamento`, FAP, índices, `quantidadeB91..B94`, `quantidadeCat`, massa salarial, vínculos, `valorTotalBeneficiosPagos`, `idContestacao`, `protocolo`, `dataDou` |
| `GET .../calculos/{id}/beneficios/` | **todas as espécies** do cálculo: `nb`, `especie`, `nit`, `cpf`, `dataNascimento`, `cnpj`, `valorMensal` (RMI), `dataDespacho`, `dataInicio`, `dataCessacao`, `dataInicioContabilizacao`, `dataFimContabilizacao`, `mesesContabilizacao`, `totalPago`, `bloqueio`, `estado` |
| `GET .../calculos/{id}/beneficios/B91` | o mesmo, filtrado por espécie (a tela usa ao clicar no número) |
| `GET .../calculos/{id}/cats` | `numeroCat`, `nit`, `cpf`, `dataNascimento`, `cnpjOriginal`, `cnpjAtribuido`, `dataAcidente`, `dataCadastroCat`, `dataObito`, `reciboEsocial`, `bloqueio`, `estado` |

Outros endpoints da mesma tela, **fora desta versão**: `massa-salarial`, `vinculos`,
`rotatividade`, `declaracoes` (CNAE) e `percentil-frequencia|gravidade|custo` (o ranking
do CNAE inteiro, 370–500 KB cada, dados de outras empresas).

Observações medidas:

- A lista do cálculo **inclui os excluídos**: na matriz da Vale (2026) o cálculo atual
  tem 32 itens (B91 e B92) e a tela mostra B91 = 5, B92 = 0 — os outros 27 estão
  `EXCLUIDO`. As quantidades do cálculo contam só os `ORIGINAL`.
- O cálculo original lista os mesmos itens, todos `ORIGINAL`.
- Escala, medida em 2026: **874 raízes, 20.320 estabelecimentos** (11 raízes deram 404
  — sem cálculo na vigência). Concentrado: Santander (90400888) 3.092, Itaú (60701190)
  2.769, 49930514 1.866, 61412110 1.222. A maioria tem cálculo sem nenhum benefício nem
  CAT. Listar os estabelecimentos das 874 raízes, em sequência, levou 932 s (média
  1,07 s por chamada, pico de 35 s). Com 8 em paralelo, uma vigência inteira é da
  ordem de 1 h (≈ 20 mil `/calculos` + os estabelecimentos com item); as 18 vigências,
  da ordem de 15–20 h, uma vez só.
- CNPJ, CPF, NIT e NB chegam como **número**: o zero à esquerda some (a lição do E01).

## Objetivos

- **G1. Base "benefícios do cálculo FAP"**: uma linha por (escritório, vigência,
  estabelecimento, tipo, identificador) — identificador = NB para B91–B94, número da
  CAT para CAT. Guarda todos os campos da tabela acima, o estado no **cálculo atual** e
  de que cálculo veio (id, tipo, data). Guarda também o estado no cálculo original
  (para dizer "foi excluído no recálculo").
- **G2. Sincronização** de todas as vigências que o portal oferece, todas as empresas
  do Painel FAP e todos os estabelecimentos.
  - No padrão do `scripts/fap_sync_cron.py`: busca em paralelo (workers no `.env`,
    padrão 8, como `FAP_SYNC_FETCH_WORKERS`), gravação no banco em sequência no fluxo
    principal. **Decisão do Thiago: não usar ritmo lento — igual ao fap_sync.**
  - Carga inicial que pode ser retomada (sessão cai, processo reinicia) e que roda por
    partes: `--vigencia`, `--empresa` (raiz), `--estabelecimento`.
  - Depois da carga, incremental: só busca de novo benefícios e CATs do
    estabelecimento cujo **id do cálculo atual mudou**.
  - Estabelecimento sem item em nenhum cálculo (soma das quantidades zero em todos os
    cálculos do histórico) não gasta a chamada de benefícios nem a de CAT.
- **G3. Completar a Central** (resolve E02 e E04): quando o NB existe em `benefits` do
  mesmo escritório, preencher `insured_cpf`, `insured_date_of_birth`,
  `initial_monthly_benefit` (RMI) e `total_paid`.
- **G4. Tela no Painel FAP** — rascunho aprovado
  (`.superpowers/mockups/listagem-beneficios-v1.html`):
  - todos os benefícios e CATs, sem distinção, uma lista só;
  - filtros com botão **Pesquisar** (padrão do FAP-33, sem busca a cada filtro):
    vigência, grupo / CNPJ raiz, estabelecimento, CPF / NIT / NB / nº CAT, **tipo**
    (B91, B92, B93, B94, CAT — os tipos das URLs do portal), situação no cálculo atual
    (conta / excluído), contestado (sim / não);
  - contadores do resultado: total, por tipo, CATs, excluídos, não contestados;
  - colunas: vigência, estabelecimento (CNPJ + nome), tipo, NB / nº CAT, NIT + CPF,
    nascimento, RMI, total pago, início → cessação (na CAT: data do acidente),
    situação no cálculo atual, contestado (com link para o benefício da Central);
  - o resto ao expandir a linha: despacho, contabilização (início, fim, meses),
    bloqueio, cálculo de origem (tipo, data, id), protocolo; na CAT: cadastro, óbito,
    CNPJ original × atribuído, recibo do eSocial.
- **G5. MCP**: a IA consegue pesquisar essa base com os mesmos filtros da tela
  (inclusive achar segurado por CPF mesmo sem contestação) e contar por tipo /
  situação / contestado, no padrão das tools FAP existentes (paginação, `require_module`
  `fap_panel`, ToolError com valores aceitos).

## Fora desta versão

- Massa salarial, vínculos, rotatividade, CNAE e percentis.
- Ler RMI e total pago do PDF do relatório — o portal entrega o dado estruturado; o
  parser do relatório não muda.
- Preencher `request_type` (tipo de pedido) e rodar o classificador de tópicos — são
  decisões à parte do E04, nada aqui depende delas.
- Nome do segurado: nenhuma fonte tem.
- Login no gov.br, renovação da sessão: continua manual (ver CLAUDE.md, "Sessão do
  portal FAP").

## Restrições e cuidados

- **Multi-tenant**: as tabelas novas têm `law_firm_id`; toda query filtra por ele. A
  credencial é da instalação (`FAP_AUTH_JSON`) e o escritório é o do
  `FAP_SYNC_LAW_FIRM_ID`, como no `fap_sync_cron`.
- **Identificadores sempre completados com zero** (`app.utils.cnpj.completar_zeros`):
  CNPJ 14, raiz 8, CPF 11; NIT e NB como string só de dígitos. Nunca `[:8]` de número
  sem zero (E01).
- **Sessão parcial** (CLAUDE.md): sem `empresasVinculadas`, o portal responde 403 para
  empresas que têm procuração. 403/401 numa empresa **não apaga nada**: fica registrado
  como "sem acesso nesta execução" e a empresa é tentada de novo na próxima.
- **Nunca apagar por ausência numa execução**: item que sumiu da resposta não é
  removido; guarda-se `last_seen_at`. (Mesmo motivo da poda suspensa no
  `fap_company_sync_service`.)
- **Dados pessoais**: CPF e data de nascimento são dado sensível de segurado. Exibidos
  inteiros (decisão do Thiago), mas só para quem tem o módulo `fap_panel`, na tela e no
  MCP; nada de CPF em log; prints e dumps de teste só em `instance/`.
- **Escala**: ~20 mil estabelecimentos × 18 vigências. A carga inicial é de horas e
  roda uma vez; o incremental diário não pode reconsultar `/calculos` de tudo todo dia
  sem medir antes (ver "Deixado ao construtor").
- Migrations no padrão do projeto (script em `database/`, idempotente, `add_*`).
- `tests/` no padrão de script do projeto; nada de rede nos testes (dublê do
  `FapWebService`).

## Decidido

- Do Thiago: todas as vigências, todos os CNPJs e estabelecimentos, numa base única; tela
  nova no Painel FAP com todos os benefícios, todos os campos e filtro por tipo
  incluindo CAT; o filtro "não contestados" é um filtro, não uma tela; paralelismo igual
  ao `fap_sync_cron`; MCP também consulta a base nesta versão; rascunho da tela
  aprovado.
- Do Thiago, depois da revisão:
  - **"Contestado" = número + vigência**: o NB (benefício) ou o número da CAT existe na
    Central do mesmo escritório **na mesma vigência** (`benefits.benefit_number` +
    vigência do benefício / `fap_contestation_cats.cat_number` + `vigencia_year`). O
    mesmo NB costuma estar no cálculo de vigências seguidas (período-base de dois
    anos); ligar só pelo número marcaria como contestado em 2026 o que só foi
    contestado em 2025, e o filtro "não contestados" esconderia justamente o que se
    quer achar. O link "ver" abre o benefício dessa vigência.
  - **CPF inteiro**, na tela e no MCP, como no resto do sistema (nenhuma tela mascara
    hoje; o rascunho mascarava só por ser rascunho). Data de nascimento também inteira.
    Continua valendo: nada de CPF em log.
- Minhas (o Thiago pode corrigir):
  - "Excluído" vem do portal (`estado` do item no cálculo atual).
  - **Estado por item em dois cálculos só**: no original e no atual. O histórico
    mostrado ao expandir a linha é o **do cálculo do estabelecimento** (original →
    recálculo 1ª → recálculo 2ª, com datas), que já vem do `/calculos` — não o estado
    do item em cada recálculo intermediário, que multiplicaria a carga inicial sem
    mudar o que a tela responde.
  - **Completar**: CPF e nascimento — o portal sobrescreve sempre (o dado é dele); RMI e
    total pago — preenche só se estiver vazio, e o total pago usado é o da linha da
    **mesma vigência** do benefício (o mesmo NB pode estar em duas vigências, com
    contabilização diferente).
  - Primeira versão: benefícios e CATs; os outros insumos ficam para depois.

## Deixado ao construtor

- Nome das tabelas, colunas e do script; nome do item no menu do Painel FAP.
- Como guardar o estado do cálculo por estabelecimento (id e tipo do cálculo atual,
  data, quantidades) para o incremental e para a retomada.
- Frequência do incremental e quais vigências entram nele (medir quanto custa
  reconsultar `/calculos` de ~20 mil estabelecimentos; recálculos acontecem nas
  vigências em julgamento).
- Onde o "completar" roda: no fim da sincronização, sob comando, ou nos dois.
- Os nomes e o recorte das tools MCP novas, e se `buscar_por_segurado` /
  `listar_beneficios_fap` passam a cair na base nova quando o CPF não está na Central.
- Índices do banco para os filtros da tela.
