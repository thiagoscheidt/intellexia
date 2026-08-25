"""
Diferenças entre a petição como o advogado entregou e como o revisor devolveu.

Sem IA, sem rede, sem banco: comparar duas versões do MESMO documento é
trabalho de ``difflib``, não de modelo de linguagem. Medido nas petições reais
do escritório (Sodexo 2023, de 164.570 e 165.757 caracteres):

===========================  ==========  =========  ========
abordagem                      entrada     tokens     tempo
===========================  ==========  =========  ========
mandar os dois documentos       330.327      82,6k     11,1s
``unified_diff``                119.698        30k       4ms
este módulo (palavra)            35.750       8,9k      87ms
===========================  ==========  =========  ========

89% menor que mandar os documentos, e **exato**: com os documentos inteiros o
modelo resumiu como "padronização terminológica" o que aqui aparece
literalmente — ``valor de R$ «XXX (XXX).»`` virando
``valor de R$ «200.000,00 (duzentos mil reais).»``, um placeholder que o
advogado esqueceu de preencher. Modelo omite; ``difflib`` não.

A economia é o que torna o resto possível: com os documentos ocupando 82,6k
tokens não sobrava espaço para mandar junto o manual (65k caracteres) e os
casos de referência (60k) — e sem o manual à vista o agente só sabia propor
regra genérica.
"""

import difflib
import re

# Duas linhas só viram um par "de → para" quando ainda são a mesma frase
# editada. Abaixo disso são parágrafos distintos, e forçar o par produziria um
# "DE/PARA" que ninguém escreveu.
MIN_SIMILARITY = 0.5

# Blocos maiores que isto viram remoção + adição sem pareamento: o pareamento é
# O(n×m) em comparações de linha, e um bloco desse tamanho é reescrita de seção
# inteira, onde o par frase a frase não diria nada de útil.
MAX_PAIRABLE_LINES = 40

# Palavras de contexto mantidas de cada lado do trecho alterado. Três bastam
# para saber onde a mudança caiu; mais que isso repete o parágrafo inteiro em
# cada um dos 240 pares.
CONTEXT_WORDS = 3

# Um par literal "removido → inserido" que aparece 2 vezes ou mais já é um
# grupo exato: a repetição é a prova de que é padrão, e não precisa de modelo
# para ser vista. Medido nas petições reais: 27 pares repetidos cobrem 90 das
# 275 mudanças (33%) — e são justamente os que viram regra de manual.
MIN_REPEATS_FOR_EXACT_GROUP = 2

# Quantas vezes um padrão precisa aparecer para não ser acidente de uma vez.
MIN_OCCURRENCES_FOR_PATTERN = 3

# Mudança que toca número, data, valor ou placeholder é factual, e erro factual
# vale regra já na primeira vez: um valor da causa deixado como "R$ XXX" não
# precisa se repetir para ser grave.
_FACTUAL = re.compile(r'\d{2,}|X{3,}')

# Quantos exemplos literais acompanham cada padrão na tela.
EXAMPLES_PER_PATTERN = 3

# Teto do texto entregue ao prompt. Documento reescrito de ponta a ponta faria
# o diff crescer até o tamanho dos dois originais, desfazendo a economia.
# Quando corta, corta À VISTA (ver `format_for_prompt`).
PROMPT_MAX_CHARS = 200_000

# Marcador que o extrator de DOCX insere onde havia imagem embutida (print do
# FAP Web, CAT, extrato). NÃO é texto da petição: é nosso. Sem tratá-lo à
# parte, uma imagem acrescentada pelo revisor virava "acrescentar «[IMAGEM
# ANEXADA NO DOCUMENTO]»" e o agente chegou a propor, como regra de manual,
# que o advogado removesse esse placeholder do texto — instrução sobre uma
# string que só existe dentro deste pipeline.
#
# Espelha `IMAGE_MARKER` de `app/blueprints/fap_review.py`; o serviço não
# importa do blueprint para não inverter as camadas, e o teste confere que os
# dois continuam iguais.
IMAGE_MARKER = '[IMAGEM ANEXADA NO DOCUMENTO]'


