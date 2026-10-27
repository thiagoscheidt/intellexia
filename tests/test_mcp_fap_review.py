#!/usr/bin/env python3
"""
Teste das tools do Revisor de Petições no MCP.

    uv run python tests/test_mcp_fap_review.py

Cobre:
  1. Revisão pedida pelo Claude entra como a da tela (RPI-37): a tool cria a
     petição e a execução "processando", responde na hora e o agente roda em
     segundo plano pelo mesmo código da tela — texto extraído do arquivo,
     pontos de atenção da revisão anterior, modelo gravado
  2. Nova revisão do mesmo Id Wrike entra como revisão 2 da mesma petição
  3. Tools de leitura: listar/detalhar/histórico, incluindo reincidência
  4. Isolamento por escritório
  5. Paridade com a tela: a revisão registrada pelo MCP abre nas telas do módulo
  ...
  10. Recusas: sem Id Wrike, Id não numérico, petição bloqueada, revisão já
      em andamento (não paga duas vezes)
  11. Andamento pelo detalhar_revisao e revisão presa vira falha
  12. E-mail a quem pediu: pronta e não concluída
  13. Comparação de versões pelo mesmo caminho
  14. Sem texto: link de envio com o curl pronto; com link do Drive: revisão
      pelo arquivo baixado; os dois juntos: erro

A IA é trocada por um agente falso e o e-mail é interceptado. Os dados criados
são removidos ao final.
"""

import os
import sys
import threading
from datetime import datetime, timedelta
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
import app.blueprints.fap_review as fap_review_bp
from app.agents.fap_review.reviewer_agent import PetitionReviewResult
from app.services import email_service
from mcp_server.tools.petition_reviewer import (
    compare_petition_versions_handler,
    review_petition_handler,
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
IDENT_BLOQUEADA = '990000000038'
IDENT_COMPARA = '990000000039'
IDENTS = (IDENT, IDENT_BLOQUEADA, IDENT_COMPARA)
TEXTO = 'Excelentíssimo Juiz, texto da petição de teste. ' * 20


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _payload(findings, resumo='Resumo executivo de teste.'):
    return {
        'focused_review': False,
        'tokens_used': 1234,
        'cost_usd': 0.0456,
        'findings': findings,
        'missing_documents': [
            {'document_type': 'CAT', 'thesis': 'Acidente de trajeto', 'manual_reference': '3.2'},
        ],
        'theses': [{'thesis': 'Acidente de trajeto', 'benefit_number': '6320957810'}],
        'executive_summary': {
            'total_findings': len(findings), 'critical_findings': 0, 'moderate_findings': 0,
            'formal_findings': 0, 'correction_priority': resumo,
        },
    }


class _AgenteFalso:
    """No lugar do FapPetitionReviewerAgent: devolve o próximo resultado da fila."""
    proximos: list = []
    recebidos: list = []

    def __init__(self, **kwargs):
        pass

    def load_reference_documents(self, **kwargs):
        pass

    async def _responder(self, analysis_type, kwargs):
        _AgenteFalso.recebidos.append(kwargs)
        proximo = _AgenteFalso.proximos.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return PetitionReviewResult(analysis_type=analysis_type, **proximo)

    async def review_petition_single_version(self, **kwargs):
        return await self._responder('single_version', kwargs)

    async def review_petition_comparative(self, **kwargs):
        return await self._responder('comparative', kwargs)


_emails: list = []


def _email_falso(to, subject, html, text=None, **kwargs):
    _emails.append({'to': to, 'subject': subject, 'html': html})
    return True


def _esperar(revisao_id: int) -> FapReviewExecution:
    """Espera a thread da revisão terminar e relê a execução do banco."""
    for t in threading.enumerate():
        if t.name == f'fap-review-{revisao_id}':
            t.join(timeout=60)
            if t.is_alive():
                print(f'  (thread da revisão {revisao_id} ainda rodando após 60 s)')
    # Encerra a transação do teste: no MySQL (REPEATABLE READ) o expire_all
    # relê o mesmo snapshot e não enxerga o commit feito pela thread.
    db.session.rollback()
    return FapReviewExecution.query.get(revisao_id)


def test_registro(law_firm_id, user_id):
    print('\n1) Revisão pedida pelo Claude entra como a da tela')
    findings = [
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP',
         'location': 'Item 3', 'correction': 'Incluir fundamento do NTEP', 'manual_reference': '2.1'},
        {'category': 'FORMAL', 'severity': 'FORMAL', 'description': 'Numeração de páginas ausente'},
    ]
    _AgenteFalso.proximos = [_payload(findings)]
    _AgenteFalso.recebidos = []
    _emails.clear()

    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id,
                                identificador_documento=IDENT, titulo='Petição de teste MCP')

    check('responde na hora dizendo que está processando',
          r.get('status') == 'processando', str(r)[:200])
    check('petição criada', r.get('peticao_criada') is True)
    check('revisão numerada como 1', r.get('numero_revisao') == 1, str(r.get('numero_revisao')))
    check('traz o link da tela da revisão',
          f'/fap-review/revision/{r.get("revisao_id")}' in (r.get('link') or ''), str(r.get('link')))
    msg = r.get('mensagem_para_usuario') or ''
    check('mensagem pronta para o usuário traz o link e o que perguntar depois',
          (r.get('link') or '-') in msg and f'Como está a revisão 1 da petição {IDENT}?' in msg, msg[:200])

    execution = _esperar(r['revisao_id'])
    check('execução concluída pela thread da tela', execution.status == 'completed',
          f'{execution.status} {execution.error_message}')
    check('agente recebeu o texto enviado (extraído do arquivo, sem anexo)',
          _AgenteFalso.recebidos and _AgenteFalso.recebidos[0].get('petition_text', '').strip() == TEXTO.strip())
    check('modelo usado gravado na execução', bool(execution.model_name), str(execution.model_name))
    check('custo e tokens registrados',
          execution.tokens_used == 1234 and float(execution.cost_usd) == 0.0456,
          f'{execution.tokens_used}/{execution.cost_usd}')
    check('texto revisado guardado em disco (a tela abre o documento)',
          bool(execution.main_document_path) and Path(execution.main_document_path).exists(),
          str(execution.main_document_path))
    check('execução ligada à petição', execution.petition_id == r['peticao_id'])

    petition = FapReviewPetition.query.get(r['peticao_id'])
    # Revisão concluída fica "em revisão" até a triagem (derive_petition_workflow_status).
    check('petição fica "em revisão" até a triagem', petition.workflow_status == 'in_review',
          petition.workflow_status)
    check('petição aponta para a última revisão', petition.latest_revision_id == execution.id)
    check('contador de revisões atualizado', petition.revision_count == 1)
    check('data da última revisão preenchida', petition.last_reviewed_at is not None)

    audits = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id, entity_id=execution.id,
                                               entity_type='execution').count()
    check('auditoria registrada (início e conclusão)', audits >= 2, str(audits))
    check('e-mail de revisão pronta enviado', len(_emails) == 1, str(len(_emails)))
    return r


