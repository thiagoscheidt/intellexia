"""
Guarda contra JS quebrado nos templates.

Existe por causa de um incidente real: uma edição automatizada comeu o `});`
que fechava um listener em 5 templates do Painel de Contestações. O Jinja
continuava válido, as rotas respondiam 200 e a API devolvia os dados certos —
mas o navegador dava "Uncaught SyntaxError: Unexpected end of input", o
DataTables nunca inicializava e a tabela aparecia vazia. Nenhum teste de
backend pegava isso.

Não substitui um parser de JS (não há node no ambiente): confere o
balanceamento de delimitadores dentro dos blocos <script>, ignorando strings,
comentários e literais de regex. Pega a classe de erro que de fato ocorreu.

Executar:
    uv run python tests/test_templates_js_balanceado.py
"""

import glob
import os
import re
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def _remover_ruido(js):
    """Tira strings, comentários e regex — só sobra a estrutura do código.

    Sem isso, uma chave dentro de um texto (`'{{ nome }}'`) contaria como
    delimitador e o teste acusaria erro onde não há.
    """
    saida = []
    i = 0
    n = len(js)
    while i < n:
        ch = js[i]
        prox = js[i + 1] if i + 1 < n else ''

        if ch == '/' and prox == '/':
            i = js.find('\n', i)
            if i == -1:
                break
            continue
        if ch == '/' and prox == '*':
            fim = js.find('*/', i + 2)
            i = n if fim == -1 else fim + 2
            continue
        if ch in ('"', "'", '`'):
            aspas = ch
            i += 1
            while i < n:
                if js[i] == '\\':
                    i += 2
                    continue
                if js[i] == aspas:
                    i += 1
                    break
                i += 1
            continue

        # Literal de regex: /.../flags. Só é regex quando um operando é
        # esperado — senão `a / b` viraria início de regex. Sem isso, um
        # padrão como /[^;]*/ contaria colchetes que não são estrutura.
        if ch == '/':
            anterior = next((c for c in reversed(saida) if not c.isspace()), '')
            if anterior in ('', '(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+', '-', '*', '%', '<', '>', '~', '^'):
                i += 1
                dentro_classe = False
                while i < n:
                    if js[i] == '\\':
                        i += 2
                        continue
                    if js[i] == '[':
                        dentro_classe = True
                    elif js[i] == ']':
                        dentro_classe = False
                    elif js[i] == '/' and not dentro_classe:
                        i += 1
                        break
                    elif js[i] == '\n':
                        break  # regex não atravessa linha: era divisão
                    i += 1
                continue

        saida.append(ch)
        i += 1
    return ''.join(saida)


def verificar(caminho):
    with open(caminho, encoding='utf-8') as arquivo:
        conteudo = arquivo.read()

    blocos = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', conteudo, re.S)
    if not blocos:
        return None

    codigo = _remover_ruido('\n'.join(blocos))
    return {
        'chaves': codigo.count('{') - codigo.count('}'),
        'parenteses': codigo.count('(') - codigo.count(')'),
        'colchetes': codigo.count('[') - codigo.count(']'),
    }


def main():
    padroes = [
        'templates/disputes_center/*.html',
        'templates/fap_panel/*.html',
        'templates/process_panel/*.html',
        'templates/partials/*.html',
    ]
    arquivos = sorted({c for p in padroes for c in glob.glob(os.path.join(RAIZ, p))})
    print(f'Conferindo o JS de {len(arquivos)} templates\n')

    analisados = 0
    for caminho in arquivos:
        saldo = verificar(caminho)
        if saldo is None:
            continue
        analisados += 1
        rel = os.path.relpath(caminho, RAIZ)
        equilibrado = saldo['chaves'] == saldo['parenteses'] == saldo['colchetes'] == 0
        if not equilibrado:
            check(f'{rel}', False,
                  f"chaves={saldo['chaves']:+d} parênteses={saldo['parenteses']:+d} "
                  f"colchetes={saldo['colchetes']:+d}")

    if not FALHAS:
        print(f'  [OK ] todos os {analisados} templates com <script> estão balanceados')

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} TEMPLATE(S) COM JS QUEBRADO')
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
