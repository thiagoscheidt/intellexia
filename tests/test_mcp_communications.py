#!/usr/bin/env python3
"""
Testa os handlers MCP do Monitoramento de Processos: listagem paginada com
filtros, detalhe com teor limpo, explicação (cache) e resumo executivo.

Uso: uv run python tests/test_mcp_communications.py
Sem chamadas reais à OpenAI (usa dados reais do escritório 1, só leitura,
exceto a explicação — mockada).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import ProcessCommunication
from mcp_server.tools.communications import (
    explain_communication_handler,
    get_communication_detail_handler,
    list_communications_handler,
    monitoring_summary_handler,
    process_communications_handler,
)

failures = []


def check(name, cond, detail=''):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(name)


with app.app_context():
    LAW_FIRM = 1

    # 1) listagem paginada
    page = list_communications_handler(LAW_FIRM, limit=5)
    check('lista retorna envelope paginado',
          {'total_encontrado', 'retornados', 'tem_mais', 'itens'} <= set(page.keys()))
    check('respeita o limite', page['retornados'] <= 5)
    if page['itens']:
        item = page['itens'][0]
        check('item tem os campos principais',
              {'id', 'tribunal', 'tipo', 'fonte', 'previa_teor', 'lida'} <= set(item.keys()))
        check('prévia sem lixo de CSS', 'font-family' not in (item.get('previa_teor') or ''))
        check('prévia curta', len(item.get('previa_teor') or '') <= 310)

    # 2) filtros
    trf = list_communications_handler(LAW_FIRM, tribunal='TRF4', limit=5)
    check('filtro por tribunal', all(i['tribunal'] == 'TRF4' for i in trf['itens']))
    nao_lidas = list_communications_handler(LAW_FIRM, somente_nao_lidas=True, limit=5)
    check('filtro só não lidas', all(i['lida'] is False for i in nao_lidas['itens']))

    # 3) data inválida → ToolError amigável
    from fastmcp.exceptions import ToolError
    try:
        list_communications_handler(LAW_FIRM, data_de='ontem')
        check('data inválida → ToolError', False)
    except ToolError as e:
        check('data inválida → ToolError', 'YYYY-MM-DD' in str(e))

    # 4) detalhe com teor limpo + tenant
    comm = (ProcessCommunication.query.filter_by(law_firm_id=LAW_FIRM)
            .filter(ProcessCommunication.texto.isnot(None)).first())
    detail = get_communication_detail_handler(comm.id, LAW_FIRM)
    check('detalhe traz teor limpo', detail['teor'] and '<' not in detail['teor'][:500])
    check('detalhe traz link e destinatários', 'link_documento_original' in detail
          and 'destinatarios' in detail)
    try:
        get_communication_detail_handler(comm.id, 999999)
        check('tenant errado → ToolError', False)
    except ToolError:
        check('tenant errado → ToolError', True)

    # 5) explicação usa cache quando existe
    cached_comm = (ProcessCommunication.query.filter_by(law_firm_id=LAW_FIRM)
                   .filter(ProcessCommunication.analysis_json.isnot(None)).first())
    check('há comunicação com análise em cache (pré-condição)', cached_comm is not None)
    if cached_comm:
        with patch('app.agents.processes.communication_explainer_agent.'
                   'CommunicationExplainerAgent.explain',
                   side_effect=AssertionError('não deveria chamar a IA')):
            result = explain_communication_handler(cached_comm.id, LAW_FIRM, user_id=1)
        check('explicação vem do cache sem chamar IA',
              result['veio_do_cache'] is True and result['explicacao'].get('resumo'))
        check('detalhe da cacheada inclui explicacao_ia',
              'explicacao_ia' in get_communication_detail_handler(cached_comm.id, LAW_FIRM))

    # 6) sem teor → ToolError
    no_text = (ProcessCommunication.query.filter_by(law_firm_id=LAW_FIRM)
               .filter(ProcessCommunication.texto.is_(None)).first())
    if no_text:
        try:
            explain_communication_handler(no_text.id, LAW_FIRM)
            check('explicar sem teor → ToolError', False)
        except ToolError:
            check('explicar sem teor → ToolError', True)

    # 7) linha do tempo por número de processo
    ref = (ProcessCommunication.query.filter_by(law_firm_id=LAW_FIRM)
           .filter(ProcessCommunication.numero_processo.isnot(None)).first())
    timeline = process_communications_handler(LAW_FIRM, ref.numero_processo)
    check('busca por dígitos encontra', timeline['total_encontrado'] >= 1, str(timeline['total_encontrado']))
    if ref.numero_processo_mascara:
        timeline_mask = process_communications_handler(LAW_FIRM, ref.numero_processo_mascara)
        check('busca por máscara encontra', timeline_mask['total_encontrado'] >= 1)
    datas = [i['data_disponibilizacao'] for i in timeline['itens'] if i['data_disponibilizacao']]
    check('linha do tempo em ordem cronológica', datas == sorted(datas))
    check('informa vínculo com o painel', 'processo_painel' in timeline)

    try:
        process_communications_handler(LAW_FIRM, '   ')
        check('número vazio → ToolError', False)
    except ToolError:
        check('número vazio → ToolError', True)

    try:
        process_communications_handler(LAW_FIRM, '12345', buscar_na_fonte=True)
        check('busca ao vivo sem CNJ completo → ToolError', False)
    except ToolError as e:
        check('busca ao vivo sem CNJ completo → ToolError', '20 dígitos' in str(e))

    # busca ao vivo com client mockado (sem rede)
    fake_item = {'id': 1, 'hash': 'h-vivo', 'siglaTribunal': 'TRF4',
                 'tipoComunicacao': 'Intimação', 'texto': 'Teor vivo',
                 'data_disponibilizacao': '2026-07-18'}
    with patch('app.services.comunica_pje_client.ComunicaPjeClient.get_comunicacoes_processo',
               return_value=[fake_item]):
        vivo = process_communications_handler(LAW_FIRM, ref.numero_processo.rjust(20, '0')[:20],
                                              buscar_na_fonte=True)
    check('DJEN ao vivo retorna itens com aviso',
          vivo['djen_ao_vivo']['total'] == 1 and 'NÃO foram' in vivo['djen_ao_vivo']['aviso'])

    # 8) resumo executivo
    resumo = monitoring_summary_handler(LAW_FIRM, dias=30)
    check('resumo traz totais e distribuições',
          {'total_geral', 'nao_lidas', 'no_periodo', 'advogados_monitorados',
           'tribunais_do_historico'} <= set(resumo.keys()))
    check('distribuição por tribunal não vazia', bool(resumo['no_periodo']['por_tribunal'])
          or resumo['no_periodo']['total'] == 0)
    check('dias clampados', monitoring_summary_handler(LAW_FIRM, dias=9999)['periodo_dias'] == 365)

if failures:
    print(f'\n❌ {len(failures)} falha(s): {failures}')
    sys.exit(1)
print('\n✅ Todos os testes passaram!')