def extract_changes(
    original: str,
    revised: str,
    context_words: int = CONTEXT_WORDS,
) -> list[dict]:
    """Mudanças entre as duas versões, uma entrada por trecho alterado.

    Cada entrada tem ``kind`` igual a ``change`` (com ``removed`` e
    ``inserted``), ``addition`` ou ``removal``. Linhas em branco são
    descartadas antes da comparação: a extração de DOCX produz muitas, e elas
    deslocariam o alinhamento sem representar mudança nenhuma.
    """
    original_lines = [line for line in (original or '').splitlines() if line.strip()]
    revised_lines = [line for line in (revised or '').splitlines() if line.strip()]

    changes: list[dict] = []
    matcher = difflib.SequenceMatcher(None, original_lines, revised_lines, autojunk=False)

    for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes():
        if tag == 'equal':
            continue

        original_block = original_lines[start_a:end_a]
        revised_block = revised_lines[start_b:end_b]

        if tag == 'delete':
            changes.extend(
                _removal(line, start_a + offset + 1)
                for offset, line in enumerate(original_block)
            )
            continue

        if tag == 'insert':
            changes.extend(_addition(line, start_a + 1) for line in revised_block)
            continue

        # tag == 'replace'
        for index_a, index_b in _pair_lines(original_block, revised_block):
            if index_a is None:
                changes.append(_addition(revised_block[index_b], start_a + 1))
            elif index_b is None:
                changes.append(_removal(original_block[index_a], start_a + index_a + 1))
            else:
                changes.extend(
                    _word_level_changes(
                        original_block[index_a],
                        revised_block[index_b],
                        line=start_a + index_a + 1,
                        context_words=context_words,
                    )
                )

    return changes


def _addition(text: str, line: int) -> dict:
    """Parágrafo que só existe na versão revisada."""
    return {'kind': 'addition', 'removed': '', 'inserted': text,
            'context_before': '', 'context_after': '', 'line': line}


def _removal(text: str, line: int) -> dict:
    """Parágrafo que o revisor tirou."""
    return {'kind': 'removal', 'removed': text, 'inserted': '',
            'context_before': '', 'context_after': '', 'line': line}


def _pair_lines(original_block: list[str], revised_block: list[str]):
    """Alinha as linhas de um bloco ``replace``, deixando as sobras sem par.

    Com blocos do mesmo tamanho o pareamento é posicional — é o caso comum, um
    parágrafo editado no lugar. Quando os tamanhos diferem (o revisor quebrou
    ou juntou parágrafos), cada linha removida procura a linha adicionada mais
    parecida; o que não passar de ``MIN_SIMILARITY`` sai como remoção ou adição
    pura, em vez de virar um par inventado.
    """
    if len(original_block) == len(revised_block):
        return [(index, index) for index in range(len(original_block))]

    if len(original_block) > MAX_PAIRABLE_LINES or len(revised_block) > MAX_PAIRABLE_LINES:
        return (
            [(index, None) for index in range(len(original_block))]
            + [(None, index) for index in range(len(revised_block))]
        )

    pairs: list[tuple[int | None, int | None]] = []
    available_revised = set(range(len(revised_block)))

    for index_a, line_a in enumerate(original_block):
        best_index, best_score = None, MIN_SIMILARITY

        for index_b in sorted(available_revised):
            matcher = difflib.SequenceMatcher(None, line_a, revised_block[index_b])

            # `real_quick_ratio` e `quick_ratio` são tetos baratos de `ratio`:
            # se nem o teto passa da melhor nota, `ratio` não passaria. É a
            # mesma cascata de `difflib.get_close_matches`.
            #
            # O `ratio` completo é indispensável — `quick_ratio` ignora a ordem
            # e só compara o conjunto de caracteres, e duas frases jurídicas em
            # português usam quase as mesmas letras. Medido: "Da tempestividade
            # do pedido de revisão administrativa." contra "Do direito
            # aplicável ao caso concreto." dá quick=0,609 e real=0,304 — pelo
            # quick as duas virariam um par "DE/PARA" que ninguém escreveu,
            # acima do corte de 0,5.
            if matcher.real_quick_ratio() <= best_score:
                continue
            if matcher.quick_ratio() <= best_score:
                continue

            score = matcher.ratio()
            if score > best_score:
                best_index, best_score = index_b, score

        if best_index is None:
            pairs.append((index_a, None))
        else:
            available_revised.discard(best_index)
            pairs.append((index_a, best_index))

    pairs.extend((None, index_b) for index_b in sorted(available_revised))
    return pairs


def _word_level_changes(before: str, after: str, line: int, context_words: int) -> list[dict]:
    """Trechos alterados dentro de um parágrafo, com contexto de cada lado.

    Recortar por palavra é o que derruba o tamanho: o parágrafo tem centenas de
    caracteres e a correção costuma ser de uma palavra.
    """
    words_before = before.split(' ')
    words_after = after.split(' ')
    matcher = difflib.SequenceMatcher(None, words_before, words_after, autojunk=False)

    changes = []
    for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes():
        if tag == 'equal':
            continue
        changes.append({
            'kind': 'change',
            'removed': ' '.join(words_before[start_a:end_a]),
            'inserted': ' '.join(words_after[start_b:end_b]),
            'context_before': ' '.join(words_before[max(0, start_a - context_words):start_a]),
            'context_after': ' '.join(words_before[end_a:end_a + context_words]),
            'line': line,
        })
    return changes


