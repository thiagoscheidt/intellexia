#!/usr/bin/env python3
"""Testes standalone dos helpers puros do fap_review_aux_service.

Uso: uv run python tests/test_fap_review_aux_service.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services import fap_review_aux_service as svc  # noqa: E402


def test_anchors_from_spreadsheet_dedupes_and_merges_theses():
    rows = [
        {'benefit_number': '123.456.789-0', 'benefit_number_normalized': '1234567890', 'thesis': 'ACIDENTE DE TRAJETO', 'sheet_name': '2021'},
        {'benefit_number': '1234567890', 'benefit_number_normalized': '1234567890', 'thesis': 'PRÉ-FAP', 'sheet_name': '2022'},
        {'benefit_number': '987.654.321-0', 'benefit_number_normalized': '9876543210', 'thesis': 'ERRO DE ESTABELECIMENTO', 'sheet_name': '2021'},
    ]
    anchors, source = svc.build_benefit_anchors(rows, petition_text='ignorado')
    assert source == 'spreadsheet', source
    assert len(anchors) == 2, anchors
    first = next(a for a in anchors if a['benefit_number_normalized'] == '1234567890')
    assert first['theses'] == ['ACIDENTE DE TRAJETO', 'PRÉ-FAP'], first


def test_anchors_fallback_from_petition_text():
    text = 'O benefício NB 123.456.789-0 foi convertido. CNPJ 12.345.678/0001-99 não é benefício. Processo 0001234-56.2020.4.04.7100.'
    anchors, source = svc.build_benefit_anchors(None, petition_text=text)
    assert source == 'petition_text', source
    numbers = {a['benefit_number_normalized'] for a in anchors}
    assert '1234567890' in numbers, numbers
    assert all(len(n) == 10 for n in numbers), numbers


def test_anchors_none_when_no_source():
    anchors, source = svc.build_benefit_anchors(None, petition_text=None)
    assert anchors == [] and source == 'none'


def test_fingerprint_stable_and_order_insensitive():
    a1 = [{'benefit_number': '1', 'benefit_number_normalized': '1111111111', 'theses': ['A', 'B']},
          {'benefit_number': '2', 'benefit_number_normalized': '2222222222', 'theses': []}]
    a2 = list(reversed([{**a, 'theses': list(reversed(a['theses']))} for a in a1]))
    assert svc.anchors_fingerprint(a1) == svc.anchors_fingerprint(a2)
    assert svc.anchors_fingerprint(a1) != svc.anchors_fingerprint([])


def test_build_review_payload_status_and_theses_enrichment():
    anchors = [{'benefit_number': '123.456.789-0', 'benefit_number_normalized': '1234567890', 'theses': ['ACIDENTE DE TRAJETO']}]
    results = [
        {'file_name': 'CAT_joao.pdf', 'from_cache': False, 'error': None,
         'extraction': {'document_type': 'CAT',
                        'related_benefits': [{'benefit_number': '123.456.789-0', 'match_reason': 'NB citado',
                                              'facts': [{'label': 'Data do acidente', 'value': '12/03/2019', 'source_excerpt': 'ocorrido em 12/03/2019'}]}],
                        'general_summary': 'CAT do trabalhador João.',
                        'potential_divergences': ['Data diverge da petição']}},
        {'file_name': 'foto.jpg', 'from_cache': True, 'error': None,
         'extraction': {'document_type': 'OUTRO', 'related_benefits': [], 'general_summary': 'Print ilegível.', 'potential_divergences': []}},
        {'file_name': 'quebrado.pdf', 'from_cache': False, 'error': 'Arquivo corrompido', 'extraction': None},
    ]
    payload = svc.build_review_payload(results, anchors, 'spreadsheet', skipped=['extra.pdf'])
    assert payload['anchor_source'] == 'spreadsheet'
    assert payload['total_documents'] == 3
    assert payload['matched_documents'] == 1
    assert payload['skipped_documents'] == ['extra.pdf']
    matched, unmatched, errored = payload['documents']
    assert matched['status'] == 'matched'
    assert matched['related_benefits'][0]['theses'] == ['ACIDENTE DE TRAJETO']
    assert matched['related_benefits'][0]['in_anchor_list'] is True
    assert unmatched['status'] == 'unmatched' and unmatched['from_cache'] is True
    assert errored['status'] == 'error' and errored['error'] == 'Arquivo corrompido'


def test_build_agent_documents_renders_content_summary():
    results = [
        {'file_name': 'CAT_joao.pdf', 'from_cache': False, 'error': None,
         'extraction': {'document_type': 'CAT',
                        'related_benefits': [{'benefit_number': '123.456.789-0', 'match_reason': 'NB citado',
                                              'facts': [{'label': 'Data do acidente', 'value': '12/03/2019', 'source_excerpt': 'ocorrido em 12/03/2019'}]}],
                        'general_summary': 'CAT do trabalhador João.',
                        'potential_divergences': ['Data diverge da petição']}},
        {'file_name': 'quebrado.pdf', 'from_cache': False, 'error': 'x', 'extraction': None},
    ]
    docs = svc.build_agent_documents(results)
    assert docs[0]['name'] == 'CAT_joao.pdf'
    summary = docs[0]['content_summary']
    assert 'Data do acidente: 12/03/2019' in summary
    assert 'ocorrido em 12/03/2019' in summary
    assert 'Possível divergência' in summary
    assert docs[1] == {'name': 'quebrado.pdf'}


# ── FB-03: conferência dos números extraídos contra o próprio documento ──

CAT = ('19 - Data do Acidente: 27/07/2018  22 - Tipo: TRAJETO\n'
       'NB 624.736.470-2   CNPJ 06.057.223/0001-71   Emissão 03.08.18')


def test_confere_data_e_numero_presentes_no_documento():
    assert svc.conferir_fato('27/07/2018', CAT, None)['status'] == 'confirmado'
    # Mesmo NB com e sem máscara.
    assert svc.conferir_fato('6247364702', CAT, None)['status'] == 'confirmado'
    # Mesma data em outro formato: 03.08.18 no documento.
    assert svc.conferir_fato('03/08/2018', CAT, None)['status'] == 'confirmado'


def test_digito_trocado_nao_confirma():
    check = svc.conferir_fato('6247364720', CAT, None)
    assert check['status'] == 'nao_confirmado', check
    assert check['base'] == 'documento' and check['faltando'] == ['6247364720'], check
    assert svc.conferir_fato('27/07/2017', CAT, None)['status'] == 'nao_confirmado'


def test_data_impossivel():
    for valor in ('27/13/2018', '32/07/2018', '27/07/2081'):
        check = svc.conferir_fato(valor, CAT, None)
        assert check['status'] == 'data_invalida', (valor, check)


def test_valor_sem_numero_nao_e_conferido():
    assert svc.conferir_fato('TRAJETO', CAT, None) is None
    assert svc.conferir_fato('VIA PUBLICA', CAT, None) is None


def test_sem_texto_confere_contra_o_trecho():
    # PDF escaneado: não há texto do documento, só o trecho que o modelo citou.
    check = svc.conferir_fato('27/07/2018', '', 'Data do Acidente: 27/07/2018')
    assert check['status'] == 'confirmado' and check['base'] == 'trecho', check
    check = svc.conferir_fato('27/07/2018', '', 'Data do Acidente: 72/07/2018')
    assert check['status'] == 'nao_confirmado' and check['base'] == 'trecho', check
    assert svc.conferir_fato('27/07/2018', '', None) is None


def test_conferencia_chega_na_tela_e_no_revisor():
    extraction = {'document_type': 'CAT', 'related_benefits': [{
        'benefit_number': '6247364702', 'match_reason': 'NB citado',
        'facts': [{'label': 'NB', 'value': '6247364720', 'source_excerpt': 'NB 624.736.470-2'},
                  {'label': 'Tipo', 'value': 'TRAJETO', 'source_excerpt': 'Tipo: TRAJETO'}]}]}
    conferida = svc.conferir_extracao(extraction, CAT)
    assert 'check' not in extraction['related_benefits'][0]['facts'][0], 'não pode mutar o original (cache)'
    results = [{'file_name': 'CAT.pdf', 'extraction': conferida, 'error': None}]
    payload = svc.build_review_payload(results, [], 'none', [])
    facts = payload['documents'][0]['related_benefits'][0]['facts']
    assert facts[0]['check']['status'] == 'nao_confirmado', facts
    assert facts[1].get('check') is None, facts
    summary = svc.build_agent_documents(results)[0]['content_summary']
    assert 'NÃO CONFIRMADO' in summary.split('NB: 6247364720')[1].splitlines()[0], summary
    assert 'NÃO CONFIRMADO' not in summary.split('Tipo: TRAJETO')[1].splitlines()[0], summary


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for test in tests:
        try:
            test()
            print(f'  OK  {test.__name__}')
        except AssertionError as exc:
            failed += 1
            print(f'FALHOU {test.__name__}: {exc}')
    print(f'\n{len(tests) - failed}/{len(tests)} testes passaram')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
