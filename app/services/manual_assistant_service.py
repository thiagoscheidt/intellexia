"""
Assistente do Manual — chat "pergunte ao manual".

Responde dúvidas sobre os painéis Dashboard, Painel FAP e Painel de Contestações
usando EXCLUSIVAMENTE o conteúdo dos manuais em ``docs/MANUAL_*.md``. Os manuais
são curtos e cabem inteiros no prompt, então não há RAG/busca vetorial: o modelo
recebe o manual completo a cada pergunta.
"""
import os
import time

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_MINI
from app.services.token_usage_service import TokenUsageService

# Raiz do projeto: .../app/services/manual_assistant_service.py -> sobe 3 níveis
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Manuais que compõem a base de conhecimento (rótulo exibido, arquivo em docs/).
_MANUAL_FILES = (
    ("Dashboard Principal", "MANUAL_DASHBOARD.md"),
    ("Painel FAP", "MANUAL_PAINEL_FAP.md"),
    ("Painel de Contestações", "MANUAL_PAINEL_CONTESTACOES.md"),
)

MAX_QUESTION_CHARS = 1000
MAX_HISTORY_MESSAGES = 6

_SYSTEM_INSTRUCTIONS = """Você é o assistente de ajuda do sistema IntellexIA. \
Seu papel é tirar dúvidas dos usuários sobre três painéis: Dashboard Principal, \
Painel FAP e Painel de Contestações.

Regras:
- Responda SOMENTE com base no conteúdo dos manuais fornecidos abaixo.
- Se a resposta não estiver nos manuais, diga com honestidade que não encontrou \
essa informação no manual e sugira acionar o suporte. NUNCA invente dados, campos, \
telas, números, prazos ou comportamentos que não estejam escritos nos manuais.
- Responda em português do Brasil, de forma clara, curta e objetiva. Use listas \
curtas quando ajudar a organizar.
- Quando fizer sentido, indique em qual painel/seção do manual está a informação.
- Se perguntarem algo fora do escopo destes painéis (assuntos gerais, jurídicos, \
técnicos, etc.), explique gentilmente que você só ajuda com o uso destes painéis \
do IntellexIA."""


class ManualAssistantService:
    """Gera respostas do chat de ajuda a partir dos manuais em ``docs/``."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("MANUAL_ASSISTANT_MODEL") or DEFAULT_MODEL_MINI
        self.llm = ChatOpenAI(model=self.model_name, temperature=0.2)
        self.token_usage_service = TokenUsageService()
        # Cache dos manuais: {caminho: (mtime, texto)}.
        self._cache: dict[str, tuple[float, str]] = {}

    # ------------------------------------------------------------------ #
    # Carregamento dos manuais (com cache por data de modificação)
    # ------------------------------------------------------------------ #
    def _read_cached(self, path: str) -> str:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return ""
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return ""
        self._cache[path] = (mtime, text)
        return text

    def _load_manuals(self) -> str:
        blocks: list[str] = []
        for label, filename in _MANUAL_FILES:
            text = self._read_cached(os.path.join(_PROJECT_ROOT, "docs", filename))
            if text.strip():
                blocks.append(f"# MANUAL: {label}\n\n{text.strip()}")
        return "\n\n---\n\n".join(blocks)

    def _build_system_prompt(self) -> str:
        manuals = self._load_manuals()
        return f"{_SYSTEM_INSTRUCTIONS}\n\n=== CONTEÚDO DOS MANUAIS ===\n\n{manuals}"

    # ------------------------------------------------------------------ #
    # Histórico
    # ------------------------------------------------------------------ #
    @staticmethod
    def _history_messages(history: list[dict] | None) -> list[dict]:
        history = history or []
        limited = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
        out: list[dict] = []
        for item in limited:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                out.append({"role": role, "content": content[:MAX_QUESTION_CHARS]})
        return out

    @staticmethod
    def _extract_reply(payload: dict) -> str:
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        if not messages:
            return ""
        last = messages[-1]
        if hasattr(last, "content"):
            return (last.content or "").strip()
        if isinstance(last, dict):
            return (last.get("content", "") or "").strip()
        return str(last).strip()

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def answer(
        self,
        question: str,
        history: list[dict] | None = None,
        *,
        user_id: int | None = None,
        law_firm_id: int | None = None,
    ) -> dict:
        """Responde à pergunta com base nos manuais.

        Retorna ``{"ok": bool, "reply": str}``. Em qualquer falha, ``ok=False``
        com uma mensagem amigável no ``reply`` (degradação graciosa).
        """
        cleaned = (question or "").strip()
        if not cleaned:
            return {"ok": False, "reply": "Faça uma pergunta sobre o sistema."}
        cleaned = cleaned[:MAX_QUESTION_CHARS]

        messages = self._history_messages(history) + [{"role": "user", "content": cleaned}]

        try:
            agent = create_agent(model=self.llm, system_prompt=self._build_system_prompt())

            started_at = time.time()
            payload = agent.invoke({"messages": messages})
            latency_ms = int((time.time() - started_at) * 1000)

            try:
                self.token_usage_service.capture_and_store(
                    payload,
                    agent_name="ManualAssistantService",
                    action_name="answer",
                    print_prefix="[ManualAssistant][tokens]",
                    model_name=self.model_name,
                    model_provider="openai",
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                    chat_session_id=None,
                    latency_ms=latency_ms,
                    status="success",
                    metadata_payload={"question": cleaned[:200]},
                )
            except Exception as e:  # rastreio de tokens é best-effort
                print(f"[ManualAssistant] falha ao registrar tokens: {e}")

            reply = self._extract_reply(payload)
            if not reply:
                return {"ok": False, "reply": "Não consegui gerar uma resposta agora. Tente novamente."}
            return {"ok": True, "reply": reply}
        except Exception as e:
            print(f"[ManualAssistant] erro ao responder: {e}")
            return {"ok": False, "reply": "Não consegui responder agora. Tente novamente em instantes."}
