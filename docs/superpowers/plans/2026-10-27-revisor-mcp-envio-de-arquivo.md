# Revisor pelo Claude: envio do arquivo — Implementation Plan

> **Substituído em 28/10/2026** por `docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md`: o Claude passou a revisar na própria conversa e o link de envio, o Drive e a revisão no servidor pelo MCP saíram.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a revisão pedida pelo Claude recebe o arquivo original da petição por link de envio de uso único (página ou `curl`) ou por link do Drive, além do texto curto que já funciona.

**Architecture:** uma função de serviço abre a revisão a partir de um arquivo já salvo (o texto vira `.txt` e usa a mesma); link de envio em tabela própria com hash do token; blueprint público `/revisao/enviar/<token>` (GET = página B, POST = recebe o arquivo, responde JSON); a ferramenta MCP escolhe a entrada. Tudo dispara `_start_review_in_background(..., notify_user=True)`, a thread da tela.

**Tech Stack:** Flask 3.1, Flask-SQLAlchemy, Jinja2, JS nativo, fastmcp 3.2.4, `requests`.

**Spec:** `docs/superpowers/specs/2026-10-27-revisor-mcp-envio-de-arquivo-design.md`

## Global Constraints

- Testes são scripts standalone (`uv run python tests/<arquivo>.py`), padrão de `tests/test_mcp_fap_review.py`: `check()`, agente falso no lugar de `fap_review_bp.FapPetitionReviewerAgent`, `email_service.send_email` interceptado, `_esperar(revisao_id)` com `db.session.rollback()` (MySQL REPEATABLE READ), limpeza no fim.
- Migration é script standalone em `database/`, idempotente, `with app.app_context()`, padrão de `database/add_api_tokens_table.py`.
- Toda query filtra `law_firm_id`. Datetimes de validade em UTC (`datetime.utcnow()` / padrão `_utcnow` do projeto).
- Tipos aceitos: `pdf`, `docx`, `txt`. `.doc` recusado. Limite **20 MB** (`MAX_UPLOAD_BYTES = 20 * 1024 * 1024`).
- Validade do link: **2 horas** (`LINK_VALIDITY = timedelta(hours=2)`), um envio.
- Conta de serviço do Drive: `intellexia-drive@intellexia-503416.iam.gserviceaccount.com`.
- Pergunta da caixa: `Como está a revisão {N} da petição {Id Wrike}?`
- Não fazer commit sem o Thiago pedir; ao fim de cada task, rodar os testes indicados e seguir.
- Textos de tela, mensagens e comentários em português, no tom do código vizinho.

## Review Focus

1. **Nome de arquivo com acento ou sem extensão** ("Petição SENDAS.docx", "peticao") — `secure_filename` tira acento e pode zerar o nome; a extensão sai do nome original, e nome vazio vira `peticao.<ext>`. Teste na Task 3.
2. **Extensão mentindo** (PDF renomeado `.docx`, `.doc` antigo renomeado) — recusa 400 pela assinatura do conteúdo, link continua valendo. Teste na Task 3.
3. **Petição bloqueada entre gerar o link e enviar** — GET mostra o estado bloqueado; POST recusa 403; link continua valendo. Teste na Task 3.
4. **Dois envios pelo mesmo link** (duplo clique, `curl` repetido) — só uma execução; o consumo é `UPDATE ... WHERE used_at IS NULL` com conferência de `rowcount`. Teste na Task 3.
5. **Token inexistente, de outro escritório ou expirado** — 404 / 410 com página própria, sem dizer de quem é o link. Teste na Task 4.

---

### Task 1: Abrir revisão a partir de um arquivo (serviço)

**Files:**
- Modify: `app/services/fap_review_service.py` (`start_text_review` e vizinhança)
- Test: `tests/test_mcp_fap_review.py` (deve continuar passando sem mudar asserts)

