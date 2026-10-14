# Google Drive pela conta de serviço — conferência e ingestão

**Data:** 2026-10-14 · **Módulo:** `settings` (tela admin) + downloads do Drive

## Objetivo

O escritório compartilha com a conta de serviço
`intellexia-drive@intellexia-503416.iam.gserviceaccount.com` (Leitor), arquivo
por arquivo, os PDFs da planilha "Petições protocoladas (pós inicial)". O
admin precisa **ver o que chegou** e **mandar cada arquivo para uma das três
bases**: peça-modelo, decisão (Base de Jurisprudência) ou Base de
Conhecimento (chat).

## Levantamento (verificado em 13–14/10/2026)

- A chave da conta abre e baixa os 6 arquivos compartilhados, inclusive os que
  respondem "sem compartilhamento" ao download anônimo.
- Nenhuma pasta nem drive compartilhado: só arquivos avulsos. Sem acesso à
  pasta-mãe, `parents` vem vazio. Um dos PDFs mora num drive compartilhado do
  escritório do qual a conta não é membro.
- O acesso **não expira**: arquivo compartilhado às 13:49 UTC de 13/10 continua
  acessível no dia seguinte ("5 a 10 minutos" é o atraso do script deles).
- Arquivo não compartilhado com a conta responde **404**, não 403.
- A planilha não está compartilhada — ler os metadados dela fica fora daqui.

## Decisões

1. **Lista ao vivo**, sem cron: a tela consulta o Drive a cada abertura e cruza
   com `drive_ingestions`. Sincronização periódica e ingestão automática ficam
   para depois; a tabela já serve de base para elas.
2. **Credencial da instalação, não do escritório** — mesmo padrão do
   `FAP_SYNC_LAW_FIRM_ID`. `.env`:
   - `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` (caminho do JSON, em `instance/`);
   - `GOOGLE_DRIVE_LAW_FIRM_ID` (escritório dono dos arquivos).
   Admin de outro escritório vê "não configurado para este escritório".
   A chave nunca vai para o banco.
3. **Sem dependência nova de instalação**: JWT assinado com `joserfc` (já vem
   com o Authlib) e trocado por token com `requests`. O `AssertionSession` do
   Authlib funciona, mas emite avisos de API obsoleta.
4. **Cada destino entra pela porta que já existe**, sem motor novo:
   - peça-modelo → `ImpugnacaoReferenceModel` + `ingest_reference` em thread
     (como o upload manual); mesmo `source_drive_file_id` ou `file_hash`
     aponta para a peça existente;
   - decisão → fila `jurisprudence_upload_service` (nova
     `receber_baixado`, mesma regra de arquivo idêntico → "revisar");
   - base de conhecimento → `KnowledgeBase` `pending`, processada por
     `scripts/process_knowledge_base.py`; mesmo `file_hash` ativo aponta para
     o existente.
5. **Registro por envio**: o mesmo arquivo pode ir a destinos diferentes, nunca
   duas vezes ao mesmo (unique `law_firm_id, drive_file_id, destination`).
   A situação exibida vem da linha de destino, não de cópia.
6. **Importadores atuais** (`download_drive_file`, usado pela importação de
   peças e pelo "Buscar PDFs no Drive" da Jurisprudência) tentam primeiro a
   conta de serviço e caem no anônimo.

## Componentes

- `app/services/google_drive_client.py` — único ponto de contato com o Drive;
  puro (sem Flask). `listar()`, `metadados()`, `baixar()` (Google Docs nativo
  é exportado em PDF; grava em `.part` e só renomeia depois de conferir que não
  é HTML e que o tamanho bate). Erros: `DriveNaoConfigurado`,
  `DriveSemAcesso` (404/sem permissão), `DriveIndisponivel` (rede, 5xx,
  credencial, API desativada, limite).
- `DriveIngestion` (`drive_ingestions`) — `database/add_drive_ingestions_table.py`.
- `app/services/drive_ingestion_service.py` — `painel()`, `ingerir()`,
  `tentar_de_novo()`.
- Rotas em `settings`: `GET /settings/google-drive`,
  `POST /settings/google-drive/ingerir`,
  `POST /settings/google-drive/envios/<id>/tentar-de-novo`.
- `scripts/drive_conferir_acesso.py` — conferência real sob comando.

## Tela

Topo com a conta e os totais; tabela com nome, tipo, tamanho, quem compartilhou
e quando, pasta (quando visível) e selos dos destinos já enviados (com a
situação e link). Filtro "ainda não ingeridos", por quem compartilhou e por
nome. "Ingerir em…" por linha e em lote (até 20). Destino desabilitado com o
motivo quando já foi enviado ou o tipo não serve (Jurisprudência só PDF; as
outras PDF e DOCX). Envios cujo arquivo deixou de ser compartilhado continuam
listados à parte. Falha vira `erro` com a mensagem e "tentar de novo"; nada é
gravado na base de destino.

## Testes

`tests/test_google_drive_client.py` (sessão HTTP falsa) e
`tests/test_drive_ingestion.py` (três destinos, repetição, duplicata, falha,
outro escritório). Os testes dos importadores continuam passando.

## Fora desta entrega

Ler a planilha pela conta; ingestão automática; abrir peças-modelo para
Embargos/ED; ligar a peça ao processo do Painel.
