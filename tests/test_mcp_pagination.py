#!/usr/bin/env python3
"""
Teste da paginação das tools de listagem do MCP.

    uv run python tests/test_mcp_pagination.py

O ponto crítico é a **ordenação estável**: os dados vêm de carga em lote, então
centenas de registros compartilham o mesmo ``created_at``. Sem desempate por id,
``LIMIT/OFFSET`` devolveria linhas repetidas e pularia outras sem avisar — e o
agente concluiria em cima de uma amostra furada achando que viu tudo.

Cobre:
  1. Envelope: total/retornados/tem_mais/proximo_deslocamento e limites saneados
  2. Varredura completa não pula nem repete registros (com dados reais empatados)
  3. Compatibilidade: chamadas sem 'deslocamento' seguem como antes
  4. Isolamento por escritório continua valendo em qualquer página
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from mcp_server.tools.fap import (
    list_fap_benefits_handler,
    list_fap_companies_handler,
    list_fap_contestacoes_handler,
)
from mcp_server.tools.pagination import MAX_LIMIT, clamp_limit, clamp_offset

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_saneamento():
    print('\n1) Saneamento de limite/deslocamento')
    check('limite inválido cai no padrão', clamp_limit('abc', 50) == 50)
    check('limite zero/negativo cai no padrão', clamp_limit(0, 50) == 50 and clamp_limit(-5, 50) == 50)
    check(f'limite absurdo é cortado em {MAX_LIMIT}', clamp_limit(99999, 50) == MAX_LIMIT)
    check('limite válido é respeitado', clamp_limit(30, 50) == 30)
    check('deslocamento negativo vira 0', clamp_offset(-10) == 0)
    check('deslocamento inválido vira 0', clamp_offset(None) == 0)


def test_envelope(law_firm_id):
    print('\n2) Envelope da resposta')
    r = list_fap_companies_handler(law_firm_id, limit=10)
    esperado = {'total_encontrado', 'retornados', 'deslocamento', 'tem_mais', 'itens'}
    check('traz as chaves do envelope', esperado <= set(r), str(set(r)))
    check('formato antigo preservado (total_encontrado/retornados/itens)',
          isinstance(r['total_encontrado'], int) and isinstance(r['itens'], list))

    if r['total_encontrado'] > 10:
        check('tem_mais verdadeiro quando trunca', r['tem_mais'] is True)
        check('indica o próximo deslocamento', r.get('proximo_deslocamento') == 10,
              str(r.get('proximo_deslocamento')))
        check('dica cita o parâmetro real da tool', 'deslocamento=' in r.get('dica', ''))
    else:
        print('     (poucos dados para testar truncamento)')

    # Página além do fim: vazia e honesta, sem erro.
    fim = list_fap_companies_handler(law_firm_id, limit=10, offset=r['total_encontrado'] + 100)
    check('página além do fim volta vazia sem erro',
          fim['itens'] == [] and fim['tem_mais'] is False, str(fim.get('retornados')))

    ultima = list_fap_companies_handler(law_firm_id, limit=10,
                                        offset=max(r['total_encontrado'] - 5, 0))
    check('última página marca tem_mais=False', ultima['tem_mais'] is False)


def _varre_tudo(handler, law_firm_id, page_size, **kwargs):
    """Percorre todas as páginas e devolve os ids na ordem em que apareceram."""
    ids, offset, guarda = [], 0, 0
    while True:
        guarda += 1
        assert guarda < 500, 'paginação não terminou — possível laço infinito'
        r = handler(law_firm_id, limit=page_size, offset=offset, **kwargs)
        ids.extend(item['id'] for item in r['itens'])
        if not r['tem_mais']:
            return ids, r['total_encontrado']
        offset = r['proximo_deslocamento']


def test_varredura(law_firm_id):
    print('\n3) Varredura completa não pula nem repete')

    # Empresas: ordenação por nome (único aqui, mas o id garante estabilidade).
    ids, total = _varre_tudo(list_fap_companies_handler, law_firm_id, 37)
    check(f'empresas: visitou todas ({len(ids)} de {total})', len(ids) == total)
    check('empresas: nenhum registro repetido', len(set(ids)) == len(ids),
          f'{len(ids) - len(set(ids))} repetidos')

    # Benefícios: o caso duro — centenas de registros com created_at idêntico.
    ids, total = _varre_tudo(list_fap_benefits_handler, law_firm_id, 50)
    check(f'benefícios: visitou todos ({len(ids)} de {total})', len(ids) == total,
          f'faltaram {total - len(set(ids))}')
    check('benefícios: nenhum repetido apesar dos created_at empatados',
          len(set(ids)) == len(ids), f'{len(ids) - len(set(ids))} repetidos')

    # Mesma varredura com página menor tem que dar o mesmo conjunto.
    ids2, _ = _varre_tudo(list_fap_benefits_handler, law_firm_id, 17)
    check('benefícios: conjunto independe do tamanho da página', set(ids) == set(ids2),
          f'diferença de {len(set(ids) ^ set(ids2))} registros')
    check('benefícios: ordem é determinística entre execuções', ids == ids2)

    # Contestações (11k linhas): confere só as primeiras páginas, por tempo.
    vistos, offset = [], 0
    for _ in range(4):
        r = list_fap_contestacoes_handler(law_firm_id, limit=100, offset=offset)
        vistos.extend(i['id'] for i in r['itens'])
        offset = r.get('proximo_deslocamento', offset)
    check('contestações: 4 páginas sem repetir (data_transmissao nula/repetida)',
          len(set(vistos)) == len(vistos), f'{len(vistos) - len(set(vistos))} repetidos')


def test_compatibilidade(law_firm_id):
    print('\n4) Compatibilidade com o comportamento anterior')
    sem_offset = list_fap_benefits_handler(law_firm_id, limit=50)
    com_zero = list_fap_benefits_handler(law_firm_id, limit=50, offset=0)
    check('chamada sem deslocamento == deslocamento 0',
          [i['id'] for i in sem_offset['itens']] == [i['id'] for i in com_zero['itens']])
    check('padrão continua devolvendo a 1ª página', sem_offset['deslocamento'] == 0)
    check('filtros seguem funcionando com paginação',
          list_fap_benefits_handler(law_firm_id, limit=5, offset=0,
                                    benefit_type='B91')['retornados'] <= 5)


def test_isolamento(law_firm_id):
    print('\n5) Isolamento por escritório em qualquer página')
    from app.models import Benefit

    outro = 99999  # escritório inexistente
    r = list_fap_benefits_handler(outro, limit=50, offset=0)
    check('escritório sem dados não vê nada', r['total_encontrado'] == 0 and r['itens'] == [])

    r = list_fap_benefits_handler(law_firm_id, limit=50, offset=100)
    ids = [i['id'] for i in r['itens']]
    if ids:
        alheios = Benefit.query.filter(Benefit.id.in_(ids),
                                       Benefit.law_firm_id != law_firm_id).count()
        check('página profunda não vaza dados de outro escritório', alheios == 0)


def main():
    with app.app_context():
        from app.models import LawFirm
        firm = LawFirm.query.order_by(LawFirm.id).first()
        if not firm:
            print('❌ Nenhum escritório no banco.')
            return 2
        print(f'Escritório: {firm.id}')

        test_saneamento()
        test_envelope(firm.id)
        test_varredura(firm.id)
        test_compatibilidade(firm.id)
        test_isolamento(firm.id)

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for f in _falhas:
            print(f'   · {f}')
        return 1
    print('✅ Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
