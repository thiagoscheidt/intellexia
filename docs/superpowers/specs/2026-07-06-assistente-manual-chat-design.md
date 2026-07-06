# Design — Assistente do Manual (chat "pergunte ao manual")

**Data:** 2026-07-06
**Status:** Aprovado para implementação

## Objetivo

Um botão flutuante na página de documentação (`/docs/manuais`) que abre um chat
onde o usuário pergunta sobre o sistema e recebe respostas **baseadas exclusivamente
nos manuais** dos painéis Dashboard, Painel FAP e Painel de Contestações.

## Decisões (do brainstorming)

| Tema | Decisão |
|---|---|
| Base de conhecimento | Só os 3 manuais (`docs/MANUAL_*.md`), lidos **inteiros** no prompt. Sem RAG. |
| Onde aparece | Apenas na página `/docs/manuais`. Não é ajuda global. |
| Modelo | `DEFAULT_MODEL_MINI` (configurável via env `MANUAL_ASSISTANT_MODEL`). |
| Histórico | Efêmero — só em memória do navegador; some ao recarregar. |

## Componentes

### 1. `ManualAssistantService` (`app/services/manual_assistant_service.py`)
- Carrega os 3 markdowns com **cache por mtime** (recarrega só quando o arquivo muda).
- Monta o system prompt: instruções de comportamento + conteúdo dos manuais.
- Chama o LLM via `create_agent(model=ChatOpenAI(...), system_prompt=...)`, seguindo o
  padrão dos agentes existentes. `temperature=0.2`.
- Rastreia tokens com `TokenUsageService.capture_and_store` (agente `ManualAssistantService`,
  ação `answer`). Falha de rastreio não derruba a resposta.
- Limites: pergunta ≤ 1000 chars; histórico ≤ 6 mensagens.
- `answer(question, history, *, user_id, law_firm_id) -> {ok: bool, reply: str}`.
  Degradação graciosa: em erro, `ok=False` + mensagem amigável.

### 2. Endpoint `POST /docs/chat` (`app/blueprints/docs.py`)
- Protegido por login (middleware já cobre `/docs`).
- Entrada: `{ message, history }`. Pergunta vazia → 400.
- Instancia o serviço de forma lazy (evita falha em import-time).
- Saída: `200 { reply }` (mesmo em erro tratado, com mensagem amigável no `reply`).

### 3. Widget de chat (na página `docs/manual_paineis.html`, fonte no scratchpad)
- Botão flutuante (canto inferior direito) no visual da página (acento azul, temas).
- Painel abre/fecha: mensagens, input, enviar. Histórico em memória JS.
- Chips de perguntas sugeridas: Data D.O.U., "Em análise", sincronização automática.
- Resposta renderizada com **markdown básico** (negrito, listas, código, links),
  sempre **escapando HTML antes** (evita injeção).
- Estados: boas-vindas, "digitando…", erro.
- No claude.ai (artifact): `/docs/chat` retorna 404 → mostra "assistente disponível
  apenas dentro do sistema".
- Acessibilidade: aria-labels, foco no input ao abrir, Esc fecha, respeita
  `prefers-reduced-motion`.

## Regras de comportamento da IA (system prompt)
- Responde **somente** com base nos manuais. Sem invenção.
- Se não estiver no manual: admite e sugere o suporte.
- Português (BR), claro e curto. Indica painel/seção quando útil.
- Fora do escopo do sistema → redireciona educadamente.

## Fora de escopo (YAGNI)
Streaming, histórico persistido, RAG, feedback 👍/👎, botão em outras telas.

## Verificação
Script standalone (`tests/test_manual_assistant.py`): (a) `ManualAssistantService`
carrega manuais e monta o system prompt com conteúdo dos 3 arquivos; (b) `POST /docs/chat`
via `test_client` — 400 em pergunta vazia; 200 com `reply` numa pergunta válida
(LLM pode ser exercitado se houver chave, senão valida o caminho de erro tratado).
