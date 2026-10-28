# Revisor pelo Claude: o arquivo da petição chega sem o Claude reescrevê-lo (RPI-37)

> **Substituído em 28/10/2026** por `docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md`: o Claude passou a revisar na própria conversa e o link de envio, o Drive e a revisão no servidor pelo MCP saíram.

## Por quê

O card RPI-37 ("revisar_peticao_inicial não devolve resultado pelo MCP") teve
duas causas, e só a primeira já está resolvida no código:

1. **A revisão rodava dentro da chamada da ferramenta.** Em produção ela passa
   de 5 minutos (prompt com manual FAP e casos de referência, raciocínio longo
   do modelo) e o app do Claude desiste antes. **Resolvido** nesta mesma branch:
   `revisar_peticao_inicial` e `comparar_versoes_peticao` exigem o Id Wrike,
   abrem a execução "processando" por `fap_review_service.start_text_review`,
   disparam `fap_review._start_review_in_background(..., notify_user=True)` — a
   mesma thread da tela — e respondem na hora com `revisao_id`, `link`,
   `mensagem_para_usuario` e `proximo_passo`. O `detalhar_revisao` mostra o
   andamento e marca como falha a revisão presa (`fail_if_stuck`). Ao terminar,
   quem pediu recebe e-mail (`send_revision_finished_email`,
   `templates/emails/revisao_concluida.html`). Teste: `tests/test_mcp_fap_review.py`.

2. **O arquivo anexado no Claude não chega ao servidor.** O MCP só recebe o que o
   Claude escreve na chamada. Com a petição anexada, o Claude lê o documento e
   *reescreve o texto inteiro* como argumento: estimado em ~10 s para 2.500
   caracteres e 10–15 min para os 174 mil da petição da SENDAS (≈45 mil tokens),
   que ainda pode bater no limite de saída. **É isto que este design resolve.**

## O que muda para o usuário

Ele pede a revisão ao Claude informando o Id Wrike. A ferramenta devolve um
caminho para o arquivo chegar, e o resto é o fluxo que já existe (processando →
e-mail → resultado no histórico e no `detalhar_revisao`). São quatro entradas
para a mesma revisão:

| Entrada | Quando | Como o arquivo chega |
|---|---|---|
| **Texto** | Petição curta, ou texto colado na conversa | O Claude manda o texto (já existe) |
| **Link do Drive** | O arquivo está no Google Drive | O usuário cola o link; o IntellexIA baixa |
| **Link de envio, pelo Claude** | Arquivo anexado e o Claude consegue rodar comandos | O Claude roda `curl` com o anexo para o link |
| **Link de envio, pela pessoa** | Qualquer outro caso | A pessoa abre o link e solta o arquivo na página |

O link de envio é **um endereço só** para as duas últimas linhas: `GET` mostra a
página, `POST` recebe o arquivo (da página ou do `curl`).

### Confirmado em 27/10/2026

No app do Claude da conta do escritório, com `rs.intellexia.com.br` liberado na
lista de rede (Settings > Capabilities), o anexo aparece em
`/mnt/user-data/attachments/` e `curl -sI https://rs.intellexia.com.br/api/v1/eu`
responde `401` do nosso servidor (passou pelo proxy do Claude e pela Cloudflare).
Sem o domínio liberado, o proxy recusa (`connect_rejected`) — por isso a página
para a pessoa é obrigatória, não um extra.

## Metas

- Petição longa revisada pelo Claude sem ele reescrever o texto.
- O que chega por link de envio ou Drive segue **o caminho da tela**, com o
  **arquivo original** (DOCX/PDF/TXT): mesma extração de texto, mesmo modo de
  anexo para PDF, pontos de atenção, achados descartados, numeração, auditoria,
  e-mail. Nenhuma lógica de revisão nova.
- Página de envio "fácil e bonita" (pedido do Thiago): a opção **B** dos modelos.
- O Claude sempre sai da chamada com algo útil para dizer: link para acompanhar,
  pergunta para fazer depois, ou o motivo exato da recusa.

## Fora do escopo (não fazer agora)

- Comparar duas versões por arquivo (link de envio ou Drive). A comparação
  continua só por texto (`comparar_versoes_peticao`).
- Documentos auxiliares e planilha de benefícios pelo link (a tela continua
  sendo o lugar deles).
- Envio do arquivo pela API pública `/api/v1` com token pessoal: o link de uso
  único dispensa colar token na conversa, que era a preocupação.

## Antimetas (falha mesmo se "funcionar")

- O link de envio virar porta para outro escritório, outra petição ou outra
  pessoa: ele vale para **um** escritório, **um** usuário (quem pediu), **um**
  Id Wrike e **um** envio, e expira.
- Arquivo que não é DOCX/PDF/TXT (ou HTML de erro do Drive) chegar ao agente.
- Revisão em dobro: segundo envio enquanto a primeira processa (cada uma é uma
  chamada paga). Vale a mesma regra do `start_text_review` (`ja_em_andamento`).
