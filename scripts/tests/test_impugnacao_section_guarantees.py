"""Garantias de seção da impugnação: tabela de benefícios por tese e
seção de pedidos reconhecidos pela União.

Fixtures baseadas em processo REAL de produção (6008199-38.2026.4.06.3800):
- benefício 1811879338 (KELVIN) com Decisão da União "exclusão aceita
  (acidente de trajeto reconhecido)" — deve gerar a seção DOS PEDIDOS
  RECONHECIDOS; os demais ("improcedência por ausência de prova...") não;
- teses do mérito saíram SEM a tabela padrão de benefícios (Seção 5.3),
  dependendo do modelo — o código passa a injetá-la quando faltar.

Rodar: uv run python scripts/tests/test_impugnacao_section_guarantees.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_section_guarantees import (
    benefit_table_markdown,
    argument_has_table,
    ensure_benefit_table_in_argument,
    detect_recognized_selections,
    build_recognized_section_text,
    insert_recognized_section,
)

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


B_KELVIN = {"benefit_number": "1811879338", "nit_number": "20491482854",
            "insured_name": "KELVIN MICHAEL CAMARA", "benefit_type": "B92",
            "fap_vigencia_year": "2021,2022", "thesis_name": "Acidente de trajeto",
            "status_label": "exclusão aceita (acidente de trajeto reconhecido)",
            "decision": ""}
B_RONALDO = {"benefit_number": "6331845066", "nit_number": "20065480869",
             "insured_name": "RONALDO PEREIRA DA SILVA", "benefit_type": "B91",
             "fap_vigencia_year": "2023,2024", "thesis_name": "Acidente em outra empresa",
             "status_label": "improcedência por ausência de prova de erro na vinculação",
             "decision": ""}
B_GERSON = {"benefit_number": "6217537803", "nit_number": "10275328934",
            "insured_name": "GERSON PEREIRA FEITOZA", "benefit_type": "B91",
            "fap_vigencia_year": "2021", "thesis_name": "Acidente em outra empresa",
            "status_label": "improcedência por ausência de prova de erro na vinculação",
            "decision": ""}
B_NEGADO = {"benefit_number": "9999", "nit_number": "1", "insured_name": "X",
            "benefit_type": "B91", "fap_vigencia_year": "2021", "thesis_name": "T",
            "status_label": "não reconhecido o erro apontado", "decision": ""}

# ── tabela ───────────────────────────────────────────────────────────
tbl = benefit_table_markdown([B_RONALDO, B_GERSON])
check("tabela tem cabeçalho padrão", "| NB | NIT | Segurado | Tipo | Vigência FAP |" in tbl)
check("tabela tem linha do Ronaldo", "| 6331845066 | 20065480869 | RONALDO PEREIRA DA SILVA | B91 | 2023,2024 |" in tbl)
check("tabela tem 2 linhas de dados", tbl.count("\n|") >= 3)

check("argumento sem tabela detectado", not argument_has_table("3.1. TESE\n\nTexto corrido."))
check("argumento com tabela detectado", argument_has_table("3.1. TESE\n\n| NB | NIT |\n| --- | --- |\n| 1 | 2 |"))

arg = "3.1. BENEFÍCIOS SEM VÍNCULO\n\nIdentificação do pedido\n\nA Autora requereu a exclusão."
novo, inserida = ensure_benefit_table_in_argument(arg, [B_RONALDO, B_GERSON])
check("tabela injetada quando falta", inserida and "| 6331845066 |" in novo)
check("tabela entra logo após o heading", novo.splitlines()[0].startswith("3.1.") and "| NB |" in "\n".join(novo.splitlines()[1:6]))
check("texto original preservado", "A Autora requereu a exclusão." in novo)

com_tabela = arg + "\n\n| NB | NIT | Segurado |\n| --- | --- | --- |\n| 6331845066 | x | y |"
novo2, inserida2 = ensure_benefit_table_in_argument(com_tabela, [B_RONALDO])
check("argumento que já tem tabela fica intacto", not inserida2 and novo2 == com_tabela)

novo3, inserida3 = ensure_benefit_table_in_argument(arg, [])
check("sem benefícios, nada é injetado", not inserida3 and novo3 == arg)

# ── detecção de reconhecidos ─────────────────────────────────────────
rec = detect_recognized_selections([B_KELVIN, B_RONALDO, B_GERSON, B_NEGADO])
check("Kelvin (exclusão aceita) detectado", [b["benefit_number"] for b in rec] == ["1811879338"], f"(veio {[b['benefit_number'] for b in rec]})")
check("improcedência não é reconhecimento", all(b["benefit_number"] != "6331845066" for b in rec))
check("'não reconhecido' não é reconhecimento", all(b["benefit_number"] != "9999" for b in rec))
check("lista vazia -> vazio", detect_recognized_selections([]) == [])

# ── seção de pedidos reconhecidos ────────────────────────────────────
sec = build_recognized_section_text(rec)
check("heading canônico", sec.splitlines()[0].strip() == "DOS PEDIDOS RECONHECIDOS PELA UNIÃO")
check("tabela com coluna Tese", "| Tese |" in sec and "Acidente de trajeto" in sec)
check("NB do Kelvin na tabela", "1811879338" in sec)
check("homologação com art. 487, III", 'art. 487, III, "a", do CPC' in sec)

# ── inserção no lugar certo ──────────────────────────────────────────
prelim = ("PRELIMINARES\n\nTexto preliminar.\n\n"
          "DA INSUFICIÊNCIA TÉCNICA E JURÍDICA DA CONTESTAÇÃO\n\nA contestação reproduz...")
res = insert_recognized_section(prelim, sec)
pos_rec = res.find("DOS PEDIDOS RECONHECIDOS")
check("entra antes da insuficiência", 0 < pos_rec < res.find("DA INSUFICIÊNCIA"))
check("depois das preliminares", pos_rec > res.find("PRELIMINARES"))

res2 = insert_recognized_section("Só texto, sem heading de insuficiência.", sec)
check("sem insuficiência -> prepend", res2.startswith("DOS PEDIDOS RECONHECIDOS"))

ja_tem = "1. DOS PEDIDOS RECONHECIDOS PELA UNIÃO\n\nJá existe.\n\nDA INSUFICIÊNCIA TÉCNICA"
check("não duplica quando o modelo já escreveu",
      insert_recognized_section(ja_tem, sec) == ja_tem)

# ── integração com o renumerador ─────────────────────────────────────
from app.agents.legal_drafting.impugnacao_numbering import renumber_document
doc = res + "\n\n## 3. DO MÉRITO PROPRIAMENTE DITO\n\n3.1. TESE X\n\nTexto.\n\nPEDIDOS\n\nRequer."
out = renumber_document(doc)
check("renumerador numera reconhecidos",
      any(l.strip().startswith("2. DOS PEDIDOS RECONHECIDOS") for l in out.splitlines()),
      f"(headings: {[l.strip()[:50] for l in out.splitlines() if l.strip()[:2].rstrip('.').isdigit()]})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
