#!/usr/bin/env python3
"""
Revisão feita no Claude: instruções, conferência e gravação.

    uv run python tests/test_fap_review_claude.py

O Claude revisa a petição na conversa com as instruções do agente do
escritório; o IntellexIA só confere o JSON (rascunho saneado) e grava, com o
selo "Feita no Claude". Spec:
docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md

Cobre:
  1. Montagem do prompt e parse do resultado sem LLM (a mesma do agente)
  2. Instruções em partes: o mesmo prompt do agente, cortado em fim de linha,
     com os pontos de atenção da última revisão do IntellexIA (nunca de uma
     feita no Claude); os casos de referência ficam sob consulta (não vão
     inteiros); o formato do JSON é repetido no fim; petição travada traz aviso
  3. Conferência: rascunho saneado; JSON fora do contrato recusado com o
     formato esperado; item ruim vira aviso e pede reenvio; achado "não
     pertinente" marcado; rascunho vencido apagado
  4. Gravação: dono, validade, idempotência, petição nova x existente,
     travada, em processamento, origem e modelo gravados
  5. Histórico: o mesmo achado com outra redação casa (reincidente), achado
     diferente da mesma categoria não casa; leitura diz a origem
  6. Regras da origem: fora da pontuação; triagem "versão final" recusada;
     mudança manual para aprovação recusada a não-admin e aceita para admin;
     telas abrem a revisão sem arquivo, com o selo

Os dados criados são removidos ao final.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.agents.fap_review.reviewer_agent import (  # noqa: E402
    FapPetitionReviewerAgent,
    PetitionReviewResult,
    ReviewOutputParseError,
)
from app.models import (  # noqa: E402
    db,
    FapReviewAuditLog,
    FapReviewDraft,
    FapReviewExecution,
    FapReviewIgnoredFinding,
    FapReviewPetition,
    FapReviewPromptVersion,
    FapReviewReferenceVersion,
    LawFirm,
    User,
)
from app.services import fap_review_claude_service as claude_svc  # noqa: E402
from app.services import fap_review_service as svc  # noqa: E402

# Id Wrike é numérico; valores altos para não colidir com petição real.
IDENT = '990000000041'
IDENT_NOVA = '990000000042'
IDENT_TRAVADA = '990000000043'
IDENT_HIST = '990000000044'
IDENT_REGRAS = '990000000045'
IDENTS = (IDENT, IDENT_NOVA, IDENT_TRAVADA, IDENT_HIST, IDENT_REGRAS)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _achado(descricao, **extra):
    base = {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': descricao,
            'location': 'Item 3', 'correction': 'Ajustar', 'manual_reference': '2.1'}
    base.update(extra)
    return base


def test_montagem_sem_llm():
    print('\n1) Prompt e resultado montados sem LLM, pelo mesmo código do agente')
    agente = FapPetitionReviewerAgent(openai_api_key='sk-teste')
    agente.load_reference_documents(manual_md='# Manual\nRegra X', cases_md='Caso Y',
                                    project_instructions_md='Instrução Z')
    for focada in (False, True):
        for comparativa in (False, True):
            esperado = agente._build_system_prompt('Identidade', 'Regras', 'formato',
                                                   focused_review=focada, comparative=comparativa)
            montado = FapPetitionReviewerAgent.montar_prompt_sistema(
                'Identidade', 'Regras', manual='# Manual\nRegra X', casos='Caso Y',
                instrucoes_projeto='Instrução Z', focused_review=focada, comparative=comparativa)
            check(f'prompt idêntico ao do agente (focada={focada}, comparativa={comparativa})',
                  esperado == montado)

    msg = FapPetitionReviewerAgent._build_single_user_message(auxiliary_documents=None)
    check('mensagem da tarefa sai sem instância', 'Revise esta petição inicial' in msg)
    msg = FapPetitionReviewerAgent._build_comparative_user_message(auxiliary_documents=None)
    check('mensagem da comparação sai sem instância', 'comparativamente' in msg)

    dados = {
        'theses': [{'thesis': 'Trajeto'}],
        'findings': [_achado('Falta o NTEP'), _achado('Falta o NTEP'),
                     _achado('Razão social grafada de forma consistente, sem divergências')],
        'missing_documents': [{'document_type': 'CAT'}],
        'executive_summary': {'total_findings': 9, 'critical_findings': 9, 'moderate_findings': 0,
                              'formal_findings': 0, 'correction_priority': 'Alta'},
    }
    resultado, erros = FapPetitionReviewerAgent.montar_resultado(
        dados, comparativa=False, revisao_focada=False)
    check('devolve PetitionReviewResult', isinstance(resultado, PetitionReviewResult))
    check('saneador tira o duplicado (R2) e o "sem problema" (R6)',
          len(resultado.findings) == 1, str(len(resultado.findings)))
    check('descartes registrados com a regra',
          sorted(d['regra'] for d in resultado.sanitizer_discards) == ['R2', 'R6'],
          str(resultado.sanitizer_discards))
    check('resumo recontado dos achados mantidos',
          resultado.executive_summary.total_findings == 1)
    check('sem erros de parse', erros == [], str(erros))

    _, erros = FapPetitionReviewerAgent.montar_resultado(
        {'findings': [_achado('ok'), {'description': 'sem gravidade'}], 'theses': [],
         'missing_documents': [], 'executive_summary': {}},
        comparativa=False, revisao_focada=False)
    check('item fora do schema vira erro de parse, sem derrubar os outros', len(erros) == 1, str(erros))

    try:
        FapPetitionReviewerAgent.montar_resultado({}, comparativa=False, revisao_focada=False)
        check('JSON vazio levanta ReviewOutputParseError', False, 'passou')
    except ReviewOutputParseError:
        check('JSON vazio levanta ReviewOutputParseError', True)

    comparado, _ = FapPetitionReviewerAgent.montar_resultado(
        {'comparative_changes': [{'original_excerpt': 'a', 'corrected_excerpt': 'b',
                                  'correction_reason': 'c', 'pattern_in_manual': True,
                                  'is_new_pattern': False}],
         'findings': [], 'executive_summary': {}},
        comparativa=True, revisao_focada=True)
    check('comparação monta as mudanças', comparado.analysis_type == 'comparative'
          and len(comparado.comparative_changes) == 1 and comparado.focused_review is True)


def _resultado(findings=None, **extra):
    dados = {
        'theses': [{'thesis': 'Acidente de trajeto', 'benefit_number': '6320957810'}],
        'findings': findings if findings is not None else [
            _achado('Falta fundamentar o NTEP'),
            _achado('Numeração de páginas ausente', category='FORMAL', severity='FORMAL'),
        ],
        'missing_documents': [{'document_type': 'CAT', 'thesis': 'Acidente de trajeto'}],
        'executive_summary': {'total_findings': 2, 'critical_findings': 1, 'moderate_findings': 0,
                              'formal_findings': 1, 'correction_priority': 'Alta'},
    }
    dados.update(extra)
    return dados


def _execucao(firm_id, user_id, petition, numero, findings, origem=None, status='completed'):
    execution = FapReviewExecution(
        law_firm_id=firm_id, user_id=user_id, petition_id=petition.id, execution_type='revision',
        status=status, revision_number=numero, law_firm_document_identifier=petition.office_document_identifier,
        result_json=json.dumps({'findings': findings}), completed_at=datetime.now(),
        review_origin=origem,
    )
    db.session.add(execution)
    db.session.flush()
    petition.latest_revision_id = execution.id
    petition.revision_count = numero
    db.session.commit()
    return execution


def test_instrucoes(firm_id, user_id):
    print('\n2) Instruções em partes')
    texto = 'linha de manual com algum conteúdo\n' * 4000 + '\n' + 'x' * 50 + '\n\nfim'
    partes = claude_svc.partes_do_texto(texto, tamanho=40_000)
    check('partes juntas reproduzem o texto', ''.join(partes) == texto)
    check('nenhuma parte passa de 40 mil caracteres', all(len(p) <= 40_000 for p in partes),
          str([len(p) for p in partes]))
    check('corte sempre em fim de linha', all(p.endswith('\n') for p in partes[:-1]))

    petition = FapReviewPetition(law_firm_id=firm_id, created_by_id=user_id, title='Petição Claude',
                                 office_document_identifier=IDENT, workflow_status='in_review')
    db.session.add(petition)
    db.session.commit()
    _execucao(firm_id, user_id, petition, 1, [_achado('Ponto da revisão oficial')])

    r = claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT)
    check('responde a parte 1 com o total', r.get('parte') == 1 and r.get('total_partes', 0) >= 1, str(r)[:200])
    completo = ''.join(
        claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT, parte=n)['conteudo']
        for n in range(1, r['total_partes'] + 1))
    montadas = claude_svc.montar_instrucoes(firm_id, 'revisao', identificador=IDENT)
    check('as partes juntas são as instruções montadas', completo == montadas['texto'])
    check('traz o contrato de saída do agente', 'CONTRATO TÉCNICO DE SAÍDA' in completo)
    casos = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=firm_id, reference_type='casos_referencia', is_active=True).first()
    if casos and len(casos.content or '') > 2000:
        trecho_dos_casos = casos.content.strip()[200:700]
        check('casos de referência não vão inteiros nas instruções', trecho_dos_casos not in completo)
    check('instruções ensinam a consultar os casos por termo',
          'ler_manual_revisor' in completo and 'casos_referencia' in completo)
    manual = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=firm_id, reference_type='manual_fap', is_active=True).first()
    if manual and manual.content:
        check('o manual continua indo inteiro', manual.content.strip()[-300:] in completo)
    ultima = claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT, parte=r['total_partes'])['conteudo']
    check('formato do JSON repetido na última parte', '"missing_documents"' in ultima
          and '"theses"' in ultima and '"benefit_number"' in ultima)
    check('instruções mandam confirmar a petição achada antes de usar o histórico',
          'confirme' in completo.lower())
    check('traz o bloco de adaptação para a conversa', 'conferir_revisao_peticao' in completo)
    check('instruções pedem a página no PDF e explicam o DOCX sem página',
          'PDF' in completo and 'página' in completo and 'DOCX' in completo)
    etapas = ['1. Ler as instruções do revisor', '2. Ler a petição', '3. Revisar',
              '4. Conferir o resultado no IntellexIA', '5. Mostrar os achados e perguntar se grava']
    check('revisão: as cinco etapas, nesta ordem, com os nomes para o usuário',
          all(e in completo for e in etapas)
          and [completo.index(e) for e in etapas] == sorted(completo.index(e) for e in etapas))
    check('pontos de atenção da revisão do IntellexIA entram', 'Ponto da revisão oficial' in completo)
    check('revisão focada marcada', r.get('revisao_focada') is True)
    check('última parte manda conferir', 'conferir_revisao_peticao' in
          claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT,
                                parte=r['total_partes'])['proximo_passo'])
    check('parte inexistente: erro com o total',
          'erro' in claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT, parte=99))

    _execucao(firm_id, user_id, petition, 2, [_achado('Ponto que só o Claude viu')], origem='claude')
    completo = claude_svc.montar_instrucoes(firm_id, 'revisao', identificador=IDENT)['texto']
    check('revisão feita no Claude não vira ponto de atenção',
          'Ponto que só o Claude viu' not in completo and 'Ponto da revisão oficial' in completo)

    nova = claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT_NOVA)
    check('petição nova: instruções sem foco', nova.get('revisao_focada') is False and nova.get('peticao') is None)
    comparacao = claude_svc.montar_instrucoes(firm_id, 'comparacao')['texto']
    check('comparação traz o contrato comparativo', 'comparative_changes' in comparacao)
    check('comparação: etapas 2 e 3 próprias, demais iguais',
          '2. Ler as duas versões' in comparacao and '3. Comparar as versões' in comparacao
          and '2. Ler a petição' not in comparacao
          and '4. Conferir o resultado no IntellexIA' in comparacao)
    check('modo inválido: erro', 'erro' in claude_svc.instrucoes(firm_id, 'outro'))
    check('petição de outro escritório: erro',
          'erro' in claude_svc.instrucoes(99999, 'revisao', peticao_id=petition.id))

    travada = FapReviewPetition(law_firm_id=firm_id, created_by_id=user_id, title='Travada',
                                office_document_identifier=IDENT_TRAVADA, workflow_status='awaiting_approval')
    db.session.add(travada)
    db.session.commit()
    r = claude_svc.instrucoes(firm_id, 'revisao', identificador=IDENT_TRAVADA)
    check('petição travada: instruções com aviso de que não grava',
          'conteudo' in r and 'não poderá ser gravada' in (r.get('aviso') or ''), str(r.get('aviso')))
    return petition


def test_conferencia(firm_id, user_id, petition):
    print('\n3) Conferência')
    dados = _resultado([_achado('Falta fundamentar o NTEP'), _achado('Falta fundamentar o NTEP'),
                        _achado('Numeração ausente', category='FORMAL', severity='FORMAL')])
    r = claude_svc.conferir(firm_id, user_id, dados, 'revisao', identificador=IDENT)
    check('JSON válido gera rascunho', bool(r.get('rascunho_id')), str(r)[:200])
    check('achados saneados (duplicado sai)', len(r.get('achados', [])) == 2, str(r.get('achados')))
    check('descarte do saneador explicado',
          [d['regra'] for d in r.get('descartados_pelo_saneador', [])] == ['R2'])
    check('manda mostrar estes achados e perguntar antes de gravar',
          'gravar_revisao_peticao' in r.get('proximo_passo', '') and 'pergunte' in r.get('proximo_passo', ''))
    como = r.get('como_mostrar', '')
    check('traz o modelo de apresentação com as cores por gravidade',
          all(i in como for i in ('🔴', '🟡', '🔵')) and 'Documentos em falta' in como, como[:200])
    check('modelo manda manter a numeração da conferência e o trecho literal em citação',
          'numeração' in como and '> ' in como)
    check('próximo passo manda seguir o modelo de apresentação', 'como_mostrar' in r.get('proximo_passo', ''))
    novo = claude_svc.conferir(firm_id, user_id, _resultado([_achado('Padrão fora do manual', is_new_pattern=True)]),
                               'revisao')
    check('padrão novo marcado no achado', novo['achados'][0].get('padrao_novo') is True, str(novo['achados'][0]))
    check('achado comum sem a marca de padrão novo', 'padrao_novo' not in r['achados'][0])
    draft = FapReviewDraft.query.get(r['rascunho_id'])
    check('rascunho guarda o resultado saneado', len(json.loads(draft.result_json)['findings']) == 2)
    check('rascunho ligado à petição e ao usuário',
          draft.petition_id == petition.id and draft.user_id == user_id)
    check('rascunho vence em 24 h',
          timedelta(hours=23) < draft.expires_at - draft.created_at <= timedelta(hours=24))

    r = claude_svc.conferir(firm_id, user_id, json.dumps(dados), 'revisao', identificador=IDENT)
    check('aceita o JSON como texto', bool(r.get('rascunho_id')))
    r = claude_svc.conferir(firm_id, user_id, '{"findings": [', 'revisao')
    check('JSON quebrado: erro, sem rascunho', 'erro' in r and 'rascunho_id' not in r)
    r = claude_svc.conferir(firm_id, user_id, {'achados': [_achado('x')]}, 'revisao')
    check('chave de primeiro nível com nome errado: erro com as chaves que faltam',
          'erro' in r and 'findings' in r['erro'], str(r)[:200])
    # O resumo é recontado dos achados: forma errada nele não pode custar o reenvio do JSON inteiro.
    sem_resumo = _resultado()
    sem_resumo.pop('executive_summary')
    r = claude_svc.conferir(firm_id, user_id, sem_resumo, 'revisao')
    check('falta executive_summary: aceita e reconta', bool(r.get('rascunho_id'))
          and r['resumo']['total_achados'] == len(sem_resumo['findings']), str(r)[:200])
    r = claude_svc.conferir(firm_id, user_id,
                            _resultado(executive_summary='Corrigir primeiro a tabela de benefícios.'), 'revisao')
    check('executive_summary em texto (o erro do teste real): aceita, texto vira a prioridade',
          bool(r.get('rascunho_id')) and not r.get('avisos')
          and r['resumo']['prioridade_de_correcao'] == 'Corrigir primeiro a tabela de benefícios.',
          str(r)[:300])
    r = claude_svc.conferir(firm_id, user_id,
                            _resultado(executive_summary={'main_legal_risks': ['Perda do benefício B91'],
                                                          'correction_priority': 'Tabela'}), 'revisao')
    check('resumo sem as contagens: riscos e prioridade não se perdem',
          r.get('resumo', {}).get('riscos') == ['Perda do benefício B91']
          and r['resumo']['prioridade_de_correcao'] == 'Tabela', str(r)[:300])
    r = claude_svc.conferir(firm_id, user_id, _resultado(findings='nada'), 'revisao')
    check('findings que não é lista: erro', 'erro' in r)
    r = claude_svc.conferir(firm_id, user_id, _resultado([_achado('ok'), {'description': 'sem gravidade'}]),
                            'revisao')
    check('item fora do schema: rascunho com aviso', bool(r.get('rascunho_id')) and len(r.get('avisos', [])) == 1,
          str(r.get('avisos')))
    check('com aviso, pede para corrigir e reenviar antes de mostrar, com o formato esperado',
          'mande de novo' in r.get('proximo_passo', '') and '"thesis"' in r.get('formato_esperado', ''),
          str(r.get('proximo_passo'))[:160])
    r = claude_svc.conferir(firm_id, user_id, _resultado(theses=['Acidente de trajeto']), 'revisao')
    check('tese em texto solto (o erro do teste real): aviso e formato esperado',
          len(r.get('avisos', [])) >= 1 and '"thesis"' in r.get('formato_esperado', ''), str(r)[:200])
    r = claude_svc.conferir(firm_id, user_id, {'achados': []}, 'revisao')
    check('JSON fora do contrato: erro traz o formato esperado', 'erro' in r
          and '"missing_documents"' in r.get('formato_esperado', ''), str(r)[:200])
    comparacao = {'comparative_changes': [], 'findings': [_achado('ok')], 'executive_summary': {}}
    check('comparação confere com as chaves dela',
          bool(claude_svc.conferir(firm_id, user_id, comparacao, 'comparacao').get('rascunho_id')))
    check('comparação sem comparative_changes: erro',
          'erro' in claude_svc.conferir(firm_id, user_id, _resultado(), 'comparacao'))

    descartado = _achado('Achado que o advogado descartou')
    origem = FapReviewExecution.query.filter_by(petition_id=petition.id).order_by(FapReviewExecution.id).first()
    db.session.add(FapReviewIgnoredFinding(
        law_firm_id=firm_id, law_firm_document_identifier=IDENT, source_execution_id=origem.id,
        created_by_id=user_id, finding_fingerprint=svc.build_finding_fingerprint(descartado),
        finding_description=descartado['description']))
    db.session.commit()
    r = claude_svc.conferir(firm_id, user_id, _resultado([descartado, _achado('Outro')]), 'revisao',
                            identificador=IDENT)
    marcados = [a for a in r.get('achados', []) if a.get('ja_marcado_nao_pertinente')]
    check('achado já marcado "não pertinente" vem marcado', len(marcados) == 1, str(r.get('achados')))

    enorme = _resultado([_achado(f'Achado {i}: ' + 'descrição longa do problema encontrado ' * 30,
                                 location_excerpt='trecho ' * 40) for i in range(60)])
    try:
        r = claude_svc.conferir(firm_id, user_id, enorme, 'revisao')
    except Exception as e:  # noqa: BLE001 — o teste é justamente não estourar
        db.session.rollback()
        r = {'excecao': f'{type(e).__name__}: {str(e)[:120]}'}
    check('resultado maior que o histórico guarda: mostra os achados, avisa e não cria rascunho',
          len(r.get('achados', [])) == 60 and 'rascunho_id' not in r and '64 KB' in r.get('aviso', ''),
          str(r)[:200])

    vencido = FapReviewDraft(law_firm_id=firm_id, user_id=user_id, mode='revisao', result_json='{}',
                             created_at=datetime.utcnow() - timedelta(days=2),
                             expires_at=datetime.utcnow() - timedelta(days=1))
    db.session.add(vencido)
    db.session.commit()
    vencido_id = vencido.id
    claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao')
    db.session.expire_all()
    check('rascunho vencido apagado na conferência seguinte', FapReviewDraft.query.get(vencido_id) is None)


def test_gravacao(firm_id, user_id, petition):
    print('\n4) Gravação')
    outro = User.query.filter(User.law_firm_id == firm_id, User.id != user_id).first()
    r = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao', identificador=IDENT)
    rascunho = r['rascunho_id']
    if outro:
        check('rascunho de outro usuário: recusado',
              'erro' in claude_svc.gravar(firm_id, outro.id, rascunho))
    check('rascunho de outro escritório: recusado', 'erro' in claude_svc.gravar(99999, user_id, rascunho))
    check('petição diferente da conferida: recusado',
          'erro' in claude_svc.gravar(firm_id, user_id, rascunho, identificador=IDENT_NOVA))

    revisoes_antes = petition.revision_count
    g = claude_svc.gravar(firm_id, user_id, rascunho, nome_arquivo='peticao.pdf', modelo='Claude Opus 5')
    check('grava na petição conferida', g.get('peticao_id') == petition.id, str(g)[:200])
    execution = FapReviewExecution.query.get(g['revisao_id'])
    check('origem "claude"', execution.review_origin == 'claude')
    check('concluída, numerada em sequência', execution.status == 'completed'
          and execution.revision_number == revisoes_antes + 1, f'{execution.status} {execution.revision_number}')
    check('modelo informado gravado', execution.model_name == 'Claude · Claude Opus 5', execution.model_name)
    check('nome do arquivo gravado, sem caminho', execution.main_document_filename == 'peticao.pdf'
          and not execution.main_document_path)
    check('sem tokens nem custo', execution.tokens_used is None and execution.cost_usd is None)
    check('resultado é o do rascunho', json.loads(execution.result_json)['findings']
          == json.loads(FapReviewDraft.query.get(rascunho).result_json)['findings'])
    db.session.refresh(petition)
    check('petição aponta para a revisão nova', petition.latest_revision_id == execution.id
          and petition.workflow_status == 'in_review')
    check('mensagem fala do selo e da aprovação', 'Feita no Claude' in g.get('mensagem_para_usuario', '')
          and 'aprovação' in g['mensagem_para_usuario'])
    check('auditoria registrada', FapReviewAuditLog.query.filter_by(
        law_firm_id=firm_id, entity_type='execution', entity_id=execution.id).count() >= 1)

    de_novo = claude_svc.gravar(firm_id, user_id, rascunho)
    check('gravar de novo devolve a mesma revisão', de_novo.get('revisao_id') == execution.id
          and de_novo.get('ja_gravada') is True)
    check('sem revisão em dobro', FapReviewExecution.query.filter_by(petition_id=petition.id).count()
          == revisoes_antes + 1)

    sem_peticao = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao')['rascunho_id']
    check('petição nova sem Id Wrike: recusado', 'erro' in claude_svc.gravar(firm_id, user_id, sem_peticao))
    check('Id Wrike não numérico: recusado',
          'erro' in claude_svc.gravar(firm_id, user_id, sem_peticao, identificador='FAP-13'))
    g = claude_svc.gravar(firm_id, user_id, sem_peticao, identificador=IDENT_NOVA, titulo='Petição nova Claude')
    check('petição nova criada com o Id Wrike', g.get('peticao_criada') is True
          and g.get('numero_revisao') == 1, str(g)[:200])
    check('título da petição nova', FapReviewPetition.query.get(g['peticao_id']).title == 'Petição nova Claude')

    travada = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao', identificador=IDENT_TRAVADA)
    check('conferência de petição travada funciona', bool(travada.get('rascunho_id')))
    check('gravar em petição travada: recusado',
          'erro' in claude_svc.gravar(firm_id, user_id, travada['rascunho_id']))

    rodando = _execucao(firm_id, user_id, petition, petition.revision_count + 1, [], status='processing')
    pendente = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao', identificador=IDENT)['rascunho_id']
    r = claude_svc.gravar(firm_id, user_id, pendente)
    check('revisão do IntellexIA em processamento: recusado, rascunho continua',
          'erro' in r and 'vale até' in r['erro'] and not FapReviewDraft.query.get(pendente).saved_execution_id,
          str(r)[:200])
    rodando.status = 'completed'
    db.session.commit()

    vencido = FapReviewDraft.query.get(pendente)
    vencido.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    check('rascunho vencido: recusado', 'erro' in claude_svc.gravar(firm_id, user_id, pendente))


def test_historico(firm_id, user_id, petition):
    print('\n5) Histórico: o mesmo achado com outra redação')
    from mcp_server.tools.petition_review_read import (
        casar_achados, get_review_detail_handler, petition_review_history_handler,
    )

    antes = [
        _achado("Substituir 'destacamos' por 'compartilhamos' no item 3", category='FORMAL', severity='FORMAL'),
        _achado('Citar os arts. 370 e 371 do CPC na fundamentação da prova', category='CAT-2'),
        _achado('Numeração de páginas ausente', category='FORMAL', severity='FORMAL'),
    ]
    depois = [
        _achado("No item 3, trocar 'destacamos' por 'compartilhamos'", category='FORMAL', severity='FORMAL'),
        _achado('Fundamentação da prova deve citar arts. 370/371 do CPC', category='CAT-2'),
        _achado('Tese sem caso de referência', category='CAT-2'),
    ]
    pares = casar_achados(antes, depois)
    check('reescrita do mesmo achado casa', (0, 0) in pares and (1, 1) in pares, str(pares))
    check('achado diferente da mesma categoria não casa',
          all(j != 2 for _, j in pares) and all(i != 2 for i, _ in pares), str(pares))
    mesmo_trecho = [_achado('Texto A', category='CAT-1', location_excerpt='a empresa autora requer')]
    outro_texto = [_achado('Redação completamente diferente', category='CAT-1',
                           location_excerpt='A empresa autora  requer')]
    check('mesmo trecho da petição casa mesmo com descrição diferente',
          casar_achados(mesmo_trecho, outro_texto) == [(0, 0)])
    check('descrição curta contida numa longa não casa (sobreposição só com 5+ palavras)', casar_achados(
        [_achado('Falta o NTEP', location='Item 1')],
        [_achado('Falta fundamentar o NTEP e anexar a CAT, o CNIS e o INFBEN do segurado', location='Item 9')])
        == [])
    check('categoria diferente não casa', casar_achados(
        [_achado('Falta o NTEP', category='CAT-1')], [_achado('Falta o NTEP', category='CAT-3')]) == [])

    hist_peticao = FapReviewPetition(law_firm_id=firm_id, created_by_id=user_id, title='Histórico',
                                     office_document_identifier=IDENT_HIST, workflow_status='in_review')
    db.session.add(hist_peticao)
    db.session.commit()
    _execucao(firm_id, user_id, hist_peticao, 1, antes)
    feita_no_claude = _execucao(firm_id, user_id, hist_peticao, 2, depois, origem='claude')
    h = petition_review_history_handler(firm_id, peticao_id=hist_peticao.id)
    rev2 = h['revisoes'][1]
    check('reincidentes com a redação nova', len(rev2['reincidentes']) == 2
          and any('trocar' in r for r in rev2['reincidentes']), str(rev2['reincidentes']))
    check('resolvido só o que sumiu de fato', rev2['resolvidos_desde_a_anterior'] == ['Numeração de páginas ausente'],
          str(rev2['resolvidos_desde_a_anterior']))
    check('novo só o achado novo', rev2['novos'] == ['Tese sem caso de referência'], str(rev2['novos']))
    check('histórico diz a origem', h['revisoes'][0]['origem'] == 'IntellexIA'
          and rev2['origem'] == 'Feita no Claude')
    d = get_review_detail_handler(firm_id, feita_no_claude.id)
    check('detalhe diz a origem', d.get('origem') == 'Feita no Claude', str(d.get('origem')))


def _cliente(user_id, firm_id, papel):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['law_firm_id'] = firm_id
        sess['user_role'] = papel
    return client


def test_regras_da_origem(firm_id, user_id):
    print('\n6) Regras da revisão feita no Claude')
    petition = FapReviewPetition(law_firm_id=firm_id, created_by_id=user_id, title='Regras Claude',
                                 office_document_identifier=IDENT_REGRAS, workflow_status='in_review')
    db.session.add(petition)
    db.session.commit()
    oficial = _execucao(firm_id, user_id, petition, 1, [_achado('Ponto oficial')])
    antes = svc.build_lawyer_statistics(firm_id)['overview']['total_revisions']
    rascunho = claude_svc.conferir(firm_id, user_id, _resultado([]), 'revisao', peticao_id=petition.id)
    gravada = claude_svc.gravar(firm_id, user_id, rascunho['rascunho_id'], nome_arquivo='minuta.docx')
    depois = svc.build_lawyer_statistics(firm_id)['overview']['total_revisions']
    check('revisão do Claude fica fora da pontuação e das estatísticas por advogado', depois == antes,
          f'{antes} -> {depois}')

    # O check_session relê o papel do banco a cada requisição: precisa de usuários reais.
    nao_admin = User.query.filter(User.law_firm_id == firm_id, User.role != 'admin',
                                  User.is_active.is_(True)).order_by(User.id).first()
    um_admin = User.query.filter(User.law_firm_id == firm_id, User.role == 'admin',
                                 User.is_active.is_(True)).order_by(User.id).first()
    if not nao_admin or not um_admin:
        check('banco local tem um admin e um não-admin para testar as telas', False)
        return
    leigo = _cliente(nao_admin.id, firm_id, nao_admin.role)
    admin = _cliente(um_admin.id, firm_id, um_admin.role)
    r = leigo.post(f'/fap-review/revision/{gravada["revisao_id"]}/complete-triage', json={'outcome': 'final_version'})
    check('triagem "versão final" recusada na revisão do Claude', r.status_code == 403
          and 'Claude' in (r.get_json() or {}).get('error', ''), f'{r.status_code} {r.get_data(as_text=True)[:120]}')
    r = admin.post(f'/fap-review/revision/{gravada["revisao_id"]}/complete-triage', json={'outcome': 'final_version'})
    check('…inclusive para admin (a triagem não é o caminho manual)', r.status_code == 403, str(r.status_code))

    r = leigo.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'awaiting_approval'})
    check('não-admin não move para aprovação com a última revisão feita no Claude',
          r.status_code == 403 and 'Claude' in (r.get_json() or {}).get('error', ''), str(r.status_code))
    # "Aprovada pelo revisor" já era só do admin (status_transition_requires_admin).
    r = leigo.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'ready_for_filing'})
    check('não-admin também não aprova', r.status_code == 403, str(r.status_code))
    r = leigo.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'awaiting_adjustments'})
    check('não-admin ainda move para outros status', r.status_code == 200, str(r.status_code))
    r = admin.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'awaiting_approval'})
    check('admin continua podendo mover à mão', r.status_code == 200, str(r.status_code))
    admin.post(f'/fap-review/petitions/{petition.id}/status', json={'workflow_status': 'in_review'})

    r = leigo.post(f'/fap-review/revision/{gravada["revisao_id"]}/complete-triage', json={'outcome': 'new_version'})
    check('triagem "nova versão" continua valendo', r.status_code == 200, f'{r.status_code} {r.get_data(as_text=True)[:120]}')

    r = leigo.get(f'/fap-review/revision/{gravada["revisao_id"]}')
    corpo = r.get_data(as_text=True)
    check('tela da revisão do Claude abre sem arquivo', r.status_code == 200, str(r.status_code))
    check('tela mostra o selo "Feita no Claude"', 'Feita no Claude' in corpo)
    check('botão de versão final vem desabilitado com o motivo',
          'id="triageFinalVersionBtn"' in corpo and 'data-bloqueado' in corpo)
    r = leigo.get(f'/fap-review/revision/{oficial.id}')
    check('revisão do IntellexIA não leva o selo', r.status_code == 200
          and 'Feita no Claude</span>' not in r.get_data(as_text=True))
    r = leigo.get(f'/fap-review/petitions/{petition.id}')
    corpo = r.get_data(as_text=True)
    check('detalhe da petição abre e mostra o selo', r.status_code == 200 and 'Feita no Claude' in corpo,
          str(r.status_code))
    check('detalhe: opções de aprovação desabilitadas para não-admin', 'data-bloqueio-claude' in corpo)
    r = leigo.get('/fap-review/')
    corpo = r.get_data(as_text=True)
    check('painel abre e marca o cartão bloqueado para aprovação',
          r.status_code == 200 and 'data-bloqueio-aprovacao' in corpo, str(r.status_code))
    r = admin.get('/fap-review/')
    check('para o admin o cartão não é bloqueado', 'data-bloqueio-aprovacao' not in r.get_data(as_text=True))


def _limpar(firm_id, user_id):
    FapReviewDraft.query.filter_by(law_firm_id=firm_id, user_id=user_id).filter(
        FapReviewDraft.identifier.in_(IDENTS) | FapReviewDraft.identifier.is_(None)).delete(
        synchronize_session=False)
    FapReviewIgnoredFinding.query.filter(
        FapReviewIgnoredFinding.law_firm_id == firm_id,
        FapReviewIgnoredFinding.law_firm_document_identifier.in_(IDENTS)).delete(synchronize_session=False)
    for p in FapReviewPetition.query.filter(FapReviewPetition.law_firm_id == firm_id,
                                            FapReviewPetition.office_document_identifier.in_(IDENTS)).all():
        p.latest_revision_id = None
        db.session.flush()
        for e in FapReviewExecution.query.filter_by(petition_id=p.id).all():
            FapReviewDraft.query.filter_by(saved_execution_id=e.id).delete(synchronize_session=False)
            FapReviewAuditLog.query.filter_by(entity_type='execution', entity_id=e.id).delete()
            db.session.delete(e)
        db.session.flush()
        FapReviewAuditLog.query.filter_by(entity_type='petition', entity_id=p.id).delete()
        db.session.delete(p)
    db.session.commit()


def main():
    test_montagem_sem_llm()
    with app.app_context():
        firm = LawFirm.query.order_by(LawFirm.id).first()
        user = User.query.filter(User.law_firm_id == firm.id).order_by(User.id).first()
        print(f'Escritório: {firm.id} | usuário: {user.id}')
        _limpar(firm.id, user.id)
        try:
            petition = test_instrucoes(firm.id, user.id)
            test_conferencia(firm.id, user.id, petition)
            test_gravacao(firm.id, user.id, petition)
            test_historico(firm.id, user.id, petition)
            test_regras_da_origem(firm.id, user.id)
        finally:
            db.session.rollback()
            _limpar(firm.id, user.id)
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