def summarize_changes(changes: list[dict]) -> dict:
    """Contagem por tipo de mudança, para a tela e para o log."""
    changes = changes or []
    return {
        'total': len(changes),
        'changes': sum(1 for change in changes if change.get('kind') == 'change'),
        'additions': sum(1 for change in changes if change.get('kind') == 'addition'),
        'removals': sum(1 for change in changes if change.get('kind') == 'removal'),
    }


def format_for_prompt(
    changes: list[dict],
    max_chars: int = PROMPT_MAX_CHARS,
    only_indices: list[int] | None = None,
) -> str:
    """Renderiza as mudanças para o prompt do agente que as agrupa.

    Se o teto for atingido, a última linha DIZ quantas ficaram de fora. Corte
    silencioso foi o defeito que originou este módulo: o agente antigo recebia
    12.000 caracteres de um documento de 164.570 e ninguém via.
    """
    changes = changes or []
    selected = list(only_indices) if only_indices is not None else list(range(len(changes)))

    blocks: list[str] = []
    size = 0

    for position, index in enumerate(selected):
        # O número exibido é o índice GLOBAL, não a posição na seleção: o
        # modelo devolve esses números e eles são resolvidos contra a lista
        # inteira de mudanças.
        block = f'#{index} {_format_change(changes[index])}'
        if size + len(block) > max_chars:
            remaining = len(selected) - position
            blocks.append(f'\n[... mais {remaining} mudanças não couberam neste recorte ...]')
            break
        blocks.append(block)
        size += len(block)

    return '\n'.join(blocks)


def _is_image_only(text: str) -> bool:
    """Se o texto é só marcador de imagem (um ou vários), sem conteúdo real."""
    resto = str(text or '').replace(IMAGE_MARKER, '').strip()
    return bool(text) and IMAGE_MARKER in str(text) and not resto


def _image_change_label(change: dict) -> str | None:
    """Descrição para mudança que é só imagem entrando ou saindo; None se não é."""
    removed, inserted = change.get('removed', ''), change.get('inserted', '')
    entrou, saiu = _is_image_only(inserted), _is_image_only(removed)

    if entrou and saiu:
        return None  # imagem trocada por imagem: nada de editorial a dizer
    if entrou and not str(removed or '').strip():
        return 'IMAGEM ACRESCENTADA'
    if saiu and not str(inserted or '').strip():
        return 'IMAGEM REMOVIDA'
    return None


def _format_change(change: dict) -> str:
    """Uma mudança, no formato que o agente lê."""
    kind = change.get('kind')
    line = change.get('line')

    imagem = _image_change_label(change)
    if imagem:
        return f'- {imagem} (linha {line})'

    if kind == 'addition':
        return f"- ADICIONADO (linha {line}): {change.get('inserted', '')}"
    if kind == 'removal':
        return f"- REMOVIDO (linha {line}): {change.get('removed', '')}"

    before = change.get('context_before', '')
    after = change.get('context_after', '')
    return (
        f"- ALTERADO (linha {line})\n"
        f"  DE:   {before} «{change.get('removed', '')}» {after}".rstrip() + "\n"
        f"  PARA: {before} «{change.get('inserted', '')}» {after}".rstrip()
    )


def reconcile_patterns(
    patterns: list[dict],
    changes: list[dict],
    already_claimed: set[int] | None = None,
) -> list[dict]:
    """Confere os padrões do modelo contra as mudanças reais.

    O modelo devolve, para cada padrão, os ÍNDICES das mudanças que o compõem —
    não um número e não exemplos escritos por ele. Aqui a contagem é feita no
    código e os exemplos são renderizados a partir das mudanças de verdade.

    Isso apaga três defeitos de uma vez, todos observados numa execução real:

    * **Contagem inventada.** Os padrões somavam 34+31+28+19+... muito além das
      275 mudanças existentes, porque cada um era contado por si.
    * **Exemplo que não bate com o rótulo.** Um padrão chamado "correção de
      placeholders" trazia como exemplo a inserção da preposição "na". Agora o
      exemplo é renderizado da mudança que o próprio modelo apontou.
    * **Índice repetido.** Uma mudança pertence a um padrão só; o primeiro que
      a reivindica fica com ela, e o resto é descartado em silêncio no total.
    """
    changes = changes or []
    claimed: set[int] = set(already_claimed or ())
    reconciled: list[dict] = []

    for pattern in patterns or []:
        indices = []
        for raw_index in pattern.get('change_indices') or []:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(changes) and index not in claimed:
                claimed.add(index)
                indices.append(index)

        if not indices:
            continue

        pattern_changes = [changes[index] for index in indices]
        reconciled.append({
            'pattern': str(pattern.get('pattern') or '').strip(),
            'occurrences': len(indices),
            'examples': [
                _format_change(change).replace('\n', ' ')
                for change in pattern_changes[:EXAMPLES_PER_PATTERN]
            ],
            'relevant_for_manual': (
                len(indices) >= MIN_OCCURRENCES_FOR_PATTERN
                or any(_touches_facts(change) for change in pattern_changes)
            ),
            'lines': sorted({change.get('line') for change in pattern_changes if change.get('line')}),
            'indices': indices,
        })

    reconciled.sort(key=lambda item: (-item['occurrences'], item['pattern']))
    return reconciled