**Interfaces:**
- Produces:
  - `check_new_revision_allowed(law_firm_id: int, identifier: str) -> tuple[FapReviewPetition | None, str]` — devolve `(petição existente ou None, identificador normalizado)`; levanta `ValueError` com a mensagem da tela (Id Wrike inválido para petição nova; `describe_new_revision_block`).
  - `running_revision(petition) -> FapReviewExecution | None` — revisão `processing` não presa da petição.
  - `open_file_review(law_firm_id: int, user_id: int | None, identifier: str, main_path: str, main_filename: str, title: str = '', compared_path: str | None = None) -> dict` — mesmo dicionário que `start_text_review` devolve hoje (`ja_em_andamento`, `peticao_id`, `revisao_id`, `numero_revisao`, `peticao_criada`, `titulo`, `petition_path`, `compared_path`). Com revisão em andamento, devolve `ja_em_andamento=True` **sem** criar nada e sem apagar o arquivo (quem chamou decide).
  - `start_text_review` passa a gravar o `.txt` e chamar `open_file_review`; se vier `ja_em_andamento`, apaga os `.txt` que acabou de gravar.

- [ ] **Step 1:** Extrair as três funções de `start_text_review` sem mudar comportamento; a gravação do `.txt` passa a acontecer **depois** de `check_new_revision_allowed` e de `running_revision` (hoje o texto não é gravado quando a revisão está em andamento — manter).
- [ ] **Step 2:** Rodar `uv run python tests/test_mcp_fap_review.py` — esperado: `✅ Todas as verificações passaram.`

### Task 2: Modelo, migration e serviço do link de envio

**Files:**
- Modify: `app/models.py` (nova classe depois de `ApiToken`)
- Create: `database/add_fap_review_upload_links_table.py`
- Create: `app/services/fap_review_upload_service.py`
- Test: `tests/test_fap_review_envio_arquivo.py` (novo; seções 1–2)

**Interfaces:**
- Produces:
  - Modelo `FapReviewUploadLink`, tabela `fap_review_upload_links`: `id`, `law_firm_id` (FK, index), `user_id` (FK users, `ondelete='CASCADE'`), `token_hash` (String 64, unique), `identifier` (String 96), `title` (String 255, default ''), `expires_at` (UTC), `used_at` (UTC, null), `execution_id` (FK `fap_review_executions.id`, `ondelete='SET NULL'`, null), `created_at` (UTC).
  - `create_upload_link(law_firm_id: int, user_id: int, identifier: str, title: str = '') -> tuple[FapReviewUploadLink, str]` — chama `check_new_revision_allowed` antes (levanta `ValueError`); token `secrets.token_urlsafe(32)`; grava só o SHA-256; devolve `(registro, token_em_claro)`.
  - `upload_link_url(token: str) -> str` — absoluto, por `url_for('fap_review_upload.enviar', token=..., _external=True)` dentro de `test_request_context(base_url=app_public_url())` (mesma técnica de `revision_result_url`).
  - `find_link(token: str) -> tuple[FapReviewUploadLink | None, str]` — estado: `'valido'`, `'expirado'`, `'usado'`, `'inexistente'`.
  - `link_page_context(link) -> dict` — `titulo` (da petição existente, senão o título informado, senão "Petição nova"), `identificador`, `peticao_nova: bool`, `proxima_revisao: int`, `pedido_por` (nome do usuário), `expira_em` (datetime SP), `bloqueio: str | None`, `em_andamento: FapReviewExecution | None`.
  - `MAX_UPLOAD_BYTES`, `LINK_VALIDITY`, `ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}`.

- [ ] **Step 1: Teste (seção 1, link):** `create_upload_link` devolve token de ≥ 40 caracteres e o banco guarda só `sha256(token)` (`token_hash != token`); `find_link(token)` → `'valido'`; `expires_at - created_at == 2h`; `find_link('lixo')` → `(None, 'inexistente')`; com `expires_at` no passado → `'expirado'`; com `used_at` preenchido → `'usado'`; Id `'FAP-1'` para petição nova levanta `ValueError`; petição `awaiting_approval` levanta `ValueError` com "não aceita nova revisão".
- [ ] **Step 2: Teste (seção 2, página):** `link_page_context` de petição existente com 2 revisões → `proxima_revisao == 3`, `peticao_nova is False`, título da petição; de Id novo → `peticao_nova is True`, `proxima_revisao == 1`.
- [ ] **Step 3:** Rodar `uv run python tests/test_fap_review_envio_arquivo.py` — esperado: falha (módulo inexistente).
- [ ] **Step 4:** Implementar modelo, migration (`criar_tabela()` como a de `api_tokens`) e as funções acima. Rodar a migration: `uv run python database/add_fap_review_upload_links_table.py` → `[OK] Tabela fap_review_upload_links criada` (e na segunda vez `já existe`).
- [ ] **Step 5:** Rodar o teste — esperado: seções 1–2 passam.

