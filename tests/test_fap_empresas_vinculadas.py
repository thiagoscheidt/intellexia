"""
Empresas do Painel FAP = procurações + vinculadas do gov.br.

O seletor "CNPJ Raiz" da tela de contestações do portal junta as duas origens;
a sincronização lia só as procurações e o grupo Vale ficou de fora. Testa as
partes puras — leitura do campo do token e a união — e a regra de poda com um
serviço falso, sem tocar no banco.

    uv run python tests/test_fap_empresas_vinculadas.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fap_company_sync_service import unir_empresas
from app.services.fap_web_service import parse_empresas_vinculadas


def test_parse_lista_completa():
    bruto = json.dumps([
        {'cnpj': '33592510000154', 'razaoSocial': 'VALE S.A.', 'dataCriacao': 'x'},
        {'cnpj': '33592510000235', 'razaoSocial': 'VALE S.A.', 'dataCriacao': 'x'},  # mesma raiz
        {'cnpj': '5014452000146', 'razaoSocial': 'MONTESINOS'},  # zero à esquerda perdido
        {'cnpj': '123', 'razaoSocial': 'lixo'},
    ])
    r = parse_empresas_vinculadas(bruto)
    assert r.ok, r.message
    assert r.data == [
        {'cnpj': '33592510', 'nome': 'VALE S.A.'},
        {'cnpj': '05014452', 'nome': 'MONTESINOS'},
    ], r.data


def test_parse_sessao_parcial():
    bruto = json.dumps({'errors': [{'code': 'ACCESSTOKEN_MUSTBENOTEXPIRED'}]})
    r = parse_empresas_vinculadas(bruto)
    assert not r.ok
    assert 'ACCESSTOKEN_MUSTBENOTEXPIRED' in r.message


def test_parse_ausente():
    assert not parse_empresas_vinculadas(None).ok


def test_unir_procuracao_tem_prioridade():
    procuracoes = [{'cnpj': '07196033', 'nome': 'NORSA', 'tipoProcuracao': {'codigo': 'X'}}]
    vinculadas = [{'cnpj': '07196033', 'nome': 'NORSA REFRIGERANTES S.A'},
                  {'cnpj': '33592510', 'nome': 'VALE S.A.'}]
    unidas = {c['cnpj']: c for c in unir_empresas(procuracoes, vinculadas)}
    assert set(unidas) == {'07196033', '33592510'}
    assert unidas['07196033']['tipoProcuracao'] == {'codigo': 'X'}
    assert unidas['33592510'] == {'cnpj': '33592510', 'nome': 'VALE S.A.', 'tipoProcuracao': None}


if __name__ == '__main__':
    falhas = 0
    for nome, fn in list(globals().items()):
        if nome.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'OK    {nome}')
            except AssertionError as e:
                falhas += 1
                print(f'FALHA {nome}: {e}')
    sys.exit(1 if falhas else 0)