def test_segunda_revisao(law_firm_id, user_id, primeiro):
    print('\n2) Segunda revisão do mesmo Id Wrike')
    findings = [
        # o CRÍTICO reincide; o FORMAL foi resolvido; entra um MODERADO novo
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP'},
        {'category': 'CAT-3', 'severity': 'MODERADO', 'description': 'Tese sem caso de referência'},
    ]
    _AgenteFalso.proximos = [_payload(findings)]
    _AgenteFalso.recebidos = []
    r = review_petition_handler('Texto revisado da petição. ' * 30, law_firm_id, user_id=user_id,
                                identificador_documento=IDENT)
    _esperar(r['revisao_id'])

    check('reaproveita a petição (não cria outra)', r.get('peticao_criada') is False)
    check('mesma petição do primeiro registro', r.get('peticao_id') == primeiro['peticao_id'])
    check('numerada como revisão 2', r.get('numero_revisao') == 2, str(r.get('numero_revisao')))
    check('agente recebeu os pontos de atenção da revisão anterior (como na tela)',
          bool(_AgenteFalso.recebidos and _AgenteFalso.recebidos[0].get('prior_attention_points')))

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
          r.get_data(as_text=True).count('Revisão') >= 2)

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


def test_recusas(law_firm_id, user_id, primeiro):
    print('\n10) Recusas')
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id)
    check('sem Id Wrike: erro pedindo o Id ao usuário',
          'erro' in r and 'Id Wrike' in r['erro'], str(r)[:160])
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id,
                                identificador_documento='FAP-2024-013')
    check('Id não numérico para petição nova: erro', 'erro' in r, str(r)[:160])
    r = review_petition_handler('curto', law_firm_id, user_id=user_id, identificador_documento=IDENT)
    check('texto curto: erro', 'erro' in r)

    # Petição bloqueada (aguardando aprovação) não aceita revisão nova, como na tela.
    petition = FapReviewPetition(law_firm_id=law_firm_id, created_by_id=user_id,
                                 office_document_identifier=IDENT_BLOQUEADA, title='Bloqueada',
                                 workflow_status='awaiting_approval')
    db.session.add(petition)
    db.session.commit()
    antes = FapReviewExecution.query.filter_by(petition_id=petition.id).count()
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id,
                                identificador_documento=IDENT_BLOQUEADA)
    check('petição aguardando aprovação recusa revisão nova',
          'erro' in r and 'não aceita nova revisão' in r['erro'], str(r)[:160])
    check('e nenhuma execução foi criada',
          FapReviewExecution.query.filter_by(petition_id=petition.id).count() == antes)

    # Revisão em andamento: não abre outra (cada uma é uma chamada paga ao modelo).
    from app.services.fap_review_service import start_text_review
    aberta = start_text_review(law_firm_id, user_id, IDENT, TEXTO)
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id, identificador_documento=IDENT)
    check('revisão já em andamento: devolve a que está rodando',
          r.get('ja_em_andamento') is True and r.get('revisao_id') == aberta['revisao_id'], str(r)[:200])
    return aberta


