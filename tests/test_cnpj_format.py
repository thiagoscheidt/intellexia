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

from app.utils.cnpj import apenas_digitos, formatar_cnpj

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


def main() -> int:
    test_apenas_digitos()
    test_formata_cnpj_cru()
    test_formatar_e_idempotente()
    test_devolve_como_veio_quando_nao_da()
    test_gerador_formata_nos_quatro_pontos()
    test_disputes_center_usa_o_mesmo_formatador()

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