### Task 3: Receber o arquivo pelo link

**Files:**
- Modify: `app/services/fap_review_upload_service.py`
- Test: `tests/test_fap_review_envio_arquivo.py` (seção 3)

**Interfaces:**
- Consumes: `open_file_review`, `running_revision`, `check_new_revision_allowed` (Task 1); `find_link` (Task 2); `fap_review._start_review_in_background`.
- Produces:
  - `class UploadRecusado(Exception)` com `status_http: int`, `mensagem: str`, `extra: dict`.
  - `validate_review_file(stream_head: bytes, filename: str) -> str` — devolve a extensão (`'pdf'|'docx'|'txt'`) ou levanta `UploadRecusado(400, ...)`. Assinaturas: PDF começa com `%PDF`; DOCX é ZIP (`PK\x03\x04`) contendo `word/document.xml`; TXT decodifica em UTF-8 (ou latin-1) sem bytes nulos.
  - `receive_upload(token: str, file_storage) -> dict` — devolve `{'revisao_id', 'numero_revisao', 'peticao_id', 'link', 'pergunta_claude', 'mensagem', 'arquivo'}`; recusas por `UploadRecusado`: 404 inexistente, 410 expirado, 409 usado (com `extra={'link': <revisão gerada>}`), 400 sem arquivo / tipo / vazio, 413 acima de `MAX_UPLOAD_BYTES`, 403 petição bloqueada, 409 revisão em andamento (`extra={'revisao_id', 'numero_revisao'}`, mensagem dizendo que dá para reenviar por este link até a validade).
  - Ordem: estado do link → arquivo presente e tamanho → grava em `upload_directory(law_firm_id, 'revisions')/<timestamp>_<nome seguro>.part` → `validate_review_file` → renomeia → `open_file_review` → se `ja_em_andamento`, apaga o arquivo e recusa 409 → consome o link com `UPDATE fap_review_upload_links SET used_at=:agora, execution_id=:id WHERE id=:id AND used_at IS NULL` na **mesma transação** do commit da execução; `rowcount == 0` → rollback, apaga arquivo, recusa 409 usado → dispara `_start_review_in_background(revisao_id, law_firm_id, caminho, None, notify_user=True)`.
  - Nome seguro: `secure_filename(nome_original)`; se vazio ou sem extensão, `peticao.<ext>`; `main_filename` da execução guarda o **nome original**.
  - Erro em qualquer passo antes do consumo apaga o `.part`/arquivo e não toca no link.

- [ ] **Step 1: Teste (seção 3):** com `FileStorage(io.BytesIO(...), 'Petição SENDAS.docx')` de um DOCX mínimo válido (gerar com `python-docx`), `receive_upload` devolve `numero_revisao == 1`, `pergunta_claude == 'Como está a revisão 1 da petição <IDENT>?'`, execução conclui pela thread com o agente falso recebendo o texto do DOCX em `petition_text`, `main_filename == 'Petição SENDAS.docx'`, link fica `'usado'` com `execution_id` preenchido, e-mail interceptado = 1. Segundo `receive_upload` com o mesmo token → `UploadRecusado` 409. Conteúdo `%PDF-1.4...` com nome `x.docx` → 400 e link segue `'valido'`. Arquivo de 0 bytes → 400. Arquivo > `MAX_UPLOAD_BYTES` (monkeypatch do limite para 1 KB) → 413. Petição bloqueada depois do link → 403 e link `'valido'`. Revisão em andamento (`start_text_review` antes, sem thread) → 409 com `extra['revisao_id']`, nenhum arquivo novo em `uploads/fap_review/<firm>/revisions` e link `'valido'`. PDF válido mínimo (`%PDF-1.4\n%%EOF`) → aceito, agente recebe `petition_text is None` (modo anexo, como na tela).
- [ ] **Step 2:** Rodar — esperado: seção 3 falha.
- [ ] **Step 3:** Implementar `validate_review_file`, `UploadRecusado`, `receive_upload`.
- [ ] **Step 4:** Rodar `uv run python tests/test_fap_review_envio_arquivo.py` e `uv run python tests/test_mcp_fap_review.py` — esperado: ambos passam.

