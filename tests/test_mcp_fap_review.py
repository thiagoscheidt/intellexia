#!/usr/bin/env python3
"""
Teste das tools do Revisor de Petições no MCP.

    uv run python tests/test_mcp_fap_review.py

Cobre:
  1. Revisão feita no Claude pelas tools: revisar_peticao_inicial entrega as
     instruções em partes, conferir_revisao_peticao devolve o rascunho saneado
     e gravar_revisao_peticao cria a petição (Id Wrike) e a revisão 1
  2. Nova revisão do mesmo Id Wrike entra como revisão 2 da mesma petição
  3. Tools de leitura: listar/detalhar/histórico, incluindo reincidência e origem
  4. Isolamento por escritório
  5. Paridade com a tela: a revisão gravada pelo Claude abre nas telas do módulo
  6. Leitura do manual/referências
  7. Auditoria
  8. Estatísticas (mesmos números da tela)
  9. Gate de administrador
  10. Comparação de versões pelo mesmo caminho e recusas das tools
  11. mudar_status_peticao: as regras da tela (aprovar, devolver e reabrir só
      admin; revisão feita no Claude não vai para aprovação por não-admin),
      papel relido do banco, status pelo código ou pelo nome, auditoria
  12. triar_achados_revisao: pertinente / não pertinente em lote, "o resto
      está ok", conclusão da triagem com as regras da tela, recusas que não
      gravam nada pela metade, e a tela continuando com o mesmo código

As regras do serviço (partes, contrato, saneador, origem) estão em
tests/test_fap_review_claude.py. Os dados criados são removidos ao final.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    db,
    FapReviewAuditLog,
    FapReviewDraft,
    FapReviewExecution,
    FapReviewFindingCheck,
    FapReviewIgnoredFinding,
    FapReviewPetition,
    LawFirm,
    User,
)
from mcp_server.tools.petition_reviewer import (
    change_status_handler,
    confer_review_handler,
    review_instructions_handler,
    save_review_handler,
    triage_findings_handler,
)
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
# Id Wrike é numérico (validate_wrike_identifier); valores altos para não
# colidir com petição real da base local.
IDENT = '990000000037'
IDENT_COMPARA = '990000000039'
IDENT_STATUS = '990000000046'
IDENT_TRIAGEM = '990000000048'
IDENTS = (IDENT, IDENT_COMPARA, IDENT_STATUS, IDENT_TRIAGEM)


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _resultado(findings):
    return {
        'theses': [{'thesis': 'Acidente de trajeto', 'benefit_number': '6320957810'}],
        'findings': findings,
        'missing_documents': [
            {'document_type': 'CAT', 'thesis': 'Acidente de trajeto', 'manual_reference': '3.2'},
        ],
        'executive_summary': {
            'total_findings': len(findings), 'critical_findings': 0, 'moderate_findings': 0,
            'formal_findings': 0, 'correction_priority': 'Resumo executivo de teste.',
        },
    }


def _ler_instrucoes(law_firm_id, modo, **kwargs):
    primeira = review_instructions_handler(law_firm_id, modo, **kwargs)
    partes = [primeira]
    for n in range(2, primeira.get('total_partes', 1) + 1):
        partes.append(review_instructions_handler(law_firm_id, modo, parte=n, **kwargs))
    return partes


def test_registro(law_firm_id, user_id):
    print('\n1) Revisão feita no Claude pelas tools')
    partes = _ler_instrucoes(law_firm_id, 'revisao', identificador_documento=IDENT)
    primeira = partes[0]
    check('instruções em partes, todas lidas', primeira.get('total_partes') == len(partes)
          and all('conteudo' in p for p in partes), str(primeira)[:200])
    check('petição nova: sem petição e sem foco', primeira.get('peticao') is None
          and primeira.get('revisao_focada') is False)
    check('última parte manda conferir', 'conferir_revisao_peticao' in partes[-1].get('proximo_passo', ''))

    findings = [
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP',
         'location': 'Item 3', 'correction': 'Incluir fundamento do NTEP', 'manual_reference': '2.1'},
        {'category': 'FORMAL', 'severity': 'FORMAL', 'description': 'Numeração de páginas ausente'},
    ]
    c = confer_review_handler(law_firm_id, user_id, _resultado(findings), 'revisao',
                              identificador_documento=IDENT)
    check('conferência devolve o rascunho e os achados', bool(c.get('rascunho_id'))
          and len(c.get('achados', [])) == 2, str(c)[:200])
    check('nada entra no histórico antes de gravar', FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id, office_document_identifier=IDENT).count() == 0)

    r = save_review_handler(law_firm_id, user_id, c['rascunho_id'], titulo='Petição de teste MCP',
                            nome_arquivo='peticao_teste.pdf', modelo='Claude Sonnet 5')
    check('petição criada pelo Id Wrike', r.get('peticao_criada') is True, str(r)[:200])
    check('revisão numerada como 1', r.get('numero_revisao') == 1, str(r.get('numero_revisao')))
    check('traz o link da tela da revisão',
          f'/fap-review/revision/{r.get("revisao_id")}' in (r.get('link') or ''), str(r.get('link')))

    execution = FapReviewExecution.query.get(r['revisao_id'])
    check('execução concluída, feita no Claude', execution.status == 'completed'
          and execution.review_origin == 'claude')
    check('modelo informado gravado', execution.model_name == 'Claude · Claude Sonnet 5', execution.model_name)
    check('execução ligada à petição', execution.petition_id == r['peticao_id'])

    petition = FapReviewPetition.query.get(r['peticao_id'])
    check('petição fica "em revisão" até a triagem', petition.workflow_status == 'in_review',
          petition.workflow_status)
    check('petição aponta para a última revisão', petition.latest_revision_id == execution.id)
    check('contador de revisões atualizado', petition.revision_count == 1)
    check('data da última revisão preenchida', petition.last_reviewed_at is not None)
    return r


def test_segunda_revisao(law_firm_id, user_id, primeiro):
    print('\n2) Segunda revisão do mesmo Id Wrike')
    partes = _ler_instrucoes(law_firm_id, 'revisao', identificador_documento=IDENT)
    check('instruções reconhecem a petição', (partes[0].get('peticao') or {}).get('peticao_id')
          == primeiro['peticao_id'])
    check('revisão anterior feita no Claude não deixa a nova em modo focado',
          partes[0].get('revisao_focada') is False)
    findings = [
        # o CRÍTICO reincide; o FORMAL foi resolvido; entra um MODERADO novo
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP'},
        {'category': 'CAT-3', 'severity': 'MODERADO', 'description': 'Tese sem caso de referência'},
    ]
    c = confer_review_handler(law_firm_id, user_id, _resultado(findings), 'revisao',
                              peticao_id=primeiro['peticao_id'])
    r = save_review_handler(law_firm_id, user_id, c['rascunho_id'])

    check('reaproveita a petição (não cria outra)', r.get('peticao_criada') is False, str(r)[:200])
    check('mesma petição do primeiro registro', r.get('peticao_id') == primeiro['peticao_id'])
    check('numerada como revisão 2', r.get('numero_revisao') == 2, str(r.get('numero_revisao')))

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
    check('status traduzido para humano', item['status_descricao'] == 'Em revisão',
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
    check('revisão do Claude sem custo nosso', d['custo_usd'] is None, str(d.get('custo_usd')))
    check('detalhe diz a origem', d.get('origem') == 'Feita no Claude', str(d.get('origem')))

    inexistente = get_review_detail_handler(law_firm_id, 999999)
    check('revisão inexistente devolve erro claro', 'erro' in inexistente)

    h = petition_review_history_handler(law_firm_id, identificador=IDENT)
    check('histórico traz as 2 revisões', h['total_revisoes'] == 2, str(h.get('total_revisoes')))
    rev2 = h['revisoes'][1]
    check('detecta achado reincidente',
          any('NTEP' in r for r in rev2['reincidentes']), str(rev2['reincidentes']))
    check('detecta achado resolvido',
          any('Numeração' in r for r in rev2['resolvidos_desde_a_anterior']),
          str(rev2['resolvidos_desde_a_anterior']))
    check('detecta achado novo',
          any('referência' in r for r in rev2['novos']), str(rev2['novos']))
    check('histórico diz a origem', rev2.get('origem') == 'Feita no Claude')

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
    print('\n5) Paridade: a revisão gravada pelo Claude aparece na tela do módulo')
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = user_id
        s['law_firm_id'] = law_firm_id

    r = client.get(f'/fap-review/revision/{primeiro["revisao_id"]}')
    check('tela de resultado da revisão abre', r.status_code == 200, str(r.status_code))
    body = r.get_data(as_text=True)
    check('achado do Claude aparece na tela', 'NTEP' in body)
    check('tela mostra o selo "Feita no Claude"', 'Feita no Claude' in body)

    r = client.get(f'/fap-review/petitions/{primeiro["peticao_id"]}')
    check('tela da petição abre', r.status_code == 200, str(r.status_code))
    check('as duas revisões aparecem na tela da petição',
          r.get_data(as_text=True).count('Revisão') >= 2)

    r = client.get('/fap-review/')
    check('índice do Revisor lista a petição criada pelo MCP',
          r.status_code == 200 and IDENT in r.get_data(as_text=True))

    r = client.get(f'/fap-review/revision/{primeiro["revisao_id"]}/document/main')
    check('revisão sem arquivo: rota do documento não quebra (sem 500)',
          r.status_code in (302, 404), str(r.status_code))



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
    check('registrou a revisão gravada pelo Claude',
          any('Claude' in (i.get('descricao') or '') for i in r['itens']), 'nenhum evento do Claude')
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


def test_comparacao_e_recusas(law_firm_id, user_id):
    print('\n10) Comparação de versões e recusas')
    partes = _ler_instrucoes(law_firm_id, 'comparacao', identificador_documento=IDENT_COMPARA)
    check('comparação entrega instruções comparativas',
          'comparative_changes' in ''.join(p['conteudo'] for p in partes))
    resultado = {
        'comparative_changes': [{'original_excerpt': 'texto antigo', 'corrected_excerpt': 'texto novo',
                                 'correction_reason': 'ajuste', 'pattern_in_manual': True,
                                 'is_new_pattern': False}],
        'findings': [],
        'executive_summary': {},
    }
    c = confer_review_handler(law_firm_id, user_id, resultado, 'comparacao',
                              identificador_documento=IDENT_COMPARA)
    check('conferência da comparação mostra as mudanças', len(c.get('mudancas_comparativas', [])) == 1,
          str(c)[:200])
    r = save_review_handler(law_firm_id, user_id, c['rascunho_id'], titulo='Comparação MCP')
    execution = FapReviewExecution.query.get(r['revisao_id'])
    check('comparação gravada como análise comparativa', execution.comparative_analysis is True)

    check('sem usuário na conexão: conferir recusa',
          'erro' in confer_review_handler(law_firm_id, None, resultado, 'comparacao'))
    check('sem usuário na conexão: gravar recusa',
          'erro' in save_review_handler(law_firm_id, None, c['rascunho_id']))
    check('parte inexistente das instruções: erro',
          'erro' in review_instructions_handler(law_firm_id, 'revisao', parte=999))


def test_mudar_status(law_firm_id, primeiro):
    print('\n11) mudar_status_peticao')
    nao_admin = User.query.filter(User.law_firm_id == law_firm_id, User.role != 'admin',
                                  User.is_active.is_(True)).order_by(User.id).first()
    admin = User.query.filter(User.law_firm_id == law_firm_id, User.role == 'admin',
                              User.is_active.is_(True)).order_by(User.id).first()
    if not nao_admin or not admin:
        check('banco local tem um admin e um não-admin', False)
        return

    # Petição com revisão do IntellexIA (feita pela tela).
    petition = FapReviewPetition(law_firm_id=law_firm_id, created_by_id=admin.id, title='Status MCP',
                                 office_document_identifier=IDENT_STATUS, workflow_status='in_review')
    db.session.add(petition)
    db.session.flush()
    execution = FapReviewExecution(
        law_firm_id=law_firm_id, user_id=admin.id, petition_id=petition.id, execution_type='revision',
        status='completed', revision_number=1, law_firm_document_identifier=IDENT_STATUS,
        result_json='{"findings": []}')
    db.session.add(execution)
    db.session.flush()
    petition.latest_revision_id = execution.id
    petition.revision_count = 1
    db.session.commit()

    r = change_status_handler(law_firm_id, nao_admin.id, 'Aguardando ajustes', identificador=IDENT_STATUS)
    check('não-admin muda para outro status, pelo nome', r.get('status') == 'awaiting_adjustments'
          and r.get('status_anterior') == 'in_review', str(r)[:200])
    check('auditoria registra a mudança via Claude', FapReviewAuditLog.query.filter_by(
        law_firm_id=law_firm_id, entity_type='petition', entity_id=petition.id,
        action='petition_status_updated').filter(
        FapReviewAuditLog.change_description.like('%Claude%')).count() == 1)
    r = change_status_handler(law_firm_id, nao_admin.id, 'awaiting_adjustments', peticao_id=petition.id)
    check('mesmo status: avisa que não mudou', r.get('sem_mudanca') is True, str(r)[:200])
    r = change_status_handler(law_firm_id, nao_admin.id, 'awaiting_approval', peticao_id=petition.id)
    check('não-admin manda para aprovação com revisão do IntellexIA', r.get('status') == 'awaiting_approval',
          str(r)[:200])
    r = change_status_handler(law_firm_id, nao_admin.id, 'ready_for_filing', peticao_id=petition.id)
    check('não-admin não aprova', 'erro' in r and 'administradores' in r['erro'], str(r)[:200])
    r = change_status_handler(law_firm_id, nao_admin.id, 'in_review', peticao_id=petition.id)
    check('não-admin não devolve petição em aprovação', 'erro' in r, str(r)[:200])
    r = change_status_handler(law_firm_id, admin.id, 'ready_for_filing', peticao_id=petition.id)
    check('admin aprova', r.get('status') == 'ready_for_filing', str(r)[:200])
    r = change_status_handler(law_firm_id, admin.id, 'in_review', peticao_id=petition.id)
    check('admin reabre', r.get('status') == 'in_review', str(r)[:200])

    # A petição do teste 1 tem a última revisão feita no Claude.
    r = change_status_handler(law_firm_id, nao_admin.id, 'awaiting_approval', peticao_id=primeiro['peticao_id'])
    check('não-admin não manda para aprovação com a última revisão feita no Claude',
          'erro' in r and 'Claude' in r['erro'], str(r)[:200])
    r = change_status_handler(law_firm_id, admin.id, 'awaiting_approval', peticao_id=primeiro['peticao_id'])
    check('admin pode, como na tela', r.get('status') == 'awaiting_approval', str(r)[:200])
    change_status_handler(law_firm_id, admin.id, 'in_review', peticao_id=primeiro['peticao_id'])

    r = change_status_handler(law_firm_id, admin.id, 'pronta', peticao_id=petition.id)
    check('status inválido: erro com a lista dos válidos', 'erro' in r and 'Aguardando aprovação' in r['erro'],
          str(r)[:200])
    check('sem petição: erro', 'erro' in change_status_handler(law_firm_id, admin.id, 'in_review'))
    check('petição de outro escritório: não encontrada',
          'erro' in change_status_handler(99999, admin.id, 'archived', peticao_id=petition.id))
    check('usuário inexistente ou de outro escritório: recusado',
          'erro' in change_status_handler(law_firm_id, 999999, 'archived', peticao_id=petition.id))
    db.session.refresh(petition)
    check('nada mudou nas recusas', petition.workflow_status == 'in_review', petition.workflow_status)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = nao_admin.id
        sess['law_firm_id'] = law_firm_id
    resp = client.post(f'/fap-review/petitions/{primeiro["peticao_id"]}/status',
                       json={'workflow_status': 'awaiting_approval'})
    check('a tela continua com a mesma regra (mesmo código)', resp.status_code == 403
          and 'Claude' in (resp.get_json() or {}).get('error', ''), str(resp.status_code))
    resp = client.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'xyz'})
    check('a tela recusa status inválido', resp.status_code == 400, str(resp.status_code))


def test_triagem(law_firm_id, primeiro):
    print('\n12) triar_achados_revisao')
    from app.services import fap_review_service as svc
    user = User.query.filter(User.law_firm_id == law_firm_id, User.is_active.is_(True)).order_by(User.id).first()
    check('gravar manda perguntar a pertinência dos achados',
          'triar_achados_revisao' in (primeiro.get('proximo_passo') or ''), primeiro.get('proximo_passo', '')[:200])

    findings = [
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP', 'location': 'Item 3'},
        {'category': 'CAT-2', 'severity': 'MODERADO', 'description': 'Pedido duplicado', 'location': 'Pedidos'},
        {'category': 'FORMAL', 'severity': 'FORMAL', 'description': 'Numeração de páginas ausente'},
    ]
    petition = FapReviewPetition(law_firm_id=law_firm_id, created_by_id=user.id, title='Triagem MCP',
                                 office_document_identifier=IDENT_TRIAGEM, workflow_status='new')
    db.session.add(petition)
    db.session.flush()
    execution = FapReviewExecution(
        law_firm_id=law_firm_id, user_id=user.id, petition_id=petition.id, execution_type='revision',
        status='completed', revision_number=1, law_firm_document_identifier=IDENT_TRIAGEM,
        review_origin='claude', result_json=json.dumps({'findings': findings}))
    db.session.add(execution)
    db.session.flush()
    petition.latest_revision_id = execution.id
    petition.revision_count = 1
    db.session.commit()

    def marcados():
        return ({c.finding_index for c in FapReviewFindingCheck.query.filter_by(execution_id=execution.id)},
                {i.finding_fingerprint for i in FapReviewIgnoredFinding.query.filter_by(
                    law_firm_id=law_firm_id, law_firm_document_identifier=IDENT_TRIAGEM)})

    # Recusas antes de gravar: nada pode ficar pela metade.
    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, pertinentes=[1], nao_pertinentes=[9])
    check('número inexistente: erro com o total de achados', 'erro' in r and '3' in r['erro'], str(r)[:200])
    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, pertinentes=[2], nao_pertinentes=[2])
    check('mesmo achado nas duas listas: erro', 'erro' in r, str(r)[:200])
    check('nada gravado nas recusas', marcados() == (set(), set()), str(marcados()))
    check('sem decisão nenhuma: erro', 'erro' in triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id))
    check('revisão de outro escritório: não encontrada', 'erro' in triage_findings_handler(
        99999, user.id, revisao_id=execution.id, pertinentes=[1]))

    r = triage_findings_handler(law_firm_id, user.id, identificador=IDENT_TRIAGEM, pertinentes=[1],
                                nao_pertinentes=['2'])
    check('pelo Id Wrike acha a última revisão', r.get('revisao_id') == execution.id, str(r)[:200])
    check('1 pertinente, 2 não pertinente, 3 pendente',
          r.get('pertinentes') == [1] and r.get('nao_pertinentes') == [2] and r.get('pendentes') == [3]
          and r.get('triagem_completa') is False, str(r)[:300])
    checks, ignorados = marcados()
    check('pertinente vira "revisado" da tela', checks == {1}, str(checks))
    check('não pertinente guarda a impressão digital para as próximas revisões',
          ignorados == {svc.build_finding_fingerprint(findings[1])}, str(ignorados))
    db.session.refresh(petition)
    check('triar põe a petição em revisão, como na tela', petition.workflow_status == 'in_review',
          petition.workflow_status)
    check('auditoria do não pertinente via Claude', FapReviewAuditLog.query.filter_by(
        entity_type='execution', entity_id=execution.id, action='revision_finding_dismissed').filter(
        FapReviewAuditLog.change_description.like('%Claude%')).count() == 1)

    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, concluir='nova_versao')
    check('concluir com achado pendente: erro com os pendentes', 'erro' in r and '3' in r['erro'], str(r)[:200])

    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, demais_pertinentes=True)
    check('"o resto está ok" marca só os pendentes', r.get('pertinentes') == [1, 3]
          and r.get('nao_pertinentes') == [2] and r.get('triagem_completa') is True, str(r)[:300])

    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, pertinentes=[2])
    checks, ignorados = marcados()
    check('voltar a ser pertinente desfaz o não pertinente', checks == {1, 2, 3} and not ignorados
          and r.get('nao_pertinentes') == [], str(r)[:300])
    triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, nao_pertinentes=[2])
    checks, ignorados = marcados()
    check('não pertinente tira o "revisado"', checks == {1, 3} and len(ignorados) == 1, str(checks))

    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, concluir='versao_final')
    check('revisão feita no Claude não conclui como versão final', 'erro' in r and 'Claude' in r['erro'],
          str(r)[:200])
    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, concluir='qualquer')
    check('desfecho inválido: erro com os válidos', 'erro' in r and 'nova_versao' in r['erro'], str(r)[:200])
    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, concluir='nova_versao')
    db.session.refresh(petition)
    check('concluir como nova versão: aguardando ajustes', r.get('status') == 'awaiting_adjustments'
          and petition.workflow_status == 'awaiting_adjustments', str(r)[:200])
    check('auditoria da conclusão via Claude', FapReviewAuditLog.query.filter_by(
        entity_type='petition', entity_id=petition.id, action='revision_triage_completed').filter(
        FapReviewAuditLog.change_description.like('%Claude%')).count() == 1)

    # A tela continua com o mesmo código: rotas respondem e recusam como antes.
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['law_firm_id'] = law_firm_id
    resp = client.post(f'/fap-review/revision/{execution.id}/findings/1/check', json={'checked': False})
    check('tela: desmarcar revisado', resp.status_code == 200 and marcados()[0] == {3}, str(resp.status_code))
    resp = client.post(f'/fap-review/revision/{execution.id}/findings/2/dismiss-feedback', json={'dismissed': False})
    check('tela: desfazer não pertinente', resp.status_code == 200 and not marcados()[1], str(resp.status_code))
    resp = client.post(f'/fap-review/revision/{execution.id}/findings/7/check', json={'checked': True})
    check('tela: achado inexistente 404', resp.status_code == 404, str(resp.status_code))
    resp = client.post(f'/fap-review/revision/{execution.id}/complete-triage', json={'outcome': 'new_version'})
    check('tela: concluir com pendentes 400', resp.status_code == 400, str(resp.status_code))

    # Revisão substituída por uma mais nova: triagem encerrada nos dois canais.
    nova = FapReviewExecution(
        law_firm_id=law_firm_id, user_id=user.id, petition_id=petition.id, execution_type='revision',
        status='completed', revision_number=2, law_firm_document_identifier=IDENT_TRIAGEM,
        result_json=json.dumps({'findings': findings[:1]}))
    db.session.add(nova)
    db.session.flush()
    petition.latest_revision_id = nova.id
    db.session.commit()
    r = triage_findings_handler(law_firm_id, user.id, revisao_id=execution.id, pertinentes=[1])
    check('revisão substituída: erro', 'erro' in r and 'substituída' in r['erro'], str(r)[:200])
    resp = client.post(f'/fap-review/revision/{execution.id}/findings/1/check', json={'checked': True})
    check('tela: revisão substituída 409', resp.status_code == 409, str(resp.status_code))
    r = triage_findings_handler(law_firm_id, user.id, identificador=IDENT_TRIAGEM, pertinentes=[1])
    check('pelo Id Wrike vai para a revisão atual', r.get('revisao_id') == nova.id
          and r.get('triagem_completa') is True, str(r)[:200])
    check('usuário de outro escritório: recusado', 'erro' in triage_findings_handler(
        law_firm_id, 999999, revisao_id=nova.id, pertinentes=[1]))


def _limpar(law_firm_id):
    petitions = FapReviewPetition.query.filter(
        FapReviewPetition.law_firm_id == law_firm_id,
        FapReviewPetition.office_document_identifier.in_(IDENTS)).all()
    FapReviewDraft.query.filter(FapReviewDraft.law_firm_id == law_firm_id,
                                FapReviewDraft.identifier.in_(IDENTS)).delete(synchronize_session=False)
    FapReviewIgnoredFinding.query.filter(
        FapReviewIgnoredFinding.law_firm_id == law_firm_id,
        FapReviewIgnoredFinding.law_firm_document_identifier.in_(IDENTS)).delete(synchronize_session=False)
    for p in petitions:
        p.latest_revision_id = None
        db.session.flush()
        FapReviewDraft.query.filter_by(petition_id=p.id).delete(synchronize_session=False)
        for e in FapReviewExecution.query.filter_by(petition_id=p.id).all():
            FapReviewDraft.query.filter_by(saved_execution_id=e.id).delete(synchronize_session=False)
            FapReviewFindingCheck.query.filter_by(execution_id=e.id).delete(synchronize_session=False)
            FapReviewAuditLog.query.filter_by(entity_type='execution', entity_id=e.id).delete()
            db.session.delete(e)
        db.session.flush()
        FapReviewAuditLog.query.filter_by(entity_type='petition', entity_id=p.id).delete()
        db.session.delete(p)
    db.session.commit()


def main():
    with app.app_context():
        firm = LawFirm.query.order_by(LawFirm.id).first()
        user = User.query.filter(User.law_firm_id == firm.id, User.email.isnot(None)).first()
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
            test_comparacao_e_recusas(firm.id, user.id)
            test_mudar_status(firm.id, primeiro)
            test_triagem(firm.id, primeiro)
        finally:
            db.session.rollback()
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
