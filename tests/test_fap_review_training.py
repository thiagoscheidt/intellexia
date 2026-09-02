"""
Teste do fluxo de Treinamento do Revisor FAP.

Regressões cobertas:

1. Com as políticas `auto_update_*` desligadas — o padrão do modelo — o passo
   de aplicação não gravava nada e a tela ainda assim dizia "Treinamento
   aplicado com sucesso". Agora o que grava é a seleção do usuário, e seleção
   vazia é vazia, não sucesso.
2. O histórico procurava `manual_updates_generated` na raiz do result_json, mas
   a gravação sempre pôs esse dado sob `training_result` — as colunas Manual e
   Casos mostravam "Não" em toda linha.
3. A numeração exibida era `1.0.{n}`, inventada, sem relação com a versão real
   da referência que o editor mostra.

Uso: uv run python tests/test_fap_review_training.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.services.fap_review_service import (  # noqa: E402
    TRAINING_TARGETS,
    accepted_edits,
    apply_chat_decision,
    apply_reference_edits,
    chat_state,
    decision_for,
    edit_id_for,
    edits_from_messages,
    record_chat_save,
    summarize_chat_execution,
    build_training_edit_groups,
    effective_edit_kind,
    parse_training_edit_selection,
    build_edit_preview,
    verify_reference_edit,
    verify_reference_edits,
    append_to_reference_content,
    summarize_training_execution,
)

PASSED = 0
FAILED = 0

MANUAL = """### 1.1 DADOS FACTUAIS

- [ ] **Razao social** — conferir a grafia em todo o documento.

### 1.6 REDACAO E FORMATACAO

