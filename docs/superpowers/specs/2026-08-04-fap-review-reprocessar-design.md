# Reprocessar revisão FAP sem reupload — design

**Data:** 2026-08-04
**Módulo:** `fap_review`
**Motivação:** as execuções 52 e 53 falharam por dois bugs já corrigidos (estouro do orçamento de saída do modelo e `decimal.ConversionSyntax` na contabilidade de custo). Hoje não há como reexecutá-las pela interface: o botão "Tentar Novamente" da tela de erro leva ao formulário vazio, exigindo reupload da petição, dos anexos e da planilha de benefícios.

## Objetivo

Permitir reexecutar uma revisão que falhou, reaproveitando os arquivos já enviados, a partir da própria tela de resultado (`/fap-review/revision/<id>`).

## Decisões tomadas

| Decisão | Escolha | Motivo |
|---|---|---|
| Onde o resultado grava | **Mesma execução** | `revision_number` representa a VERSÃO da petição revisada, não a tentativa de processamento. Uma falha técnica não é uma revisão nova. Criar R4 inflaria `revision_count`, o Kanban e as estatísticas por advogado |
| Quando o botão aparece | **Somente `status == 'failed'`** | O watchdog existente já converte execução travada em `failed` (ver abaixo), então esse caso chega ao botão sozinho |
| Permissão | **Mesma de criar revisão** (módulo `fap_review`) | Custo e efeito equivalentes a um envio novo; ser mais restrito seria incoerente |
| Cópia de arquivos | **Não copia** | A execução aponta para os mesmos caminhos. Reprocessar não é um envio novo |
| Versões de prompt/manual | **As ativas no momento do reprocesso** | É o que faz o reprocessamento pegar as correções |

### O que NÃO entra

- Reprocessar execução `completed` — sobrescreveria achados já triados e queimaria ~US$ 1 por clique acidental.
- Reprocessar execução de `training` — fluxo distinto, fora do escopo.
- Criar histórico de tentativas — a trilha fica no log de auditoria.

## Contexto do código existente

O terreno já suporta a feature; nenhuma peça de processamento nova é necessária.

- Todos os caminhos estão persistidos na execução: `main_document_path`, `auxiliary_documents_json`, `benefits_spreadsheet_json`, `compared_document_path`.
- `_execute_reviewer_agent(execution_id, law_firm_id, petition_file_path, compared_file_path, benefits_spreadsheet)` lê os documentos auxiliares da própria execução (`fap_review.py:705`) e carrega as referências **ativas** (manual, casos, instruções).
- `_load_execution_benefits_spreadsheet(execution)` (`fap_review.py:386`) extrai a planilha da execução.
- `_sync_petition_after_revision` usa `max()` em `revision_count` — não incrementa — e `derive_petition_workflow_status('processing')` devolve `'in_review'`. Reusá-lo é seguro: a petição sai de "Aguardando ajustes" e volta a "Em revisão".

### Watchdog de execução travada

A rota `revision_result` (`fap_review.py:1413-1423`) já detecta execução presa em `processing` há mais de 15 minutos — cenário real, porque a thread é `daemon=True` e morre se o processo web reiniciar — e a converte em `failed` com mensagem explicativa, commitando.

Consequência de design: **não é preciso um verificador de "travada" na feature nova**. O caso chega ao botão já como `failed`. Os 15 minutos ficam como estão, num único lugar.

## Arquitetura

Uma rota nova e um helper extraído. Sem serviço novo, sem tabela nova, sem migration.

### Componentes

| Peça | Responsabilidade |
|---|---|
| `_start_review_in_background(app_obj, execution_id, law_firm_id, petition_file_path, compared_file_path, benefits_spreadsheet)` | Dispara a thread do agente e garante `status='failed'` se ela estourar. Extraído de `POST /revision` (`fap_review.py:1336-1364`) sem mudança de comportamento |
| `reprocess_revision(execution_id)` | Rota `POST /fap-review/revision/<id>/reprocess`: valida, reseta e dispara |
| Botão no template | Substitui o "Tentar Novamente" atual no bloco `failed` |

A extração do helper existe para evitar que o tratamento de thread e o fallback de falha fiquem duplicados entre criar e reprocessar — duas cópias divergiriam com o tempo.

### Fluxo

1. Carrega a execução filtrando por `law_firm_id` — multi-tenancy obrigatória; senão 404.
2. Recusa `execution_type != 'revision'`.
3. Recusa status diferente de `failed` (409). Barra duplo clique e protege execução concluída.
4. Verifica que `main_document_path` ainda existe em disco; senão 422.
5. Preserva o `error_message` anterior em variável, para o log.
6. Reseta: `status='processing'`, `error_message=None`, `completed_at=None`.
7. `_sync_petition_after_revision(execution)` e commit.
8. Grava auditoria `revision_reprocessed`, **incluindo o erro anterior truncado** — é o que preserva a informação que a sobrescrita apagaria.
9. Dispara via `_start_review_in_background`.
10. Retorna JSON; a tela recarrega e o auto-refresh de 3s do bloco `processing` acompanha até o fim.

### Erros

| Situação | Resposta |
|---|---|
| Execução de outro escritório / inexistente | 404 |
| Status diferente de `failed` | 409 com o status atual na mensagem |
| `execution_type != 'revision'` | 409 |
| Documento principal ausente do disco | 422, "o arquivo original não está mais no servidor; refaça o upload" |
| Falha do agente durante o reprocesso | Caminho atual, inalterado: `failed` + `error_message` |

Anexo auxiliar ou planilha ausente do disco **não** bloqueia: a revisão segue sem eles e o fato vai para o log. Só o documento principal é essencial.

`NEW_REVISION_BLOCKED_STATUSES` não se aplica — guarda a criação de revisões novas, e reprocessar não cria nada.

## Testes

Script standalone em `tests/test_fap_review_reprocess.py`, no padrão do módulo (executável por `uv run python`, com contador de passou/falhou).

Casos:

1. Execução `failed` é aceita: status volta a `processing`, `error_message` limpa.
2. `revision_number` e `petition.revision_count` **não** mudam — a garantia central da decisão de reaproveitar a execução.
3. Status `completed` é recusado (409).
4. Status `processing` é recusado (409).
5. `execution_type='training'` é recusado (409).
6. Execução de outro escritório devolve 404 — isolamento multi-tenant.
7. Documento principal ausente do disco devolve 422 e **não** altera o status.
8. O log de auditoria registra `revision_reprocessed` com o erro anterior.

## Riscos

**O botão só funciona com os fixes em produção.** Reprocessar a 53 com o código antigo estoura o mesmo teto e falha de novo, cobrando outra vez. Ordem: deploy dos fixes → deploy do botão → reprocessar.

**A execução 52 pode não precisar de reprocessamento.** O crash do `Decimal` ocorreu depois de `result_json` ser atribuído ao objeto e antes do `commit`; como o `except` recupera o mesmo objeto da identity map do SQLAlchemy e commita, o resultado pode ter sido gravado junto com `status='failed'`. Verificar `LENGTH(result_json)` na 52 antes de gastar tokens; se estiver preenchido, o conserto é um `UPDATE` de status.
