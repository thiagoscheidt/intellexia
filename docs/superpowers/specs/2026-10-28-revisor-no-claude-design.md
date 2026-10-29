# Revisor no Claude: a revisão roda na conversa e só o resultado vai ao IntellexIA

## Por quê

O RPI-37 levou a revisão pedida pelo Claude para o servidor: a revisão roda em
segundo plano e o arquivo chega por link de envio, `curl` ou Drive. A equipe da
Protege testou em produção em 28/10/2026 (Daniella, Wrike 1577619636,
revisão 3). Funcionou: a revisão saiu em 1 minuto, o e-mail chegou e ela
entrou no histórico. Mas o formato não serve à equipe:

- **O `curl` falhou** com `Could not resolve host`, mesmo com a organização
  liberando todos os sites. A pessoa teve de soltar o arquivo na página nas
  duas tentativas.
- **O caminho do anexo estava errado.** A ferramenta manda procurar em
  `/mnt/user-data/attachments/`, mas no claude.ai dela o arquivo estava em
  `/mnt/user-data/uploads/`.
- **A página de envio ficou em "em processamento" por 30 minutos**, com a
  revisão já concluída.
- **O histórico marcou achados como resolvidos e novos ao mesmo tempo** quando
  o revisor só mudou a redação ("arts. 370/371", "destacamos/compartilhamos").
- **O fluxo "link + e-mail + voltar ao Claude" não funciona para eles.** Eles
  querem o resultado no próprio chat, com andamento. Querem mandar a petição
  sem depender da rede do Claude e não querem ser obrigados a informar o Id
  Wrike.

A proposta do Thiago (28/10) inverte o fluxo. O IntellexIA não recebe a
petição: ele entrega ao Claude as instruções do agente revisor do escritório,
e o Claude revisa ali mesmo, na conversa, com o arquivo que já está anexado.
O resultado sai no formato JSON que o agente devolve. Só no fim, e só se o
usuário quiser, o resultado vai ao IntellexIA e entra no histórico da petição.

Com isso o arquivo chega do jeito que a pessoa anexou, sem `curl`, link,
transcrição nem rede. O resultado aparece no chat, e não há chamada longa que
estoure o tempo do cliente.

## O que muda para o usuário

1. A pessoa anexa a petição na conversa e pede a revisão. Se for comparação,
   anexa as duas versões.
2. O Claude busca as instruções do Revisor do escritório e avisa que vai levar
   alguns minutos. Se a pessoa citar a petição, ou se o Claude a achar pelo
   nome da empresa e confirmar, as instruções já vêm com os pontos de atenção
   da última revisão do IntellexIA.
3. O Claude revisa e manda o resultado ao IntellexIA para conferência. O que
   volta (achados já saneados) é o que ele mostra na conversa.
4. O Claude pergunta se a pessoa quer gravar no histórico do Revisor.
   - **Não**: nada fica no histórico.
   - **Sim**: o Claude grava. Petição existente recebe a próxima revisão; para
     petição nova, ele pede o Id Wrike nessa hora.
5. A revisão gravada aparece no Revisor com o selo **"Feita no Claude"**.

## Decisões do Thiago (28/10/2026)

- A revisão gravada pelo Claude leva o selo **"Feita no Claude"**.
- **Ela não conta na pontuação dos advogados** nem nas estatísticas por
  advogado.
- **Ela não envia para aprovação.** Para mandar a petição à aprovação, a
  última revisão tem de ser uma revisão do IntellexIA, feita pela tela.
- **O fluxo do RPI-37 sai nesta mesma entrega** (decisão de 28/10, depois da
  primeira versão deste desenho). Saem a revisão no servidor pedida pelo
  Claude e todas as entradas de arquivo criadas para ela: o link de envio
  (página e `curl`), o link do Drive e o texto colado mandado ao servidor.
  O Claude passa a revisar só na conversa.

## Metas

- Revisão completa (uma versão, ou comparação original × revisada) feita na
  conversa com as **mesmas instruções** que o agente do escritório recebe:
  identidade, regras, contrato de saída, manual FAP, casos de referência,
  instruções do projeto e pontos de atenção da revisão anterior.
