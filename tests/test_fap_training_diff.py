"""
Teste do serviço de diferenças do Treinamento FAP (sem IA, sem rede).

Por que este módulo existe: o agente recebia `texto[:12000]` de documentos com
164.570 caracteres — 93% jogado fora em silêncio — e, mesmo after de passar a
receber os documentos inteiros, resumia como "padronização terminológica" o que
o difflib mostra literalmente. Comparar duas versões do mesmo documento é
trabalho determinístico.

Uso: uv run python tests/test_fap_training_diff.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fap_training_diff_service import (  # noqa: E402
    IMAGE_MARKER,
    cluster_repeated_changes,
    extract_changes,
    format_for_prompt,
    reconcile_patterns,
    summarize_changes,
    unassigned_count,
)

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def run():
    print("[1] Correção de uma palavra no meio do parágrafo")
    changes = extract_changes(
        'O cálculo do índice FAP é regulamentado pelo CNPS.',
        'O cálculo do índice do FAP é regulamentado pelo CNPS.',
    )
    check("uma mudança", len(changes) == 1, f"(obteve {len(changes)})")
    m = changes[0]
    check("kind alteração", m['kind'] == 'change')
    check("insere a preposição", m['inserted'] == 'do', f"(obteve {m['inserted']!r})")
    check("contexto de onde caiu", m['context_before'] == 'cálculo do índice',
          f"(obteve {m['context_before']!r})")
    check("não arrasta o parágrafo inteiro", len(str(m)) < 250, f"(obteve {len(str(m))} chars)")

    print("[2] Placeholder esquecido — o achado que o modelo omitia")
    changes = extract_changes(
        'Dá-se à causa o valor de R$ XXX (XXX).',
        'Dá-se à causa o valor de R$ 200.000,00 (duzentos mil reais).',
    )
    texto = format_for_prompt(changes)
    check("o placeholder aparece", 'XXX' in texto, f"(saída: {texto!r})")
    check("o valor preenchido aparece", '200.000,00' in texto)
    check("os dois lados no mesmo block", 'DE:' in texto and 'PARA:' in texto)

    print("[3] Parágrafo inteiramente novo é adição, não alteração")
    changes = extract_changes('Linha A\nLinha B', 'Linha A\nParágrafo inédito aqui.\nLinha B')
    kinds = {m['kind'] for m in changes}
    check("classificado como adição", kinds == {'addition'}, f"(obteve {kinds})")
    check("traz o texto novo",
          any('inédito' in m['inserted'] for m in changes))

    print("[4] Parágrafo removido é remoção")
    changes = extract_changes('Linha A\nSai daqui.\nLinha B', 'Linha A\nLinha B')
    check("classificado como remoção", {m['kind'] for m in changes} == {'removal'},
          f"(obteve {[m['kind'] for m in changes]})")

    print("[5] Documentos idênticos não geram mudança")
    texto = 'Parágrafo um.\nParágrafo dois.'
    check("nenhuma mudança", extract_changes(texto, texto) == [])
    check("nenhuma mudança com lines em branco a mais",
          extract_changes(texto, 'Parágrafo um.\n\n\nParágrafo dois.') == [],
          "(linha em branco da extração de DOCX não pode virar mudança)")

    print("[6] Bloco com contagem diferente pareia por semelhança")
    changes = extract_changes(
        'A empresa autora requer a exclusão.\nOutro parágrafo.',
        'A empresa Autora requer a exclusão do benefício.\nOutro parágrafo.\nTerceiro parágrafo.',
    )
    alteracoes = [m for m in changes if m['kind'] == 'change']
    adicoes = [m for m in changes if m['kind'] == 'addition']
    check("a frase editada virou alteração, não remoção+adição", len(alteracoes) >= 1,
          f"(obteve {[m['kind'] for m in changes]})")
    check("o parágrafo novo virou adição", len(adicoes) == 1, f"(obteve {len(adicoes)})")

    print("[7] Linhas sem parentesco não viram par inventado")
    changes = extract_changes(
        'Da tempestividade do pedido de revisão administrativa.',
        'Dos fatos.\nDo direito aplicável ao caso concreto.',
    )
    for m in changes:
        if m['kind'] == 'change':
            check("não pareou frases sem relação", False,
                  f"(pareou {m['removed'][:40]!r} com {m['inserted'][:40]!r})")
            break
    else:
        check("não pareou frases sem relação", True)

    print("[8] Resumo por tipo")
    changes = extract_changes('A\nB\nC', 'A modificado\nC\nD')
    contagem = summarize_changes(changes)
    check("total bate com a lista", contagem['total'] == len(changes))
    check("soma das categorias fecha",
          contagem['changes'] + contagem['additions'] + contagem['removals'] == contagem['total'],
          f"(obteve {contagem})")
    check("lista vazia não quebra", summarize_changes([])['total'] == 0)
    check("None não quebra", summarize_changes(None)['total'] == 0)

    print("[9] Entrada vazia não quebra")
    check("original vazio", all(m['kind'] == 'addition' for m in extract_changes('', 'Novo.')))
    check("revisado vazio", all(m['kind'] == 'removal' for m in extract_changes('Sai.', '')))
    check("os dois vazios", extract_changes('', '') == [])
    check("None nos dois", extract_changes(None, None) == [])

    print("[10] Corte do prompt é visível, nunca silencioso")
    muitas = extract_changes(
        '\n'.join(f'Parágrafo número {i} do documento.' for i in range(200)),
        '\n'.join(f'Parágrafo numero {i} do documento.' for i in range(200)),
    )
    check("gerou mudanças suficientes para testar o teto", len(muitas) > 50,
          f"(obteve {len(muitas)})")
    cortado = format_for_prompt(muitas, max_chars=500)
    check("respeitou o teto", len(cortado) < 800, f"(obteve {len(cortado)})")
    check("avisa quantas ficaram de fora", 'não couberam' in cortado,
          f"(termina em {cortado[-80:]!r})")
    inteiro = format_for_prompt(muitas)
    check("sem teto atingido, não avisa nada", 'não couberam' not in inteiro)

    print("[11] Mudanças vão numeradas para o prompt")
    changes = extract_changes('A um\nB dois\nC três', 'A UM\nB dois\nC TRÊS')
    texto = format_for_prompt(changes)
    check("primeira mudança é #0", texto.startswith('#0 '), f"(começa em {texto[:20]!r})")
    check("todas numeradas",
          all(f'#{i} ' in texto for i in range(len(changes))),
          f"({len(changes)} mudanças)")

    print("[12] Contagem vem dos índices, não do número que o modelo disse")
    changes = extract_changes(
        'O índice FAP sobe.\nO cálculo do índice FAP muda.\nO índice FAP cai.\nOutra frase.',
        'O índice do FAP sobe.\nO cálculo do índice do FAP muda.\nO índice do FAP cai.\nOutra frase!',
    )
    check("o diff achou 4 mudanças", len(changes) == 4, f"(obteve {len(changes)})")
    reconciliados = reconcile_patterns(
        [{'pattern': 'Inserção de "do" antes de FAP', 'change_indices': [0, 1, 2]}],
        changes,
    )
    check("um padrão", len(reconciliados) == 1)
    check("ocorrências contadas no código", reconciliados[0]['occurrences'] == 3,
          f"(obteve {reconciliados[0]['occurrences']})")

    print("[13] Exemplos são renderizados das mudanças reais, não escritos pelo modelo")
    exemplos = reconciliados[0]['examples']
    check("três exemplos", len(exemplos) == 3, f"(obteve {len(exemplos)})")
    check("cada exemplo traz DE e PARA", all('DE:' in e and 'PARA:' in e for e in exemplos))
    check("o texto é literalmente o da mudança",
          all('«do»' in e for e in exemplos), f"(obteve {exemplos[0]!r})")

    print("[14] Uma mudança pertence a um padrão só")
    reconciliados = reconcile_patterns(
        [
            {'pattern': 'Primeiro', 'change_indices': [0, 1]},
            {'pattern': 'Segundo', 'change_indices': [1, 2]},  # 1 já foi reivindicado
        ],
        changes,
    )
    por_nome = {p['pattern']: p for p in reconciliados}
    check("o primeiro fica com as duas", por_nome['Primeiro']['occurrences'] == 2)
    check("o segundo não recebe a repetida", por_nome['Segundo']['occurrences'] == 1,
          f"(obteve {por_nome['Segundo']['occurrences']})")
    check("a soma não passa do total real",
          sum(p['occurrences'] for p in reconciliados) <= len(changes),
          "(era assim que 34+31+28+19 estourava as 275 mudanças)")

    print("[15] Índice inventado é descartado")
    reconciliados = reconcile_patterns(
        [{'pattern': 'Com lixo', 'change_indices': [0, 999, -5, 'abc', None]}], changes)
    check("só o índice válido entra", reconciliados[0]['occurrences'] == 1,
          f"(obteve {reconciliados[0]['occurrences']})")
    check("padrão sem índice válido some",
          reconcile_patterns([{'pattern': 'Vazio', 'change_indices': [999]}], changes) == [])

    print("[16] Relevância é calculada, não opinada")
    reconciliados = reconcile_patterns(
        [{'pattern': 'Repetido', 'change_indices': [0, 1, 2]}], changes)
    check("3 ocorrências é padrão", reconciliados[0]['relevant_for_manual'] is True)

    reconciliados = reconcile_patterns(
        [{'pattern': 'Uma vez só', 'change_indices': [3]}], changes)
    check("1 ocorrência sem número é ruído",
          reconciliados[0]['relevant_for_manual'] is False,
          f"(mudança: {changes[3]})")

    factual = extract_changes(
        'Dá-se à causa o valor de R$ XXX (XXX).',
        'Dá-se à causa o valor de R$ 200.000,00 (duzentos mil reais).',
    )
    reconciliados = reconcile_patterns(
        [{'pattern': 'Placeholder do valor da causa', 'change_indices': [0]}], factual)
    check("1 ocorrência que toca dado factual é relevante",
          reconciliados[0]['relevant_for_manual'] is True,
          "(um 'R$ XXX' não precisa se repetir para virar regra)")

    print("[17] O que ficou sem padrão é contado")
    reconciliados = reconcile_patterns(
        [{'pattern': 'Só duas', 'change_indices': [0, 1]}], changes)
    check("2 das 4 sobraram", unassigned_count(reconciliados, changes) == 2,
          f"(obteve {unassigned_count(reconciliados, changes)})")
    check("nada classificado = tudo sobrando",
          unassigned_count([], changes) == len(changes))
    check("entradas vazias não quebram", unassigned_count(None, None) == 0)

    print("[18] Ordenado por frequência, o que mais se repete primeiro")
    reconciliados = reconcile_patterns(
        [
            {'pattern': 'Raro', 'change_indices': [3]},
            {'pattern': 'Comum', 'change_indices': [0, 1, 2]},
        ],
        changes,
    )
    check("o de 3 vem antes do de 1",
          [p['pattern'] for p in reconciliados] == ['Comum', 'Raro'],
          f"(obteve {[p['pattern'] for p in reconciliados]})")

    print("[19] O que se repete literalmente agrupa sem IA")
    changes = extract_changes(
        'O índice FAP sobe.\nO cálculo do índice FAP muda.\nO índice FAP cai.\nUma frase só.',
        'O índice do FAP sobe.\nO cálculo do índice do FAP muda.\nO índice do FAP cai.\nUma frase apenas.',
    )
    grupos, resto = cluster_repeated_changes(changes)
    check("um grupo exato", len(grupos) == 1, f"(obteve {len(grupos)})")
    check("com as 3 repetições", grupos[0]['occurrences'] == 3, f"(obteve {grupos[0]['occurrences']})")
    check("rótulo escrito do próprio par", grupos[0]['pattern'] == 'Inserir «do»',
          f"(obteve {grupos[0]['pattern']!r})")
    check("repetição já é relevância", grupos[0]['relevant_for_manual'] is True)
    check("a mudança de par único sobra para o modelo", len(resto) == 1, f"(obteve {resto})")
    check("nada se perde",
          grupos[0]['occurrences'] + len(resto) == len(changes),
          f"({grupos[0]['occurrences']} + {len(resto)} ≠ {len(changes)})")

    print("[20] Rótulo cobre as quatro formas de mudança")
    for antes_txt, depois_txt, esperado in (
        ('a X b\nc X d', 'a Y b\nc Y d', 'Trocar «X» por «Y»'),
        ('a b\nc b', 'a Z b\nc Z b', 'Inserir «Z»'),
        ('a Z b\nc Z b', 'a b\nc b', 'Remover «Z»'),
    ):
        grupos, _ = cluster_repeated_changes(extract_changes(antes_txt, depois_txt))
        rotulos = [g['pattern'] for g in grupos]
        check(f"{esperado!r}", esperado in rotulos, f"(obteve {rotulos})")

    grupos, _ = cluster_repeated_changes(
        extract_changes('a\nb', 'a\nNOVO PARAGRAFO\nb\nNOVO PARAGRAFO'))
    check("'Acrescentar' para parágrafo repetido",
          any(g['pattern'].startswith('Acrescentar') for g in grupos),
          f"(obteve {[g['pattern'] for g in grupos]})")

    print("[21] Par que acontece uma vez só não vira grupo exato")
    grupos, resto = cluster_repeated_changes(extract_changes('a b c', 'a X c'))
    check("nenhum grupo", grupos == [])
    check("tudo sobra para o modelo", len(resto) == 1)
    check("entrada vazia não quebra", cluster_repeated_changes([]) == ([], []))
    check("None não quebra", cluster_repeated_changes(None) == ([], []))

    print("[22] Numeração global sobrevive ao recorte")
    changes = extract_changes('a\nb\nc\nd', 'A\nB\nC\nD')
    texto = format_for_prompt(changes, only_indices=[1, 3])
    check("só duas mudanças no texto", texto.count('- ALTERADO') == 2, f"(obteve {texto!r})")
    check("mantém o índice global #1", '#1 ' in texto)
    check("mantém o índice global #3", '#3 ' in texto)
    check("não renumera para #0", '#0 ' not in texto,
          "(renumerar quebraria a resolução dos índices devolvidos pelo modelo)")

    print("[23] Índice já reivindicado pelo grupo exato não é reatribuído")
    reconciliados = reconcile_patterns(
        [{'pattern': 'Do modelo', 'change_indices': [0, 1, 2]}],
        changes,
        already_claimed={0, 1},
    )
    check("só o índice livre entra", reconciliados[0]['occurrences'] == 1,
          f"(obteve {reconciliados[0]['occurrences']})")

    print("[24] Marcador de imagem não é texto da petição")
    changes = extract_changes(
        'Parágrafo um.\nParágrafo dois.',
        f'Parágrafo um.\n{IMAGE_MARKER}\nParágrafo dois.\n{IMAGE_MARKER}',
    )
    texto = format_for_prompt(changes)
    check("não manda editar o marcador", 'Acrescentar «[IMAGEM' not in texto,
          f"(obteve {texto!r})")
    check("descreve como imagem", 'IMAGEM ACRESCENTADA' in texto, f"(obteve {texto!r})")

    grupos, _ = cluster_repeated_changes(changes)
    check("o grupo fala de imagem, não de string",
          any(g['pattern'] == 'Acrescentar imagem (prova anexada ao documento)' for g in grupos),
          f"(obteve {[g['pattern'] for g in grupos]})")
    check("nenhum rótulo cita o marcador",
          all(IMAGE_MARKER not in g['pattern'] for g in grupos),
          "(era assim que virava regra de manual mandando remover o placeholder)")

    changes = extract_changes(f'a\n{IMAGE_MARKER}\nb\n{IMAGE_MARKER}', 'a\nb')
    grupos, _ = cluster_repeated_changes(changes)
    check("remoção de imagem também",
          any(g['pattern'] == 'Remover imagem do documento' for g in grupos),
          f"(obteve {[g['pattern'] for g in grupos]})")

    print("[25] Texto de verdade junto do marcador continua sendo texto")
    changes = extract_changes(
        f'O laudo comprova. {IMAGE_MARKER}',
        f'O laudo médico comprova. {IMAGE_MARKER}',
    )
    texto = format_for_prompt(changes)
    check("a correção textual aparece", '«médico»' in texto or 'médico' in texto,
          f"(obteve {texto!r})")
    check("não vira 'IMAGEM ACRESCENTADA'", 'IMAGEM ACRESCENTADA' not in texto)

    print("[26] O marcador espelha o do extrator")
    import os
    os.environ.setdefault('OPENAI_API_KEY', 'test-key')
    from app.blueprints.fap_review import IMAGE_MARKER as MARCADOR_DO_EXTRATOR  # noqa: E402
    check("constantes iguais", IMAGE_MARKER == MARCADOR_DO_EXTRATOR,
          f"(serviço={IMAGE_MARKER!r}, extrator={MARCADOR_DO_EXTRATOR!r})")

    print("[27] Economia real, medida nas petições do escritório")
    caminho = Path('uploads/fap_review/1/training')
    arquivos = sorted(caminho.glob('20260825_130614_*.docx')) if caminho.is_dir() else []
    if len(arquivos) != 2:
        print("  – documentos reais indisponíveis nesta máquina; medição pulada")
        return

    import os
    os.environ.setdefault('OPENAI_API_KEY', 'test-key')
    from main import app  # noqa: E402
    from app.blueprints.fap_review import _extract_text_from_document  # noqa: E402

    with app.app_context():
        original = _extract_text_from_document(str([a for a in arquivos if 'original' in a.name][0]))
        revisado = _extract_text_from_document(str([a for a in arquivos if 'revised' in a.name][0]))

    changes = extract_changes(original, revisado)
    saida = format_for_prompt(changes)
    completo = len(original) + len(revisado)
    reducao = 100 * (1 - len(saida) / completo)

    print(f"    documentos: {completo:,} chars | diff: {len(saida):,} chars | redução: {reducao:.1f}%")
    check("reduz pelo menos 80%", reducao >= 80, f"(obteve {reducao:.1f}%)")
    check("o placeholder R$ XXX sobrevive", 'XXX (XXX).' in saida)
    check("a troca de data sobrevive", '«7»' in saida and '«12»' in saida)
    check("a preposição do FAP sobrevive", '«do»' in saida)


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
