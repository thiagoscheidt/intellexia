#!/usr/bin/env python3
"""
Testes do saneador de achados do Revisor FAP
(app/agents/fap_review/finding_sanitizer.py).

Função pura: não precisa de rede, banco, LLM nem contexto Flask.

    uv run python tests/test_fap_review_finding_sanitizer.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.fap_review.finding_sanitizer import sanear, fingerprint_achado

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def achado(**kwargs) -> dict:
    """Achado mínimo válido, com os campos que o saneador lê."""
    base = {
        'category': 'CAT-1',
        'severity': 'CRÍTICO',
        'description': 'Descrição do achado',
        'location': 'Qualificação, parágrafo 1',
        'location_excerpt': None,
        'correction': None,
        'manual_reference': '1.1',
    }
    base.update(kwargs)
    return base


# Trecho real da inicial que gerou os relatos de RPI-12 no documento de feedbacks.
PETICAO = (
    'SENDAS DISTRIBUIDORA S.A., pessoa jurídica de direito privado, inscrita no '
    'CNPJ sob o nº 06.057.223/0001-71, com endereço Avenida Ayrton Senna, nº 06000, '
    'Lot 2 Pal 48959 Anexo A, Jacarepaguá, Rio de Janeiro/RJ, CEP 22.775-005 e suas '
    'filiais, vem, perante Vossa Excelência,'
)


# ── R1 — RPI-12: sugestão idêntica ao que já está no documento ──────────

def test_r1_descarta_sugestao_ja_presente_no_documento():
    print('\n1. R1 — sugestão que o documento já atende')

    # Caso literal do feedback: o CEP está correto e a IA manda "corrigir" para
    # exatamente o que está escrito.
    cep = achado(
        description="CEP '22.775-005' grafado incorretamente, sem ponto separador após o segundo dígito.",
        correction="Corrigir para 'CEP 22.775-005'",
    )
    mantidos, descartes = sanear([cep], PETICAO)

    check('achado do CEP é descartado', mantidos == [], f'sobraram {len(mantidos)}')
    check('registra exatamente 1 descarte', len(descartes) == 1, str(descartes))
    if descartes:
        check('descarte diz a regra', descartes[0].get('regra') == 'R1', str(descartes[0]))
        check('descarte guarda o achado', descartes[0].get('achado') == cep)
        check('descarte tem motivo legível',
              'já' in (descartes[0].get('motivo') or '').lower(),
              repr(descartes[0].get('motivo')))


def test_r1_descarta_razao_social_identica():
    print('\n2. R1 — razão social sugerida igual à do documento')

    sendas = achado(
        description="Razão social 'SENDAS DISTRIBUIDORA S.A.' grafada como "
                    "'SENDAS DISTRIBUIDORA S.A.' (sem ponto) na qualificação.",
        correction="Corrigir para 'SENDAS DISTRIBUIDORA S.A.'",
    )
    mantidos, _ = sanear([sendas], PETICAO)

    check('achado da razão social é descartado', mantidos == [], f'sobraram {len(mantidos)}')


def test_r1_preserva_correcao_real():
    print('\n3. R1 — correção legítima sobrevive')

    real = achado(
        description="CNPJ da autora diverge do que consta no cartão CNPJ.",
        correction="Corrigir para '06.057.223/0001-72'",
    )
    mantidos, descartes = sanear([real], PETICAO)

    check('achado legítimo é mantido', mantidos == [real], f'mantidos={len(mantidos)}')
    check('nada foi descartado', descartes == [], str(descartes))


def test_r1_preserva_correcao_so_de_caixa():
    print('\n4. R1 — correção que muda só a caixa é achado de verdade')

    # "Sendas Distribuidora S.A." não está no documento; lá está em caixa alta.
    # Comparar sem diferenciar maiúsculas descartaria um achado legítimo.
    caixa = achado(
        description='Razão social grafada em caixa alta, fora do padrão do manual.',
        correction="Corrigir para 'Sendas Distribuidora S.A.'",
    )
    mantidos, _ = sanear([caixa], PETICAO)

    check('correção de caixa é mantida', len(mantidos) == 1, f'mantidos={len(mantidos)}')


def test_r1_ignora_achado_sem_correcao():
    print('\n5. R1 — achado sem sugestão não é tocado')

    sem = achado(description='Falta a data do acidente no tópico 4.', correction=None)
    mantidos, descartes = sanear([sem], PETICAO)

    check('achado sem correção é mantido', mantidos == [sem])
    check('nada descartado', descartes == [])


def test_r1_sem_documento_nao_descarta():
    print('\n6. R1 — sem texto do documento, não há o que comparar')

    cep = achado(
        description="CEP '22.775-005' grafado incorretamente.",
        correction="Corrigir para 'CEP 22.775-005'",
    )
    mantidos, descartes = sanear([cep], '')

    check('mantém o achado quando não há documento', mantidos == [cep])
    check('nada descartado', descartes == [])


# ── R2 — RPI-13: o mesmo achado apontado mais de uma vez ────────────────

def test_r2_deduplica_achado_repetido():
    print('\n7. R2 — achado repetido aparece uma vez só')

    # Caso literal do feedback: o mesmo B91 apontado nos pontos 15 e 21.
    texto = ('Benefício B91 nº 6214157201 já foi tratado no tópico 11 da petição '
             'inicial, mas não foi incluído na tabela de pedidos.')
    ponto15 = achado(description=texto, location='Tabela de pedidos',
                     correction='Incluir o benefício na tabela de pedidos.')
    ponto21 = achado(description=texto, location='Tabela de pedidos',
                     correction='Incluir o benefício na tabela de pedidos.')

    mantidos, descartes = sanear([ponto15, ponto21], PETICAO)

    check('sobra um único achado', len(mantidos) == 1, f'sobraram {len(mantidos)}')
    check('registra 1 descarte', len(descartes) == 1, str(len(descartes)))
    if descartes:
        check('descarte diz a regra', descartes[0].get('regra') == 'R2', str(descartes[0].get('regra')))
        check('motivo fala de repetição',
              'repet' in (descartes[0].get('motivo') or '').lower()
              or 'duplic' in (descartes[0].get('motivo') or '').lower(),
              repr(descartes[0].get('motivo')))


def test_r2_mantem_a_primeira_ocorrencia():
    print('\n8. R2 — quem fica é a primeira ocorrência')

    primeiro = achado(description='Mesmo texto', location='Tópico 4', location_excerpt='trecho A')
    segundo = achado(description='Mesmo texto', location='Tópico 4', location_excerpt='trecho B')

    mantidos, _ = sanear([primeiro, segundo], PETICAO)

    check('mantém o primeiro', mantidos == [primeiro], str(mantidos))


def test_r2_achados_diferentes_sobrevivem():
    print('\n9. R2 — achados distintos não se anulam')

    a = achado(description='Falta a CAT do benefício 6214157201.')
    b = achado(description='Falta a CAT do benefício 6408721579.')

    mantidos, descartes = sanear([a, b], PETICAO)

    check('os dois são mantidos', len(mantidos) == 2, f'mantidos={len(mantidos)}')
    check('nada descartado', descartes == [], str(descartes))


def test_fingerprint_ignora_o_trecho_citado():
    print('\n10. Fingerprint — trecho citado não entra na identidade')

    # Deliberado: no caso real os dois apontamentos citavam trechos diferentes
    # do mesmo problema. Entrando na identidade, a duplicata escaparia.
    a = achado(description='Mesmo problema', location_excerpt='um trecho')
    b = achado(description='Mesmo problema', location_excerpt='outro trecho')

    check('mesmo fingerprint', fingerprint_achado(a) == fingerprint_achado(b))


def test_fingerprint_acompanha_o_do_servico():
    print('\n11. Fingerprint — mesmo valor do usado para achado descartado')

    # Se divergirem, um achado marcado "não pertinente" numa revisão deixaria de
    # ser reconhecido na seguinte.
    from app.services.fap_review_service import build_finding_fingerprint

    exemplo = achado(description='Divergência de NIT', correction='Conferir no CNIS')
    check('sanitizer e serviço concordam',
          fingerprint_achado(exemplo) == build_finding_fingerprint(exemplo))


# ── R6 — falso positivo de razão social (regra que já existia no agente) ─

def test_r6_descarta_achado_que_diz_nao_haver_divergencia():
    print('\n12. R6 — achado sobre razão social que ele mesmo diz estar certa')

    auto = achado(
        description='Razão social da autora grafada de forma consistente em todo o documento, '
                    'sem divergências detectadas.',
    )
    mantidos, descartes = sanear([auto], PETICAO)

    check('achado é descartado', mantidos == [], f'sobraram {len(mantidos)}')
    check('regra é R6', descartes and descartes[0].get('regra') == 'R6',
          str(descartes[0].get('regra')) if descartes else 'sem descarte')


def test_r6_preserva_divergencia_real_de_razao_social():
    print('\n13. R6 — divergência real de razão social sobrevive')

    real = achado(
        description="Razão social da autora diverge entre a qualificação e a procuração.",
        correction="Uniformizar para 'MUNDIAL MIX COMERCIO DE ALIMENTOS LTDA'",
    )
    mantidos, _ = sanear([real], PETICAO)

    check('achado é mantido', mantidos == [real], f'mantidos={len(mantidos)}')


def test_r6_nao_toca_achado_de_outro_assunto():
    print('\n14. R6 — "sem divergência" fora de razão social não é descartado')

    outro = achado(description='Sem divergência nas datas, mas falta a CAT do benefício.')
    mantidos, _ = sanear([outro], PETICAO)

    check('achado é mantido', mantidos == [outro], f'mantidos={len(mantidos)}')


def main() -> int:
    print('=' * 62)
    print('SANEADOR DE ACHADOS — Revisor FAP')
    print('=' * 62)

    test_r1_descarta_sugestao_ja_presente_no_documento()
    test_r1_descarta_razao_social_identica()
    test_r1_preserva_correcao_real()
    test_r1_preserva_correcao_so_de_caixa()
    test_r1_ignora_achado_sem_correcao()
    test_r1_sem_documento_nao_descarta()
    test_r2_deduplica_achado_repetido()
    test_r2_mantem_a_primeira_ocorrencia()
    test_r2_achados_diferentes_sobrevivem()
    test_fingerprint_ignora_o_trecho_citado()
    test_fingerprint_acompanha_o_do_servico()
    test_r6_descarta_achado_que_diz_nao_haver_divergencia()
    test_r6_preserva_divergencia_real_de_razao_social()
    test_r6_nao_toca_achado_de_outro_assunto()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