- O que fica gravado é **exatamente** o que o Claude mostrou ao usuário.
- O resultado gravado passa pelo **mesmo parse e pelo mesmo saneador** da
  revisão do servidor.
- Nenhuma chamada de ferramenta demora mais que alguns segundos.
- O Id Wrike só é exigido para criar petição nova, na hora de gravar.

## Fora do escopo

- Documentos auxiliares e planilha de benefícios (continuam só na tela).
- Dividir a revisão em agentes por assunto (proposta da Daniella): card
  próprio. O desenho aqui não impede; as instruções em partes já são um passo
  nessa direção.
- "Só o Id Wrike" como forma de mandar a petição: não há integração com o
  Wrike, e falta perguntar à Daniella o que ela quis dizer.
- A identidade do "não pertinente" (`fingerprint_achado`, 6 campos exatos) tem
  a mesma rigidez do histórico: um achado descartado que volta com outra
  redação reaparece. Fica para outro card, porque mexer nela muda o que já foi
  descartado.

## Antimetas (falha mesmo se "funcionar")

- Revisão feita no Claude passar por revisão do IntellexIA: sem selo, contando
  na pontuação ou liberando a aprovação.
- Gravar sem o usuário ter dito que sim.
- Gravar algo diferente do que foi mostrado.
- Reescrever ou "adaptar" os prompts e referências do escritório. Eles vão
  como estão no banco. O que muda é um bloco do código, como o contrato de
  saída que o agente já tem.
- Rascunho de um usuário gravado por outro, ou petição de outro escritório.
- Revisão gravada em petição travada (aguardando aprovação, aprovada,
  protocolada, arquivada).

## Como é feito

### As ferramentas do MCP (módulo `fap_review`)

Os nomes `revisar_peticao_inicial` e `comparar_versoes_peticao` continuam.
São os que as pessoas já usam, e agentes salvos na Biblioteca de IA podem
citá-los. O que muda é o que elas fazem: agora entregam as instruções. Entram
duas ferramentas novas, `conferir_revisao_peticao` e `gravar_revisao_peticao`.

**1. `revisar_peticao_inicial(identificador_documento=None, peticao_id=None, parte=1)` e `comparar_versoes_peticao(identificador_documento=None, peticao_id=None, parte=1)`**

- A primeira entrega as instruções da revisão de uma versão (modo
  `revisao`); a segunda, as da comparação original × revisada (modo
  `comparacao`). As duas usam o mesmo handler, mudando só o modo.
- A petição é opcional, por `peticao_id` ou pelo Id Wrike. Se não for
  encontrada, é tratada como nova, sem pontos de atenção.
- Petição travada: devolve as instruções com um `aviso` de que a revisão não
  poderá ser gravada. A pessoa pode querer só conferir na conversa.
- O conteúdo é o que o agente monta hoje, saído do mesmo código, sem cópia:
  - o prompt de sistema de `FapPetitionReviewerAgent._build_system_prompt`,
    com os prompts e referências ativos do escritório e a flag de revisão
    focada;
  - a mensagem da tarefa de `_build_single_user_message` ou
    `_build_comparative_user_message`, com `petition_text=None` (o texto
    "o documento foi enviado como anexo" vale para o anexo da conversa);
  - os pontos de atenção de `_build_prior_attention_points`.
  Para isso, a montagem sai da instância do agente para funções que não exigem
  chave da OpenAI, e o agente passa a chamar essas mesmas funções.
- **Em partes de até 40 mil caracteres** (o mesmo teto do
  `MAX_REFERENCE_CHARS` das ferramentas de referência), cortadas em fim de
  seção ou parágrafo, nunca no meio de uma linha. A ordem é:
  1. prompt de sistema sem as referências, mais o bloco de adaptação;
  2. manual;
  3. casos de referência;
  4. instruções do projeto;
  5. por último, a tarefa.

  Cada parte traz `parte`, `total_partes` e `conteudo`; a última traz também
  o `proximo_passo`. No banco local são cerca de 131 mil caracteres, ou 4 a 5
  partes.
