# Importação de peças-modelo a partir de planilha (Drive)

**Data:** 2026-07-28 · **Módulo:** `impugnacao_references`

## Objetivo

Popular a base de peças-modelo em lote a partir da planilha de controle do
escritório ("Petições protocoladas (pós inicial) — Revisão de Insumos"), que já
traz metadados curados e o link do arquivo no Google Drive.

## Levantamento da planilha real (verificado)

- Aba `Planilha de teses`; cabeçalho na **linha 3**; dados a partir da linha 4;
  6.417 linhas.
- Colunas: `Nº | AUTORA | TRIBUNAL | ÓRGÃO JULGADOR | TESES / TÓPICOS | QNT. |
  MANIFESTAÇÕES APÓS A INICIAL | PROTOCOLADO` (A..H).
- **Uma linha por tese**; as linhas de uma mesma peça repetem Nº/AUTORA/tipo e
  apontam para o mesmo arquivo. A unidade de importação é o **arquivo**.
- Filtrando `MANIFESTAÇÕES APÓS A INICIAL` por "IMPUGNAÇÃO À CONTESTAÇÃO"
  (inclui a variante "… DO INSS"): **366 peças**, sendo **350 com link** e 16
  sem arquivo. Média **7,3 teses por peça** (máx. 23) — 2.667 linhas no total.
  (O hyperlink aparece só na primeira linha de cada grupo; contar linhas com
  link dá ~2,6 por peça, que **não** é o número de teses.)
- O link é hyperlink de célula (`cell.hyperlink.target`), formato
  `https://drive.google.com/file/d/<ID>/view`.
- **Compartilhamento varia por arquivo**: amostra de 20 → 11 baixam anonimamente,
  9 exigem login. Estimativa: ~190 de 350 baixam hoje.

## Decisões (aprovadas pelo usuário)

1. Download **anônimo** via `https://drive.usercontent.google.com/download?id=<ID>&export=download`.
   Arquivo restrito → item falha com mensagem explícita e link, para o usuário
   liberar no Drive e reprocessar. Sem setup no Google Cloud; o downloader fica
   com ponto de extensão para conta de serviço no futuro.
2. **Dedup em duas camadas**: `source_drive_file_id` (evita baixar de novo) e
   `file_hash` SHA-256 do conteúdo (pega o mesmo arquivo por outro caminho).
   Duplicata não cria peça nova — o item fica `skipped_duplicate` apontando para
   a peça existente.
3. Processamento **um a um, em fila persistida no banco** (não thread solta):
   sobrevive a restart e é retomável. Tela acompanha por polling.
4. Metadados da planilha entram como **fato curado** (autora, tribunal, órgão
   julgador, teses); a IA só preenche o que faltar (CNJ, juiz, modo A/B).

## Modelo de dados

**`impugnacao_import_jobs`** — um por planilha enviada:
`id, law_firm_id(idx), user_id, original_filename, file_path, status
('draft'|'running'|'completed'|'failed'), total_items, error_message,
created_at, updated_at, started_at, finished_at`.

**`impugnacao_import_items`** — um por peça candidata:
`id, job_id(FK CASCADE, idx), law_firm_id(idx), row_number, numero, autora,
tribunal_raw, trf_region, orgao_julgador, document_type_label, drive_file_id,
drive_url, theses_json, protocolado_at, selected(bool, default True),
status ('pending'|'downloading'|'indexing'|'completed'|'skipped_duplicate'|
'skipped_by_user'|'failed'), error_message, file_hash, reference_id(FK
nullable), created_at, updated_at`.

**Colunas novas em `impugnacao_reference_models`**:
`file_hash` VARCHAR(64) idx, `source_drive_file_id` VARCHAR(80) idx,
`source_theses_json` JSON.

Migration standalone aditiva, no padrão do projeto (cria as duas tabelas via
`db.create_all()` restrito e adiciona as 3 colunas com verificação prévia).

## Serviços