### Task 4: Página pública de envio (blueprint + template)

**Files:**
- Create: `app/blueprints/fap_review_upload.py` (`fap_review_upload_bp`, sem `url_prefix`)
- Create: `templates/fap_review/envio_arquivo.html` (standalone, não herda `base.html`)
- Modify: `app/blueprints/__init__.py`, `main.py` (registrar), `app/middlewares.py` (`check_session`: deixar passar `request.path.startswith('/revisao/enviar/')`, como `/api/v1`)
- Test: `tests/test_fap_review_envio_arquivo.py` (seção 4)

**Interfaces:**
- Consumes: `find_link`, `link_page_context`, `receive_upload`, `UploadRecusado` (Tasks 2–3).
- Produces: endpoint `fap_review_upload.enviar`, rota `/revisao/enviar/<token>`, `GET` e `POST`.
  - `GET` → 200 com a página B (antes); estados `expirado` (410), `usado` (200, com botão para a revisão gerada), `inexistente` (404), bloqueado e em andamento (200, aviso no lugar da área de envio).
  - `POST` (campo `arquivo`) → JSON: 200 `{'ok': True, ...receive_upload}`; recusa → `status_http` de `UploadRecusado` com `{'ok': False, 'erro': mensagem, **extra}`.
  - `Cache-Control: no-store` nas duas respostas; `<meta name="robots" content="noindex">` na página.

- [ ] **Step 1: Teste (seção 4)** com `app.test_client()` **sem sessão**: GET válido → 200 e o corpo contém o Id Wrike, "revisão 1" e "Confira e envie o arquivo"; GET token lixo → 404 e o corpo não contém o Id; GET expirado → 410; POST multipart com DOCX válido → 200, `json['ok'] is True`, `json['pergunta_claude']`; POST repetido → 409 JSON; POST sem campo `arquivo` → 400 JSON; com sessão de usuário logado o GET também abre (não redireciona).
- [ ] **Step 2:** Rodar — esperado: seção 4 falha.
- [ ] **Step 3:** Implementar blueprint, registro, desvio no middleware e o template conforme o modelo aprovado `.superpowers/brainstorm/563760-1793110571/content/pagina-envio-b-v3.html` (opção B): cartão com logo (`static/assets/img/logo_maior.png`) e selo "Revisor de Petições", linhas Petição / Id Wrike / Esta será a revisão N / Pedido por "<nome>, pelo Claude", área de arrastar ou escolher ("PDF, DOCX ou TXT · válido até HH:MM"), barra de progresso do upload via `XMLHttpRequest` (`upload.onprogress`), mensagens de erro na própria área; depois do envio, troca para: círculo de processando, "Revisão N em processamento", nome do arquivo e hora, "Leva alguns minutos. Você recebe um e-mail quando terminar.", botão **Acompanhar a revisão** (`link`), e a caixa escura rotulada "Claude" com `pergunta_claude` e botão **Copiar** (`navigator.clipboard.writeText`, com fallback por `document.execCommand('copy')` num `textarea`), que vira "✓ Copiado" por 2 s. CSS inline no template, responsivo (cartão `max-width: 440px`, largura total no celular). `pergunta_claude` e nomes entram por `textContent`, nunca `innerHTML`.
- [ ] **Step 4:** Rodar o teste — esperado: passa. Tirar print com `uv run --with playwright python /tmp/print_mock.py "http://127.0.0.1:<porta>/revisao/enviar/<token>" instance/print_envio.png` (app de dev rodando) e conferir contra o modelo: antes, erro de tipo, depois do envio, botão Copiar.