- **Bloco de adaptação** (código, antes das referências):
  - leia a petição do anexo da conversa; sem anexo, peça o arquivo; com mais
    de um, pergunte qual é, ou, na comparação, qual é a original e qual a
    revisada;
  - o JSON do contrato de saída vai no argumento de `conferir_revisao_peticao`
    e não é mostrado ao usuário;
  - as imagens que você vê no documento valem como o marcador
    `[IMAGEM ANEXADA NO DOCUMENTO]` (o anexo da conversa não tem marcador);
  - avise antes de começar que leva alguns minutos e diga em que passo está.
  - Se o teste T1 (abaixo) mostrar que o Claude não vê as imagens de dentro do
    DOCX, o bloco ganha mais uma regra: arquivo DOCX com prints → peça o PDF.
- `proximo_passo` (última parte):
  - revise só depois de ler todas as partes;
  - mande o JSON a `conferir_revisao_peticao`;
  - se a conversa já tiver uma revisão, sugira abrir conversa nova, porque o
    contexto acumulado gasta o limite do plano da pessoa.

**2. `conferir_revisao_peticao(resultado_json, modo="revisao", identificador_documento=None, peticao_id=None)`**

- `resultado_json` aceita objeto ou texto JSON.
- Passa pelo mesmo caminho do fim de `review_petition_single_version` e de
  `review_petition_comparative`: `_parse_theses`, `_parse_findings` (saneador),
  `_parse_missing_documents`, `_ensure_output_parsed` e
  `_build_executive_summary`, montando o `PetitionReviewResult`. Esse trecho
  vira uma função pura usada pelo agente e por esta ferramenta, sem duplicar.
- O saneador roda **sem o texto da petição**. As regras que dependem dele (R1,
  correção já atendida; R3, achado dentro de citação) ficam desligadas, como o
  próprio `sanear` prevê com texto vazio. As outras (R2 duplicado, R4 conta
  DCB/DIB, R6 "sem problema", R7 só formatação) valem.
- **Quando recusa**: JSON inválido, ou faltando alguma chave de primeiro
  nível do contrato (ou com o nome errado), devolve `erro` com os problemas
  para o Claude corrigir e mandar de novo, e não cria rascunho.
  - As chaves são `theses`, `findings`, `missing_documents` e
    `executive_summary` na revisão, e `comparative_changes`, `findings` e
    `executive_summary` na comparação.
  - Sem essa trava, `{"achados": [...]}` passaria pelo `_ensure_output_parsed`
    e viraria uma revisão "limpa", com zero achados, pronta para gravar.
- **Item que não passa no parse** é deixado de fora, como no servidor, e vem
  na resposta em `avisos` (o `parse_errors` do parse). O Claude pode corrigir
  e reenviar, mas não é obrigado.
- **Achado já marcado "não pertinente"** nessa petição (fingerprint em
  `_get_ignored_finding_fingerprints` pelo Id Wrike) vem marcado
  `ja_marcado_nao_pertinente`, como a tela de resultado faz, para o chat e a
  tela não discordarem.
- Válido: grava um **rascunho** e devolve:
  - `rascunho_id`;
  - os achados formatados para exibir (nº, gravidade, categoria, descrição,
    local, correção, referência do manual), documentos em falta, teses,
    resumo e, na comparação, as mudanças;
  - `descartados_pelo_saneador` (regra e motivo);
  - `proximo_passo`: mostre **estes** achados, não os do seu JSON; depois
    pergunte se a pessoa quer gravar no histórico; só chame
    `gravar_revisao_peticao` se ela disser que sim.
- **Tabela `fap_review_drafts`**, com `law_firm_id`. Colunas:
  - `user_id`, `mode` (`revisao`/`comparacao`), `petition_id` (nullable),
    `identifier` (nullable);
  - `result_json` (o `PetitionReviewResult` saneado) e `used_versions_json`
    (`collect_active_versions` no momento da conferência);
  - `created_at`, `expires_at` (+24 h), `saved_execution_id` (nullable,
    `SET NULL`), `saved_at`; tudo em UTC.
  - Cada conferência apaga os rascunhos vencidos do escritório.
  - Migration: `database/add_fap_review_drafts_table.py`.

**3. `gravar_revisao_peticao(rascunho_id, identificador_documento=None, peticao_id=None, titulo="", nome_arquivo="", modelo="")`**

