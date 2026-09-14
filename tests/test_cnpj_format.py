#!/usr/bin/env python3
"""
Testes do formatador de CNPJ compartilhado (app/utils/cnpj.py) e do uso dele
no gerador de petições — GER-01, "Máscara de CNPJ no template".

Função pura: não precisa de rede, banco, LLM nem contexto Flask.

    uv run python tests/test_cnpj_format.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.cnpj import (
    apenas_digitos, completar_zeros, formatar_cnpj, formatar_cnpj_raiz, formatar_cpf,
)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# ── apenas_digitos ──────────────────────────────────────────────────────

def test_apenas_digitos():
    print('\n1. apenas_digitos — tira tudo que não é dígito')

    check('formatado vira cru',
          apenas_digitos('19.630.496/0001-05') == '19630496000105')
    check('cru continua cru',
          apenas_digitos('19630496000105') == '19630496000105')
    check('espaço nas pontas não conta',
          apenas_digitos('  19630496000105  ') == '19630496000105')
    check('None vira vazio', apenas_digitos(None) == '')
    check('texto sem dígito vira vazio', apenas_digitos('Não informado') == '')


# ── formatar_cnpj ───────────────────────────────────────────────────────

def test_formata_cnpj_cru():
    print('\n2. formatar_cnpj — o caso do GER-01')

    # É este o valor que hoje chega cru na peça gerada.
    check('14 dígitos ganham a máscara',
          formatar_cnpj('19630496000105') == '19.630.496/0001-05',
          formatar_cnpj('19630496000105'))
    check('espaço nas pontas não atrapalha',
          formatar_cnpj(' 19630496000105 ') == '19.630.496/0001-05')


def test_formatar_e_idempotente():
    print('\n3. formatar_cnpj — aplicar duas vezes não estraga')

    # O cadastro tem os dois formatos, porque o campo é texto livre. Formatar
    # o que já está formatado tem de devolver a mesma coisa, senão o valor
    # dependeria de por onde passou.
    ja = '19.630.496/0001-05'
    check('já formatado sai igual', formatar_cnpj(ja) == ja, formatar_cnpj(ja))
    check('formatar duas vezes é igual a uma',
          formatar_cnpj(formatar_cnpj('19630496000105')) == '19.630.496/0001-05')


def test_devolve_como_veio_quando_nao_da():
    print('\n4. formatar_cnpj — o que não é CNPJ passa intacto')

    # O gerador passa este literal quando o caso não tem cliente. Ele não pode
    # virar string vazia, senão a peça sairia com um campo em branco no lugar
    # de dizer que o dado não existe.
    check('"Não informado" sobrevive',
          formatar_cnpj('Não informado') == 'Não informado',
          formatar_cnpj('Não informado'))
    check('None vira vazio', formatar_cnpj(None) == '')
    check('vazio continua vazio', formatar_cnpj('') == '')
    check('dígitos de menos passam intactos', formatar_cnpj('123') == '123')
    check('dígitos demais passam intactos',
          formatar_cnpj('196304960001051') == '196304960001051')
    # CNPJ alfanumérico (regra que entra em vigor a partir de 2026): não temos
    # nenhum na base, e mascarar por posição corromperia o valor. Passa inteiro.
    check('CNPJ com letra passa intacto',
          formatar_cnpj('AB.630.496/0001-05') == 'AB.630.496/0001-05')


# ── uso no gerador de petições ──────────────────────────────────────────

def test_gerador_formata_nos_quatro_pontos():
    print('\n5. GER-01 — o gerador não escreve mais CNPJ cru')

    fonte = (Path(__file__).resolve().parent.parent / 'agent_document_generator.py').read_text(
        encoding='utf-8')

    crus = [
        (n, linha.strip())
        for n, linha in enumerate(fonte.splitlines(), 1)
        if re.search(r'client\.cnpj', linha) and 'formatar_cnpj' not in linha
    ]
    check('nenhum client.cnpj sai sem passar pelo formatador',
          not crus,
          '; '.join(f'linha {n}: {t}' for n, t in crus))

    usos = len(re.findall(r'formatar_cnpj\(', fonte))
    check('os quatro pontos usam o formatador', usos == 4, f'{usos} uso(s)')
    check('o formatador vem do util compartilhado',
          'from app.utils.cnpj import' in fonte)


def test_disputes_center_usa_o_mesmo_formatador():
    print('\n6. GER-01 — o blueprint passa a delegar, não a ter cópia')

    fonte = (Path(__file__).resolve().parent.parent
             / 'app' / 'blueprints' / 'disputes_center.py').read_text(encoding='utf-8')

    check('importa do util compartilhado',
          'from app.utils.cnpj import' in fonte)
    # A máscara literal não pode existir em dois lugares: ter uma cópia privada
    # aqui foi exatamente o que deixou o gerador sem ela.
    check('não sobrou máscara literal no blueprint',
          '/{digits[8:12]}-' not in fonte,
          'ainda há montagem manual da máscara')


# ── Retorno da homologação: zeros à esquerda em Procurações ─────────────
# O portal FAP manda CNPJ raiz e CPF como NÚMERO: 00.482.840 chega como
# 482840 e fica gravado assim. A correção é só de exibição — a máscara
# devolve os zeros na tela, sem mexer no dado.

def test_completar_zeros():
    print('\n7. completar_zeros — devolve os zeros que o número comeu')

    check('raiz de 6 dígitos volta a ter 8', completar_zeros(482840, 8) == '00482840',
          completar_zeros(482840, 8))
    check('aceita string', completar_zeros('3227056', 8) == '03227056')
    check('já completo não muda', completar_zeros('84590900', 8) == '84590900')
    check('com máscara vira só dígitos', completar_zeros('00.482.840', 8) == '00482840')
    check('CPF de 7 dígitos volta a ter 11', completar_zeros(7488971, 11) == '00007488971',
          completar_zeros(7488971, 11))
    check('None continua None', completar_zeros(None, 8) is None)
    check('vazio vira None', completar_zeros('', 8) is None)
    # Mais dígitos que o tamanho não é zero faltando: é outro dado. Cortar
    # inventaria um documento; devolve os dígitos como vieram.
    check('dígitos demais não são cortados', completar_zeros('123456789', 8) == '123456789')


def test_formatar_cnpj_raiz():
    print('\n8. formatar_cnpj_raiz — o caso do print do Fred')

    check('482840 → 00.482.840', formatar_cnpj_raiz(482840) == '00.482.840',
          formatar_cnpj_raiz(482840))
    check('3227056 → 03.227.056', formatar_cnpj_raiz('3227056') == '03.227.056')
    check('sem zero faltando', formatar_cnpj_raiz('84590900') == '84.590.900')
    check('idempotente', formatar_cnpj_raiz('00.482.840') == '00.482.840')
    check('None vira vazio', formatar_cnpj_raiz(None) == '')
    check('lixo passa intacto', formatar_cnpj_raiz('123456789') == '123456789')


def test_formatar_cpf():
    print('\n9. formatar_cpf — o CPF do outorgado, que perdia 4 zeros')

    # 000.074.889-71 tem dígito verificador válido: os zeros eram mesmo zeros.
    check('7488971 → 000.074.889-71', formatar_cpf(7488971) == '000.074.889-71',
          formatar_cpf(7488971))
    check('CPF completo', formatar_cpf('12345678901') == '123.456.789-01')
    check('idempotente', formatar_cpf('000.074.889-71') == '000.074.889-71')
    check('None vira vazio', formatar_cpf(None) == '')


def test_tela_de_procuracoes_usa_os_filtros():
    print('\n10. Procurações — a tela não imprime mais o número cru')

    tela = (Path(__file__).resolve().parent.parent
            / 'templates' / 'fap_panel' / 'procuracoes.html').read_text(encoding='utf-8')
    check('raiz do outorgante passa pelo filtro',
          'r.cnpj_raiz_outorgante | cnpj_raiz' in tela)
    check('CPF do outorgado passa pelo filtro', 'r.cpf_outorgado | cpf' in tela)
    check('raiz do outorgado passa pelo filtro', 'r.cnpj_raiz_outorgado | cnpj_raiz' in tela)

    from main import app
    with app.app_context():
        filtros = app.jinja_env.filters
        check('filtros registrados no Jinja', 'cnpj_raiz' in filtros and 'cpf' in filtros)
        if 'cnpj_raiz' in filtros:
            check('filtro renderiza a máscara',
                  app.jinja_env.from_string('{{ 482840 | cnpj_raiz }}').render() == '00.482.840')


def main() -> int:
    test_apenas_digitos()
    test_formata_cnpj_cru()
    test_formatar_e_idempotente()
    test_devolve_como_veio_quando_nao_da()
    test_gerador_formata_nos_quatro_pontos()
    test_disputes_center_usa_o_mesmo_formatador()
    test_completar_zeros()
    test_formatar_cnpj_raiz()
    test_formatar_cpf()
    test_tela_de_procuracoes_usa_os_filtros()

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