def test_andamento(law_firm_id, aberta):
    print('\n11) Andamento pelo detalhar_revisao')
    d = get_review_detail_handler(law_firm_id, aberta['revisao_id'])
    check('em processamento: diz que está processando', d.get('status') == 'processando', str(d)[:200])
    check('mostra há quanto tempo', 'processando_ha_minutos' in d, str(d)[:200])

    execution = FapReviewExecution.query.get(aberta['revisao_id'])
    execution.updated_at = datetime.now() - timedelta(minutes=20)
    db.session.commit()
    d = get_review_detail_handler(law_firm_id, aberta['revisao_id'])
    db.session.expire_all()
    check('presa além do limite: vira falha, como na tela',
          d.get('status') == 'falhou' and FapReviewExecution.query.get(aberta['revisao_id']).status == 'failed',
          str(d)[:200])


def test_email(law_firm_id, user_id, primeiro):
    print('\n12) E-mail a quem pediu')
    user = User.query.get(user_id)
    _emails.clear()
    _AgenteFalso.proximos = [_payload([
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'Falta fundamentar o NTEP'},
        {'category': 'CAT-2', 'severity': 'CRÍTICO', 'description': 'Falta CAT'},
        {'category': 'FORMAL', 'severity': 'FORMAL', 'description': 'Numeração'},
    ])]
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id, identificador_documento=IDENT)
    _esperar(r['revisao_id'])
    check('um e-mail, para o e-mail de quem pediu',
          len(_emails) == 1 and user.email in str(_emails[0]['to']), str(_emails)[:200])
    if _emails:
        e = _emails[0]
        check('assunto diz que está pronta', 'pronta' in e['subject'].lower(), e['subject'])
        check('corpo traz o link absoluto da revisão',
              f'/fap-review/revision/{r["revisao_id"]}' in e['html'] and 'http' in e['html'])
        check('corpo traz os achados por gravidade', '2 crítico' in e['html'].lower(), '')

    _emails.clear()
    _AgenteFalso.proximos = [RuntimeError('modelo fora do ar')]
    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id, identificador_documento=IDENT)
    execution = _esperar(r['revisao_id'])
    check('falha do agente marca a execução como falha', execution.status == 'failed', execution.status)
    check('e avisa por e-mail que não concluiu',
          len(_emails) == 1 and 'não' in _emails[0]['subject'].lower(), str(_emails)[:200])
    d = get_review_detail_handler(law_firm_id, r['revisao_id'])
    check('detalhar_revisao mostra a falha com o motivo',
          d.get('status') == 'falhou' and 'fora do ar' in (d.get('erro_execucao') or ''), str(d)[:200])


def test_comparacao(law_firm_id, user_id):
    print('\n13) Comparação de versões pelo mesmo caminho')
    _emails.clear()
    _AgenteFalso.proximos = [_payload([])]
    _AgenteFalso.recebidos = []
    original = 'Versão original da petição. ' * 20
    revisado = 'Versão revisada da petição. ' * 20
    r = compare_petition_versions_handler(original, revisado, law_firm_id, user_id=user_id,
                                          identificador_documento=IDENT_COMPARA)
    check('responde na hora', r.get('status') == 'processando', str(r)[:200])
    execution = _esperar(r['revisao_id'])
    check('concluída como comparativa',
          execution.status == 'completed' and execution.comparative_analysis is True,
          f'{execution.status} {execution.error_message}')
    k = _AgenteFalso.recebidos[0] if _AgenteFalso.recebidos else {}
    check('agente recebeu as duas versões na ordem certa',
          k.get('original_petition_text', '').strip() == original.strip()
          and k.get('revised_petition_text', '').strip() == revisado.strip())
    check('versão revisada guardada em disco',
          bool(execution.compared_document_path) and Path(execution.compared_document_path).exists())
    check('sem Id Wrike: erro', 'erro' in compare_petition_versions_handler(
        original, revisado, law_firm_id, user_id=user_id))