**`app/services/impugnacao_import_service.py`**
- `parse_spreadsheet(file_path, *, document_type_filter='IMPUGNAÇÃO À CONTESTAÇÃO') -> list[dict]`
  — localiza o cabeçalho, agrupa por `(numero, autora, drive_file_id)`, filtra
  pelo tipo (comparação sem acento/caixa, `in`), devolve candidatos com
  `{numero, autora, tribunal_raw, trf_region, orgao_julgador,
  document_type_label, drive_file_id, drive_url, teses[], protocolado_at,
  row_number}`. Peças sem link entram com `drive_file_id=None`.
- `normalize_tribunal(raw) -> Optional[str]` — `'TRF-4'`/`'TRF 4'`/`'trf4'` →
  `'TRF4'`; devolve None para o que não for TRF1..TRF6.
- `download_drive_file(drive_file_id, dest_dir) -> (path, filename, sha256)` —
  download anônimo; resposta `text/html` significa restrito → levanta
  `DriveAccessError` com mensagem pronta para a tela. Nome do arquivo vem do
  `Content-Disposition`, com fallback `<id>.pdf`.

**`app/services/impugnacao_reference_ingestion.py`** — extração do corpo do
worker de ingestão que hoje vive em `impugnacao_references._run_reference_ingestion`:
`ingest_reference(law_firm_id, ref_id, *, is_new)`, exigindo app context ativo e
**sem** `db.session.remove()` (quem chama gerencia a sessão). O blueprint passa a
ser só a casca de thread; o worker de importação chama a função direto no laço.

## Fluxo

1. `GET/POST /referencias-impugnacao/importar` — upload da planilha; no POST,
   parseia, cria o job (`draft`) e os itens, redireciona para o job.
2. `GET /referencias-impugnacao/importar/<job_id>` — lista os candidatos com
   checkbox (todos marcados), mostrando autora, tribunal, órgão julgador, nº de
   teses e situação (peça sem link vem desmarcada e bloqueada). Quando o job já
   está rodando, a mesma tela mostra o progresso.
3. `POST /referencias-impugnacao/importar/<job_id>/iniciar` — grava a seleção
   (não selecionados viram `skipped_by_user`), muda o job para `running` e
   dispara a thread; guard contra duplo disparo.
4. `GET /referencias-impugnacao/importar/<job_id>/status` — JSON com contadores
   e status por item, para o polling.

**Worker** (`_run_import_job`): para cada item selecionado, em ordem —
dedup por `drive_file_id` → `downloading` → download → SHA-256 → dedup por hash
→ salva em `uploads/impugnacao_references/{law_firm_id}/` → cria
`ImpugnacaoReferenceModel` com os metadados curados + `ingestion_status='processing'`
→ `indexing` → `ingest_reference(...)` → `completed`. Exceção no item →
`failed` + mensagem, e **o laço continua** para o próximo. Ao fim, job
`completed` (ou `failed` se explodir fora do laço). `db.session.remove()` só no
`finally` do job.

## Tratamento de erros

- Arquivo restrito no Drive → item `failed` com "arquivo sem compartilhamento
  público — libere no Drive e reprocesse" + link.
- Planilha sem cabeçalho reconhecível ou sem linhas do tipo → erro amigável no
  upload, sem criar job.
- Falha de ingestão (Docling/IA/Qdrant) → a peça fica criada com
  `ingestion_status='failed'` e o item `failed`; reindexar pela tela da peça
  resolve sem reimportar.
- Restart do processo no meio → itens ficam em `pending`/`downloading`; a tela
  oferece "Retomar", que redispara o worker pulando os `completed`.

## Fora de escopo

Conta de serviço do Drive (ponto de extensão documentado); importação de outros
tipos de documento (o filtro é parametrizável, mas a tela expõe só impugnação);
mapear as teses da planilha para o catálogo `JudicialLegalThesis` (ficam
guardadas em `source_theses_json` e servem de insumo futuro).

## Testes

- `parse_spreadsheet` sobre planilha sintética criada no próprio teste
  (cabeçalho fora da linha 1, agrupamento, filtro por tipo, variante "DO INSS",
  linha sem hyperlink).
- `normalize_tribunal` (TRF-4, TRF 4, trf4, TJSC → None).
- Detecção de resposta restrita do Drive (HTML → `DriveAccessError`) sem rede.
