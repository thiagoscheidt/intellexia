"""Pré-verificação da fila dos processadores (scripts/process_*.py).

Confere que o SQL puro que os scripts rodam antes de `import main` responde o
mesmo que a query do serviço, e que a URL do engine aponta para o mesmo banco
do Flask (no SQLite, dentro de `instance/`).

    uv run python tests/test_fila_leve_processadores.py
"""

import importlib.util
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from main import app  # noqa: E402
from app.models import db  # noqa: E402
from app.services.judicial_document_service import JudicialDocumentService  # noqa: E402
from app.services.knowledge_base_processing_service import KnowledgeBaseProcessingService  # noqa: E402
from app.utils import database_config  # noqa: E402


def _script(nome):
    caminho = os.path.join(PROJECT_ROOT, "scripts", f"{nome}.py")
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"{'OK ' if ok else 'ERRO'} {rotulo}: pré-filtro={obtido} serviço={esperado}")
    if not ok:
        falhas.append(rotulo)


kb_script = _script("process_knowledge_base")
jd_script = _script("process_judicial_documents")

with app.app_context():
    engine_flask = str(db.engine.url)
    engine_leve = database_config._engine_uri()
    if engine_flask.startswith("sqlite"):
        conferir("mesmo arquivo SQLite", engine_leve.split("///", 1)[1], db.engine.url.database)

    kb = KnowledgeBaseProcessingService(flask_app=app)
    jd = JudicialDocumentService(flask_app=app)
    for include_errors in (False, True):
        statuses = ["pending", "error"] if include_errors else ["pending"]
        conferir(
            f"knowledge_base {statuses}",
            database_config.existe_na_fila(kb_script.SQL_HA_PENDENTES, ativo=True, statuses=statuses),
            kb._build_query(include_errors=include_errors).first() is not None,
        )
        conferir(
            f"judicial_documents {statuses}",
            database_config.existe_na_fila(jd_script.SQL_HA_PENDENTES, statuses=statuses),
            jd._build_query(include_errors=include_errors).first() is not None,
        )

    # Banco inacessível: o pré-filtro não pode parar a fila.
    original = database_config._engine_uri
    database_config._engine_uri = lambda: "mysql+pymysql://x:y@127.0.0.1:1/nada"
    try:
        conferir("falha de conexão devolve True", database_config.existe_na_fila("SELECT 1"), True)
    finally:
        database_config._engine_uri = original

print("\nFALHOU:", falhas if falhas else "nada")
sys.exit(1 if falhas else 0)