def test_entradas_de_arquivo(law_firm_id, user_id):
    print('\n14) Entradas de arquivo: link de envio e Drive')
    from app.services import fap_review_upload_service as up
    from app.services import impugnacao_import_service as imp
    from app.models import FapReviewUploadLink

    r = review_petition_handler(None, law_firm_id, user_id=user_id,
                                identificador_documento=IDENT_COMPARA, titulo='Pelo link')
    check('sem texto nem Drive: aguardando o arquivo', r.get('status') == 'aguardando_arquivo', str(r)[:200])
    link = r.get('link_envio') or ''
    check('link de envio público', '/revisao/enviar/' in link, link)
    check('comando curl pronto com o link', 'arquivo=@' in (r.get('comando_curl') or '')
          and link in (r.get('comando_curl') or ''), r.get('comando_curl'))
    token = link.rsplit('/', 1)[-1]
    check('o link vale', up.find_link(token)[1] == 'valido')
    check('mensagem para o usuário com link e validade',
          link in (r.get('mensagem_para_usuario') or '') and r.get('expira_em') in (r.get('mensagem_para_usuario') or ''),
          (r.get('mensagem_para_usuario') or '')[:200])
    check('orienta a escolher o anexo certo', 'mais de um' in (r.get('proximo_passo') or '').lower(),
          (r.get('proximo_passo') or '')[:200])

    antes = FapReviewUploadLink.query.filter_by(law_firm_id=law_firm_id).count()
    r = review_petition_handler(None, law_firm_id, user_id=user_id, identificador_documento='FAP-1')
    check('Id inválido: erro e nenhum link criado',
          'erro' in r and FapReviewUploadLink.query.filter_by(law_firm_id=law_firm_id).count() == antes, str(r)[:160])

    r = review_petition_handler(TEXTO, law_firm_id, user_id=user_id, identificador_documento=IDENT_COMPARA,
                                link_drive='https://drive.google.com/file/d/1AbcDeFgH/view')
    check('texto e Drive juntos: erro', 'erro' in r and 'não os dois' in r['erro'], str(r)[:160])

    original = imp.download_drive_file
    try:
        def baixa_docx(file_id, dest_dir, *, law_firm_id, gdoc_como=None, timeout=90):
            import io
            from docx import Document
            doc = Document(); doc.add_paragraph('Petição que veio do Drive pelo Claude.')
            destino = os.path.join(dest_dir, f'drive_{file_id}.docx')
            doc.save(destino)
            return destino, 'Do Drive.docx', 'x'
        imp.download_drive_file = baixa_docx
        _AgenteFalso.proximos = [_payload([])]
        _AgenteFalso.recebidos = []
        r = review_petition_handler(None, law_firm_id, user_id=user_id, identificador_documento=IDENT_COMPARA,
                                    link_drive='https://drive.google.com/file/d/1AbcDeFgH/view')
        check('Drive: processando', r.get('status') == 'processando', str(r)[:200])
        if r.get('revisao_id'):
            execution = _esperar(r['revisao_id'])
            check('Drive: revisão concluída com o texto do arquivo',
                  execution.status == 'completed' and 'veio do Drive'
                  in ((_AgenteFalso.recebidos or [{}])[0].get('petition_text') or ''),
                  f'{execution.status} {execution.error_message}')
            check('Drive: nome original na execução', execution.main_document_filename == 'Do Drive.docx',
                  execution.main_document_filename)
    finally:
        imp.download_drive_file = original
    FapReviewUploadLink.query.filter_by(law_firm_id=law_firm_id, identifier=IDENT_COMPARA).delete()
    db.session.commit()


def _limpar(law_firm_id):
    petitions = FapReviewPetition.query.filter(
        FapReviewPetition.law_firm_id == law_firm_id,
        FapReviewPetition.office_document_identifier.in_(IDENTS)).all()
    for p in petitions:
        execs = FapReviewExecution.query.filter_by(petition_id=p.id).all()
        for e in execs:
            for caminho in (e.main_document_path, e.compared_document_path):
                if caminho:
                    Path(caminho).unlink(missing_ok=True)
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
        user = User.query.filter(User.law_firm_id == firm.id, User.email.isnot(None)).first()
        print(f'Escritório: {firm.id} | usuário: {user.id}')

        _limpar(firm.id)  # resíduo de execução anterior
        originais = (fap_review_bp.FapPetitionReviewerAgent, email_service.send_email,
                     os.environ.get('OPENAI_API_KEY'))
        fap_review_bp.FapPetitionReviewerAgent = _AgenteFalso
        email_service.send_email = _email_falso
        os.environ.setdefault('OPENAI_API_KEY', 'sk-teste')
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
            aberta = test_recusas(firm.id, user.id, primeiro)
            test_andamento(firm.id, aberta)
            test_email(firm.id, user.id, primeiro)
            test_comparacao(firm.id, user.id)
            test_entradas_de_arquivo(firm.id, user.id)
        finally:
            fap_review_bp.FapPetitionReviewerAgent, email_service.send_email = originais[:2]
            if originais[2] is None:
                os.environ.pop('OPENAI_API_KEY', None)
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