def _touches_facts(change: dict) -> bool:
    """Se a mudança mexe em número, data, valor ou placeholder."""
    return bool(
        _FACTUAL.search(str(change.get('removed') or ''))
        or _FACTUAL.search(str(change.get('inserted') or ''))
    )


def unassigned_count(patterns: list[dict], changes: list[dict]) -> int:
    """Quantas mudanças o modelo não colocou em padrão nenhum.

    É o número que diz se o agrupamento leu a lista inteira ou desistiu no
    meio — sem ele, um agrupamento que cobriu 40 das 275 mudanças pareceria
    tão completo quanto um que cobriu todas.
    """
    return max(0, len(changes or []) - sum(p.get('occurrences', 0) for p in patterns or []))


def cluster_repeated_changes(changes: list[dict]) -> tuple[list[dict], list[int]]:
    """Agrupa, sem IA, as mudanças cujo par literal se repete.

    Devolve ``(grupos, índices restantes)``. Um par ``removido → inserido`` que
    aparece duas vezes ou mais é padrão por definição: a repetição É a prova.
    Rótulo, contagem e exemplo saem do próprio par, então não existe rótulo que
    não bate com o exemplo — o defeito que o agrupamento por modelo repetiu em
    três execuções seguidas ("pontuação" ilustrada com preposição, "ortografia"
    escondendo a troca de "Administração Pública" por "Previdência Social").

    O que sobra tem par único — aconteceu uma vez — e vai para o modelo, onde
    um rótulo impreciso custa pouco: mudança isolada e não factual já é
    marcada como ruído.
    """
    changes = changes or []

    by_pair: dict[tuple, list[int]] = {}
    for index, change in enumerate(changes):
        key = (change.get('kind'), change.get('removed', ''), change.get('inserted', ''))
        by_pair.setdefault(key, []).append(index)

    groups: list[dict] = []
    remaining: list[int] = []

    for (kind, removed, inserted), indices in by_pair.items():
        if len(indices) < MIN_REPEATS_FOR_EXACT_GROUP:
            remaining.extend(indices)
            continue

        group_changes = [changes[index] for index in indices]
        groups.append({
            'pattern': _exact_label(kind, removed, inserted),
            'occurrences': len(indices),
            'examples': [
                _format_change(change).replace('\n', ' ')
                for change in group_changes[:EXAMPLES_PER_PATTERN]
            ],
            # Repetição já é relevância: o par apareceu ao menos duas vezes.
            'relevant_for_manual': True,
            'lines': sorted({c.get('line') for c in group_changes if c.get('line')}),
            'indices': indices,
        })

    groups.sort(key=lambda item: (-item['occurrences'], item['pattern']))
    return groups, sorted(remaining)


def _exact_label(kind: str, removed: str, inserted: str) -> str:
    """Rótulo do grupo exato, escrito a partir do próprio par.

    Sem modelo no meio, então o rótulo descreve exatamente o que os membros do
    grupo têm em comum — que é a definição do grupo.
    """
    def curto(texto: str, limite: int = 60) -> str:
        texto = ' '.join(str(texto or '').split())
        return texto if len(texto) <= limite else texto[:limite - 1] + '…'

    imagem = _image_change_label({'removed': removed, 'inserted': inserted})
    if imagem == 'IMAGEM ACRESCENTADA':
        return 'Acrescentar imagem (prova anexada ao documento)'
    if imagem == 'IMAGEM REMOVIDA':
        return 'Remover imagem do documento'

    if kind == 'addition':
        return f'Acrescentar «{curto(inserted)}»'
    if kind == 'removal':
        return f'Remover «{curto(removed)}»'
    if not removed:
        return f'Inserir «{curto(inserted)}»'
    if not inserted:
        return f'Remover «{curto(removed)}»'
    return f'Trocar «{curto(removed)}» por «{curto(inserted)}»'
