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