- Petição bloqueada (aguardando aprovação, aprovada, protocolada, arquivada)
  receber revisão por um caminho lateral — usa `describe_new_revision_block`.

## Como é feito

### Ferramenta `revisar_peticao_inicial`

Assinatura passa a ser `(identificador_documento, titulo="", texto_peticao=None,
link_drive=None)`. `identificador_documento` continua obrigatório (o Claude
pergunta o Id Wrike antes — já na docstring).

- **Com `texto_peticao`** → como hoje.
- **Com `link_drive`** → baixa o arquivo (abaixo) e abre a revisão com ele.
- **Sem os dois** → cria o link de envio e responde com: `link_envio`, validade,
  o comando `curl` pronto (`curl -sS -F arquivo=@"<caminho do anexo>" <link>`),
  e uma `mensagem_para_usuario` com o link para a pessoa abrir se o Claude não
  conseguir enviar. A docstring orienta a ordem: arquivo anexado → tente o
  `curl` com o caminho em `/mnt/user-data/attachments/`; se falhar (rede
  recusada, comando indisponível), repasse o link à pessoa.
- **Com os dois** (texto e link) → erro claro pedindo um só.

A docstring orienta quando usar cada entrada: texto só para petição curta
(ordem de grandeza: até ~20 mil caracteres); arquivo anexado ou petição longa →
sem texto, pelo link; arquivo no Drive → `link_drive`.

Antes de criar o link ou baixar do Drive, a ferramenta já recusa o que a tela
recusaria: Id Wrike inválido para petição nova, petição bloqueada. A checagem de
revisão em andamento acontece **no envio** (é quando a execução nasce).

### Abrir a revisão a partir de um arquivo (serviço)

`start_text_review` hoje grava o texto em `.txt` e cria a execução. Extrair dela
uma função que recebe **um arquivo já salvo** (caminho + nome original) e faz o
resto (petição por Id, bloqueio, em andamento, numeração, execução
"processando", auditoria "via MCP"). `start_text_review` passa a ser: grava o
`.txt` → chama essa função. Drive e link de envio chamam a mesma função com o
arquivo deles. Disparo: `_start_review_in_background(..., notify_user=True)`.

O arquivo é salvo em `upload_directory(law_firm_id, 'revisions')`, com o mesmo
esquema de nome da tela (`timestamp_` + `secure_filename`). Tipos aceitos:
`pdf`, `docx`, `txt` (o `.doc` a tela recusa; aqui também). Conferir a extensão
**e** o conteúdo (assinatura `%PDF`, ZIP para DOCX) antes de salvar o arquivo
final — lição do DOU e do Drive: nada vira arquivo antes de provar que é o tipo
certo.

### Link do Drive

- Id do arquivo tirado do link (`/d/<id>`, `?id=<id>`); link sem id → erro
  dizendo o formato esperado.
- Download por `impugnacao_import_service.download_drive_file(id, dir,
  law_firm_id=...)`, que já tenta a conta de serviço (só para o escritório
  configurado em `GOOGLE_DRIVE_LAW_FIRM_ID`) e cai no anônimo.
- Sem acesso → a resposta repete a regra para o usuário: o arquivo tem de estar
  **compartilhado com `intellexia-drive@intellexia-503416.iam.gserviceaccount.com`**
  (Leitor) **ou** público para quem tem o link. As mensagens prontas já existem
  (`_RESTRICTED_MESSAGE`, `_RESTRICTED_MESSAGE_WITH_ACCOUNT`).
- O download roda dentro da chamada da ferramenta (segundos; o lento é a
  revisão, que continua em segundo plano).

### Link de envio

**Registro** em tabela nova `fap_review_upload_links` (migration
`database/add_fap_review_upload_links_table.py`, padrão do projeto), com
`law_firm_id`: hash SHA-256 do token (o token em si só existe no link), usuário
que pediu, Id Wrike, título informado, `expires_at`, `used_at`, `execution_id`,
`created_at`. Token aleatório (`secrets.token_urlsafe`), nunca gravado em claro —
mesmo padrão do `api_token_service`.

**Rotas** no app web (é ele que serve `rs.intellexia.com.br`), num blueprint
próprio, fora da sessão: o `check_session` de `app/middlewares.py` precisa
deixar passar esse prefixo, como já faz com `/api/v1`. O token na URL é a
autorização.

- `GET /revisao/enviar/<token>` → página B (antes). Mostra petição (título ou
  "petição nova"), Id Wrike, "esta será a revisão N", "pedido por <nome>, pelo
  Claude", área de arrastar/escolher (PDF, DOCX ou TXT) e a validade.
  Estados próprios, sem quebrar: link expirado, link já usado (com o link da
  revisão que ele gerou), link inexistente, petição bloqueada.
