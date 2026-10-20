#!/usr/bin/env python3
"""
Raiz do CNPJ com zero à esquerda nas contestações e procurações FAP — E01 da
Remessa R09 ("Filtro por CNPJ raiz esconde contestações e procurações").

O portal manda ``cnpj`` e ``cnpjRaiz`` como número: 07.718.633/0081-63 chega
como ``7718633008163``. Desde 02/07/2026 a raiz era tirada dos 8 primeiros
dígitos desse número sem zero, e a UNIDASUL (07718633) ficou com 370
contestações gravadas como ``77186330``.

Partes puras (raiz a partir do item do portal) e um escritório descartável
para os filtros do MCP, criado e removido no fim.

    uv run python tests/test_fap_cnpj_raiz_zeros.py
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, FapWebContestacao, FapWebProcuracao
from app.utils.cnpj import raiz_contestacao_fap

FIRM_NAME = '__TESTE_CNPJ_RAIZ_ZEROS__'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_raiz_do_item():
    print('\n1. raiz_contestacao_fap — a raiz a partir do item do portal')

    unidasul = {'cnpj': 7718633008163, 'cnpjRaiz': 7718633}
    check('UNIDASUL: CNPJ numérico sem o zero volta a 07718633',
          raiz_contestacao_fap(unidasul) == '07718633', raiz_contestacao_fap(unidasul))

    sendas = {'cnpj': 6057223000171, 'cnpjRaiz': 6057223}
    check('Sendas: 06057223', raiz_contestacao_fap(sendas) == '06057223',
          raiz_contestacao_fap(sendas))

    check('sem cnpjRaiz, completa o CNPJ para 14 antes de cortar',
          raiz_contestacao_fap({'cnpj': 7718633008163}) == '07718633',
          raiz_contestacao_fap({'cnpj': 7718633008163}))

    sem_zero = {'cnpj': 79894168000127, 'cnpjRaiz': 79894168}
    check('raiz sem zero continua igual', raiz_contestacao_fap(sem_zero) == '79894168')

    # Vigências antigas: o item não traz cnpj, só a raiz da empresa consultada.
    # Foi para não virar "00000079" que o código mudou em julho.
    antiga = {'cnpjRaiz': 79894168}
    check('vigência antiga sem cnpj não vira 00000079',
          raiz_contestacao_fap(antiga, fallback_raiz='79894168') == '79894168',
          raiz_contestacao_fap(antiga, fallback_raiz='79894168'))
    check('sem nada no item, usa a raiz da empresa',
          raiz_contestacao_fap({}, fallback_raiz='7718633') == '07718633',
          raiz_contestacao_fap({}, fallback_raiz='7718633'))

    check('string formatada também serve',
          raiz_contestacao_fap({'cnpj': '07.718.633/0081-63'}) == '07718633')


def test_os_dois_caminhos_de_sincronizacao_usam_a_funcao():
    print('\n2. Botão do Painel FAP e cron gravam a raiz pela mesma função')

    from app.blueprints import fap_panel
    src_painel = inspect.getsource(fap_panel)
    check('Painel FAP chama raiz_contestacao_fap', 'raiz_contestacao_fap(' in src_painel)
    check('Painel FAP não corta mais os dígitos sem zero',
          'cnpj_raiz_8 = cnpj_digits[:8]' not in src_painel)

    src_cron = (Path(__file__).resolve().parent.parent / 'scripts' / 'fap_sync_cron.py').read_text()
    check('cron chama raiz_contestacao_fap', 'raiz_contestacao_fap(' in src_cron)
    check('cron não corta mais os dígitos sem zero',
          'cnpj_raiz_item = cnpj_item_digits[:8]' not in src_cron)


def _criar_escritorio():
    firm = LawFirm.query.filter_by(name=FIRM_NAME).first()
    if firm:
        _remover_escritorio(firm.id)
    firm = LawFirm(name=FIRM_NAME, cnpj='99000000000199')
    db.session.add(firm)
    db.session.commit()
    return firm.id


def _remover_escritorio(law_firm_id):
    FapWebContestacao.query.filter_by(law_firm_id=law_firm_id).delete()
    FapWebProcuracao.query.filter_by(law_firm_id=law_firm_id).delete()
    LawFirm.query.filter_by(id=law_firm_id).delete()
    db.session.commit()


def test_mcp_procuracoes_acha_com_e_sem_zero(law_firm_id):
    print('\n3. MCP listar_procuracoes_fap acha a raiz com e sem o zero')
    from mcp_server.tools.fap import list_fap_procuracoes_handler

    # O banco guarda a raiz das procurações como veio do portal, sem o zero
    # (decisão de c9c90eb) — quem compensa é o filtro.
    db.session.add(FapWebProcuracao(
        law_firm_id=law_firm_id, protocolo='398881',
        cnpj_raiz_outorgante='7718633', nome_empresa_outorgante='UNIDASUL',
    ))
    db.session.add(FapWebProcuracao(
        law_firm_id=law_firm_id, protocolo='900001',
        cnpj_raiz_outorgante='77186330', nome_empresa_outorgante='OUTRA',
    ))
    db.session.commit()

    for termo in ('07718633', '7718633', '07.718.633'):
        res = list_fap_procuracoes_handler(law_firm_id, cnpj_raiz=termo)
        protocolos = [p['protocolo'] for p in res['itens']]
        check(f'"{termo}" acha a 398881 e só ela', protocolos == ['398881'], str(protocolos))


def test_mcp_contestacoes_aceita_raiz_sem_zero(law_firm_id):
    print('\n4. MCP listar_contestacoes_fap completa o zero da raiz pedida')
    from mcp_server.tools.fap import list_fap_contestacoes_handler

    db.session.add(FapWebContestacao(
        law_firm_id=law_firm_id, contestacao_id=990001, cnpj='07718633008163',
        cnpj_raiz='07718633', ano_vigencia=2026,
    ))
    db.session.commit()

    for termo in ('07718633', '7718633'):
        res = list_fap_contestacoes_handler(law_firm_id, cnpj_raiz=termo)
        check(f'"{termo}" acha a contestação', res['total_encontrado'] == 1, str(res['total_encontrado']))


def main() -> int:
    test_raiz_do_item()
    test_os_dois_caminhos_de_sincronizacao_usam_a_funcao()

    with app.app_context():
        law_firm_id = _criar_escritorio()
        try:
            test_mcp_procuracoes_acha_com_e_sem_zero(law_firm_id)
            test_mcp_contestacoes_aceita_raiz_sem_zero(law_firm_id)
        finally:
            db.session.rollback()
            _remover_escritorio(law_firm_id)

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