- Só grava rascunho do mesmo usuário e escritório, dentro da validade.
  Rascunho já gravado devolve a revisão que ele gerou, sem gravar de novo.
- Petição:
  - se o rascunho foi conferido para uma petição, a gravação tem de ser nela
    (outra, recusa) e pode vir sem identificação;
  - sem petição no rascunho, informe uma existente (`peticao_id` ou Id Wrike);
  - para petição nova, o Id Wrike é obrigatório (`validate_wrike_identifier`)
    e o título vem de `build_petition_title`.
- Recusas, com o rascunho continuando válido:
  - petição travada (`describe_new_revision_block`);
  - revisão do IntellexIA em processamento na mesma petição
    (`running_revision`): "espere terminar; o rascunho vale até HH:MM".
- Cria a `FapReviewExecution`:
  - `execution_type='revision'`, `status='completed'`, `completed_at`;
  - `revision_number` seguinte (`_next_revision_number`);
  - **`review_origin='claude'`**;
  - `model_name` = `"Claude · <modelo informado>"`, ou
    `"Claude · modelo não informado"`;
  - `result_json` e `used_versions_json` do rascunho;
  - `comparative_analysis` conforme o modo;
  - `main_document_filename` = `nome_arquivo`, e `main_document_path` vazio;
  - sem tokens nem custo.
