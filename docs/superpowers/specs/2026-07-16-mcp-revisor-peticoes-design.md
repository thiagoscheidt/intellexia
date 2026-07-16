# MCP — Revisor de Petições: leitura do módulo e revisão registrada

**Data:** 2026-07-16
**Status:** aprovado para implementação

## Problema

O MCP expõe **uma** tool do módulo Revisor (`revisar_peticao_inicial`) e ela tem dois
defeitos que só aparecem quando se compara com a tela:

1. **A revisão feita pelo Claude é invisível para o módulo.** O handler chama o agente e
   devolve o resultado, sem criar `FapReviewExecution`: não entra no histórico da petição,
   não move o `workflow_status`, não conta no score do advogado e não registra custo.
   A tela grava; o MCP não. Mesma classe de divergência dos exports em Excel.
2. **O Claude não consegue ler as revisões que já existem.** Só sabe criar novas — caras
   (~1 min de IA) e desconectadas do fluxo. A pergunta natural ("o que a revisão da
   petição X apontou? me ajuda a corrigir") é impossível hoje.

## Decisões

| Tema | Decisão |
|---|---|
| Prioridade | Tools de **leitura** primeiro (valor imediato, risco zero) + registrar a revisão |
| Regra de workflow | Serviço compartilhado — tela e MCP usam a mesma função (padrão do `fap_digest_service`) |
| Registro da revisão | Só quando o usuário informa o **identificador do documento**; sem ele, continua efêmera e a resposta diz isso |
| Estatísticas por advogado | **Fora deste escopo** — na tela é admin-only (`require_admin_user`) e o MCP hoje só espelha permissão de módulo |
| Treinamento / prompts / referências | Fora do MCP — área admin de configuração do agente |

## Arquitetura

### 1. `app/services/fap_review_service.py` (novo)

Fonte única das regras de workflow, hoje presas ao blueprint:

```python
PETITION_WORKFLOW_STATUSES        # rótulos dos status
build_petition_title(...)
derive_petition_workflow_status(execution_status)
sync_petition_after_revision(execution)
load_execution_result_payload(execution)
log_audit(law_firm_id, user_id, action, ...)   # user_id explícito (MCP não tem sessão Flask)
record_text_review(...)                        # registra a revisão vinda do MCP
```

O blueprint passa a importar daqui. `_log_audit` continua existindo lá como wrapper fino
que injeta `session['user_id']` — os 17 pontos de chamada não mudam.

`record_text_review` reusa exatamente o caminho da tela: cria/reaproveita a
`FapReviewPetition` pelo `office_document_identifier`, grava o texto revisado como arquivo
em `uploads/fap_review/{law_firm_id}/revisions/` (para a tela poder abrir o documento),
cria a `FapReviewExecution` já `completed` com `result_json`, `tokens_used`/`cost_usd`, e
chama `sync_petition_after_revision`.

### 2. Tools novas (módulo `fap_review`)

| Tool | O que faz |
|---|---|
| `listar_peticoes_revisao` | Petições com status do fluxo, nº de revisões e data da última (paginada) |
| `detalhar_revisao` | Achados de uma revisão já feita: severidade, localização, correção sugerida, referência do manual, documentos faltantes, teses e resumo executivo |
| `historico_revisoes_peticao` | Evolução entre as revisões da mesma petição: o que saiu, o que reincidiu |

### 3. `revisar_peticao_inicial` (alterada, compatível)

Ganha `identificador_documento` e `titulo` opcionais:

- **com identificador** → registra a revisão (histórico, custo, status da petição) e devolve
  `registrado_no_sistema: true` + `peticao_id`/`revisao_id`;
- **sem identificador** → comportamento atual, com `registrado_no_sistema: false` explícito
  na resposta para o agente não dar a entender que ficou salvo.

### 4. Prompts

| Prompt | O que faz |
|---|---|
| `corrigir_peticao` | A partir de uma revisão existente, devolve achado a achado o trecho reescrito |
| `pronto_para_protocolo` | Checklist objetivo: críticos em aberto + documentos faltantes → pode protocolar? |
| `devolutiva_ao_advogado` | Transforma os achados em devolutiva construtiva, ordenada por gravidade |

## Não quebrar o que funciona

- Tela do Revisor: a extração é de helpers puros; o blueprint mantém os mesmos nomes locais.
- `revisar_peticao_inicial` sem os parâmetros novos se comporta como hoje.
- Execução registrada com documento em disco → o botão "abrir documento" da tela funciona
  (a rota já degrada com `flash` quando não há arquivo, mas aqui haverá).
- Multi-tenancy: toda query filtra `law_firm_id`; o identificador é único por escritório.
