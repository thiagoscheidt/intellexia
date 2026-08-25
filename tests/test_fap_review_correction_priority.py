"""
Teste da prioridade de correção do Revisor FAP.

Regressão: o valor ia inteiro para uma pílula `.badge` (que é `white-space:
nowrap`). Quando o modelo escrevia o plano de ação junto do nível — "Alta —
corrigir prioritariamente os 7 achados críticos (...)" — a linha não quebrava e
a tela do resultado ganhava rolagem horizontal.

Uso: uv run python tests/test_fap_review_correction_priority.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.services.fap_review_service import split_correction_priority  # noqa: E402

PASSED = 0
FAILED = 0

REAL_VALUE = (
    "Alta — corrigir prioritariamente os 7 achados críticos (valor da causa, "
    "placeholder de data DOU, CNPJ incorreto, divergência de quantidade de "
    "benefícios no Tópico 6, uso indevido de 'Previdência Social', seção de "
    "comprovação das alegações incompatível com o caso, e erro no pedido de "
    "diligência do item 4.2) antes do protocolo. Em seguida, tratar os achados "
    "moderados relacionados à completude dos pedidos de diligência e à precisão "
    "técnica dos índices de restabelecimento. Os achados formais podem ser "
    "corrigidos em revisão final de redação."
)


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def run():
    print("[1] Valor real: nível separado do plano de ação")
    parsed = split_correction_priority(REAL_VALUE)
    check("nível extraído", parsed['level'] == 'Alta', f"(obteve {parsed['level']!r})")
    check("cor de crítico", parsed['level_style'] == 'danger', f"(obteve {parsed['level_style']!r})")
    check("plano de ação fora da pílula",
          parsed['detail'].startswith('Corrigir prioritariamente os 7 achados'),
          f"(obteve {parsed['detail'][:60]!r})")
    check("travessão consumido", '—' not in parsed['detail'])
    check("nada perdido no caminho",
          parsed['detail'].endswith('revisão final de redação.'),
          f"(termina em {parsed['detail'][-40:]!r})")

    print("[2] Contrato do agente: só o nível")
    for value, level, style in (
        ('ALTA', 'Alta', 'danger'),
        ('MÉDIA', 'Média', 'warning'),
        ('Media', 'Média', 'warning'),
        ('BAIXA', 'Baixa', 'success'),
        ('N/A', 'Sem achados', 'secondary'),
        ('sem achados', 'Sem achados', 'secondary'),
        ('Erro na análise', 'Erro na análise', 'secondary'),
    ):
        parsed = split_correction_priority(value)
        check(f"{value!r} → {level} / {style}",
              parsed['level'] == level and parsed['level_style'] == style and not parsed['detail'],
              f"(obteve {parsed})")

    print("[3] Outros separadores")
    for value in ('Alta: revisar antes do protocolo', 'ALTA - revisar antes do protocolo',
                  'Alta. Revisar antes do protocolo', 'Alta, revisar antes do protocolo',
                  'Alta\n\nRevisar antes do protocolo'):
        parsed = split_correction_priority(value)
        check(f"{value.splitlines()[0]!r}",
              parsed['level'] == 'Alta' and parsed['detail'] == 'Revisar antes do protocolo',
              f"(obteve {parsed})")

    print("[4] Texto sem nível conhecido → sem pílula, texto inteiro")
    parsed = split_correction_priority('Revisar tudo antes de protocolar')
    check("sem nível", parsed['level'] == '', f"(obteve {parsed['level']!r})")
    check("texto preservado", parsed['detail'] == 'Revisar tudo antes de protocolar')

    print("[5] Prefixo parecido não vira nível")
    parsed = split_correction_priority('Altamente recomendável revisar os pedidos')
    check("'Altamente' não é 'Alta'", parsed['level'] == '', f"(obteve {parsed['level']!r})")
    check("texto preservado", parsed['detail'].startswith('Altamente recomendável'))

    print("[6] Vazio não renderiza nada")
    for value in (None, '', '   '):
        parsed = split_correction_priority(value)
        check(f"{value!r} → bloco omitido",
              not parsed['raw'] and not parsed['level'] and not parsed['detail'],
              f"(obteve {parsed})")

    print("[7] Templates compilam com o filtro novo")
    from main import app  # noqa: E402  (importa a app inteira: mais lento)
    for template_name in ('fap_review/revision_result.html', 'fap_review/petition_detail.html'):
        try:
            app.jinja_env.get_template(template_name)
            check(f"{template_name} compila", True)
        except Exception as error:
            check(f"{template_name} compila", False, f"({error})")

    check("filtro registrado", 'correction_priority' in app.jinja_env.filters)


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
