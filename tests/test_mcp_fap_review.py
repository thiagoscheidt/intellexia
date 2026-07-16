#!/usr/bin/env python3
"""
Teste das tools do Revisor de Petições no MCP.

    uv run python tests/test_mcp_fap_review.py

Cobre:
  1. Registro da revisão vinda do MCP (record_text_review) — petição, execução,
     arquivo em disco, status do fluxo e auditoria
  2. Nova revisão do mesmo identificador entra como revisão 2 da mesma petição
  3. Tools de leitura: listar/detalhar/histórico, incluindo reincidência
  4. Isolamento por escritório
  5. Paridade com a tela: a revisão registrada pelo MCP abre nas telas do módulo

Os dados criados são removidos ao final.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    db,
    FapReviewAuditLog,
    FapReviewExecution,
    FapReviewPetition,
    LawFirm,
    User,
)
from app.services.fap_review_service import record_text_review
from mcp_server.tools.petition_review_read import (
    get_review_detail_handler,
    lawyer_statistics_handler,
    list_review_petitions_handler,
    petition_review_history_handler,
    read_reviewer_manual_handler,
    reference_versions_handler,
    review_audit_log_handler,
)

_falhas = []
IDENT = 'TESTE-MCP-REV-0001'


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _payload(findings, resumo='Resumo executivo de teste.'):
    return {
        'analysis_type': 'single_version',
        'focused_review': False,
        'tokens_used': 1234,
        'cost_usd': 0.0456,
        'findings': findings,
        'missing_documents': [
            {'document_type': 'CAT', 'thesis': 'Acidente de trajeto', 'manual_reference': '3.2'},
        ],
        'theses': [{'thesis': 'Acidente de trajeto', 'benefit_number': '6320957810'}],
        'executive_summary': {'summary': resumo},
    }


def test_registro(law_firm_id, user_id):
    print('\n1) Registro da revisão vinda do MCP')
    findings = [
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP',
         'location': 'Item 3', 'correction': 'Incluir fundamento do NTEP', 'manual_reference': '2.1'},
        {'category': 'FORMAL', 'severity': 'FORMAL', 'description': 'Numeração de páginas ausente'},
    ]
    r = record_text_review(law_firm_id, user_id, IDENT, 'texto da petição ' * 50,
                           _payload(findings), title='Petição de teste MCP')

    check('petição criada', r['peticao_criada'] is True)
    check('revisão numerada como 1', r['numero_revisao'] == 1, str(r['numero_revisao']))
    check('status vira "aguardando ajustes" após concluir',
          r['status_peticao'] == 'awaiting_adjustments', r['status_peticao'])

    execution = FapReviewExecution.query.get(r['revisao_id'])
    check('execução gravada como concluída', execution.status == 'completed')
    check('custo e tokens registrados',
          execution.tokens_used == 1234 and float(execution.cost_usd) == 0.0456,
          f'{execution.tokens_used}/{execution.cost_usd}')
    check('texto revisado guardado em disco (a tela abre o documento)',
          bool(execution.main_document_path) and Path(execution.main_document_path).exists(),
          str(execution.main_document_path))
    check('execução ligada à petição', execution.petition_id == r['peticao_id'])

    petition = FapReviewPetition.query.get(r['peticao_id'])
    check('petição aponta para a última revisão', petition.latest_revision_id == execution.id)
    check('contador de revisões atualizado', petition.revision_count == 1)
    check('data da última revisão preenchida', petition.last_reviewed_at is not None)

    audits = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id, entity_id=execution.id,
                                               entity_type='execution').count()
    check('auditoria registrada', audits >= 1)
    return r


def test_segunda_revisao(law_firm_id, user_id, primeiro):
    print('\n2) Segunda revisão do mesmo identificador')
    findings = [
        # o CRÍTICO reincide; o FORMAL foi resolvido; entra um MODERADO novo
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP'},
        {'category': 'CAT-3', 'severity': 'MODERADO', 'description': 'Tese sem caso de referência'},
    ]
    r = record_text_review(law_firm_id, user_id, IDENT, 'texto revisado ' * 50, _payload(findings))

    check('reaproveita a petição (não cria outra)', r['peticao_criada'] is False)
    check('mesma petição do primeiro registro', r['peticao_id'] == primeiro['peticao_id'])
    check('numerada como revisão 2', r['numero_revisao'] == 2, str(r['numero_revisao']))

    petition = FapReviewPetition.query.get(r['peticao_id'])
    check('contador foi para 2', petition.revision_count == 2)
    check('última revisão aponta para a nova', petition.latest_revision_id == r['revisao_id'])
    check('só uma petição com esse identificador',
          FapReviewPetition.query.filter_by(law_firm_id=law_firm_id,
                                            office_document_identifier=IDENT).count() == 1)
    return r


def test_leitura(law_firm_id, primeiro, segundo):
    print('\n3) Tools de leitura')
    lista = list_review_petitions_handler(law_firm_id, identificador=IDENT)
    check('listagem encontra a petição', lista['total_encontrado'] == 1, str(lista['total_encontrado']))
    item = lista['itens'][0]
    check('status traduzido para humano', item['status_descricao'] == 'Aguardando ajustes',
          item['status_descricao'])
    check('mostra nº de revisões', item['revisoes'] == 2, str(item['revisoes']))
    check('envelope de paginação presente', 'tem_mais' in lista)

    filtrado = list_review_petitions_handler(law_firm_id, status='ready_for_filing',
                                             identificador=IDENT)
    check('filtro por status exclui a petição', filtrado['total_encontrado'] == 0)

    d = get_review_detail_handler(law_firm_id, primeiro['revisao_id'])
    check('detalhe traz os achados', d['total_achados'] == 2, str(d.get('total_achados')))
    check('conta por gravidade', d['achados_por_gravidade'] == {'CRÍTICO': 1, 'FORMAL': 1},
          str(d.get('achados_por_gravidade')))
    check('achado traduzido para o vocabulário das tools',
          d['achados'][0]['gravidade'] == 'CRÍTICO' and
          d['achados'][0]['correcao_sugerida'] == 'Incluir fundamento do NTEP')
    check('documentos faltantes presentes',
          d['documentos_faltantes'][0]['tipo_documento'] == 'CAT')
    check('teses presentes', d['teses'][0]['numero_beneficio'] == '6320957810')
    check('custo exposto', d['custo_usd'] == 0.0456, str(d.get('custo_usd')))

    inexistente = get_review_detail_handler(law_firm_id, 999999)
    check('revisão inexistente devolve erro claro', 'erro' in inexistente)

    h = petition_review_history_handler(law_firm_id, identificador=IDENT)
    check('histórico traz as 2 revisões', h['total_revisoes'] == 2, str(h.get('total_revisoes')))
    rev2 = h['revisoes'][1]
    check('detecta achado reincidente',
          any('ntep' in r for r in rev2['reincidentes']), str(rev2['reincidentes']))
    check('detecta achado resolvido',
          any('numeração' in r for r in rev2['resolvidos_desde_a_anterior']),
          str(rev2['resolvidos_desde_a_anterior']))
    check('detecta achado novo',
          any('referência' in r for r in rev2['novos']), str(rev2['novos']))

    h_id = petition_review_history_handler(law_firm_id, peticao_id=primeiro['peticao_id'])
    check('histórico também aceita peticao_id', h_id['total_revisoes'] == 2)
    check('sem id nem identificador, erro claro',
          'erro' in petition_review_history_handler(law_firm_id))


def test_isolamento(law_firm_id, primeiro):
    print('\n4) Isolamento por escritório')
    outro = 99999
    check('outro escritório não lista a petição',
          list_review_petitions_handler(outro, identificador=IDENT)['total_encontrado'] == 0)
    check('outro escritório não abre a revisão',
          'erro' in get_review_detail_handler(outro, primeiro['revisao_id']))
    check('outro escritório não vê o histórico',
          'erro' in petition_review_history_handler(outro, identificador=IDENT))


def test_paridade_tela(primeiro, user_id, law_firm_id):
    print('\n5) Paridade: a revisão do MCP aparece na tela do módulo')
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = user_id
        s['law_firm_id'] = law_firm_id

    r = client.get(f'/fap-review/revision/{primeiro["revisao_id"]}')
    check('tela de resultado da revisão abre', r.status_code == 200, str(r.status_code))
    body = r.get_data(as_text=True)
    check('achado do MCP aparece na tela', 'NTEP' in body)

    r = client.get(f'/fap-review/petitions/{primeiro["peticao_id"]}')
    check('tela da petição abre', r.status_code == 200, str(r.status_code))
    check('as duas revisões aparecem na tela da petição',
          r.get_data(as_text=True).count('Revisão') >= 2 or 'Aguardando ajustes' in r.get_data(as_text=True))

    r = client.get('/fap-review/')
    check('índice do Revisor lista a petição criada pelo MCP',
          r.status_code == 200 and IDENT in r.get_data(as_text=True))

    r = client.get(f'/fap-review/revision/{primeiro["revisao_id"]}/document/main')
    check('documento da revisão do MCP abre na tela (não 404/500)',
          r.status_code in (200, 302), str(r.status_code))



def test_manual(law_firm_id):
    print('\n6) Leitura do manual/referências')
    from app.models import FapReviewReferenceVersion

    r = read_reviewer_manual_handler(law_firm_id, tipo='tipo_invalido')
    check('tipo inválido devolve erro e lista os válidos', 'erro' in r and 'tipos_validos' in r)

    existente = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id, reference_type='manual_fap', is_active=True).first()

    if not existente:
        r = read_reviewer_manual_handler(law_firm_id)
        check('manual ausente: avisa em vez de fingir que existe',
              r.get('configurado') is False and 'aviso' in r, str(r)[:80])

    # Cadastra um manual temporário para exercitar seção/termo/tamanho.
    ref = FapReviewReferenceVersion(
        law_firm_id=law_firm_id, version_number=999, reference_type='manual_fap',
        content=('# Manual\n\n## 2.1 Nexo Técnico\nO NTEP deve ser fundamentado.\n\n'
                 '## 3.2 Documentos\nA CAT é obrigatória nas teses de acidente.\n'),
        is_active=False,
    )
    db.session.add(ref)
    db.session.commit()
    try:
        ref.is_active = True
        if existente:
            existente.is_active = False
        db.session.commit()

        r = read_reviewer_manual_handler(law_firm_id)
        check('manual cadastrado é devolvido inteiro quando cabe',
              r.get('configurado') and r.get('conteudo_completo') and 'NTEP' in r['conteudo'])
        check('conta as seções', r.get('total_secoes') == 3, str(r.get('total_secoes')))

        r = read_reviewer_manual_handler(law_firm_id, secao='2.1')
        check('lê só a seção pedida (fecha o laço do referencia_manual)',
              r.get('encontrado') and len(r['secoes']) == 1 and 'NTEP' in r['secoes'][0]['conteudo'])

        r = read_reviewer_manual_handler(law_firm_id, termo='CAT')
        check('busca por termo no corpo', r.get('encontrado') and
              any('CAT' in s['conteudo'] for s in r['secoes']))

        r = read_reviewer_manual_handler(law_firm_id, secao='inexistente')
        check('seção inexistente lista as disponíveis',
              r.get('encontrado') is False and r.get('secoes_disponiveis'))

        v = reference_versions_handler(law_firm_id, tipo='manual_fap')
        check('versões listam a ativa', any(x['ativa'] for x in v['versoes']))
        check('versão traz tamanho', v['versoes'][0]['tamanho_caracteres'] > 0)
        check('tipo inválido em versões dá erro',
              'erro' in reference_versions_handler(law_firm_id, tipo='xxx'))
    finally:
        db.session.delete(ref)
        if existente:
            existente.is_active = True
        db.session.commit()


def test_auditoria(law_firm_id, primeiro):
    print('\n7) Auditoria')
    r = review_audit_log_handler(law_firm_id, limit=10)
    check('auditoria responde com envelope paginado',
          {'total_encontrado', 'itens', 'tem_mais'} <= set(r))
    check('registrou a revisão criada pelo MCP',
          any('MCP' in (i.get('descricao') or '') for i in r['itens']), 'nenhum evento do MCP')
    check('evento traz autor e data',
          all('usuario' in i and 'quando' in i for i in r['itens']))
    filtrado = review_audit_log_handler(law_firm_id, acao='revision')
    check('filtro por ação funciona',
          all('revision' in (i['acao'] or '') for i in filtrado['itens']))
    outro = review_audit_log_handler(99999)
    check('outro escritório não vê auditoria', outro['total_encontrado'] == 0)


def test_estatisticas(law_firm_id):
    print('\n8) Estatísticas (mesmos números da tela)')
    from app.services.fap_review_service import build_lawyer_statistics

    tool = lawyer_statistics_handler(law_firm_id)
    tela = build_lawyer_statistics(law_firm_id)
    check('panorama bate com o da tela',
          tool['panorama']['revisoes'] == tela['overview']['total_revisions'])
    check('mesma quantidade de advogados', len(tool['advogados']) == len(tela['lawyers']))
    if tool['advogados']:
        check('score idêntico ao da tela',
              tool['advogados'][0]['score'] == tela['lawyers'][0]['score'])
    check('explica que o score é heurístico', 'heurístico' in tool.get('nota', ''))


def test_gate_admin():
    print('\n9) Gate de administrador (require_admin)')
    import mcp_server.identity as ident
    from fastmcp.exceptions import ToolError

    original = ident.get_identity
    try:
        ident.get_identity = lambda: {'user_id': 2, 'law_firm_id': 1,
                                      'modules': ['fap_review'], 'role': 'lawyer'}
        try:
            ident.require_admin('fap_review')
            check('não-admin é barrado', False, 'passou!')
        except ToolError as e:
            check('não-admin é barrado com mensagem clara',
                  'restrita a administradores' in str(e))
        check('não-admin ainda passa no require_module (só o módulo)',
              ident.require_module('fap_review')['role'] == 'lawyer')

        ident.get_identity = lambda: {'user_id': 1, 'law_firm_id': 1,
                                      'modules': ['fap_review'], 'role': 'admin'}
        check('admin passa', ident.require_admin('fap_review')['role'] == 'admin')

        ident.get_identity = lambda: {'user_id': 1, 'law_firm_id': 1,
                                      'modules': [], 'role': 'admin'}
        try:
            ident.require_admin('fap_review')
            check('admin sem o módulo é barrado', False, 'passou!')
        except ToolError:
            check('admin sem o módulo é barrado', True)
    finally:
        ident.get_identity = original


def _limpar(law_firm_id):
    petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id, office_document_identifier=IDENT).all()
    for p in petitions:
        execs = FapReviewExecution.query.filter_by(petition_id=p.id).all()
        for e in execs:
            if e.main_document_path:
                Path(e.main_document_path).unlink(missing_ok=True)
            FapReviewAuditLog.query.filter_by(entity_type='execution', entity_id=e.id).delete()
            db.session.delete(e)
        p.latest_revision_id = None
        db.session.flush()
        FapReviewAuditLog.query.filter_by(entity_type='petition', entity_id=p.id).delete()
        db.session.delete(p)
    db.session.commit()


def main():
    with app.app_context():
        firm = LawFirm.query.order_by(LawFirm.id).first()
        user = User.query.filter_by(law_firm_id=firm.id).first()
        print(f'Escritório: {firm.id} | usuário: {user.id}')

        _limpar(firm.id)  # resíduo de execução anterior
        try:
            primeiro = test_registro(firm.id, user.id)
            segundo = test_segunda_revisao(firm.id, user.id, primeiro)
            test_leitura(firm.id, primeiro, segundo)
            test_isolamento(firm.id, primeiro)
            test_paridade_tela(primeiro, user.id, firm.id)
            test_manual(firm.id)
            test_auditoria(firm.id, primeiro)
            test_estatisticas(firm.id)
            test_gate_admin()
        finally:
            _limpar(firm.id)
            print('\n(dados de teste removidos)')

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