### Task 5: Link do Drive

**Files:**
- Modify: `app/services/google_drive_client.py` (`baixar` ganha `gdoc_como: str = MIME_PDF`)
- Modify: `app/services/impugnacao_import_service.py` (`download_drive_file(..., gdoc_como: str | None = None)` repassa para a conta de serviço)
- Modify: `app/services/fap_review_upload_service.py`
- Test: `tests/test_fap_review_envio_arquivo.py` (seção 5)

**Interfaces:**
- Produces:
  - `drive_file_id_from_link(link: str) -> tuple[str, bool]` — `(id, eh_google_docs)`; aceita `/file/d/<id>`, `/document/d/<id>`, `?id=<id>`, `open?id=`; `eh_google_docs` quando o host é `docs.google.com` e o caminho começa em `/document/`. Link sem id → `ValueError("Não reconheci o link do Drive. Use o link de compartilhamento do arquivo (https://drive.google.com/file/d/...).")`.
  - `download_review_file_from_drive(link: str, law_firm_id: int) -> tuple[str, str]` — `(caminho salvo, nome original)` em `upload_directory(law_firm_id, 'revisions')`, conferido por `validate_review_file`. Google Docs nativo: conta de serviço com `gdoc_como=MIME_DOCX`; anônimo por `https://docs.google.com/document/d/<id>/export?format=docx`. Arquivo comum: `download_drive_file(id, dir, law_firm_id=..., gdoc_como=MIME_DOCX)`. Sem acesso → `ValueError` com: "Não consegui abrir o arquivo no Drive. Compartilhe com intellexia-drive@intellexia-503416.iam.gserviceaccount.com (Leitor) ou deixe aberto a qualquer pessoa com o link, e me peça de novo."; tipo não aceito → `ValueError` com os tipos aceitos.
  - Os outros chamadores de `baixar`/`download_drive_file` não mudam (padrão continua PDF).

- [ ] **Step 1: Teste (seção 5):** `drive_file_id_from_link` para os quatro formatos e para um link qualquer (`ValueError`). `download_review_file_from_drive` com `impugnacao_import_service.download_drive_file` substituído por um falso que grava um DOCX válido → devolve caminho existente; falso levantando `DriveAccessError` → `ValueError` contendo `intellexia-drive@`; falso gravando HTML → `ValueError` de tipo e nenhum arquivo deixado na pasta. Link de Docs com o anônimo falso (monkeypatch do `requests.get` usado pela função) devolvendo DOCX → aceito.
- [ ] **Step 2:** Rodar — falha. **Step 3:** implementar. **Step 4:** rodar — passa; rodar também `uv run python tests/test_drive_ingestion.py` se existir (`ls tests/ | grep -i drive`) para garantir que a exportação padrão segue PDF.

### Task 6: Ferramenta MCP escolhe a entrada + documentação

**Files:**
- Modify: `mcp_server/tools/petition_reviewer.py`, `mcp_server/server.py` (`revisar_peticao_inicial`, docstring de `detalhar_revisao`)
- Modify: `docs/MANUAL_REVISOR_PETICOES.md`, `docs/MANUAL_MCP.md`, `docs/MCP_CONEXAO.md`, `CLAUDE.md` (linha do blueprint `fap_review_upload` na tabela; nota sobre liberar `rs.intellexia.com.br` em Capabilities do Claude para o `curl`)
- Test: `tests/test_mcp_fap_review.py` (seção 14)

