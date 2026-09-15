#!/usr/bin/env python3
"""
Testes das regras da remessa R02 no Revisor de Petições
(app/services/fap_review_service.py).

Quase tudo é função pura — sem banco, rede nem contexto Flask. A exceção é o
teste 20, que confere a query agregada do RPI-04 contra o banco local.

    uv run python tests/test_fap_review_r02.py
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.fap_review_service import (
    MODEL_NOT_RECORDED,
    SEM_REVISOR,
    agrupar_peticoes_por_advogado,
    describe_model_name,
    validate_wrike_identifier,
)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# ── RPI-23 — Id Wrike aceita só números ─────────────────────────────────

def test_wrike_aceita_numero():
    print('\n1. RPI-23 — identificador numérico é aceito')

    valor, erro = validate_wrike_identifier('1790631885')
    check('sem erro', erro is None, str(erro))
    check('devolve o valor', valor == '1790631885', repr(valor))


def test_wrike_apara_espacos_das_pontas():
    print('\n2. RPI-23 — espaço nas pontas não invalida')

    valor, erro = validate_wrike_identifier('  1790631885 \n')
    check('sem erro', erro is None, str(erro))
    check('valor aparado', valor == '1790631885', repr(valor))


def test_wrike_preserva_zero_a_esquerda():
    print('\n3. RPI-23 — é identificador, não número: zero à esquerda fica')

    valor, erro = validate_wrike_identifier('0079')
    check('sem erro', erro is None, str(erro))
    check('zero preservado', valor == '0079', repr(valor))


def test_wrike_recusa_letras():
    print('\n4. RPI-23 — texto é recusado')

    for entrada in ('ABC-123', '1790631885x', '#1790631885',
                    'https://wrike.com/open.htm?id=1790631885'):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)
        if erro:
            check(f'mensagem de {entrada!r} fala em números', 'número' in erro.lower(), erro)
            break


def test_wrike_recusa_espaco_no_meio():
    print('\n5. RPI-23 — espaço no meio quebraria a busca')

    _, erro = validate_wrike_identifier('1790 631885')
    check('recusa', erro is not None)


def test_wrike_recusa_vazio():
    print('\n6. RPI-23 — campo é obrigatório')

    for entrada in ('', '   ', None):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)
        if erro:
            check('mensagem pede o preenchimento', 'informe' in erro.lower(), erro)


def test_wrike_recusa_longo_demais():
    print('\n7. RPI-23 — limite da coluna continua valendo')

    _, erro = validate_wrike_identifier('9' * 97)
    check('recusa 97 dígitos', erro is not None)
    if erro:
        check('mensagem fala do limite', '96' in erro, erro)

    _, erro_ok = validate_wrike_identifier('9' * 96)
    check('aceita 96 dígitos', erro_ok is None, str(erro_ok))


def test_wrike_erros_sao_distintos():
    print('\n8. RPI-23 — formato e obrigatoriedade têm mensagens diferentes')

    _, vazio = validate_wrike_identifier('')
    _, formato = validate_wrike_identifier('ABC')
    check('mensagens distintas', vazio != formato, f'{vazio!r} == {formato!r}')


def test_wrike_recusa_digito_nao_ascii():
    print('\n8b. RPI-23 — dígito unicode não é dígito para a busca')

    # 'isdigit()' do Python aceita '²' e '١٢٣'. Passariam na validação e
    # quebrariam exatamente a busca por Id que o requisito quer proteger.
    for entrada in ('179063188\u00b2', '\u0661\u0662\u0663'):
        _, erro = validate_wrike_identifier(entrada)
        check(f'recusa {entrada!r}', erro is not None)


# ── RPI-18 — o debug não pode inventar o modelo ─────────────────────────

def test_modelo_registrado_aparece():
    print('\n9. RPI-18 — modelo gravado é exibido como está')

    check('sonnet', describe_model_name('claude-sonnet-5') == 'claude-sonnet-5')
    check('gpt', describe_model_name('gpt-4o-mini') == 'gpt-4o-mini')


def test_modelo_ausente_nao_e_chutado():
    print('\n10. RPI-18 — execução antiga não recebe palpite')

    # Foi um literal chutado no template que criou o RPI-18: com a coluna
    # inexistente, o Jinja caía sempre em 'gpt-4o-mini' e mentia sobre o Sonnet.
    for vazio in (None, '', '   '):
        rotulo = describe_model_name(vazio)
        check(f'{vazio!r} vira rótulo de ausência', rotulo == MODEL_NOT_RECORDED, repr(rotulo))
        check(f'{vazio!r} não vira nome de modelo', 'gpt' not in rotulo.lower(), repr(rotulo))


# ── RPI-19 — a barra de aprovação não pode viver dentro dos achados ─────

_TAG_IF = re.compile(r'{%-?\s*(if|endif)\b')


def _fim_do_bloco(texto: str, inicio: int) -> int:
    """Posição logo após o {% endif %} que fecha o {% if %} em `inicio`."""
    profundidade = 0
    for m in _TAG_IF.finditer(texto, inicio):
        profundidade += 1 if m.group(1) == 'if' else -1
        if profundidade == 0:
            return texto.index('%}', m.end()) + 2
    raise AssertionError('bloco Jinja sem fechamento')


def barra_esta_fora_do_bloco_de_achados(html: str) -> bool:
    """A barra de conclusão da triagem existe fora do `if result_data.findings`?"""
    ini_findings = html.index('{% if result_data.findings %}')
    fim_findings = _fim_do_bloco(html, ini_findings)
    pos_barra = html.index('id="triageCompleteActions"')
    return not (ini_findings < pos_barra < fim_findings)


def test_barra_de_aprovacao_sobrevive_a_revisao_sem_achados():
    print('\n11. RPI-19 — aprovar petição sem nenhum erro')

    # Com a barra aninhada no bloco de achados, uma revisão que não encontra
    # nada não renderiza o botão: a regra de negócio libera a aprovação, mas a
    # página não tem por onde. Foi o que travou o caso do João.
    html = (RAIZ / 'templates/fap_review/revision_result.html').read_text()

    check('barra fica fora do bloco de achados',
          barra_esta_fora_do_bloco_de_achados(html))
    check('texto cobre o caso de zero achados',
          'Nenhum ponto de atenção nesta revisão' in html)



# ── RPI-04 — contador por advogado e por situação ───────────────────────

def _linhas(*tuplas):
    """Linhas como a query agregada devolve: (user_id, nome, status, quantidade)."""
    return list(tuplas)


def test_rpi04_agrupa_e_soma_por_advogado():
    print('\n13. RPI-04 — cada advogado vira uma linha, com o total somado')

    grupos = agrupar_peticoes_por_advogado(_linhas(
        (7, 'Rodrigo', 'in_review', 3),
        (7, 'Rodrigo', 'awaiting_approval', 5),
        (7, 'Rodrigo', 'ready_for_filing', 4),
        (9, 'Isrhael', 'in_review', 2),
    ))
    check('dois advogados', len(grupos) == 2, str(len(grupos)))
    rodrigo = next((g for g in grupos if g['name'] == 'Rodrigo'), None)
    check('total do Rodrigo é 12', rodrigo and rodrigo['total'] == 12,
          str(rodrigo['total']) if rodrigo else 'ausente')
    check('mantém a quebra por status',
          rodrigo and rodrigo['por_status'].get('awaiting_approval') == 5)
    check('guarda o id para o filtro da tela',
          rodrigo and rodrigo['user_id'] == 7)


def test_rpi04_ordena_por_volume():
    print('\n14. RPI-04 — quem tem mais petições aparece primeiro')

    grupos = agrupar_peticoes_por_advogado(_linhas(
        (9, 'Isrhael', 'in_review', 2),
        (7, 'Rodrigo', 'in_review', 12),
        (3, 'Ana', 'in_review', 2),
    ))
    check('o maior vem primeiro', grupos[0]['name'] == 'Rodrigo', grupos[0]['name'])
    # Empate no total: ordem alfabética, para a lista não dançar entre recargas.
    check('empate desempata por nome',
          [g['name'] for g in grupos[1:]] == ['Ana', 'Isrhael'],
          str([g['name'] for g in grupos[1:]]))


def test_rpi04_peticao_sem_revisor():
    print('\n15. RPI-04 — petição sem revisão fica visível, não some')

    grupos = agrupar_peticoes_por_advogado(_linhas(
        (7, 'Rodrigo', 'in_review', 3),
        (None, None, 'new', 4),
    ))
    sem = next((g for g in grupos if g['user_id'] is None), None)
    check('vira um grupo próprio', sem is not None)
    check('com rótulo explícito', sem and sem['name'] == SEM_REVISOR, sem['name'] if sem else '')
    # Vai por último mesmo tendo mais petições: não é advogado, é ausência de um.
    check('fica por último', grupos[-1]['user_id'] is None)


def test_rpi04_ignora_linha_sem_quantidade():
    print('\n16. RPI-04 — status zerado não cria advogado fantasma')

    grupos = agrupar_peticoes_por_advogado(_linhas(
        (7, 'Rodrigo', 'in_review', 3),
        (9, 'Isrhael', 'in_review', 0),
    ))
    check('só quem tem petição aparece', len(grupos) == 1, str(len(grupos)))


def test_rpi04_lista_vazia():
    print('\n17. RPI-04 — escritório sem petição não quebra a tela')

    check('devolve lista vazia', agrupar_peticoes_por_advogado([]) == [])


def test_rpi04_seletor_existe_na_tela():
    print('\n18. RPI-04 — o seletor de advogado está na listagem')

    index = (RAIZ / 'templates' / 'fap_review' / 'index.html').read_text(encoding='utf-8')
    check('há chip de advogado', 'lawyer-chip' in index)
    check('a linha carrega o id do revisor para o 2º nível',
          'data-reviewer' in index)
    check('o JS filtra por advogado', 'activeLawyer' in index)


def test_rpi04_busca_textual_filtra_dentro_da_selecao():
    print('\n19. RPI-04 — a busca é o 2º nível, não substitui o 1º')

    index = (RAIZ / 'templates' / 'fap_review' / 'index.html').read_text(encoding='utf-8')
    trecho = re.search(r'function applyFilters\(\)\s*\{.*?\n        \}', index, re.S)
    check('applyFilters existe', trecho is not None)
    corpo = trecho.group(0) if trecho else ''
    check('a visibilidade exige advogado E busca E status',
          'matchesLawyer' in corpo and 'matchesSearch' in corpo and 'matchesFilter' in corpo,
          'faltou combinar os três níveis')


def test_rpi04_contagem_bate_com_o_banco():
    print('\n20. RPI-04 — a soma dos contadores bate com a listagem')

    from main import app
    from app.models import FapReviewPetition
    from app.services.fap_review_service import lawyer_petition_counts

    with app.app_context():
        firm = FapReviewPetition.query.with_entities(
            FapReviewPetition.law_firm_id).first()
        if not firm:
            check('sem petições no banco local — nada a conferir', True)
            return
        law_firm_id = firm[0]

        grupos = lawyer_petition_counts(law_firm_id)
        somado = sum(g['total'] for g in grupos)
        listadas = FapReviewPetition.query.filter(
            FapReviewPetition.law_firm_id == law_firm_id,
            FapReviewPetition.workflow_status != 'archived',
        ).count()
        check('soma dos advogados = petições não arquivadas',
              somado == listadas, f'{somado} contra {listadas}')

        # Arquivada fora da conta é decisão, não descuido: a listagem também a
        # esconde por padrão, e um contador que não bate com o que se vê mente.
        arquivadas = FapReviewPetition.query.filter_by(
            law_firm_id=law_firm_id, workflow_status='archived').count()
        check('arquivadas ficam fora da conta',
              'archived' not in {s for g in grupos for s in g['por_status']},
              f'{arquivadas} arquivada(s) no banco')


# ── RPI-09 — arquivar pela lista, com reflexo nas estatísticas ──────────

def test_rpi09_botao_arquivar_na_lista():
    print('\n21. RPI-09 — arquivar direto da linha da lista')

    index = (RAIZ / 'templates' / 'fap_review' / 'index.html').read_text(encoding='utf-8')
    check('a linha tem botão de arquivar', 'archive-petition-btn' in index)
    # Mesma regra do botão do detalhe: fora de aprovação só admin arquiva, e o
    # endpoint já recusa. Botão que aparece e depois dá 403 é pior que nenhum.
    trecho = re.search(r'\{%-? if petition\.workflow_status != \'archived\'[^%]*%\}\s*'
                       r'<button type="button" class="btn btn-sm btn-outline-dark archive-petition-btn',
                       index)
    check('só aparece para quem pode arquivar', trecho is not None)
    check('confirma antes de arquivar', "Arquivar \"${title}\"?" in index)
    check('usa a rota de status que já existe',
          "workflow_status: 'archived'" in index)


def _escritorio_com_uma_arquivada():
    """Escritório descartável: uma petição ativa e uma arquivada, uma revisão cada."""
    import json as _json
    from main import app
    from app.models import db, LawFirm, User, FapReviewPetition, FapReviewExecution

    firm = LawFirm(name='__TESTE_RPI09__', cnpj='00000000000191')
    db.session.add(firm); db.session.flush()
    user = User(law_firm_id=firm.id, name='Advogada Teste', email='rpi09@teste.invalid',
                password_hash='x', role='admin')
    db.session.add(user); db.session.flush()

    achados = _json.dumps({'findings': [
        {'category': 'CAT-1', 'severity': 'CRÍTICO', 'description': 'x'},
        {'category': 'CAT-2', 'severity': 'FORMAL', 'description': 'y'},
    ]})
    peticoes = []
    for titulo, status, wrike in (('Ativa', 'in_review', '101'), ('Caso de teste', 'archived', '102')):
        pet = FapReviewPetition(law_firm_id=firm.id, title=titulo,
                                office_document_identifier=wrike, workflow_status=status)
        db.session.add(pet); db.session.flush()
        exe = FapReviewExecution(law_firm_id=firm.id, user_id=user.id, petition_id=pet.id,
                                 execution_type='revision', status='completed',
                                 revision_number=1, result_json=achados)
        db.session.add(exe); db.session.flush()
        pet.latest_revision_id = exe.id
        peticoes.append(pet)
    db.session.commit()
    return firm, user


def _remover_escritorio(firm_id):
    from app.models import (db, LawFirm, User, UserPageVisit, FapReviewSetting,
                            FapReviewAuditLog, FapReviewPetition, FapReviewExecution)
    db.session.rollback()
    # A tela de treinamento cria as configurações padrão do escritório no acesso.
    FapReviewSetting.query.filter_by(law_firm_id=firm_id).delete()
    # Abrir a tela pelo test_client grava visita de página (middleware de
    # auditoria de acesso) — sem apagá-la, a FK impede remover o usuário.
    UserPageVisit.query.filter_by(law_firm_id=firm_id).delete()
    FapReviewAuditLog.query.filter_by(law_firm_id=firm_id).delete()
    FapReviewPetition.query.filter_by(law_firm_id=firm_id).update({'latest_revision_id': None})
    FapReviewExecution.query.filter_by(law_firm_id=firm_id).delete()
    FapReviewPetition.query.filter_by(law_firm_id=firm_id).delete()
    User.query.filter_by(law_firm_id=firm_id).delete()
    LawFirm.query.filter_by(id=firm_id).delete()
    db.session.commit()


def test_rpi09_estatisticas_ignoram_arquivadas():
    print('\n22. RPI-09 — petição arquivada sai dos números')

    from main import app
    from app.models import db, LawFirm
    from app.services.fap_review_service import build_lawyer_statistics

    with app.app_context():
        velho = LawFirm.query.filter_by(name='__TESTE_RPI09__').first()
        if velho:
            _remover_escritorio(velho.id)
        firm, user = _escritorio_com_uma_arquivada()
        firm_id, user_id, role, nome = firm.id, user.id, user.role, user.name
        try:
            stats = build_lawyer_statistics(firm_id)
            advogado = stats['lawyers'][0] if stats['lawyers'] else {}
            check('desempenho conta só a revisão da petição ativa',
                  advogado.get('total_revisions') == 1, str(advogado.get('total_revisions')))
            check('achados da arquivada não entram',
                  advogado.get('total_findings') == 2, str(advogado.get('total_findings')))
            check('visão geral também', stats['overview'].get('total_revisions') == 1,
                  str(stats['overview'].get('total_revisions')))

            client = app.test_client()
            with client.session_transaction() as sessao:
                sessao.update(user_id=user_id, law_firm_id=firm_id, user_role=role, user_name=nome)
            html = client.get('/fap-review/').data.decode('utf-8')
            valores = re.findall(r'<div class="sc-value">\s*([^<]+?)\s*</div>', html)
            check('card "total de petições" não conta a arquivada',
                  bool(valores) and valores[0] == '1', str(valores[:1]))
            check('"revisões realizadas" não conta a da arquivada',
                  '1 revisões realizadas' in html,
                  (re.search(r'\d+ revisões realizadas', html) or [''])[0])
            check('a arquivada continua acessível pelo filtro próprio',
                  'Arquivadas (1)' in html)
        finally:
            _remover_escritorio(firm_id)


# ── RPI-02 (parte do histórico) — lotes de treinamento sem corte em 12 ──

def test_rpi02_historico_paginado_com_usuario():
    print('\n23. RPI-02 — histórico de treinamento completo, paginado, com quem rodou')

    from datetime import datetime, timedelta
    from main import app
    from app.models import db, LawFirm, User, FapReviewExecution

    with app.app_context():
        velho = LawFirm.query.filter_by(name='__TESTE_RPI09__').first()
        if velho:
            _remover_escritorio(velho.id)
        firm = LawFirm(name='__TESTE_RPI09__', cnpj='00000000000191')
        db.session.add(firm); db.session.flush()
        user = User(law_firm_id=firm.id, name='Advogada Treino', email='rpi02@teste.invalid',
                    password_hash='x', role='admin')
        db.session.add(user); db.session.flush()
        base = datetime(2026, 9, 1, 8, 0)
        for i in range(25):
            db.session.add(FapReviewExecution(
                law_firm_id=firm.id, user_id=user.id, execution_type='training',
                status='completed', main_document_filename=f'lote-{i:02d}.docx',
                created_at=base + timedelta(hours=i)))
        db.session.commit()
        firm_id, user_id = firm.id, user.id

        try:
            client = app.test_client()
            with client.session_transaction() as sessao:
                sessao.update(user_id=user_id, law_firm_id=firm_id, user_role='admin', user_name='Advogada Treino')

            html = client.get('/fap-review/training').data.decode('utf-8')
            ids = re.findall(r'<td class="ps-3"><span class="text-muted small">(\d+)</span></td>', html)
            check('primeira página não corta em 12', len(ids) == 20, str(len(ids)))
            # O nome também está no cabeçalho (usuário logado): olha a célula da tabela.
            check('mostra quem rodou o lote',
                  re.search(r'class="[^"]*training-user[^"]*"[^>]*>\s*Advogada Treino', html) is not None)
            check('tem paginação', 'page=2' in html)

            html2 = client.get('/fap-review/training?page=2').data.decode('utf-8')
            ids2 = re.findall(r'<td class="ps-3"><span class="text-muted small">(\d+)</span></td>', html2)
            check('segunda página traz o resto', len(ids2) == 5, str(len(ids2)))
            check('nenhum lote repetido nem perdido entre as páginas',
                  len(set(ids) | set(ids2)) == 25 and not set(ids) & set(ids2))
            check('mais recente primeiro', ids and int(ids[0]) == max(int(x) for x in ids + ids2))

            r = client.get('/fap-review/training?page=99')
            check('página além do fim não quebra', r.status_code in (200, 404), str(r.status_code))
        finally:
            _remover_escritorio(firm_id)


def main() -> int:
    print('=' * 62)
    print('REMESSA R02 — regras do Revisor de Petições')
    print('=' * 62)

    test_wrike_aceita_numero()
    test_wrike_apara_espacos_das_pontas()
    test_wrike_preserva_zero_a_esquerda()
    test_wrike_recusa_letras()
    test_wrike_recusa_espaco_no_meio()
    test_wrike_recusa_vazio()
    test_wrike_recusa_longo_demais()
    test_wrike_erros_sao_distintos()
    test_wrike_recusa_digito_nao_ascii()
    test_modelo_registrado_aparece()
    test_modelo_ausente_nao_e_chutado()
    test_barra_de_aprovacao_sobrevive_a_revisao_sem_achados()
    test_rpi04_agrupa_e_soma_por_advogado()
    test_rpi04_ordena_por_volume()
    test_rpi04_peticao_sem_revisor()
    test_rpi04_ignora_linha_sem_quantidade()
    test_rpi04_lista_vazia()
    test_rpi04_seletor_existe_na_tela()
    test_rpi04_busca_textual_filtra_dentro_da_selecao()
    test_rpi04_contagem_bate_com_o_banco()
    test_rpi09_botao_arquivar_na_lista()
    test_rpi09_estatisticas_ignoram_arquivadas()
    test_rpi02_historico_paginado_com_usuario()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
