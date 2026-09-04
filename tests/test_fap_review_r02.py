#!/usr/bin/env python3
"""
Testes das regras da remessa R02 no Revisor de Petições
(app/services/fap_review_service.py).

Funções puras: não precisam de banco, rede nem contexto Flask.

    uv run python tests/test_fap_review_r02.py
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.fap_review_service import (
    MODEL_NOT_RECORDED,
    describe_model_name,
    validate_wrike_identifier,
)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# ── RPI-23 — Id Wrike aceita só números ─────────────────────────────────

def test_wrike_aceita_numero():
    print('\n1. RPI-23 — identificador numérico é aceito')

    valor, erro = validate_wrike_identifier('1790631885')
    check('sem erro', erro is None, str(erro))
    check('devolve o valor', valor == '1790631885', repr(valor))


def test_wrike_apara_espacos_das_pontas():
    print('\n2. RPI-23 — espaço nas pontas não invalida')

    valor, erro = validate_wrike_identifier('  1790631885 \n')
    check('sem erro', erro is None, str(erro))
    check('valor aparado', valor == '1790631885', repr(valor))


def test_wrike_preserva_zero_a_esquerda():
    print('\n3. RPI-23 — é identificador, não número: zero à esquerda fica')

    valor, erro = validate_wrike_identifier('0079')
    check('sem erro', erro is None, str(erro))
    check('zero preservado', valor == '0079', repr(valor))


def test_wrike_recusa_letras():
    print('\n4. RPI-23 — texto é recusado')

    for entrada in ('ABC-123', '1790631885x', '#1790631885',
                    'https://wrike.com/open.htm?id=1790631885'):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)
        if erro:
            check(f'mensagem de {entrada!r} fala em números', 'número' in erro.lower(), erro)
            break


def test_wrike_recusa_espaco_no_meio():
    print('\n5. RPI-23 — espaço no meio quebraria a busca')

    _, erro = validate_wrike_identifier('1790 631885')
    check('recusa', erro is not None)


def test_wrike_recusa_vazio():
    print('\n6. RPI-23 — campo é obrigatório')

    for entrada in ('', '   ', None):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)
        if erro:
            check('mensagem pede o preenchimento', 'informe' in erro.lower(), erro)


def test_wrike_recusa_longo_demais():
    print('\n7. RPI-23 — limite da coluna continua valendo')

    _, erro = validate_wrike_identifier('9' * 97)
    check('recusa 97 dígitos', erro is not None)
    if erro:
        check('mensagem fala do limite', '96' in erro, erro)

    _, erro_ok = validate_wrike_identifier('9' * 96)
    check('aceita 96 dígitos', erro_ok is None, str(erro_ok))


def test_wrike_erros_sao_distintos():
    print('\n8. RPI-23 — formato e obrigatoriedade têm mensagens diferentes')

    _, vazio = validate_wrike_identifier('')
    _, formato = validate_wrike_identifier('ABC')
    check('mensagens distintas', vazio != formato, f'{vazio!r} == {formato!r}')


def test_wrike_recusa_digito_nao_ascii():
    print('\n8b. RPI-23 — dígito unicode não é dígito para a busca')

    # 'isdigit()' do Python aceita '²' e '١٢٣'. Passariam na validação e
    # quebrariam exatamente a busca por Id que o requisito quer proteger.
    for entrada in ('179063188\u00b2', '\u0661\u0662\u0663'):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)


# ── RPI-18 — o debug não pode inventar o modelo ─────────────────────────

def test_modelo_registrado_aparece():
    print('\n9. RPI-18 — modelo gravado é exibido como está')

    check('sonnet', describe_model_name('claude-sonnet-5') == 'claude-sonnet-5')
    check('gpt', describe_model_name('gpt-4o-mini') == 'gpt-4o-mini')


def test_modelo_ausente_nao_e_chutado():
    print('\n10. RPI-18 — execução antiga não recebe palpite')

    # Foi um literal chutado no template que criou o RPI-18: com a coluna
    # inexistente, o Jinja caía sempre em 'gpt-4o-mini' e mentia sobre o Sonnet.
    for vazio in (None, '', '   '):
        rotulo = describe_model_name(vazio)
        check(f'{vazio!r} vira rótulo de ausência', rotulo == MODEL_NOT_RECORDED, repr(rotulo))
        check(f'{vazio!r} não vira nome de modelo', 'gpt' not in rotulo.lower(), repr(rotulo))


# ── RPI-19 — a barra de aprovação não pode viver dentro dos achados ─────

_TAG_IF = re.compile(r'{%-?\s*(if|endif)\b')


def _fim_do_bloco(texto: str, inicio: int) -> int:
    """Posição logo após o {% endif %} que fecha o {% if %} em `inicio`."""
    profundidade = 0
    for m in _TAG_IF.finditer(texto, inicio):
        profundidade += 1 if m.group(1) == 'if' else -1
        if profundidade == 0:
            return texto.index('%}', m.end()) + 2
    raise AssertionError('bloco Jinja sem fechamento')


def barra_esta_fora_do_bloco_de_achados(html: str) -> bool:
    """A barra de conclusão da triagem existe fora do `if result_data.findings`?"""
    ini_findings = html.index('{% if result_data.findings %}')
    fim_findings = _fim_do_bloco(html, ini_findings)
    pos_barra = html.index('id="triageCompleteActions"')
    return not (ini_findings < pos_barra < fim_findings)


def test_barra_de_aprovacao_sobrevive_a_revisao_sem_achados():
    print('\n11. RPI-19 — aprovar petição sem nenhum erro')

    # Com a barra aninhada no bloco de achados, uma revisão que não encontra
    # nada não renderiza o botão: a regra de negócio libera a aprovação, mas a
    # página não tem por onde. Foi o que travou o caso do João.
    html = (RAIZ / 'templates/fap_review/revision_result.html').read_text()

    check('barra fica fora do bloco de achados',
          barra_esta_fora_do_bloco_de_achados(html))
    check('texto cobre o caso de zero achados',
          'Nenhum ponto de atenção nesta revisão' in html)


def main() -> int:
    print('=' * 62)
    print('REMESSA R02 — regras do Revisor de Petições')
    print('=' * 62)

    test_wrike_aceita_numero()
    test_wrike_apara_espacos_das_pontas()
    test_wrike_preserva_zero_a_esquerda()
    test_wrike_recusa_letras()
    test_wrike_recusa_espaco_no_meio()
    test_wrike_recusa_vazio()
    test_wrike_recusa_longo_demais()
    test_wrike_erros_sao_distintos()
    test_wrike_recusa_digito_nao_ascii()
    test_modelo_registrado_aparece()
    test_modelo_ausente_nao_e_chutado()
    test_barra_de_aprovacao_sobrevive_a_revisao_sem_achados()

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