**Interfaces:**
- Consumes: `create_upload_link`, `upload_link_url`, `download_review_file_from_drive`, `open_file_review` (Tasks 1, 2, 5).
- Produces:
  - Tool `revisar_peticao_inicial(identificador_documento: str, titulo: str = "", texto_peticao: str | None = None, link_drive: str | None = None)`.
  - `review_petition_handler(law_firm_id, user_id=None, identificador_documento=None, titulo="", petition_text=None, link_drive=None) -> dict` — os testes existentes chamam com `petition_text` posicional: ajustar as chamadas para palavra-chave.
  - Sem texto nem Drive → `{'status': 'aguardando_arquivo', 'link_envio', 'expira_em' (HH:MM, SP), 'comando_curl': 'curl -sS -F arquivo=@"<caminho do anexo>" <link>', 'mensagem_para_usuario', 'proximo_passo'}`. `proximo_passo`: se há arquivo anexado em `/mnt/user-data/attachments/`, rodar o `comando_curl` com o caminho real e repassar a `mensagem` do JSON devolvido; se o comando falhar ou não houver como rodar, repassar `mensagem_para_usuario` (link para a pessoa abrir). `mensagem_para_usuario` cita o link, a validade e "solte o arquivo da petição".
  - Com `link_drive` → `check_new_revision_allowed` e `running_revision` **antes** de baixar (não baixa à toa), depois baixa, abre por `open_file_review`, dispara a thread, responde como o caminho de texto (`status: 'processando'`, `mensagem_para_usuario` etc.). Com `ja_em_andamento`, apaga o arquivo baixado.
  - Texto **e** Drive → `{'erro': 'Mande o texto ou o link do Drive, não os dois.'}`.
  - Docstring: ordem de escolha (arquivo anexado → sem texto, pelo link de envio e `curl`; arquivo no Drive → `link_drive`; texto só para petição curta, até ~20 mil caracteres); continua mandando perguntar o Id Wrike antes.
  - **Qual anexo enviar** (docstring e `proximo_passo`): antes do `curl`, listar `/mnt/user-data/attachments/` (`ls -la`) e considerar só PDF, DOCX e TXT. A pasta guarda todos os anexos da conversa, não só os da última mensagem. Regra:
    - **nenhum** desses → não rodar o `curl`; pedir ao usuário que anexe ou repassar o link da página;
    - **um** → usar esse, dizendo o nome do arquivo na resposta ("Enviei *Petição SENDAS.docx*…");
    - **mais de um** → perguntar ao usuário qual é a petição, listando os nomes, **antes** de enviar — a não ser que ele já tenha dito o nome. O link vale 2 horas; dá tempo de perguntar.
  - O JSON do `POST` devolve `arquivo` (nome recebido) para o Claude confirmar ao usuário o que foi enviado.
  - `detalhar_revisao` docstring: para "como está a revisão N da petição X?", chamar `historico_revisoes_peticao(identificador=X)` e pegar o `revisao_id` da revisão N.

- [ ] **Step 1: Teste (seção 14):** sem texto e sem Drive → `status == 'aguardando_arquivo'`, `link_envio` contém `/revisao/enviar/`, `comando_curl` contém o link e `arquivo=@`, e `find_link` do token do link → `'valido'`; Id inválido → `erro` sem criar link; texto e Drive juntos → `erro`; `link_drive` com download falso → `status == 'processando'` e execução conclui.
- [ ] **Step 2:** Rodar — falha. **Step 3:** implementar código e docs. **Step 4:** rodar `tests/test_mcp_fap_review.py`, `tests/test_fap_review_envio_arquivo.py` e `tests/test_mcp_catalogo.py` — todos passam; conferir a assinatura com `uv run python -c` listando `server.mcp.get_tool('revisar_peticao_inicial').parameters`.

### Task 7: Verificação final

- [ ] Rodar: `tests/test_mcp_fap_review.py`, `tests/test_fap_review_envio_arquivo.py`, `tests/test_mcp_catalogo.py`, `tests/test_fap_review_approval_workflow.py`, `tests/test_fap_review_reprocess.py`, `tests/test_fap_review_final_stage.py`, `tests/test_fap_review_kanban.py`, `tests/test_fap_review_reuse_previous_files.py`, `tests/test_fap_review_cost_persistence.py`, `tests/test_fap_review_user_review_status.py` — todos com saída 0.
- [ ] Revisão do branch inteiro por um revisor novo (código, não conclusões).
- [ ] Relatar ao Thiago: o que mudou, o que falta no deploy (migration `database/add_fap_review_upload_links_table.py`, restart do web e do MCP, conferir `client_max_body_size` ≥ 20 MB no nginx do site, primeiro envio real pelo `curl` do Claude), e perguntar sobre commit.
