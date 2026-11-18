"""
Navegador da Consulta do FAP: abre a tela do portal e tira o print — processo à parte.

Roda como ``python -m app.services.fap_portal_navegador --pedido '<json>' --saida DIR``
e responde **uma linha de JSON** na saída padrão. Quem chama é o
``fap_portal_print_service``, num subprocesso com tempo-limite: o Playwright
síncrono não roda dentro do loop asyncio do MCP, e um Chromium travado morre
com o processo em vez de segurar um worker do app.

Não importa Flask nem banco: a sessão vem do ``FAP_AUTH_JSON`` herdado do
ambiente, e a validação do pedido (escritório, CNPJ da base) já foi feita
antes de chegar aqui.

O roteiro foi mapeado na tela real em 18/11/2026 (portal React + Design System
gov.br + MUI DataGrid v4):

- os três seletores são autocompletes ``#anoVigencia``, ``#cnpjRaiz`` e
  ``#estabelecimentos``, com as opções em ``[id^="<campo>-option-"]``. A lista de
  empresas só desenha as opções visíveis: é preciso digitar para filtrar, e o
  rótulo vem pontuado ("00.025.841 - NOME") — dígito cru não acha nada;
- os números sublinhados de "Dados do Cálculo" são
  ``span[title="Clique para ver detalhes"]`` no mesmo bloco
  (``div.MuiGrid-grid-sm-4``) do rótulo; número zero não é clicável;
- o detalhe abre em ``.modal-table`` com uma DataGrid paginada (5, 10, 20, 50,
  100 linhas) que só desenha as colunas que cabem — os B91 têm 17 colunas e a
  1920 px aparecem 12; as outras (nascimento, CNPJ, NIT, CPF, DIB, DCB...) saem
  num segundo print, com a tabela rolada até o fim, como a pessoa faria;
- o filtro por número é o do próprio portal (FILTROS: coluna, operador, valor);
- o Histórico troca o cálculo exibido ao clicar ("Cálculo Original").

Códigos de erro (campo ``codigo``): ``sessao_expirada``, ``vigencia_inexistente``,
``empresa_fora_do_portal``, ``estabelecimento_fora_do_portal``, ``sem_calculo``,
``sem_calculo_original``, ``sem_itens``, ``numero_nao_encontrado``,
``portal_indisponivel`` e ``erro_navegacao``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE = 'https://fap-mps.dataprev.gov.br'
DOMINIO = 'fap-mps.dataprev.gov.br'
LARGURA = 1920
ALTURA = 1080
TIMEOUT_MS = 45_000
MENU_PRINCIPAL = 'button[aria-label="Abrir Menu Principal"]'
CLICAVEL = 'span[title="Clique para ver detalhes"]'

# O frontend só se considera logado com idp + sessionId no storage (o mesmo do
# scripts/fap_navegar_portal.py); o sessionId é só do navegador.
STORAGE_MINIMO = """
for (const st of [window.sessionStorage, window.localStorage]) {
  try {
    if (!st.getItem('idp')) st.setItem('idp', 'fapgovbridp');
    if (!st.getItem('sessionId')) st.setItem('sessionId', 'intellexia-navegador');
  } catch (e) {}
}
"""

# tela → (rótulo do bloco em "Dados do Cálculo", coluna do filtro por número)
TELAS_DETALHE = {
    'B91': ('(B91)', 'Número do Benefício'),
    'B92': ('(B92)', 'Número do Benefício'),
    'B93': ('(B93)', 'Número do Benefício'),
    'B94': ('(B94)', 'Número do Benefício'),
    'CAT': ('(CAT)', 'Número da CAT'),
    'beneficios_pagos': ('Valor Total de Benefícios Pagos', 'Número do Benefício'),
    'massa_salarial': ('Massa Salarial', None),
    'vinculos': ('Número Médio de Vínculos', None),
}
TAMANHOS_PAGINA = (10, 20, 50, 100)


class Falha(Exception):
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def _digitos(texto: str) -> str:
    return re.sub(r'\D', '', texto or '')


def _cnpj_formatado(c: str) -> str:
    return f'{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}'


def _raiz_formatada(r: str) -> str:
    return f'{r[:2]}.{r[2:5]}.{r[5:8]}'


def _esperar(page, ms: int = 600) -> None:
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(ms)


def _escolher(page, campo: str, casa, digitar: str | None, codigo: str, mensagem: str) -> str:
    """Abre o autocomplete, filtra digitando e clica na opção que ``casa(rótulo)``."""
    entrada = page.locator(f'#{campo}')
    entrada.click()
    if digitar:
        entrada.fill(digitar)
    page.wait_for_timeout(1000)
    opcoes = page.locator(f'[id^="{campo}-option-"]')
    rotulos = [opcoes.nth(i).inner_text().strip() for i in range(opcoes.count())]
    indice = next((i for i, r in enumerate(rotulos) if casa(r)), None)
    if indice is None:
        raise Falha(codigo, mensagem)
    opcoes.nth(indice).click()
    _esperar(page)
    return rotulos[indice]


def _vinculadas_com_erro(token: dict) -> bool:
    bruto = token.get('empresasVinculadas')
    try:
        dado = json.loads(bruto) if isinstance(bruto, str) else bruto
    except ValueError:
        return True
    return isinstance(dado, dict) and bool(dado.get('errors'))


def _fechar_painel(page, caixa) -> None:
    """Fecha o painel de filtro clicando no alto da caixa branca. Escape fecharia a janela inteira."""
    box = caixa.bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + 10)
    page.wait_for_timeout(800)


def _filtrar(page, modal, caixa, coluna: str, numero: str) -> int:
    """Filtro do próprio portal (FILTROS → coluna, "contém", valor). Devolve as linhas que ficaram."""
    modal.get_by_text('Filtros').first.click()
    page.wait_for_timeout(800)
    selects = page.locator('select:visible')
    for i in range(selects.count()):
        sel = selects.nth(i)
        opcoes = [o.strip() for o in sel.locator('option').all_inner_texts()]
        if coluna in opcoes:
            sel.select_option(label=coluna)
        elif 'contém' in opcoes:
            sel.select_option(label='contém')
    page.locator('input[placeholder="Filtrar valor"]').first.fill(numero)
    page.wait_for_timeout(1500)
    _fechar_painel(page, caixa)
    return modal.locator('.MuiDataGrid-row').count()


def _total_linhas(modal) -> int | None:
    legenda = modal.locator('.MuiTablePagination-caption').last.inner_text() if modal.locator(
        '.MuiTablePagination-caption').count() else ''
    m = re.search(r'de\s+([\d.]+)', legenda)
    return int(m.group(1).replace('.', '')) if m else None


def _mostrar_todas(page, modal, total: int) -> None:
    alvo = next((t for t in TAMANHOS_PAGINA if t >= total), TAMANHOS_PAGINA[-1])
    if alvo <= 10:
        return
    seletor = modal.locator('.MuiTablePagination-root [role=button], .MuiTablePagination-root select').first
    if seletor.evaluate('e => e.tagName') == 'SELECT':
        seletor.select_option(label=str(alvo))
    else:
        seletor.click()
        page.wait_for_timeout(500)
        page.locator('[role=listbox] [role=option]', has_text=re.compile(rf'^\s*{alvo}\s*$')).first.click()
    page.wait_for_timeout(1200)


def _prints_do_modal(page, modal, caixa, pasta: Path, prefixo: str) -> list[dict]:
    """Um print da janela; outro com a tabela rolada até o fim quando há colunas escondidas."""
    partes = []
    arquivo = pasta / f'{prefixo}_1.png'
    caixa.screenshot(path=str(arquivo))
    partes.append({'arquivo': str(arquivo), 'descricao': 'colunas iniciais'})
    grade = modal.locator('.MuiDataGrid-root').first
    total_cols = int(grade.get_attribute('aria-colcount') or 0)
    visiveis = grade.locator('.MuiDataGrid-columnHeader').count()
    if total_cols and visiveis and total_cols > visiveis:
        rolou = grade.evaluate("""g => {
            const w = g.querySelector('.MuiDataGrid-window') || g.querySelector('.MuiDataGrid-virtualScroller');
            if (!w || w.scrollWidth <= w.clientWidth) return false;
            w.scrollLeft = w.scrollWidth; return true; }""")
        if rolou:
            page.wait_for_timeout(900)
            arquivo = pasta / f'{prefixo}_2.png'
            caixa.screenshot(path=str(arquivo))
            partes.append({'arquivo': str(arquivo), 'descricao': 'colunas finais (tabela rolada até o fim)'})
    return partes


def capturar(pedido: dict, pasta: Path) -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from app.services.fap_web_service import FapWebAuthPayload

    auth = FapWebAuthPayload.from_env()
    if auth is None:
        raise Falha('sessao_expirada', 'FAP_AUTH_JSON ausente ou inválido no .env desta instalação.')

    cnpj, ano = pedido['cnpj'], int(pedido['vigencia'])
    raiz = cnpj[:8]
    tela, numero = pedido['tela'], pedido.get('numero')
    calculo = pedido.get('calculo') or 'atual'
    pasta.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(user_agent=auth.effective_user_agent, locale='pt-BR',
                                      viewport={'width': LARGURA, 'height': ALTURA})
            ctx.add_cookies([{'name': k, 'value': v, 'domain': DOMINIO, 'path': '/', 'secure': True}
                             for k, v in auth.cookies.items() if k and v])
            ctx.add_init_script(STORAGE_MINIMO)
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT_MS)

            try:
                with page.expect_response(lambda r: r.url.split('?')[0].endswith('/gateway/oauth2/token')) as info:
                    page.goto(BASE + '/', wait_until='domcontentloaded')
            except PlaywrightError as e:
                raise Falha('portal_indisponivel', f'O portal do FAP não respondeu ({str(e).splitlines()[0][:120]}).')
            token = info.value
            if token.status in (401, 403):
                raise Falha('sessao_expirada', 'A sessão do portal FAP expirou: é preciso logar de novo no '
                            'gov.br e atualizar o FAP_AUTH_JSON.')
            if token.status >= 500:
                raise Falha('portal_indisponivel', f'O portal do FAP respondeu {token.status} (fora do ar).')
            try:
                sessao_parcial = _vinculadas_com_erro(token.json())
            except Exception:
                sessao_parcial = False
            _esperar(page)

            page.locator(MENU_PRINCIPAL).click()
            page.locator('a[href="/consultar-fap"]:visible').first.click()
            _esperar(page, 1000)

            _escolher(page, 'anoVigencia', lambda r: r.strip() == str(ano), None, 'vigencia_inexistente',
                      f'A vigência {ano} não existe na Consulta do FAP.')
            rotulo_empresa = _escolher(
                page, 'cnpjRaiz', lambda r: _digitos(r).startswith(raiz), _raiz_formatada(raiz),
                'empresa_fora_do_portal',
                f'A empresa {_raiz_formatada(raiz)} não aparece na Consulta do FAP com a sessão atual'
                + (' — a sessão está parcial (perdeu as empresas vinculadas do gov.br); um login novo resolve.'
                   if sessao_parcial else ' (sem procuração para este CPF/escritório).'))
            _escolher(page, 'estabelecimentos', lambda r: _digitos(r) == cnpj, _cnpj_formatado(cnpj),
                      'estabelecimento_fora_do_portal',
                      f'O estabelecimento {_cnpj_formatado(cnpj)} não aparece na vigência {ano} do portal.')

            page.get_by_role('button', name='Consultar').click()
            _esperar(page, 2000)
            if not page.get_by_text('Dados do Cálculo').count():
                raise Falha('sem_calculo', f'O portal não mostra cálculo do FAP {ano} para '
                            f'{_cnpj_formatado(cnpj)}.')

            if calculo == 'original':
                item = page.get_by_text('Cálculo Original', exact=True)
                if not item.count():
                    raise Falha('sem_calculo_original', 'O Histórico deste estabelecimento não tem '
                                '"Cálculo Original".')
                item.first.click()
                _esperar(page, 1500)

            card_fap = page.get_by_text('Realizado em').first.locator('xpath=ancestor::div[contains(@class,"br-card")][1]')
            resumo_fap = re.sub(r'\s+', ' ', card_fap.inner_text()).replace('Informações da Extração', '').strip() \
                if card_fap.count() else ''
            marcado = page.locator('li.timeline-selected').first
            rotulo_calculo = re.sub(r'\s+', ' ', marcado.inner_text()).strip() if marcado.count() else ''
            resultado = {
                'ok': True, 'empresa': rotulo_empresa, 'fap': resumo_fap[:200], 'calculo': rotulo_calculo[:150],
                'sessao_parcial': sessao_parcial, 'linhas': None, 'linhas_omitidas': 0,
            }

            if tela == 'calculo':
                arquivo = pasta / 'tela_1.png'
                page.screenshot(path=str(arquivo), full_page=True)
                resultado['partes'] = [{'arquivo': str(arquivo), 'descricao': 'tela da Consulta do FAP'}]
                return resultado

            rotulo, coluna = TELAS_DETALHE[tela]
            bloco = page.locator('div.MuiGrid-grid-sm-4').filter(has=page.locator('span.text-base', has_text=rotulo))
            alvo = bloco.locator(CLICAVEL).first
            if not alvo.count():
                raise Falha('sem_itens', f'O cálculo não tem {tela} para abrir (o número está zerado na tela).')
            alvo.click()
            modal = page.locator('.modal-table').first
            modal.wait_for(state='visible')
            caixa = modal.locator('.modal-table-content').first
            _esperar(page, 1200)

            if numero:
                linhas = _filtrar(page, modal, caixa, coluna, numero)
                if not linhas:
                    raise Falha('numero_nao_encontrado', f'O número {numero} não está na lista de {tela} '
                                f'deste cálculo.')
                resultado['linhas'] = linhas
            else:
                total = _total_linhas(modal) or 0
                resultado['linhas'] = total
                if total > 10:
                    # janela mais alta para a tabela inteira caber no print
                    page.set_viewport_size({'width': LARGURA, 'height': max(ALTURA, 420 + 38 * min(total, 100))})
                    _mostrar_todas(page, modal, total)
                    resultado['linhas_omitidas'] = max(0, total - 100)
            resultado['partes'] = _prints_do_modal(page, modal, caixa, pasta, 'tela')
            return resultado
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description='Print da Consulta do FAP (uso interno do IntellexIA).')
    ap.add_argument('--pedido', required=True, help='JSON: cnpj, vigencia, tela, numero, calculo')
    ap.add_argument('--saida', required=True, help='pasta onde gravar as imagens')
    args = ap.parse_args()
    try:
        resposta = capturar(json.loads(args.pedido), Path(args.saida))
    except Falha as e:
        resposta = {'ok': False, 'codigo': e.codigo, 'mensagem': str(e)}
    except Exception as e:  # o processo pai só lê o JSON
        resposta = {'ok': False, 'codigo': 'erro_navegacao',
                    'mensagem': f'{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ""}'}
    print(json.dumps(resposta, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
