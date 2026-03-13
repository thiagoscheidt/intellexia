"""
Script de teste do DocumentProcessorService.

Uso:
    uv run scripts/tests/test_document_processor_service.py --knowledge-id 23
    uv run scripts/tests/test_document_processor_service.py --knowledge-id 23 --method markitdown
    uv run scripts/tests/test_document_processor_service.py --knowledge-id 23 --method docling
    uv run scripts/tests/test_document_processor_service.py --knowledge-id 23 --method process
    uv run scripts/tests/test_document_processor_service.py --knowledge-id 23 --method rag --query "sua pergunta aqui"
    uv run scripts/tests/test_document_processor_service.py --file caminho/para/arquivo.pdf --method all
"""


import argparse
import sys
from pathlib import Path
from rich import print
from rich.panel import Panel
from rich.rule import Rule

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import KnowledgeBase
from app.services.document_processor_service import DocumentProcessorService


METHODS = ("markitdown", "docling", "process", "rag", "all")


def _pick_knowledge_item(knowledge_id: int) -> KnowledgeBase | None:
    candidates = (
        KnowledgeBase.query.filter(KnowledgeBase.is_active.is_(True), KnowledgeBase.id == knowledge_id)
        .order_by(KnowledgeBase.uploaded_at.desc())
        .all()
    )
    for item in candidates:
        if item.file_path and Path(item.file_path).exists():
            return item
    return None


def test_markitdown(service: DocumentProcessorService, file_path: Path) -> None:
    print(Rule("[bold cyan]convert_with_markitdown"))
    text = service.convert_with_markitdown(file_path)
    print(Panel(text[:3000] + ("..." if len(text) > 3000 else ""), title="Resultado", expand=False))
    print(f"Total de caracteres: [bold]{len(text)}[/bold]\n")


def test_docling(service: DocumentProcessorService, file_path: Path) -> None:
    print(Rule("[bold cyan]convert_with_docling"))
    text = service.convert_with_docling(file_path)
    print(Panel(text[:3000] + ("..." if len(text) > 3000 else ""), title="Resultado (markdown)", expand=False))
    print(f"Total de caracteres: [bold]{len(text)}[/bold]\n")


def test_process_file(service: DocumentProcessorService, file_path: Path) -> None:
    print(Rule("[bold cyan]process_file"))
    result = service.process_file(file_path)

    print(f"Arquivo      : [bold]{result.file_path}[/bold]")
    print(f"Total páginas: [bold]{result.total_pages}[/bold]")
    print(f"Texto total  : [bold]{len(result.full_text)} chars[/bold]")
    print(f"Páginas      : [bold]{len(result.pages)}[/bold]")
    print(f"Chunks       : [bold]{len(result.chunks_with_pages)}[/bold]")
    print()
    print(result.pages)
    exit()

    for page in result.pages[:5]:
        preview = page.text[:300].replace("\n", " ") + ("..." if len(page.text) > 300 else "")
        print(Panel(preview, title=f"Página {page.page}", expand=False))

    if len(result.pages) > 5:
        print(f"  ... ({len(result.pages) - 5} páginas restantes omitidas)\n")

    if result.chunks_with_pages:
        print(Rule("Primeiro chunk"))
        first = result.chunks_with_pages[0]
        print(f"  página : {first.get('page')}")
        print(f"  texto  : {first.get('text', '')[:300]}")
    print()


def test_rag(service: DocumentProcessorService, file_path: Path, query: str) -> None:
    print(Rule("[bold cyan]RAG com FAISS"))
    print(f"Query: [bold yellow]{query}[/bold yellow]\n")

    print("Indexando arquivo...")
    vectorstore = service.build_faiss_index(file_path=file_path)

    results = service.search(vectorstore, query)
    print(f"Top {len(results)} resultados:\n")
    for i, r in enumerate(results, 1):
        page_info = f" (pág. {r.page})" if r.page else ""
        score_info = f" | score: {r.score:.4f}" if r.score is not None else ""
        preview = r.text[:500].replace("\n", " ") + ("..." if len(r.text) > 500 else "")
        print(Panel(preview, title=f"#{i}{page_info}{score_info}", expand=False))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa o DocumentProcessorService")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--knowledge-id", type=int, help="ID da tabela knowledge_base")
    group.add_argument("--file", help="Caminho direto para o arquivo")
    parser.add_argument(
        "--method",
        choices=METHODS,
        default="all",
        help="Método a testar (padrão: all)",
    )
    parser.add_argument(
        "--query",
        default="Quais são os benefícios listados no documento?",
        help="Query para o teste de RAG",
    )
    args = parser.parse_args()

    def _resolve_file_path() -> Path | None:
        if args.file:
            p = Path(args.file)
            if not p.exists():
                print(f"[red]Arquivo não encontrado: {p}[/red]")
                return None
            return p

        with app.app_context():
            kb_item = _pick_knowledge_item(args.knowledge_id)
            if not kb_item:
                print(f"[red]Nenhum arquivo válido encontrado para knowledge_id={args.knowledge_id}[/red]")
                return None
            print(f"[dim]knowledge_base.id : {kb_item.id}[/dim]")
            print(f"[dim]original_filename : {kb_item.original_filename}[/dim]")
            print(f"[dim]file_path         : {kb_item.file_path}[/dim]\n")
            return Path(kb_item.file_path)

    file_path = _resolve_file_path()
    if file_path is None:
        return 1

    print(f"[bold]Arquivo:[/bold] {file_path}")
    print(f"[bold]Método :[/bold] {args.method}\n")

    service = DocumentProcessorService()

    if args.method in ("markitdown", "all"):
        test_markitdown(service, file_path)

    if args.method in ("docling", "all"):
        test_docling(service, file_path)

    if args.method in ("process", "all"):
        test_process_file(service, file_path)

    if args.method in ("rag", "all"):
        test_rag(service, file_path, args.query)

    return 0


if __name__ == "__main__":
    sys.exit(main())
