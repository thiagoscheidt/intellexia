#!/usr/bin/env python3
"""
Testes do saneador de achados do Revisor FAP
(app/agents/fap_review/finding_sanitizer.py).

Função pura: não precisa de rede, banco, LLM nem contexto Flask.

    uv run python tests/test_fap_review_finding_sanitizer.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.fap_review.finding_sanitizer import (
    sanear, fingerprint_achado, dias_entre_beneficios)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def achado(**kwargs) -> dict:
    """Achado mínimo válido, com os campos que o saneador lê."""
    base = {
        'category': 'CAT-1',
        'severity': 'CRÍTICO',
        'description': 'Descrição do achado',
        'location': 'Qualificação, parágrafo 1',
        'location_excerpt': None,
        'correction': None,
        'manual_reference': '1.1',
    }
    base.update(kwargs)
    return base


# Trecho real da inicial que gerou os relatos de RPI-12 no documento de feedbacks.
PETICAO = (
    'SENDAS DISTRIBUIDORA S.A., pessoa jurídica de direito privado, inscrita no '
    'CNPJ sob o nº 06.057.223/0001-71, com endereço Avenida Ayrton Senna, nº 06000, '
    'Lot 2 Pal 48959 Anexo A, Jacarepaguá, Rio de Janeiro/RJ, CEP 22.775-005 e suas '
    'filiais, vem, perante Vossa Excelência,'
)


# ── R1 — RPI-12: sugestão idêntica ao que já está no documento ──────────

def test_r1_descarta_sugestao_ja_presente_no_documento():
    print('\n1. R1 — sugestão que o documento já atende')

    # Caso literal do feedback: o CEP está correto e a IA manda "corrigir" para
    # exatamente o que está escrito.
    cep = achado(
        description="CEP '22.775-005' grafado incorretamente, sem ponto separador após o segundo dígito.",
        correction="Corrigir para 'CEP 22.775-005'",
    )
    mantidos, descartes = sanear([cep], PETICAO)

    check('achado do CEP é descartado', mantidos == [], f'sobraram {len(mantidos)}')
    check('registra exatamente 1 descarte', len(descartes) == 1, str(descartes))
    if descartes:
        check('descarte diz a regra', descartes[0].get('regra') == 'R1', str(descartes[0]))
        check('descarte guarda o achado', descartes[0].get('achado') == cep)
        check('descarte tem motivo legível',
              'já' in (descartes[0].get('motivo') or '').lower(),
              repr(descartes[0].get('motivo')))


def test_r1_descarta_razao_social_identica():
    print('\n2. R1 — razão social sugerida igual à do documento')

    sendas = achado(
        description="Razão social 'SENDAS DISTRIBUIDORA S.A.' grafada como "
                    "'SENDAS DISTRIBUIDORA S.A.' (sem ponto) na qualificação.",
        correction="Corrigir para 'SENDAS DISTRIBUIDORA S.A.'",
    )
    mantidos, _ = sanear([sendas], PETICAO)

    check('achado da razão social é descartado', mantidos == [], f'sobraram {len(mantidos)}')


def test_r1_preserva_correcao_real():
    print('\n3. R1 — correção legítima sobrevive')

    real = achado(
        description="CNPJ da autora diverge do que consta no cartão CNPJ.",
        correction="Corrigir para '06.057.223/0001-72'",
    )
    mantidos, descartes = sanear([real], PETICAO)

    check('achado legítimo é mantido', mantidos == [real], f'mantidos={len(mantidos)}')
    check('nada foi descartado', descartes == [], str(descartes))


def test_r1_preserva_correcao_so_de_caixa():
    print('\n4. R1 — correção que muda só a caixa é achado de verdade')

    # "Sendas Distribuidora S.A." não está no documento; lá está em caixa alta.
    # Comparar sem diferenciar maiúsculas descartaria um achado legítimo.
    caixa = achado(
        description='Razão social grafada em caixa alta, fora do padrão do manual.',
        correction="Corrigir para 'Sendas Distribuidora S.A.'",
    )
    mantidos, _ = sanear([caixa], PETICAO)

    check('correção de caixa é mantida', len(mantidos) == 1, f'mantidos={len(mantidos)}')


def test_r1_ignora_achado_sem_correcao():
    print('\n5. R1 — achado sem sugestão não é tocado')

    sem = achado(description='Falta a data do acidente no tópico 4.', correction=None)
    mantidos, descartes = sanear([sem], PETICAO)

    check('achado sem correção é mantido', mantidos == [sem])
    check('nada descartado', descartes == [])


def test_r1_sem_documento_nao_descarta():
    print('\n6. R1 — sem texto do documento, não há o que comparar')

    cep = achado(
        description="CEP '22.775-005' grafado incorretamente.",
        correction="Corrigir para 'CEP 22.775-005'",
    )
    mantidos, descartes = sanear([cep], '')

    check('mantém o achado quando não há documento', mantidos == [cep])
    check('nada descartado', descartes == [])


# ── R2 — RPI-13: o mesmo achado apontado mais de uma vez ────────────────

def test_r2_deduplica_achado_repetido():
    print('\n7. R2 — achado repetido aparece uma vez só')

    # Caso literal do feedback: o mesmo B91 apontado nos pontos 15 e 21.
    texto = ('Benefício B91 nº 6214157201 já foi tratado no tópico 11 da petição '
             'inicial, mas não foi incluído na tabela de pedidos.')
    ponto15 = achado(description=texto, location='Tabela de pedidos',
                     correction='Incluir o benefício na tabela de pedidos.')
    ponto21 = achado(description=texto, location='Tabela de pedidos',
                     correction='Incluir o benefício na tabela de pedidos.')

    mantidos, descartes = sanear([ponto15, ponto21], PETICAO)

    check('sobra um único achado', len(mantidos) == 1, f'sobraram {len(mantidos)}')
    check('registra 1 descarte', len(descartes) == 1, str(len(descartes)))
    if descartes:
        check('descarte diz a regra', descartes[0].get('regra') == 'R2', str(descartes[0].get('regra')))
        check('motivo fala de repetição',
              'repet' in (descartes[0].get('motivo') or '').lower()
              or 'duplic' in (descartes[0].get('motivo') or '').lower(),
              repr(descartes[0].get('motivo')))


def test_r2_mantem_a_primeira_ocorrencia():
    print('\n8. R2 — quem fica é a primeira ocorrência')

    primeiro = achado(description='Mesmo texto', location='Tópico 4', location_excerpt='trecho A')
    segundo = achado(description='Mesmo texto', location='Tópico 4', location_excerpt='trecho B')

    mantidos, _ = sanear([primeiro, segundo], PETICAO)

    check('mantém o primeiro', mantidos == [primeiro], str(mantidos))


def test_r2_achados_diferentes_sobrevivem():
    print('\n9. R2 — achados distintos não se anulam')

    a = achado(description='Falta a CAT do benefício 6214157201.')
    b = achado(description='Falta a CAT do benefício 6408721579.')

    mantidos, descartes = sanear([a, b], PETICAO)

    check('os dois são mantidos', len(mantidos) == 2, f'mantidos={len(mantidos)}')
    check('nada descartado', descartes == [], str(descartes))


def test_fingerprint_ignora_o_trecho_citado():
    print('\n10. Fingerprint — trecho citado não entra na identidade')

    # Deliberado: no caso real os dois apontamentos citavam trechos diferentes
    # do mesmo problema. Entrando na identidade, a duplicata escaparia.
    a = achado(description='Mesmo problema', location_excerpt='um trecho')
    b = achado(description='Mesmo problema', location_excerpt='outro trecho')

    check('mesmo fingerprint', fingerprint_achado(a) == fingerprint_achado(b))


def test_fingerprint_acompanha_o_do_servico():
    print('\n11. Fingerprint — mesmo valor do usado para achado descartado')

    # Se divergirem, um achado marcado "não pertinente" numa revisão deixaria de
    # ser reconhecido na seguinte.
    from app.services.fap_review_service import build_finding_fingerprint

    exemplo = achado(description='Divergência de NIT', correction='Conferir no CNIS')
    check('sanitizer e serviço concordam',
          fingerprint_achado(exemplo) == build_finding_fingerprint(exemplo))


# ── R6 — falso positivo de razão social (regra que já existia no agente) ─

def test_r6_descarta_achado_que_diz_nao_haver_divergencia():
    print('\n12. R6 — achado sobre razão social que ele mesmo diz estar certa')

    auto = achado(
        description='Razão social da autora grafada de forma consistente em todo o documento, '
                    'sem divergências detectadas.',
    )
    mantidos, descartes = sanear([auto], PETICAO)

    check('achado é descartado', mantidos == [], f'sobraram {len(mantidos)}')
    check('regra é R6', descartes and descartes[0].get('regra') == 'R6',
          str(descartes[0].get('regra')) if descartes else 'sem descarte')


def test_r6_preserva_divergencia_real_de_razao_social():
    print('\n13. R6 — divergência real de razão social sobrevive')

    real = achado(
        description="Razão social da autora diverge entre a qualificação e a procuração.",
        correction="Uniformizar para 'MUNDIAL MIX COMERCIO DE ALIMENTOS LTDA'",
    )
    mantidos, _ = sanear([real], PETICAO)

    check('achado é mantido', mantidos == [real], f'mantidos={len(mantidos)}')


def test_r6_nao_toca_achado_de_outro_assunto():
    print('\n14. R6 — "sem divergência" fora de razão social não é descartado')

    outro = achado(description='Sem divergência nas datas, mas falta a CAT do benefício.')
    mantidos, _ = sanear([outro], PETICAO)

    check('achado é mantido', mantidos == [outro], f'mantidos={len(mantidos)}')



# ── R3 — RPI-07: achado dentro de citação direta ────────────────────────

# Petição com dois blocos de citação direta — uma transcrição de sentença e um
# artigo de lei — e texto próprio do advogado em volta. Os relatos do RPI-07
# são exatamente estes: o agente mandou uniformizar expressão dentro da
# transcrição e atualizar terminologia dentro da citação literal da lei.
PECA_COM_CITACAO = (
    'Como se depreende da r. sentença proferida nos autos, "o auxílio-doença '
    'acidentário concedido ao obreiro não guarda nexo com as atividades '
    'desenvolvidas na empresa reclamada", razão pela qual a autora requer a '
    'exclusão do benefício. Dispõe o artigo 22 da Lei nº 8.213/91 que "a empresa '
    'deverá comunicar o acidente do trabalho à Previdência Social até o primeiro '
    'dia útil seguinte ao da ocorrência". A autora comunicou o acidente do '
    'trabalho fora do prazo legal, o que não afasta o direito à revisão.'
)


def test_r3_descarta_achado_dentro_da_transcricao():
    print('\n15. R3 — achado dentro de citação direta')

    dentro = achado(
        category='CAT-3',
        description='Uniformizar a expressão "obreiro" para "trabalhador".',
        location='Fundamentação',
        location_excerpt='concedido ao obreiro não guarda nexo com as atividades',
    )
    mantidos, descartes = sanear([dentro], PECA_COM_CITACAO)
    check('achado é descartado', len(mantidos) == 0 and len(descartes) == 1)
    check('regra é R3', descartes and descartes[0]['regra'] == 'R3',
          descartes[0]['regra'] if descartes else 'nenhum descarte')


def test_r3_descarta_achado_dentro_da_citacao_de_lei():
    print('\n16. R3 — achado dentro de citação literal de lei')

    dentro = achado(
        category='CAT-6',
        description='Atualizar a terminologia: "Previdência Social" hoje é INSS.',
        location='Fundamentação',
        location_excerpt='comunicar o acidente do trabalho à Previdência Social',
    )
    mantidos, descartes = sanear([dentro], PECA_COM_CITACAO)
    check('achado é descartado', len(mantidos) == 0 and len(descartes) == 1)
    check('regra é R3', descartes and descartes[0]['regra'] == 'R3')


def test_r3_preserva_achado_no_texto_do_advogado():
    print('\n17. R3 — texto próprio da peça continua auditado')

    # Mesmo assunto, mas fora das aspas: é texto do advogado e tem de ser
    # corrigido. Descartar aqui seria o oposto do pedido.
    fora = achado(
        category='CAT-6',
        description='Terminologia desatualizada no texto da peça.',
        location='Fundamentação',
        location_excerpt='A autora comunicou o acidente do trabalho fora do prazo legal',
    )
    mantidos, descartes = sanear([fora], PECA_COM_CITACAO)
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_trecho_dentro_e_fora_das_aspas_sobrevive():
    print('\n18. R3 — na dúvida, mantém')

    # "acidente do trabalho" aparece dentro da citação de lei e também no texto
    # do advogado. Não dá para saber a qual o achado se refere; descartar
    # engoliria um apontamento legítimo.
    doc = 'Dispõe a lei que "a empresa deve comunicar o acidente do trabalho". ' \
          'A autora não comunicou o acidente do trabalho.'
    ambiguo = achado(location_excerpt='o acidente do trabalho')
    mantidos, descartes = sanear([ambiguo], doc)
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_aspas_tipograficas():
    print('\n19. R3 — aspas tipográficas do Word')

    doc = 'Conforme a sentença, \u201co obreiro laborava em condi\u00e7\u00f5es insalubres\u201d, ' \
          'o que a autora contesta.'
    dentro = achado(location_excerpt='o obreiro laborava em condi\u00e7\u00f5es insalubres')
    mantidos, descartes = sanear([dentro], doc)
    check('achado é descartado', len(mantidos) == 0 and len(descartes) == 1)
    check('regra é R3', descartes and descartes[0]['regra'] == 'R3')


def test_r3_aspa_sem_par_nao_engole_o_documento():
    print('\n20. R3 — aspa solta não vira citação até o fim da peça')

    # Uma aspa de abertura sem fechamento é erro de digitação, não citação.
    # Se ela abrisse um span, todo o resto da peça deixaria de ser auditado.
    doc = 'A autora afirma que "houve erro de estabelecimento. ' \
          'O benefício foi vinculado ao CNPJ incorreto pela autarquia.'
    depois = achado(location_excerpt='vinculado ao CNPJ incorreto pela autarquia')
    mantidos, descartes = sanear([depois], doc)
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_apostrofo_nao_delimita_citacao():
    print('\n21. R3 — apóstrofo não abre citação')

    # Aspas simples marcam valor proposto na R1, não citação. Tratá-las como
    # delimitador faria qualquer apóstrofo silenciar o texto em volta.
    doc = "A empresa d'Água Ltda. informou o CNPJ 19.630.496/0001-05 na inicial."
    a = achado(location_excerpt='informou o CNPJ 19.630.496/0001-05 na inicial')
    mantidos, descartes = sanear([a], doc)
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_sem_documento_nao_descarta():
    print('\n22. R3 — sem o texto do documento, a regra não roda')

    a = achado(location_excerpt='concedido ao obreiro não guarda nexo')
    mantidos, descartes = sanear([a], '')
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_achado_sem_trecho_nao_descarta():
    print('\n23. R3 — achado sem trecho literal não tem como ser localizado')

    a = achado(location_excerpt=None,
               description='Falta o pedido de tutela de urgência.')
    mantidos, descartes = sanear([a], PECA_COM_CITACAO)
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)


def test_r3_descarte_traz_motivo_legivel():
    print('\n24. R3 — o descarte diz por que descartou')

    dentro = achado(location_excerpt='concedido ao obreiro não guarda nexo com as atividades')
    _, descartes = sanear([dentro], PECA_COM_CITACAO)
    motivo = descartes[0]['motivo'] if descartes else ''
    check('motivo menciona a citação', 'citação' in motivo, motivo)



# ── R4 — RPI-10: intervalo entre DCB e DIB ──────────────────────────────

def test_dias_entre_beneficios_confere_os_exemplos_do_aceite():
    print('\n25. RPI-10 — os dois exemplos do aceite')

    # São estes os números do briefing. A frase do documento de feedbacks
    # ("não contar o primeiro dia e contar o último") daria 31 no primeiro
    # caso, contradizendo o próprio exemplo — vale o exemplo.
    check('22/12/2017 → 22/01/2018 dá 30',
          dias_entre_beneficios('22/12/2017', '22/01/2018') == 30,
          str(dias_entre_beneficios('22/12/2017', '22/01/2018')))
    check('01/01/2020 → 02/01/2020 dá 0',
          dias_entre_beneficios('01/01/2020', '02/01/2020') == 0,
          str(dias_entre_beneficios('01/01/2020', '02/01/2020')))


def test_dias_entre_beneficios_bordas():
    print('\n26. RPI-10 — bordas do cálculo')

    check('mesmo dia dá 0', dias_entre_beneficios('01/01/2020', '01/01/2020') == 0)
    check('DIB antes da DCB não é calculável',
          dias_entre_beneficios('10/01/2020', '01/01/2020') is None)
    check('data inválida não é calculável',
          dias_entre_beneficios('31/02/2020', '01/03/2020') is None)
    check('texto que não é data não é calculável',
          dias_entre_beneficios('sem data', '01/03/2020') is None)
    # 60 exato não é "inferior a 60": a fronteira da tese tem de ser exata.
    check('01/01/2020 → 02/03/2020 dá 60',
          dias_entre_beneficios('01/01/2020', '02/03/2020') == 60,
          str(dias_entre_beneficios('01/01/2020', '02/03/2020')))


def test_r4_corrige_o_numero_de_dias():
    print('\n27. R4 — número errado é corrigido, não descartado')

    errado = achado(
        category='CAT-2',
        description='Restabelecimento: entre a DCB de 22/12/2017 e a DIB de '
                    '22/01/2018 decorreram 31 dias, intervalo inferior a 60 dias.',
        correction='Ajustar para 31 dias.',
    )
    mantidos, descartes = sanear([errado], '')
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)
    if mantidos:
        check('descrição passa a dizer 30 dias', '30 dias' in mantidos[0]['description'],
              mantidos[0]['description'])
        check('31 dias sai da descrição', '31 dias' not in mantidos[0]['description'])
        check('a correção também é ajustada', '30 dias' in (mantidos[0].get('correction') or ''),
              mantidos[0].get('correction'))
        fix = mantidos[0].get('sanitizer_fix')
        check('a correção fica registrada no achado', isinstance(fix, dict))
        check('registro diz a regra', fix and fix.get('regra') == 'R4')
        check('registro diz de quanto para quanto',
              fix and fix.get('de') == 31 and fix.get('para') == 30,
              str(fix))


def test_r4_nao_mexe_quando_o_numero_ja_esta_certo():
    print('\n28. R4 — número certo passa intacto')

    certo = achado(
        description='Restabelecimento: DCB 22/12/2017 e DIB 22/01/2018, 30 dias '
                    'de intervalo, inferior a 60 dias.',
    )
    original = certo['description']
    mantidos, descartes = sanear([certo], '')
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)
    check('descrição não muda', mantidos and mantidos[0]['description'] == original)
    check('não há registro de correção',
          mantidos and mantidos[0].get('sanitizer_fix') is None)


def test_r4_descarta_quando_o_intervalo_derruba_a_tese():
    print('\n29. R4 — intervalo real não sustenta o restabelecimento')

    # 01/01/2020 → 01/06/2020 são 151 dias: não é restabelecimento.
    insustentavel = achado(
        description='Restabelecimento: DCB 01/01/2020 e DIB 01/06/2020, '
                    'intervalo inferior a 60 dias.',
    )
    mantidos, descartes = sanear([insustentavel], '')
    check('achado é descartado', len(mantidos) == 0 and len(descartes) == 1)
    check('regra é R4', descartes and descartes[0]['regra'] == 'R4')
    check('motivo traz o intervalo real',
          descartes and '151' in descartes[0]['motivo'],
          descartes[0]['motivo'] if descartes else '')


def test_r4_so_atua_em_achado_da_tese_dos_60_dias():
    print('\n30. R4 — duas datas fora da tese não são recalculadas')

    # Datas de vigência e de protocolo não têm nada a ver com DCB/DIB.
    outro = achado(
        category='CAT-1',
        description='A vigência de 01/01/2020 foi protocolada em 01/06/2020, '
                    'fora do prazo de 30 dias previsto.',
    )
    original = outro['description']
    mantidos, descartes = sanear([outro], '')
    check('achado é mantido', len(mantidos) == 1 and len(descartes) == 0)
    check('descrição não muda', mantidos and mantidos[0]['description'] == original)


def test_r4_precisa_de_exatamente_duas_datas():
    print('\n31. R4 — sem par de datas, não há o que recalcular')

    uma_data = achado(description='Restabelecimento com DCB 22/12/2017, 31 dias depois.')
    original = uma_data['description']
    mantidos, _ = sanear([uma_data], '')
    check('uma data só: intacto', mantidos and mantidos[0]['description'] == original)

    tres = achado(description='Restabelecimento: DCB 22/12/2017, DIB 22/01/2018, '
                              'contestada em 05/05/2018, 31 dias.')
    original3 = tres['description']
    mantidos3, _ = sanear([tres], '')
    check('três datas: intacto (ambíguo)',
          mantidos3 and mantidos3[0]['description'] == original3)


# ── R7 — FB-02: petição x anexo/planilha divergindo só na formatação ─────

def _regras(achados, documento=PETICAO):
    mantidos, descartes = sanear(achados, documento)
    return len(mantidos), [d['regra'] for d in descartes]


def test_r7_razao_social_so_pontuacao_contra_anexo():
    print('\n32. R7 — razão social que difere do anexo só na pontuação')
    a = achado(description='A razão social "SENDAS DISTRIBUIDORA S.A" diverge da CAT_joao.pdf, '
                           'que traz "SENDAS DISTRIBUIDORA S.A."',
               correction='Conferir a grafia com o documento auxiliar.')
    mantidos, regras = _regras([a])
    check('descartado pela R7', mantidos == 0 and regras == ['R7'], f'{mantidos} {regras}')

    b = achado(description='Razão social na petição: "SENDAS DISTRIBUIDORA S/A"; na planilha: '
                           '"SENDAS DISTRIBUIDORA S.A."')
    mantidos, regras = _regras([b])
    check('S/A contra S.A. da planilha também sai', mantidos == 0 and regras == ['R7'], f'{mantidos} {regras}')


def test_r7_nit_formatado_contra_digitos():
    print('\n33. R7 — NIT igual, escrito com e sem pontuação')
    a = achado(description='O NIT "123.45678.90-1" não corresponde ao da planilha, "12345678901".')
    mantidos, regras = _regras([a])
    check('NIT com os mesmos dígitos sai', mantidos == 0 and regras == ['R7'], f'{mantidos} {regras}')


def test_r7_preserva_divergencia_dentro_da_peticao():
    print('\n34. R7 — dentro da própria petição o rigor do manual continua')
    # Revisão 62: tabela de anexos da petição com "S.A" e qualificação com "S.A.".
    a = achado(description='A razão social aparece como "SENDAS DISTRIBUIDORA S.A" na tabela de '
                           'documentos anexos e "SENDAS DISTRIBUIDORA S.A." na qualificação.')
    mantidos, regras = _regras([a])
    check('achado interno mantido', mantidos == 1 and regras == [], f'{mantidos} {regras}')


def test_r7_preserva_divergencia_real():
    print('\n35. R7 — divergência de verdade contra o anexo continua')
    casos = {
        'forma societária diferente': 'A petição traz "SENDAS DISTRIBUIDORA S.A." e a CAT_x.pdf "SENDAS DISTRIBUIDORA LTDA".',
        'NIT com outro dígito': 'O NIT "123.45678.90-1" diverge da planilha, que traz "12345678902".',
        'valor com vírgula em outro lugar': 'O valor "1.000,00" diverge da planilha, que traz "10.000,0".',
        'data com dígitos trocados': 'A data "1/12/2020" diverge da CAT_x.pdf, que traz "11/2/2020".',
        'um valor só entre aspas': 'A razão social diverge da planilha: "SENDAS DISTRIBUIDORA S.A".',
    }
    for nome, descricao in casos.items():
        mantidos, regras = _regras([achado(description=descricao)])
        check(nome, mantidos == 1 and 'R7' not in regras, f'{mantidos} {regras}')


def main() -> int:
    print('=' * 62)
    print('SANEADOR DE ACHADOS — Revisor FAP')
    print('=' * 62)

    test_r1_descarta_sugestao_ja_presente_no_documento()
    test_r1_descarta_razao_social_identica()
    test_r1_preserva_correcao_real()
    test_r1_preserva_correcao_so_de_caixa()
    test_r1_ignora_achado_sem_correcao()
    test_r1_sem_documento_nao_descarta()
    test_r2_deduplica_achado_repetido()
    test_r2_mantem_a_primeira_ocorrencia()
    test_r2_achados_diferentes_sobrevivem()
    test_fingerprint_ignora_o_trecho_citado()
    test_fingerprint_acompanha_o_do_servico()
    test_r6_descarta_achado_que_diz_nao_haver_divergencia()
    test_r6_preserva_divergencia_real_de_razao_social()
    test_r6_nao_toca_achado_de_outro_assunto()
    test_r3_descarta_achado_dentro_da_transcricao()
    test_r3_descarta_achado_dentro_da_citacao_de_lei()
    test_r3_preserva_achado_no_texto_do_advogado()
    test_r3_trecho_dentro_e_fora_das_aspas_sobrevive()
    test_r3_aspas_tipograficas()
    test_r3_aspa_sem_par_nao_engole_o_documento()
    test_r3_apostrofo_nao_delimita_citacao()
    test_r3_sem_documento_nao_descarta()
    test_r3_achado_sem_trecho_nao_descarta()
    test_r3_descarte_traz_motivo_legivel()
    test_dias_entre_beneficios_confere_os_exemplos_do_aceite()
    test_dias_entre_beneficios_bordas()
    test_r4_corrige_o_numero_de_dias()
    test_r4_nao_mexe_quando_o_numero_ja_esta_certo()
    test_r4_descarta_quando_o_intervalo_derruba_a_tese()
    test_r4_so_atua_em_achado_da_tese_dos_60_dias()
    test_r4_precisa_de_exatamente_duas_datas()

    test_r7_razao_social_so_pontuacao_contra_anexo()
    test_r7_nit_formatado_contra_digitos()
    test_r7_preserva_divergencia_dentro_da_peticao()
    test_r7_preserva_divergencia_real()

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