- `sync_petition_after_revision`, auditoria ("revisão feita no Claude
  gravada"; "petição criada via Claude" quando nova) e o rascunho marcado como
  gravado, na mesma transação.
- Devolve `revisao_id`, `numero_revisao`, `link` (`revision_result_url`) e uma
  mensagem dizendo que para enviar à aprovação a última revisão tem de ser do
  IntellexIA.
- Sem e-mail: a pessoa está na conversa.

### Origem da revisão

- Coluna nova `fap_review_executions.review_origin` (`VARCHAR(20)`, nullable).
  Vazia é revisão do IntellexIA: a da tela e as que o Claude pediu pelo
  fluxo do RPI-37 antes de ele sair, que rodaram no servidor com o modelo do
  escritório. `'claude'` é revisão feita no Claude. Constante no `fap_review_service`,
  rótulo "Feita no Claude". Migration:
  `database/add_fap_review_executions_review_origin_column.py`.
- **Onde a origem muda o comportamento**:
  1. **Pontuação e estatísticas por advogado**: as revisões do Claude ficam de
     fora da query do `fap_review_service` (`build_lawyer_statistics`), que
     serve a tela e a ferramenta `estatisticas_revisor`. O cartão "N revisões
     realizadas" e os filtros por advogado da lista do Revisor contam
     normalmente: são volume e responsável pela petição, não desempenho.
  2. **Ir para aprovação**: a regra vale quando a **última revisão** da petição
     é do Claude.
     - **Concluir triagem com "Versão final — enviar para aprovação"**: o
       servidor recusa, e a tela mostra o botão desabilitado com o motivo.
       "Revisada — enviar nova versão" continua.
     - **Mudança manual de status** (`petition_update_status`: o seletor do
       detalhe da petição e o arrastar do kanban) para "Aguardando aprovação"
       ou "Aprovada pelo revisor": recusada para quem não é admin, com o mesmo
       motivo; a opção ou coluna aparece desabilitada.
     - **O admin continua podendo mudar à mão.** Hoje ele já pode aprovar
       direto de "Em revisão", sem triagem, e é quem aprova. A regra existe
       para o advogado não mandar à aprovação uma revisão feita no Claude.
     Como continua valendo a regra de revisão substituída
     (`is_execution_superseded`), uma revisão do Claude depois de uma do
     IntellexIA faz a petição precisar de nova revisão do IntellexIA para ir à
     aprovação.
  3. **Pontos de atenção da revisão anterior**: `_build_prior_attention_points`
     considera só revisões do IntellexIA, tanto na revisão da tela quanto nas
     instruções para o Claude. Uma revisão feita no Claude, talvez com outro
     modelo, não pode estreitar a revisão oficial seguinte para "modo focado"
     nos achados dela.
- **Onde não muda**: numeração, histórico da petição, triagem por achado,
  "não pertinente", `detalhar_revisao`, `historico_revisoes_peticao` e
  `listar_peticoes_revisao`. As ferramentas de leitura passam a devolver
  `origem` ("IntellexIA" ou "Feita no Claude").
- **Telas**: selo "Feita no Claude" no resultado da revisão, no histórico da
  petição e na lista do Revisor, com o modelo informado. A revisão sem
  arquivo tem de abrir sem erro em todas as telas que mostram revisão (as que
  mostram o documento já conferem `main_document_path`).

### O que sai (fluxo do RPI-37)

Tudo o que existia só para a revisão no servidor pedida pelo Claude, conferido
no código em 28/10:

- **Link de envio**: o blueprint `fap_review_upload` (registro no `main.py` e
  no `app/blueprints/__init__.py`, e o desvio de `/revisao/enviar/` no
  `check_session` de `app/middlewares.py`), o `fap_review_upload_service`
  inteiro (link, recebimento, conferência do arquivo, Drive),
  `templates/fap_review/envio_arquivo.html`, o modelo `FapReviewUploadLink`
  e `database/add_fap_review_upload_links_table.py`.
- **Revisão no servidor pelo MCP**: `open_file_review`, `start_text_review` e
  `_in_progress_payload` do `fap_review_service`, e os handlers antigos de
  `mcp_server/tools/petition_reviewer.py` (texto, Drive, link de envio).
- **E-mail de revisão concluída**: `send_revision_finished_email`,
  `templates/emails/revisao_concluida.html` e o `notify_user` do
  `_start_review_in_background`. A tela nunca o usou.
- **Exportar Google Docs em DOCX**: o parâmetro `gdoc_como` de
  `google_drive_client.baixar` e de
  `impugnacao_import_service.download_drive_file` volta como era, porque só
  esse fluxo usava.
- **Testes e documentação**: `tests/test_fap_review_envio_arquivo.py`, as
  partes de `tests/test_mcp_fap_review.py` sobre o fluxo antigo, e nos
  manuais e no `CLAUDE.md` o link de envio, o Drive, o `curl` e a liberação
  de `*.intellexia.com.br` no Claude, que deixa de ser necessária. As
  mudanças desses documentos que ainda não foram para o git são refeitas.
  A spec e o plano do RPI-37 em `docs/superpowers/` ficam como histórico,
  com uma linha no topo apontando para este desenho.

**Fica**, porque a tela usa ou a gravação nova precisa:
- `check_new_revision_allowed`, `running_revision`, `_next_revision_number`,
  `revision_result_url` e `describe_new_revision_block`;
- `fail_if_stuck` e o `processando` do `detalhar_revisao`, que valem para
  revisão da tela em andamento.

**Dados**:
- A tabela `fap_review_upload_links` fica no banco. Um script
  `database/remove_fap_review_upload_links_table.py` (idempotente) a apaga,
  rodado só quando o Thiago decidir.
- Os arquivos que já chegaram pelo link ou pelo Drive continuam: são o
  documento de revisões que estão no histórico.

### Histórico: o mesmo achado com outra redação

`petition_review_history_handler` deixa de comparar a descrição idêntica e
passa a casar os achados de duas revisões seguidas, um para um:

- Candidatos: mesma categoria normalizada.
- Nota:
  - 1, se o `location_excerpt` normalizado for igual;
  - senão, a **sobreposição** das palavras da descrição (palavras em comum
    divididas pelas da descrição menor), normalizadas sem acento e sem caixa,
    ignorando palavras de até 2 letras e as genéricas ("ainda", "permanece",
    "manual"…), mantendo os números ("370", "371");
  - Jaccard quando uma das descrições tem menos de 5 palavras, para "Falta o
    NTEP" não casar com qualquer achado longo que cite o NTEP.
- Casa a partir de 0,55, ou de 0,4 quando a localização (`location`) é a
  mesma. Maior nota primeiro, um para um.
- Casado é reincidente (com a redação nova); sobra da anterior é resolvido;
  sobra da atual é novo.
- **Calibrado nas revisões do banco local (28/10)**: o mesmo achado reescrito
  ficou entre 0,56 e 0,80; achados diferentes da mesma categoria, até 0,36.
  O Jaccard que o desenho sugeria de início dava 0,37 a 0,42 para reescritas
  óbvias e as perderia.

## Ajuste depois do teste em homologação (28/10/2026)

Duas revisões reais na conta do Thiago, em homologação, com a petição da
FRASLE (DOCX de 1.068 linhas). As duas demoraram muito; a segunda foi
compactada duas vezes pelo claude.ai. Medido em homologação: manual 126.883
caracteres, casos de referência 196.942, instruções do projeto 4.838. As
instruções iam em 10 partes, cerca de 100 mil tokens, antes da petição.

- **Casos de referência sob consulta** (decisão do Thiago): não vão inteiros.
  O Claude os consulta por termo com `ler_manual_revisor(tipo="casos_referencia",
  termo=...)`. O manual, a régua, continua inteiro. Estimativa em homologação:
  de 10 para cerca de 4 partes. É a única diferença em relação às instruções
  do agente da tela.
- **Formato do JSON repetido no fim**, junto da tarefa: a compactação levava a
  parte 1, onde está o contrato, e o Claude chutava o formato (teses recusadas
  no 1º teste, documentos em falta no 2º).
- **Item fora do formato vira aviso e pedido de reenvio** com o
  `formato_esperado`. Item que não era objeto (tese em texto solto) sumia sem
  registro nenhum, inclusive no agente da tela; agora entra em `parse_errors`.
- **Confirmar a petição achada pelo Claude** antes de usar o histórico: no 2º
  teste ele usou a petição 69 por conta própria.
- Fora deste ajuste, anotado para card próprio: a regra R4 do saneador (60 dias)
  descartou nos dois testes um achado de data divergente ("DIB 04/05/1993" no
  texto x 26/04/2013 na tabela), porque descarta qualquer achado que cite
  DCB/DIB com duas datas a mais de 60 dias, mesmo sem falar de
  restabelecimento. Vale também para a revisão da tela.

## Testes no claude.ai

- **T1, antes de construir** (5 min, conta do escritório, conversa nova):
  - Anexar uma petição em DOCX que tenha prints (CAT, telas do FAP) e
    perguntar: "Sem usar código: quantas imagens há neste documento, logo
    depois de qual título está cada uma, e o que cada uma mostra?".
  - Repetir com a mesma petição em PDF.
  - Se ele não vir as imagens do DOCX, entra a regra "DOCX com prints → peça
    o PDF" no bloco de adaptação.
- **T2, logo depois de `revisar_peticao_inicial` nova no ar**, antes do resto:
  - Pedir "chame revisar_peticao_inicial, leia todas as partes e me diga
    quantas recebeu e as últimas palavras de cada uma".
  - Se alguma parte vier cortada, reduzir o tamanho das partes.
- **T3, ponta a ponta com a equipe**: a Protege 2018 de novo. Revisão na
  conversa, conferência, gravar e não gravar, selo na tela, triagem sem
  "versão final".

## Testes automatizados

No padrão de `tests/test_mcp_fap_review.py` (script executável):

- **Instruções**: o conteúdo bate com o que o agente monta (mesma função);
  vêm em partes de no máximo 40 mil caracteres que, juntas, reproduzem o
  prompt; trazem os pontos de atenção da última revisão do IntellexIA e não
  os de uma revisão do Claude; petição travada traz o aviso.
- **Conferência**:
  - JSON válido gera rascunho com os achados saneados (R2/R6 descartam, R4
    corrige);
  - JSON inválido não gera rascunho, e chave de primeiro nível faltando ou com
    nome errado também não;
  - item ruim sai com aviso;
  - achado descartado na petição vem marcado;
  - rascunhos vencidos são apagados.
- **Gravação**:
  - rascunho de outro usuário ou escritório é recusado, e o vencido também;
  - gravar duas vezes devolve a mesma revisão;
  - petição nova sem Id Wrike, petição travada e revisão em processamento são
    recusadas;
  - a revisão grava com `review_origin='claude'`, numeração seguinte e
    petição em "Em revisão".
- **Origem**:
  - a revisão do Claude fica fora da pontuação;
  - "versão final" é recusada na triagem;
  - a mudança manual para aprovação é recusada a não-admin e aceita para o
    admin;
  - a tela do resultado abre sem arquivo.
- **O que sai**: `/revisao/enviar/<token>` responde 404 e volta a exigir
  login como o resto do app; `revisar_peticao_inicial` não aceita mais
  `texto_peticao` nem `link_drive`; a suíte do Drive
  (`tests/test_google_drive_client.py`) continua passando sem o `gdoc_como`.
- **Histórico**: a reescrita do mesmo achado casa; achados diferentes da
  mesma categoria não casam.

## Documentação

- `docs/MANUAL_REVISOR_PETICOES.md`, seção do Claude:
  - a revisão na conversa como caminho principal;
  - o selo "Feita no Claude" e as duas regras (fora da pontuação, sem
    aprovação);
  - uma revisão por conversa;
  - sem link de envio, Drive nem liberação de domínio.
- `docs/MANUAL_MCP.md`: a nova descrição de `revisar_peticao_inicial` e
  `comparar_versoes_peticao`, as duas ferramentas novas com a coluna Nome, e
  a contagem de ferramentas. Conferir com `tests/test_mcp_catalogo.py`.
- `docs/MCP_CONEXAO.md`: sem o passo de liberar o domínio.
- `CLAUDE.md`:
  - sem a linha do blueprint `fap_review_upload` nem a do
    `fap_review_upload_service`;
  - a linha do `fap_review_service` refeita;
  - uma nota sobre `review_origin` e as três regras.

## Decisões que tomei (Claude), para conferir

- **Há um passo de conferência antes de perguntar se grava** (rascunho no
  IntellexIA), diferente de "só manda no fim". Motivos:
  - o saneador corrige e descarta (a R4 corrige a contagem de dias entre DCB e
    DIB; a R2 tira duplicado), e mostrar o resultado antes dele significaria
    gravar algo diferente do que a pessoa viu;
  - o JSON chega validado antes de a pessoa ver "pronto";
  - na gravação o Claude não reescreve o JSON.

  O rascunho guarda só o resultado (nunca a petição), não entra no histórico e
  vence em 24 h.
- **R1 e R3 desligadas** nesse fluxo, porque o servidor não tem o texto da
  petição.
- **Pontos de atenção só de revisões do IntellexIA**, nos dois fluxos.
- **Revisão do Claude depois de uma do IntellexIA** exige nova revisão do
  IntellexIA para ir à aprovação. É a consequência de "a última revisão tem
  de ser do IntellexIA".
- **Petição travada**: dá para revisar na conversa, mas não para gravar.
- **Aprovação**: a trava vale também para a mudança manual de status por quem
  não é admin. O admin continua podendo mudar à mão.
- **"Fora da pontuação"** é só a pontuação e as estatísticas por advogado. O
  cartão de total de revisões e os filtros por advogado contam a revisão do
  Claude.
- **Conferência**: recusa chave de primeiro nível faltando ou com nome errado;
  item ruim fica de fora com aviso, como no servidor; achado já marcado "não
  pertinente" vem marcado.
- **Instruções em partes de 40 mil caracteres**, para não depender do teto de
  resposta do cliente, que não conhecemos no claude.ai.
- **O modelo gravado é o que o Claude informa**, sem conferência.
- **Fora da API `/api/v1` nesta entrega**: o Revisor não tem nenhuma rota na
  API hoje, e gravar por ela seria uma terceira origem a tratar. As
  ferramentas vão ao MCP e ao `MANUAL_MCP.md`, que alimenta a Biblioteca de IA.
- **Os nomes `revisar_peticao_inicial` e `comparar_versoes_peticao` ficam**,
  agora entregando as instruções, para não quebrar quem já os usa.
- **A tabela do link de envio fica no banco** até você rodar o script de
  remoção.
- **A correção do histórico** (mesmo achado com outra redação) entra junto. A
  pasta do anexo e a página de envio deixam de existir com o fluxo antigo.

## O que fica com quem constrói

- Nome e lugar das funções extraídas do agente (montagem das instruções e
  parse do resultado), desde que o agente passe a usá-las.
- O corte exato das partes, desde que nunca no meio de uma linha.
- O formato da lista de achados que a conferência devolve para exibir.
- O visual do selo e do botão desabilitado.
