#!/usr/bin/env python3
"""
Localiza e edita o site do nginx para publicar o MCP — usado por deploy/mcp/core.sh.

    nginx_mcp.py find  --domain D --sites-dir DIR
    nginx_mcp.py apply --file F --domain D --port P [--dry-run]

Por que não "antes da última chave do arquivo", como o deploy_mcp.sh antigo:
o site de homologação tem o bloco 443 PRIMEIRO e o redirect da porta 80 por
último — o snippet cairia no bloco 80, o `nginx -t` passaria e o /mcp não
responderia pelo HTTPS. Aqui o alvo é o bloco `server` que escuta 443 E tem o
domínio no `server_name`, achado por contagem de chaves.

Códigos de saída do apply: 0 inserido (ou inseriria, no dry-run), 3 já presente
e correto, 2 erro (nada foi escrito).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "IntellexIA MCP"

SNIPPET = """
    # ── {marker} (uvicorn 127.0.0.1:{port}) ── gerado por deploy/mcp ──
    # O prefixo público /mcp é removido antes de chegar ao backend (que serve na raiz).
    location = /mcp {{
        proxy_pass http://127.0.0.1:{port}/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 3600;
        proxy_buffering off;
    }}

    location /mcp/ {{
        proxy_pass http://127.0.0.1:{port}/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 3600;
        proxy_buffering off;
    }}

    # Discovery OAuth (RFC 8414 / RFC 9728) — precisa viver na raiz do domínio
    location = /.well-known/oauth-authorization-server/mcp {{
        proxy_pass http://127.0.0.1:{port}/.well-known/oauth-authorization-server;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location = /.well-known/oauth-authorization-server {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /.well-known/oauth-protected-resource {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    # ── fim {marker} ──
"""


def _mask(text: str) -> str:
    """Troca comentários e strings por espaços, preservando os índices.

    Assim uma chave dentro de `# comentário {` ou de uma string não bagunça a
    contagem, e os índices achados valem para o texto original.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if c in "\"'":
            q = c
            out[i] = " "
            i += 1
            while i < n and text[i] != q:
                if text[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                    if text[i] == q:
                        out[i] = " "
                        i += 1
                        continue
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def server_blocks(text: str) -> list[tuple[int, int]]:
    """(início, índice da `}` de fechamento) de cada `server { }` de nível zero."""
    masked = _mask(text)
    blocks, depth, start = [], 0, None
    for m in re.finditer(r"\bserver\s*\{|[{}]", masked):
        tok = m.group(0)
        if tok.startswith("server"):
            if depth == 0:
                start = m.start()
            depth += 1
        elif tok == "{":
            depth += 1
        else:
            depth -= 1
            if depth < 0:
                raise ValueError("chaves desbalanceadas no arquivo")
            if depth == 0 and start is not None:
                blocks.append((start, m.start()))
                start = None
    if depth != 0:
        raise ValueError("chaves desbalanceadas no arquivo")
    return blocks


def _directive_args(masked_block: str, name: str) -> list[list[str]]:
    return [m.group(1).split() for m in re.finditer(rf"(?m)^\s*{name}\s+([^;]*);", masked_block)]


def block_matches(masked_block: str, domain: str) -> bool:
    listens_443 = any(
        any(re.fullmatch(r"(?:[\[\]\w.:]*:)?443", a) for a in args)
        for args in _directive_args(masked_block, "listen")
    )
    names = {n.lower() for args in _directive_args(masked_block, "server_name") for n in args}
    return listens_443 and domain.lower() in names


def target_block(text: str, domain: str) -> tuple[int, int]:
    masked = _mask(text)
    hits = [(s, e) for s, e in server_blocks(text) if block_matches(masked[s:e], domain)]
    if not hits:
        raise LookupError(f"nenhum bloco `server` com listen 443 e server_name {domain}")
    if len(hits) > 1:
        raise LookupError(f"{len(hits)} blocos `server` 443 com server_name {domain} — ambíguo")
    return hits[0]


def cmd_find(domain: str, sites_dir: Path) -> int:
    found = []
    for f in sorted(sites_dir.iterdir()):
        if not f.is_file() or ".bak" in f.name or f.name.endswith("~"):
            continue
        try:
            target_block(f.read_text(), domain)
            found.append(f)
        except (LookupError, ValueError, UnicodeDecodeError):
            continue
    if len(found) != 1:
        print(f"encontrado(s) {len(found)} site(s) para {domain}: {[str(f) for f in found]}", file=sys.stderr)
        return 2
    print(found[0])
    return 0


def cmd_apply(path: Path, domain: str, port: int, dry_run: bool) -> int:
    text = path.read_text()
    try:
        start, end = target_block(text, domain)
    except (LookupError, ValueError) as exc:
        print(f"❌ {path}: {exc}", file=sys.stderr)
        return 2

    block = text[start:end]
    if MARKER in text:
        if MARKER not in block:
            print(f"❌ {path}: o trecho '{MARKER}' existe, mas FORA do bloco 443 de {domain} "
                  "(provavelmente no bloco da porta 80). Remova-o à mão e rode de novo.", file=sys.stderr)
            return 2
        ports = set(re.findall(r"proxy_pass\s+http://127\.0\.0\.1:(\d+)", block[block.index(MARKER):]))
        if ports != {str(port)}:
            print(f"❌ {path}: o trecho do MCP aponta para a(s) porta(s) {sorted(ports)}, "
                  f"mas este ambiente usa {port}. Corrija à mão ou ajuste MCP_PORT.", file=sys.stderr)
            return 2
        print(f"   trecho do MCP já presente no bloco 443 de {domain}, porta {port} — nada a fazer")
        return 3

    if dry_run:
        print(f"   [dry-run] inseriria o trecho do MCP (porta {port}) no bloco 443 de {domain}")
        return 0

    # Recua até o fim da última linha com conteúdo, para o snippet entrar
    # antes da `}` com a indentação limpa.
    cut = end
    while cut > start and text[cut - 1] in " \t":
        cut -= 1
    path.write_text(text[:cut] + SNIPPET.format(marker=MARKER, port=port).lstrip("\n") + text[cut:])
    print(f"   trecho do MCP inserido no bloco 443 de {domain} (porta {port})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--domain", required=True)
    f.add_argument("--sites-dir", type=Path, required=True)
    a = sub.add_parser("apply")
    a.add_argument("--file", type=Path, required=True)
    a.add_argument("--domain", required=True)
    a.add_argument("--port", type=int, required=True)
    a.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.cmd == "find":
        return cmd_find(args.domain, args.sites_dir)
    return cmd_apply(args.file, args.domain, args.port, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
