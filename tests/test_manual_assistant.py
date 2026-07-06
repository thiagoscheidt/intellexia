"""
Verificação do Assistente do Manual (chat "pergunte ao manual").

Rode com:
    uv run python tests/test_manual_assistant.py

Cobre (sem depender de banco):
  1. ManualAssistantService carrega os 3 manuais e monta o system prompt.
  2. _history_messages limita e filtra o histórico.
  3. Endpoint POST /docs/chat responde 400 para mensagem vazia (sem chamar LLM).
  4. Endpoint docs.chat está registrado no url_map.
  5. (opcional) Pergunta real ao LLM, se houver OPENAI_API_KEY.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from app.services.manual_assistant_service import ManualAssistantService, MAX_HISTORY_MESSAGES

failures = []


def check(name, cond):
    print(("OK  " if cond else "FALHOU  ") + name)
    if not cond:
        failures.append(name)


# 1) Carregamento dos manuais + montagem do system prompt
svc = ManualAssistantService()
prompt = svc._build_system_prompt()
check("system prompt inclui instruções de comportamento", "SOMENTE com base" in prompt)
check("system prompt inclui manual do Dashboard", "Dashboard Principal" in prompt and "Publicação D.O.U." in prompt)
check("system prompt inclui manual do Painel FAP", "Sincronização automática" in prompt)
check("system prompt inclui manual de Contestações", "Categoria FAP" in prompt)
print(f"    (system prompt tem {len(prompt)} caracteres)")

# 2) Histórico: limite e filtragem
long_hist = [{"role": "user", "content": f"q{i}"} for i in range(20)]
msgs = svc._history_messages(long_hist)
check("histórico limitado a MAX_HISTORY_MESSAGES", len(msgs) == MAX_HISTORY_MESSAGES)
mixed = [{"role": "system", "content": "x"}, {"role": "user", "content": ""}, {"role": "assistant", "content": "ok"}]
check("histórico filtra roles/vazios inválidos", svc._history_messages(mixed) == [{"role": "assistant", "content": "ok"}])

# 3) Endpoint 400 em mensagem vazia (não chama LLM)
from app.blueprints.docs import chat as chat_view
with app.test_request_context("/docs/chat", method="POST", json={"message": "   "}):
    resp = chat_view()
    body, status = (resp if isinstance(resp, tuple) else (resp, 200))
    check("POST /docs/chat com mensagem vazia retorna 400", status == 400)

# 4) Rota registrada
rules = {r.endpoint for r in app.url_map.iter_rules()}
check("endpoint docs.chat registrado", "docs.chat" in rules)

# 5) Pergunta real ao LLM (opcional — só se houver chave configurada)
if os.getenv("OPENAI_API_KEY"):
    print("\n[live] OPENAI_API_KEY presente — testando pergunta real...")
    try:
        with app.app_context():
            result = svc.answer("De onde vem a Data D.O.U.?")
        print("    ok:", result.get("ok"))
        print("    reply:", (result.get("reply") or "")[:300])
        check("resposta real não vazia", bool((result.get("reply") or "").strip()))
    except Exception as e:
        print(f"    [live] não foi possível (rede/credenciais): {e}")
else:
    print("\n[live] OPENAI_API_KEY ausente — pulando teste de pergunta real.")

print()
if failures:
    print(f"RESULTADO: {len(failures)} verificação(ões) falharam: {failures}")
    sys.exit(1)
print("RESULTADO: todas as verificações determinísticas passaram.")