- [ ] **Regencia** — escrever "indice do FAP".
- [ ] **Datas** — usar "em DD/MM/AAAA".
"""


EXTRACT = {
    'comparison_summary': 'A revisão padronizou a razão social e retirou pedido sem lastro.',
    'key_changes': ['Razão social padronizada', 'Pedido genérico retirado'],
    'manual_patch_markdown': '### Categoria 3 — Pedido sem lastro na planilha\n\nNão incluir pedido genérico.',
    'case_reference_markdown': '## Caso 24 — Whirlpool S.A., vigência 2024',
    'training_ready': True,
}


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def run():
    EDICOES = [
        {'target': 'manual_fap', 'kind': 'substitution', 'section': '1.6 REDACAO E FORMATACAO',
         'anchor': '- [ ] **Regencia** — escrever "indice do FAP".',
         'new_text': '- [ ] **Regencia em expressoes tecnicas** — "indice do FAP", "na vigencia de".',
         'rationale': 'A regra cobre um caso; a revisao mostrou mais cinco.',
         'evidence': ['40x regencia']},
        {'target': 'manual_fap', 'kind': 'addition', 'section': '1.1 DADOS FACTUAIS',
         'anchor': '- [ ] **Razao social** — conferir a grafia em todo o documento.',
         'new_text': '- [ ] **Autoria do erro** — imputar a Previdencia Social.',
         'rationale': 'Regra nova.', 'evidence': ['2x merito']},
        {'target': 'casos_referencia', 'kind': 'addition', 'section': '',
         'anchor': '', 'new_text': '## Caso 24 — Sodexo', 'rationale': 'Registro do caso.'},
    ]

    print("[1] Um bloco por destino, só com as edições daquele destino")
    grupos = build_training_edit_groups(
        EDICOES,
        {'manual_fap': 12, 'casos_referencia': 7},
        {'manual_fap': MANUAL, 'casos_referencia': '## Caso 23'},
    )
    por_chave = {g['key']: g for g in grupos}
    check("dois destinos", len(grupos) == 2, f"(obteve {len(grupos)})")
    check("manual com duas edições", len(por_chave['manual_fap']['edits']) == 2)
    check("casos com uma", len(por_chave['casos_referencia']['edits']) == 1)
    check("versão real, não inventada",
          por_chave['manual_fap']['current_version'] == 12
          and por_chave['manual_fap']['next_version'] == 13,
          f"(obteve {por_chave['manual_fap']['current_version']})")

    print("[2] Cada edição chega conferida e com o diff pronto")
    primeira = por_chave['manual_fap']['edits'][0]
    check("id é a posição na lista", primeira['id'] == 0)
    check("status conferido", primeira['status'] == 'ok', f"(obteve {primeira['status']})")
    check("traz o diff", primeira['preview']['status'] == 'ok' and primeira['preview']['lines'])
    check("conta quantas são aplicáveis", por_chave['manual_fap']['applicable'] == 2,
          f"(obteve {por_chave['manual_fap']['applicable']})")

    print("[3] Edição com âncora quebrada vem marcada, não some")
    grupos = build_training_edit_groups(
        [dict(EDICOES[0], anchor='trecho que nao existe no manual')],
        {'manual_fap': 12}, {'manual_fap': MANUAL})
    edicao = grupos[0]['edits'][0]
    check("continua na lista", len(grupos[0]['edits']) == 1)
    check("marcada como bloqueada", edicao['status'] == 'not_found')
    check("nenhuma aplicável", grupos[0]['applicable'] == 0)
    check("o diff explica", edicao['preview']['header'] == 'trecho não localizado')

    print("[4] Destino sem edição não vira bloco")
    grupos = build_training_edit_groups(
        [EDICOES[2]], {'casos_referencia': 7}, {'casos_referencia': ''})
    check("só o destino que tem edição", [g['key'] for g in grupos] == ['casos_referencia'],
          f"(obteve {[g['key'] for g in grupos]})")
    check("lista vazia não vira bloco", build_training_edit_groups([], {}, {}) == [])

    print("[5] Só grava o que foi marcado")
    selecao = parse_training_edit_selection(['0', '2'], EDICOES)
    check("duas edições", len(selecao) == 2, f"(obteve {len(selecao)})")
    check("são as marcadas", [s['id'] for s in selecao] == [0, 2])
    check("nenhuma marcada não grava nada", parse_training_edit_selection([], EDICOES) == [])
    check("id inventado é ignorado", parse_training_edit_selection(['99', 'abc'], EDICOES) == [])

    print("[6] O texto editado à mão vence o da IA")
    selecao = parse_training_edit_selection(['0'], EDICOES, {'0': '  Regra reescrita à mão.  '})
    check("texto do formulário prevalece", selecao[0]['new_text'] == '  Regra reescrita à mão.  ',
          f"(obteve {selecao[0]['new_text']!r})")
    check("a edição original não foi mutada",
          EDICOES[0]['new_text'].startswith('- [ ] **Regencia em expressoes'),
          "(parse não pode alterar a lista recebida)")

    print("[7] Caixa esvaziada não grava")
    check("texto em branco cai fora",
          parse_training_edit_selection(['0'], EDICOES, {'0': '   '}) == [])

    print("[8] Listagem lê os destinos do caminho certo do JSON")
    resumo = summarize_training_execution('completed', {
        'stage': 'applied',
        'applied': {
            'activated': True,
            'targets': [
                {'key': 'manual_fap', 'label': 'Manual de revisão FAP', 'version_number': 13, 'activated': True},
                {'key': 'casos_referencia', 'label': 'Casos de referência', 'version_number': 8, 'activated': False},
            ],
        },
    })
    check("situação concluída", resumo['situation']['label'] == 'Concluída')
    check("dois destinos", len(resumo['targets']) == 2, f"(obteve {len(resumo['targets'])})")
    check("versão do manual", resumo['targets'][0]['version_number'] == 13)
    check("rascunho não aparece como ativado", resumo['targets'][1]['activated'] is False)

    print("[9] Execuções antigas continuam legíveis (formato training_result)")
    resumo = summarize_training_execution('completed', {
        'stage': 'applied',
        'training_result': {
            'manual_updates_generated': True,
            'reference_versions': {'manual_fap': 12, 'casos_referencia': None},
        },
    })
    check("destino recuperado do formato antigo",
          len(resumo['targets']) == 1 and resumo['targets'][0]['version_number'] == 12,
          f"(obteve {resumo['targets']})")
    check("casos sem versão não vira linha",
          all(t['key'] != 'casos_referencia' for t in resumo['targets']))

    print("[10] Situações da listagem")
    check("pendente é 'Aguardando sua confirmação'",
          summarize_training_execution('pending', {})['situation']['label'] == 'Aguardando sua confirmação')
    check("pendente é sinalizado para o botão Retomar",
          summarize_training_execution('pending', {})['is_pending'] is True)
    check("processando", summarize_training_execution('processing', {})['is_processing'] is True)
    check("erro", summarize_training_execution('failed', {})['situation']['style'] == 'danger')
    check("status desconhecido não quebra a linha",
          summarize_training_execution('etc', None)['situation']['style'] == 'secondary')

    print("[11] O agente devolve edições ancoradas")
    from app.agents.fap_review.training_apply_agent import ComparisonExtract, ReferenceEdit  # noqa: E402
    check("ComparisonExtract.edits", 'edits' in ComparisonExtract.model_fields)
    for campo in ('target', 'kind', 'section', 'anchor', 'new_text', 'rationale', 'evidence'):
        check(f"ReferenceEdit.{campo}", campo in ReferenceEdit.model_fields)
    check("destinos conhecidos batem com os do serviço",
          {t['key'] for t in TRAINING_TARGETS} == {'manual_fap', 'casos_referencia'})

    print("[12] O selo sai do diff, não do que o modelo declarou")
    linhas_troca = {'lines': [{'kind': 'ctx'}, {'kind': 'del'}, {'kind': 'ins'}]}
    linhas_so_insere = {'lines': [{'kind': 'ctx'}, {'kind': 'ins'}]}

    check("declarou substituição e o diff troca mesmo → substituição",
          effective_edit_kind('substitution', linhas_troca) == 'substitution')
    check("declarou substituição mas nada sai → adição",
          effective_edit_kind('substitution', linhas_so_insere) == 'addition',
          "(o modelo monta 'âncora + regra nova' e chama de substituição)")
    check("refinamento é preservado quando o diff troca",
          effective_edit_kind('refinement', linhas_troca) == 'refinement',
          "(refinamento e substituição têm a mesma mecânica; só a intenção separa)")
    check("adição continua adição", effective_edit_kind('addition', linhas_so_insere) == 'addition')
    check("sem diff, mantém o declarado", effective_edit_kind('substitution', {}) == 'substitution')
    check("sem nada não quebra", effective_edit_kind(None, None) == '')

    grupos = build_training_edit_groups(
        [{'target': 'manual_fap', 'kind': 'substitution',
          'anchor': '- [ ] **Regencia** — escrever "indice do FAP".',
          'new_text': '- [ ] **Regencia** — escrever "indice do FAP".\n- [ ] **Datas e prazos** — nova regra.'}],
        {'manual_fap': 1}, {'manual_fap': MANUAL})
    check("na montagem do bloco, o selo já vem corrigido",
          grupos[0]['edits'][0]['effective_kind'] == 'addition',
          f"(obteve {grupos[0]['edits'][0]['effective_kind']!r})")

    print("[13] Âncora encontrada uma vez: edição aplicável")
    edicao = {
        'target': 'manual_fap', 'kind': 'substitution',
        'anchor': '- [ ] **Regencia** — escrever "indice do FAP".',
        'new_text': '- [ ] **Regencia em expressoes tecnicas** — "indice do FAP", "na vigencia de".',
    }
    check("status ok", verify_reference_edit(edicao, MANUAL)['status'] == 'ok')
    novo, aplicadas = apply_reference_edits(MANUAL, [edicao])
    check("o trecho antigo saiu", '- [ ] **Regencia** — escrever "indice do FAP".' not in novo)
    check("o novo entrou", 'expressoes tecnicas' in novo)
    check("o resto do manual ficou intacto", '### 1.1 DADOS FACTUAIS' in novo and '**Datas**' in novo)
    check("registrada como aplicada", aplicadas[0]['status'] == 'applied')

    print("[14] Âncora que não existe é recusada, não aplicada no lugar errado")
    inventada = dict(edicao, anchor='- [ ] **Regencia** — sempre usar indice do FAP nas secoes tecnicas.')
    conferida = verify_reference_edit(inventada, MANUAL)
    check("status not_found", conferida['status'] == 'not_found', f"(obteve {conferida['status']})")
    check("tem motivo legível", 'não existe no documento' in (conferida['blocked_reason'] or ''))
    intacto, aplicadas = apply_reference_edits(MANUAL, [inventada])
    check("o manual não foi tocado", intacto == MANUAL)
    check("a edição consta como bloqueada", aplicadas[0]['status'] == 'not_found')

    print("[15] Âncora ambígua também é recusada")
    repetido = 'Uma linha.\nOutra.\nUma linha.'
    conferida = verify_reference_edit(
        {'kind': 'substitution', 'anchor': 'Uma linha.', 'new_text': 'X'}, repetido)
    check("status ambiguous", conferida['status'] == 'ambiguous', f"(obteve {conferida['status']})")
    check("explica o porquê", 'mais de uma vez' in (conferida['blocked_reason'] or ''))

    print("[16] Edição malformada não passa")
    for edicao_ruim, esperado in (
        ({'kind': 'substitution', 'anchor': '', 'new_text': 'X'}, 'no_anchor'),
        ({'kind': 'addition', 'anchor': '', 'new_text': '  '}, 'no_text'),
        ({'kind': 'apagar_tudo', 'anchor': 'x', 'new_text': 'y'}, 'bad_kind'),
        ({}, 'bad_kind'),
    ):
        obtido = verify_reference_edit(edicao_ruim, MANUAL)['status']
        check(f"{esperado}", obtido == esperado, f"(obteve {obtido})")

    print("[17] Adição entra depois da âncora; sem âncora, no fim")
    novo, _ = apply_reference_edits(MANUAL, [{
        'kind': 'addition', 'anchor': '- [ ] **Datas** — usar "em DD/MM/AAAA".',
        'new_text': '- [ ] **Travessao** — usar en dash.',
    }])
    check("veio logo depois da âncora",
          '- [ ] **Datas** — usar "em DD/MM/AAAA".\n- [ ] **Travessao** — usar en dash.' in novo,
          f"(obteve …{novo[-140:]!r})")

    novo, _ = apply_reference_edits(MANUAL, [{
        'kind': 'addition', 'anchor': '', 'new_text': '## Caso 24 — Sodexo'}])
    check("sem âncora vai para o fim", novo.rstrip().endswith('## Caso 24 — Sodexo'))

    print("[18] Cada edição é reconferida contra o texto já modificado")
    primeira = {'kind': 'substitution',
                'anchor': '- [ ] **Datas** — usar "em DD/MM/AAAA".',
                'new_text': '- [ ] **Datas e prazos** — usar "em DD/MM/AAAA".'}
    segunda = {'kind': 'addition',
               'anchor': '- [ ] **Datas** — usar "em DD/MM/AAAA".',   # a primeira apagou esta âncora
               'new_text': '- [ ] **Travessao** — usar en dash.'}
    novo, aplicadas = apply_reference_edits(MANUAL, [primeira, segunda])
    check("a primeira aplicou", aplicadas[0]['status'] == 'applied')
    check("a segunda foi bloqueada, não aplicada no lugar errado",
          aplicadas[1]['status'] == 'not_found', f"(obteve {aplicadas[1]['status']})")
    check("o texto da segunda não entrou", 'Travessao' not in novo)

    print("[19] Diff da edição, no formato da tela")
    preview = build_edit_preview(MANUAL, edicao)
    check("status ok", preview['status'] == 'ok')
    check("cabeçalho aponta a linha", preview['header'] == 'linha 7', f"(obteve {preview['header']!r})")
    tipos = [linha['kind'] for linha in preview['lines']]
    check("tem remoção e inserção", 'del' in tipos and 'ins' in tipos, f"(obteve {tipos})")
    check("tem contexto em volta", tipos.count('ctx') >= 2, f"(obteve {tipos})")
    numeros = [linha['number'] for linha in preview['lines'] if linha['kind'] != 'ins']
    check("numeração é a do documento atual", numeros == sorted(numeros), f"(obteve {numeros})")

    print("[20] Diff de edição bloqueada mostra o que entraria e o motivo")
    preview = build_edit_preview(MANUAL, inventada)
    check("status carrega o bloqueio", preview['status'] == 'not_found')
    check("cabeçalho avisa", preview['header'] == 'trecho não localizado')
    check("linhas sem número real", all(l['number'] == '?' for l in preview['lines']))

    print("[21] Verificação em lote usa o conteúdo de cada destino")
    conferidas = verify_reference_edits(
        [
            dict(edicao, target='manual_fap'),
            {'target': 'casos_referencia', 'kind': 'addition', 'anchor': '', 'new_text': '## Caso 24'},
            dict(edicao, target='casos_referencia'),   # a âncora do manual não existe nos casos
        ],
        {'manual_fap': MANUAL, 'casos_referencia': '## Caso 23\nTexto.'},
    )
    check("manual ok", conferidas[0]['status'] == 'ok')
    check("caso novo no fim ok", conferidas[1]['status'] == 'ok')
    check("âncora do manual não vale nos casos", conferidas[2]['status'] == 'not_found',
          f"(obteve {conferidas[2]['status']})")

    print("[23] Edições da conversa recebem id estável por mensagem")
    class Msg:
        def __init__(self, id, role, edits_json=None):
            self.id, self.role, self.edits_json = id, role, edits_json
    mensagens = [
        Msg(10, 'user'),
        Msg(11, 'assistant', json.dumps([{'target': 'manual_fap', 'kind': 'addition', 'anchor': '', 'new_text': 'A'},
                                         {'target': 'casos_referencia', 'kind': 'addition', 'anchor': '', 'new_text': 'B'}])),
        Msg(12, 'user'),
        Msg(13, 'assistant', json.dumps([{'target': 'manual_fap', 'kind': 'addition', 'anchor': '', 'new_text': 'C'}])),
        Msg(14, 'assistant', 'json quebrado {'),
    ]
    por_id = edits_from_messages(mensagens)
    check("três edições", len(por_id) == 3, f"(obteve {sorted(por_id)})")
    check("id é mensagem-posição", set(por_id) == {'11-0', '11-1', '13-0'}, f"(obteve {sorted(por_id)})")
    check("o id vai dentro da edição", por_id['11-1']['id'] == '11-1')
    check("json quebrado é ignorado, não derruba", '14-0' not in por_id)
    check("helper de id bate", edit_id_for(11, 1) == '11-1')

    print("[24] Aceitar / recusar / desfazer, sem gravar nada")
    payload = {}
    payload = apply_chat_decision(payload, '11-0', 'accept')
    check("aceita entra", chat_state(payload)['accepted'] == ['11-0'])
    payload = apply_chat_decision(payload, '11-1', 'refuse')
    check("recusada entra na outra lista", chat_state(payload)['refused'] == ['11-1'])
    payload = apply_chat_decision(payload, '11-1', 'accept')
    check("aceitar tira de recusadas", chat_state(payload)['refused'] == [])
    check("e ordena por aceite", chat_state(payload)['accepted'] == ['11-0', '11-1'])
    payload = apply_chat_decision(payload, '11-0', 'undo')
    check("desfazer tira das duas", '11-0' not in chat_state(payload)['accepted'])
    check("estado consultável", decision_for(payload, '11-1') == 'accepted'
          and decision_for(payload, '11-0') == 'open')
    try:
        apply_chat_decision(payload, '11-0', 'apagar'); check("decisão inválida é recusada", False)
    except ValueError:
        check("decisão inválida é recusada", True)

    print("[25] A bandeja é o que foi aceito, na ordem, com o texto da proposta")
    payload = apply_chat_decision({}, '13-0', 'accept')
    payload = apply_chat_decision(payload, '11-0', 'accept')
    bandeja = accepted_edits(payload, por_id)
    check("duas na bandeja", [e['id'] for e in bandeja] == ['13-0', '11-0'], f"(obteve {[e['id'] for e in bandeja]})")
    check("com o texto", bandeja[0]['new_text'] == 'C')
    check("id de mensagem apagada não quebra", accepted_edits(apply_chat_decision({}, '99-9', 'accept'), por_id) == [])

    print("[26] Gravar esvazia a bandeja e registra a versão")
    payload = record_chat_save(payload, [{'key': 'manual_fap', 'label': 'Manual', 'version_number': 4,
                                          'activated': True, 'edits': 2}], True, '26/08/2026 10:00')
    check("bandeja vazia", chat_state(payload)['accepted'] == [])
    check("gravação registrada", len(chat_state(payload)['saved']) == 1)
    check("com os ids que entraram", chat_state(payload)['saved'][0]['edit_ids'] == ['13-0', '11-0'])
    resumo = summarize_chat_execution('pending', payload, 'Datas de acidente')
    check("lista mostra a versão gravada", resumo['targets'][0]['version_number'] == 4)
    check("em andamento enquanto não encerra", resumo['situation']['label'] == 'Em andamento')
    check("é conversa", resumo['is_chat'] is True)
    pendente = summarize_chat_execution('pending', apply_chat_decision({}, '11-0', 'accept'), '')
    check("nota de pendência", pendente['pending_note'] == '1 aceita, não salva', f"(obteve {pendente['pending_note']!r})")
    check("encerrada vira concluída", summarize_chat_execution('completed', {}, '')['situation']['label'] == 'Concluída')

    print("[22] Templates compilam e as rotas existem")
    from main import app  # noqa: E402  (importa a app inteira: mais lento)
    for template_name in ('fap_review/training.html', 'fap_review/training_comparison.html',
                          'fap_review/training_chat.html', 'fap_review/_training_edit_card.html',
                          'fap_review/_training_chat_message.html', 'fap_review/_training_chat_tray.html'):
        try:
            app.jinja_env.get_template(template_name)
            check(f"{template_name} compila", True)
        except Exception as error:
            check(f"{template_name} compila", False, f"({error})")

    rules = {rule.endpoint for rule in app.url_map.iter_rules()}
    for endpoint in ('fap_review.training', 'fap_review.training_compare', 'fap_review.training_comparison',
                     'fap_review.training_apply', 'fap_review.training_chat_start', 'fap_review.training_chat',
                     'fap_review.training_chat_message', 'fap_review.training_chat_decision',
                     'fap_review.training_chat_save', 'fap_review.training_chat_close'):
        check(f"{endpoint} registrada", endpoint in rules)


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