- `POST /revisao/enviar/<token>` (multipart, campo `arquivo`) → valida, marca o
  link como usado **na mesma transação** que cria a execução (dois envios
  simultâneos não abrem duas revisões), dispara a thread, responde **JSON**
  (`revisao_id`, `numero_revisao`, `link`, `pergunta_claude`, `mensagem`) — a
  página consome por `fetch`, o `curl` lê direto.
- Sem CSRF de formulário (não há sessão; o token é o segredo).

**Página B (depois do envio)** — conforme o modelo aprovado
(`.superpowers/brainstorm/563760-1793110571/pagina-envio-b-v3.png`): círculo de
processando, "Revisão N em processamento", nome do arquivo e hora, "leva alguns
minutos, você recebe um e-mail quando terminar", botão **Acompanhar a revisão**
(tela do Revisor — pede login, como qualquer tela) e, separado, a caixa escura
estilo bloco de código com o rótulo "Claude", a pergunta
`Como está a revisão N da petição <Id Wrike>?` e o botão **Copiar** (vira
"✓ Copiado" por alguns segundos). A pergunta leva o Id Wrike para funcionar
numa conversa nova.

Página standalone (não herda o `base.html` com menu, porque não há sessão), com
JS nativo, funcionando em celular. Logo do IntellexIA.

### `detalhar_revisao` e a pergunta da caixa

A pergunta "Como está a revisão N da petição <Id>?" tem de levar o Claude ao
resultado. Hoje `detalhar_revisao` pede `revisao_id`; o Claude chega a ele por
`historico_revisoes_peticao(identificador=...)`. A docstring de
`detalhar_revisao` deve dizer esse caminho (ou o handler aceitar Id Wrike +
número da revisão — decisão do builder).

### Documentação

- `docs/MANUAL_REVISOR_PETICOES.md` (seção do Claude): as formas de mandar o
  arquivo e a regra do Drive.
- `docs/MANUAL_MCP.md`: descrição da `revisar_peticao_inicial`.
- `docs/MCP_CONEXAO.md` e o CLAUDE.md (blueprint novo na tabela de blueprints;
  liberação do domínio no Claude para o `curl` funcionar).

## Decisões que tomei (Claude), para conferir

- **Validade do link: 2 horas**, um envio só.
- **Sem login na página**: o token é a autorização (o Thiago pediu "link
  público, que tenha duração"). O botão "Acompanhar a revisão" leva à tela do
  Revisor, que pede login normalmente.
- **Limite de tamanho do arquivo: 50 MB** (a Cloudflare corta em 100 MB).
- **Texto só para petição curta**, com a referência de ~20 mil caracteres na
  docstring — o Claude decide; não há corte no servidor além do mínimo de 200.
- **Drive baixa dentro da chamada**, revisão em segundo plano.
- **Comparação por arquivo fica fora** desta entrega.
- **Arquivo enviado enquanto outra revisão da petição processa: recusado, e o
  link continua valendo.** A página e o JSON dizem que a revisão N ainda está
  rodando e que dá para enviar de novo por este mesmo link (até a validade). O
  arquivo não é guardado. Motivo: quem solta um arquivo novo quase sempre tem
  uma versão mais nova que a em revisão — descartar em silêncio (como o
  `ja_em_andamento` faz com texto) perderia o envio, e enfileirar seria
  mecanismo novo para um caso raro.
- **Qualquer recusa deixa o link reutilizável** (tipo errado, tamanho, petição
  bloqueada, revisão em andamento, falha ao salvar). O link só é consumido na
  transação que cria a execução.
- **Google Docs nativo no `link_drive` é exportado como DOCX**, não PDF: com
  DOCX o agente recebe o texto extraído (como na tela), com PDF iria como anexo,
  com outra qualidade e custo. Vale para a conta de serviço (acrescentar o
  formato DOCX à exportação do `google_drive_client`) e para o anônimo
  (`docs.google.com/document/d/<id>/export?format=docx`, que serve a Doc
  público). Doc sem acesso recebe a mesma mensagem de compartilhamento.
- **Limite de tamanho: 20 MB, não 50.** O nginx do app web em produção não está
  no repositório e pode cortar antes (413 sem mensagem amigável). Petição em
  DOCX/PDF raramente passa de alguns MB. **Conferir no deploy** o
  `client_max_body_size` do site web; se for menor que 20 MB, subir. O primeiro
  envio real pelo `curl` do Claude também é teste de deploy — até agora só os
  cabeçalhos foram testados.

## O que fica com quem constrói

- Nome do blueprint e do módulo de serviço do link de envio.
- Como a página mostra erro de tipo/tamanho e o progresso do upload.
- Se o handler de `detalhar_revisao` ganha busca por Id Wrike + número.
- Testes: seguir o padrão de `tests/test_mcp_fap_review.py` (agente falso,
  e-mail interceptado, thread real), cobrindo os estados do link (válido,
  expirado, usado, de outro escritório), os dois envios simultâneos, os tipos
  recusados e o Drive com download simulado.
