"""Renumeração determinística da impugnação gerada + guardas de costura.

Fixtures baseadas em documento REAL gerado em produção (29/07/2026) em que:
- "DA INSUFICIÊNCIA TÉCNICA" saiu sem número e "DO MÉRITO" saiu como 3.;
- "PEDIDOS" saiu sem número;
- o fecho "Nestes termos / Pede deferimento." saiu duplicado;
- o título da subseção de compensação saiu repetido;
- o corpo vazou referência interna ("tese 6.6", "catálogo do escritório").

Rodar: uv run python scripts/tests/test_impugnacao_numbering.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_numbering import (
    renumber_document,
    strip_trailing_closing,
    strip_leading_duplicate_heading,
    detect_internal_references,
)

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


# ── renumber_document: caso real de produção (condensado) ────────────
DOC = """EXCELENTÍSSIMO(A) SENHOR(A) JUIZ(A) FEDERAL DA 12ª VARA FEDERAL DE BELO HORIZONTE

Processo nº 6008199-38.2026.4.06.3800

CONSTRUTORA REMO LTDA, já qualificada nos autos, vem apresentar IMPUGNAÇÃO À CONTESTAÇÃO, pelos fundamentos a seguir expostos.

DA INSUFICIÊNCIA TÉCNICA E JURÍDICA DA CONTESTAÇÃO

A contestação reproduz a Nota SEI nº 178/2026 e as Resoluções CNPS nº 1.329/2017 e nº 1.347/2021.

a) Nota SEI — natureza opinativa

Esse procedimento foi adotado conforme os subtópicos 3.1, 3.2 e 3.3 desta impugnação.

## 3. DO MÉRITO PROPRIAMENTE DITO

3.1. BENEFÍCIOS SEM VÍNCULO NA DATA DOS ACIDENTES

Texto da tese, citando o art. 85, §11, do CPC e a Resolução nº 1.316/2010.

3.2. CONCESSÃO CONCOMITANTE DE BENEFÍCIOS

| Vigências do FAP | CNPJ | NB |
| 2022 | 18.225.557/0004-39 | 6217537803 |

### 3.3. COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS

Texto da compensação (arts. 165 e 170 do CTN).

PEDIDOS

Por todo o exposto, requer.
"""

out = renumber_document(DOC)
lines = out.splitlines()


def _has_line(prefix):
    return any(l.strip().lstrip('#').strip().startswith(prefix) for l in lines)


check("insuficiência ganhou 1.", _has_line("1. DA INSUFICIÊNCIA TÉCNICA"))
check("mérito 3 -> 2", _has_line("2. DO MÉRITO PROPRIAMENTE DITO"))
check("subseção 3.1 -> 2.1", _has_line("2.1. BENEFÍCIOS SEM VÍNCULO"))
check("subseção 3.2 -> 2.2", _has_line("2.2. CONCESSÃO CONCOMITANTE"))
check("subseção 3.3 -> 2.3", _has_line("2.3. COMPENSAÇÃO E RESTITUIÇÃO"))
check("PEDIDOS ganhou 3.", _has_line("3. PEDIDOS"))
check("remissão 3.1/3.2/3.3 -> 2.1/2.2/2.3",
      "subtópicos 2.1, 2.2 e 2.3" in out, f"(veio: {[l for l in lines if 'subtópicos' in l]})")
check("Resolução 1.329/2017 intacta", "nº 1.329/2017" in out)
check("Resolução 1.347/2021 intacta", "nº 1.347/2021" in out)
check("Resolução 1.316/2010 intacta", "nº 1.316/2010" in out)
check("art. 85, §11 intacto", "art. 85, §11" in out)
check("tabela intacta", "| 2022 | 18.225.557/0004-39 | 6217537803 |" in out)
check("endereçamento não numerado", not _has_line("1. EXCELENTÍSSIMO"))
check("CNPJ no corpo intacto", "18.225.557/0004-39" in out)
check("nº do processo intacto", "6008199-38.2026.4.06.3800" in out)

# Documento já numerado corretamente não muda.
DOC_OK = """Intro.

1. PRELIMINARES

Texto.

2. DO MÉRITO PROPRIAMENTE DITO

2.1. ACIDENTE DE TRAJETO

Texto conforme o subtópico 2.1.

3. PEDIDOS

Requer.
"""
check("documento correto é idempotente", renumber_document(DOC_OK) == DOC_OK)

# Modo B (sem mérito): mérito sintético numerado 1, pedidos 2.
DOC_B = """Intro.

1. MÉRITO

1.1. DO RECONHECIMENTO DE ERROS

1.2. DA REVELIA

2. PEDIDOS

Requer.
"""
check("modo B idempotente", renumber_document(DOC_B) == DOC_B)

# ── strip_trailing_closing ───────────────────────────────────────────
req = "g. Que todas as publicações sejam em nome da advogada.\n\nNestes termos,\n\nPede deferimento."
check("fecho em duas linhas removido do fim",
      strip_trailing_closing(req).rstrip().endswith("advogada."))

req2 = "Requer a procedência.\n\nNestes termos, pede deferimento."
check("fecho em linha única removido", strip_trailing_closing(req2).rstrip().endswith("procedência."))

req3 = "Requer a procedência integral dos pedidos."
check("texto sem fecho fica intacto", strip_trailing_closing(req3) == req3)

req4 = "Nestes termos, o pedido se impõe porque a lei determina.\n\nRequer."
check("'Nestes termos' no meio do texto não é removido",
      strip_trailing_closing(req4) == req4)

# ── strip_leading_duplicate_heading ──────────────────────────────────
comp = "COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS\n\nA Autora pleiteia a restituição."
check("título duplicado removido do início",
      strip_leading_duplicate_heading(comp, "COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS")
      .startswith("A Autora"))

comp2 = "A Autora pleiteia a restituição."
check("conteúdo sem título fica intacto",
      strip_leading_duplicate_heading(comp2, "COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS") == comp2)

# ── detect_internal_references ───────────────────────────────────────
body = ("As hipóteses previstas na sub-hipótese aplicável da tese 6.6 e o "
        "catálogo do escritório (6.6) confirmam a exclusão.")
notes = detect_internal_references(body)
check("vazamento 'tese 6.6' detectado", any("tese 6.6" in n for n in notes), f"(veio {notes})")
check("vazamento 'catálogo do escritório' detectado",
      any("catálogo do escritório" in n.lower() for n in notes))

clean_body = "A jurisprudência do TRF4 confirma a tese da Autora (AC 5025207-60.2021.4.04.7200)."
check("texto limpo não gera nota", detect_internal_references(clean_body) == [])

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
