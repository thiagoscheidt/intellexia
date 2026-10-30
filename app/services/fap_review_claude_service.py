"""
Revisão feita no Claude: instruções, conferência e gravação.

O Claude do usuário revisa a petição na própria conversa, com o arquivo que já
está anexado, seguindo as mesmas instruções que o agente revisor do escritório
recebe. O IntellexIA não recebe a petição: entrega as instruções, confere o
JSON do resultado (o mesmo parse e o mesmo saneador do agente) e, se o usuário
quiser, grava a revisão no histórico com o selo "Feita no Claude".

Substitui o fluxo do RPI-37 (revisão no servidor com o arquivo chegando por
link de envio, `curl` ou Drive): a equipe quer o resultado na conversa e sem
depender da rede do Claude. Spec:
docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.agents.fap_review.reviewer_agent import FapPetitionReviewerAgent, ReviewOutputParseError
from app.models import (
    db,
    FapReviewDraft,
    FapReviewExecution,
    FapReviewPetition,
    FapReviewPromptVersion,
    FapReviewReferenceVersion,
)
from app.services import fap_review_arquivos_service as _arquivos
from app.services import fap_review_service as _svc
from app.utils import planilha_beneficios as _planilha
from app.utils.timezone import SP_TZ

MODO_REVISAO = 'revisao'
MODO_COMPARACAO = 'comparacao'
MODOS = (MODO_REVISAO, MODO_COMPARACAO)

# Mesmo teto das ferramentas de referência do Revisor (MAX_REFERENCE_CHARS):
# não conhecemos o limite de resposta de ferramenta do claude.ai, e uma parte
# cortada pelo cliente deixaria o Claude revisar com metade do manual.
TAMANHO_PARTE = 40_000

VALIDADE_RASCUNHO = timedelta(hours=24)

# `result_json` é TEXT no MySQL (64 KB) no rascunho e em fap_review_executions.
# A revisão do servidor nunca chegou perto (máximo de 32 KB no banco local,
# com indentação), mas o Claude pode ser mais prolixo: acima disto o INSERT
# estoura com "Data too long" e o Claude receberia um erro genérico.
LIMITE_RESULTADO_BYTES = 65_535

# Chaves de primeiro nível do contrato de saída de cada modo. Sem conferir
# isso, `{"achados": [...]}` passaria pelo parse como revisão sem nenhum achado
# — uma petição "limpa" pronta para gravar.
CHAVES_DO_CONTRATO = {
    MODO_REVISAO: ('theses', 'findings', 'missing_documents'),
    MODO_COMPARACAO: ('comparative_changes', 'findings'),
}
# executive_summary fica fora da cobrança: as contagens são recontadas dos achados
# e o texto que vier (objeto, texto solto ou nada) é aproveitado no parse. Recusar
# por ele obrigava o Claude a reescrever o JSON inteiro — a parte demorada.

_ADAPTACAO = """COMO FAZER ESTA REVISÃO AQUI NA CONVERSA (instruções do IntellexIA para o Claude)

Você vai revisar a petição nesta conversa, no lugar do agente revisor do escritório. As instruções \
depois deste bloco são exatamente as que o agente recebe: siga-as à risca, inclusive o manual, os casos \
de referência e os pontos de atenção.

- {fonte}
- Não reescreva nem corrija a petição: aponte só o que as instruções pedem.
- O arquivo anexado não traz o marcador [IMAGEM ANEXADA NO DOCUMENTO]: as imagens que você vê no \
documento valem como esse marcador.
- O "CONTRATO TÉCNICO DE SAÍDA" vale para o argumento `resultado_json` da ferramenta \
conferir_revisao_peticao (modo "{modo}"). Não mostre o JSON ao usuário: quem mostra o resultado é a \
conferência.
- Em `location`, diga o tópico ou a seção e a página do arquivo (ex.: "Tópico 6 · p. 12"); o \
`location_excerpt` vai literal, para o usuário achar com Ctrl+F. PDF já tem página. No DOCX a página depende \
de quem monta o documento: antes de revisar, converta cada DOCX para PDF no seu ambiente de código e leia o texto por página, \
para saber em que página cai cada trecho (troque o caminho; na comparação, uma pasta por versão):
  soffice --headless --convert-to pdf --outdir /tmp/paginas "CAMINHO_DA_PETICAO.docx"
  python3 -c "import glob; c = glob.glob('/tmp/paginas/*.pdf')[0]
try:
    import pdfplumber; t = [p.extract_text() or '' for p in pdfplumber.open(c).pages]
except ImportError:
    from pypdf import PdfReader; t = [p.extract_text() or '' for p in PdfReader(c).pages]
for i, x in enumerate(t): print('=== PÁGINA %d ===' % (i + 1)); print(x)"
  A paginação do LibreOffice pode diferir em uma página da do Word: diga isso uma vez ao usuário, no topo \
do resultado. Sem ambiente de código ou sem o soffice, fique no tópico e avise uma vez que a página não \
pôde ser indicada.
- Os casos de referência não vêm inteiros (veja "CASOS DE REFERÊNCIA" abaixo): consulte-os por termo \
quando precisar.
- Se você mesmo encontrou a petição no IntellexIA (o usuário não informou), confirme com ele que é ela antes \
de usar o histórico dela.

ETAPAS — faça nesta ordem, sem pular nenhuma. A lista de tarefas (ou de progresso) da conversa é \
exatamente estas cinco, com estes nomes: se você já montou outra, substitua por estas agora. Antes de \
começar, avise o usuário que a revisão leva alguns minutos; ao passar de uma etapa para a outra, diga \
em qual está usando o nome abaixo:
1. Ler as instruções do revisor — todas as partes desta ferramenta, dizendo "parte N de M"; só siga \
depois da última.
{etapas}
4. Conferir o resultado no IntellexIA — mande o resultado para conferir_revisao_peticao, com a mesma \
lista de conferir_dados_beneficios em beneficios_conferidos; se voltarem avisos de formato, corrija e \
mande de novo antes de seguir.
5. Mostrar os achados e perguntar se grava — mostre o que a conferência devolveu e pergunte se o \
usuário quer gravar no IntellexIA; só chame gravar_revisao_peticao se ele disser que sim. Gravada, \
anexe os arquivos à revisão seguindo "envio_dos_arquivos" da resposta."""

_FONTE = {
    MODO_REVISAO: ('A petição é o arquivo anexado nesta conversa. Sem anexo, peça o arquivo ao usuário '
                   'antes de começar; com mais de um, pergunte qual é a petição.'),
    MODO_COMPARACAO: ('As duas versões são os arquivos anexados nesta conversa. Pergunte qual é a versão '
                      'original e qual a revisada se não estiver claro; sem os dois anexos, peça-os antes '
                      'de começar.'),
}

# Etapas 2 e 3 de cada modo; as demais são as mesmas e ficam em _ADAPTACAO.
# A conferência dos dados é da base do escritório, não do manual: sem dizer o
# que fazer com ela, o resultado ficava só na conversa e não ia para a revisão.
_DADOS_VIRAM_ACHADOS = (
    'Cada divergência de conferir_dados_beneficios vira achado, com o valor da petição e o da base '
    '(número que não existe na base ou CPF de outra pessoa é crítico); alerta da base que muda o pedido '
    '(já excluído do cálculo, fora do cálculo, não contestado, já deferido) também vira achado. '
    '"nao_conferidos" não é erro da petição.'
)

_ETAPAS = {
    MODO_REVISAO: ('2. Ler a petição — o arquivo anexado inteiro, inclusive as tabelas de benefícios e as '
                   'imagens. Chame conferir_dados_beneficios uma vez, com todos os benefícios citados e o que '
                   'a petição diz de cada um. Se houver planilha de benefícios anexada (.xlsx ou .csv), ou se '
                   'o usuário pedir a checagem dela, rode também a de conferir_planilha_beneficios.\n'
                   '3. Revisar — compare a petição com o manual e as regras das instruções; na dúvida '
                   'sobre um ponto, consulte os casos de referência por termo. ' + _DADOS_VIRAM_ACHADOS),
    MODO_COMPARACAO: ('2. Ler as duas versões — a original e a revisada, inteiras, inclusive tabelas e '
                      'imagens. Chame conferir_dados_beneficios uma vez, com os benefícios citados na versão '
                      'revisada e o que ela diz de cada um. Se houver planilha de benefícios anexada (.xlsx ou '
                      '.csv), rode a checagem de conferir_planilha_beneficios contra a versão revisada.\n'
                      '3. Comparar as versões — o que a revisada corrigiu do que o revisor apontou e o '
                      'que ficou pendente; na dúvida, consulte os casos de referência por termo. '
                      + _DADOS_VIRAM_ACHADOS),
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _sp(momento: datetime) -> datetime:
    return momento.replace(tzinfo=timezone.utc).astimezone(SP_TZ)


# ── Petição ──────────────────────────────────────────────────────────


def _localizar_peticao(law_firm_id: int, identificador: str | None,
                       peticao_id: int | None) -> tuple[FapReviewPetition | None, str]:
    """(petição ou None, Id Wrike informado). Levanta ValueError para id inexistente."""
    identificador = str(identificador or '').strip()
    if peticao_id:
        petition = FapReviewPetition.query.filter_by(id=peticao_id, law_firm_id=law_firm_id).first()
        if not petition:
            raise ValueError(f'Petição {peticao_id} não encontrada neste escritório.')
        return petition, petition.office_document_identifier or identificador
    if identificador:
        petition = FapReviewPetition.query.filter_by(
            law_firm_id=law_firm_id, office_document_identifier=identificador).first()
        return petition, identificador
    return None, ''


def _peticao_resumo(petition: FapReviewPetition | None) -> dict | None:
    if not petition:
        return None
    return {
        'peticao_id': petition.id,
        'identificador': petition.office_document_identifier,
        'titulo': petition.title,
        'status_descricao': _svc.PETITION_WORKFLOW_STATUSES.get(petition.workflow_status,
                                                                petition.workflow_status),
        'revisoes': petition.revision_count or 0,
    }


_CASOS_SOB_CONSULTA = (
    "Os casos de referência do escritório ({tamanho} caracteres) não vêm nestas instruções, porque "
    "estouravam a conversa. O MANUAL acima é a régua; os casos mostram como o escritório a aplicou "
    "(os títulos são por empresa, ex.: \"CASO 1 — EMPRESA X\"). Quando encontrar um ponto e quiser saber "
    "o que foi decidido em situação parecida, consulte por termo: "
    "ler_manual_revisor(tipo=\"casos_referencia\", termo=\"<palavra-chave do ponto>\"). Cite o caso em "
    "manual_reference quando ele embasar o achado."
)

_FORMATO_NO_FIM = """=== FORMATO DA RESPOSTA (o mesmo do CONTRATO TÉCNICO DE SAÍDA, repetido aqui no fim) ===

Mande para conferir_revisao_peticao, em resultado_json, um objeto JSON exatamente assim:
{schema}

- Cada item de cada lista é um OBJETO com esses campos — nunca texto solto.
- Use os nomes de campo em inglês, como acima; os valores em português.
"""

# Como o Claude apresenta o resultado conferido. Volta na resposta da
# conferência, que é quando ele vai escrever para o usuário.
_COMO_MOSTRAR = """Monte a resposta ao usuário em Markdown, nesta ordem (pule a seção que vier vazia):

## Revisão da petição
**N achados** · 🔴 N críticos · 🟡 N moderados · 🔵 N formais
Uma ou duas frases com a prioridade de correção.

### 🔴 Críticos

#### 🔴 1 · Título curto do achado
📍 Tópico 6 · p. 12 · 📘 Manual: referência, se houver · 🆕 Padrão novo — confirme, se `padrao_novo`

```text
trecho literal do achado
```

✏️ **Correção:** a correção sugerida

---

### 🟡 Moderados
Mesmo formato, com 🟡 no título de cada achado (#### 🟡 4 · Título).

### 🔵 Formais
Até 10, no mesmo formato, com 🔵. Mais que isso, uma tabela por tema:
| Tema | Achados | Exemplos |
|---|---|---|
| Pontuação | 35, 36, 43 | vírgulas, travessões |

### 🔁 Mudanças entre as versões
Só na comparação: o que a revisada corrigiu e o que ficou pendente.

### 📄 Documentos em falta
| Tese / tópico | Documento | Manual |
|---|---|---|

### 🔎 Dados dos benefícios
Uma linha com o resultado de conferir_dados_beneficios: "N benefícios conferidos com a base: X conferem, \
Y com divergência, Z não encontrados". As divergências e os alertas já estão nos achados — não repita.

### 📊 Planilha de benefícios
Só se houve checagem da planilha: "N de M benefícios da planilha citados na petição", depois a tabela \
com os que faltam primeiro:
| Aba | Benefício | Tese | Na petição |
|---|---|---|---|
| 2022 | 633.333.333-3 | B31 indevido | ❌ |
Mais de 20 citados: mostre só os que faltam e diga quantos foram encontrados.

### 🧹 Ajustes do saneador
O que ele descartou ou corrigiu, e por quê. Achados já marcados como "não pertinente" nesta \
petição também vêm aqui.

---
Pergunta sobre gravar no histórico.

Regras:
- Mantenha a numeração da conferência (`numero`): é por ela que o usuário vai citar o achado.
- Críticos e moderados aparecem todos, um a um; nunca agrupe nem resuma esses.
- Título de cada achado como subtítulo (####), com a cor e o número separados por "·". Nunca comece a \
linha com "4." — o Markdown transforma em lista, renumera e cola a linha seguinte no título.
- Local, manual e padrão novo numa linha só, logo abaixo do título.
- O trecho vai num bloco de código ```text (a conversa mostra um botão de copiar), exatamente como veio, \
sem aspas; sem trecho, omita o bloco.
- Linha em branco entre título, trecho e correção, e --- entre um achado e outro.
- Não mostre o JSON nem nomes de campo."""


def formato_esperado(modo: str) -> str:
    """O contrato de saída do agente para o modo — o que a conferência espera receber."""
    if modo == MODO_COMPARACAO:
        return FapPetitionReviewerAgent._OUTPUT_SCHEMA_COMPARATIVE
    return FapPetitionReviewerAgent._OUTPUT_SCHEMA_SINGLE


def _pontos_de_atencao(law_firm_id: int, petition, identificador: str) -> str | None:
    from app.blueprints.fap_review import _build_prior_attention_points

    return _build_prior_attention_points(
        law_firm_id=law_firm_id,
        petition_id=petition.id if petition else None,
        law_firm_document_identifier=identificador or '',
        current_execution_id=0,
    )


# ── Instruções ───────────────────────────────────────────────────────


def _conteudo_prompt(law_firm_id: int, tipo: str) -> str:
    versao = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id, prompt_type=tipo, is_active=True,
    ).order_by(FapReviewPromptVersion.version_number.desc()).first()
    return versao.content if versao and versao.content else ''


def _conteudo_referencia(law_firm_id: int, tipo: str) -> str:
    versao = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id, reference_type=tipo, is_active=True,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()
    return versao.content if versao and versao.content else ''


def montar_instrucoes(law_firm_id: int, modo: str, *, identificador: str | None = None,
                      peticao_id: int | None = None) -> dict:
    """Instruções completas da revisão, pelo mesmo código que monta as do agente.

    Prompt de sistema (identidade, regras, contrato de saída, manual, casos,
    instruções do projeto) e mensagem da tarefa com os pontos de atenção da
    última revisão do IntellexIA, precedidos do bloco que adapta a revisão à
    conversa. Levanta ValueError para modo ou petição inválidos.
    """
    if modo not in MODOS:
        raise ValueError(f'Modo inválido: use {" ou ".join(MODOS)}.')
    petition, identificador = _localizar_peticao(law_firm_id, identificador, peticao_id)
    pontos = _pontos_de_atencao(law_firm_id, petition, identificador)
    comparativa = modo == MODO_COMPARACAO

    # Casos sob consulta (decisão do Thiago, 28/10/2026): em homologação eram 197
    # mil caracteres, 60% das instruções — 10 partes, e a conversa do Claude
    # compactava no meio da revisão, perdendo o formato do JSON.
    casos = _conteudo_referencia(law_firm_id, 'casos_referencia')
    sistema = FapPetitionReviewerAgent.montar_prompt_sistema(
        _conteudo_prompt(law_firm_id, 'revisor_identity'),
        _conteudo_prompt(law_firm_id, 'revisor_rules'),
        manual=_conteudo_referencia(law_firm_id, 'manual_fap'),
        casos=_CASOS_SOB_CONSULTA.format(tamanho=f'{len(casos):,}'.replace(',', '.')) if casos else '',
        instrucoes_projeto=_conteudo_referencia(law_firm_id, 'project_instructions'),
        focused_review=bool(pontos),
        comparative=comparativa,
    )
    if comparativa:
        tarefa = FapPetitionReviewerAgent._build_comparative_user_message(
            auxiliary_documents=None, prior_attention_points=pontos)
    else:
        tarefa = FapPetitionReviewerAgent._build_single_user_message(
            auxiliary_documents=None, prior_attention_points=pontos)

    texto = (_ADAPTACAO.format(fonte=_FONTE[modo], modo=modo, etapas=_ETAPAS[modo])
             + '\n\n=== INSTRUÇÕES DO AGENTE REVISOR DO ESCRITÓRIO ===\n\n' + sistema
             + '\n\n=== TAREFA ===\n\n' + tarefa + '\n\n'
             + _FORMATO_NO_FIM.format(schema=formato_esperado(modo)))

    aviso = None
    bloqueio = _svc.describe_new_revision_block(petition)
    if bloqueio:
        aviso = f'{bloqueio} A revisão pode ser feita aqui na conversa, mas não poderá ser gravada no histórico.'
    return {
        'texto': texto,
        'peticao': petition,
        'identificador': identificador,
        'revisao_focada': bool(pontos),
        'aviso': aviso,
    }


def partes_do_texto(texto: str, tamanho: int = TAMANHO_PARTE) -> list[str]:
    """Corta o texto em partes de até `tamanho`, sempre em fim de linha.

    Prefere cortar depois de uma linha em branco (fim de parágrafo ou seção)
    quando ela está na segunda metade da parte. As partes juntas reproduzem o
    texto. Só uma linha maior que a parte inteira é cortada no meio.
    """
    partes: list[str] = []
    atual: list[str] = []
    tamanho_atual = 0
    for linha in texto.splitlines(keepends=True):
        while len(linha) > tamanho:
            if atual:
                partes.append(''.join(atual))
                atual, tamanho_atual = [], 0
            partes.append(linha[:tamanho])
            linha = linha[tamanho:]
        if atual and tamanho_atual + len(linha) > tamanho:
            corte = len(atual)
            acumulado = tamanho_atual
            for i in range(len(atual) - 1, 0, -1):
                acumulado -= len(atual[i])
                if not atual[i - 1].strip():
                    # atual[:i] termina numa linha em branco
                    if acumulado >= tamanho // 2 and tamanho_atual - acumulado + len(linha) <= tamanho:
                        corte = i
                    break
            partes.append(''.join(atual[:corte]))
            atual = atual[corte:]
            tamanho_atual = sum(len(x) for x in atual)
        atual.append(linha)
        tamanho_atual += len(linha)
    if atual:
        partes.append(''.join(atual))
    return partes or ['']


def instrucoes(law_firm_id: int, modo: str, *, identificador: str | None = None,
               peticao_id: int | None = None, parte: int = 1) -> dict:
    """Uma parte das instruções, no formato das ferramentas do MCP."""
    try:
        montadas = montar_instrucoes(law_firm_id, modo, identificador=identificador, peticao_id=peticao_id)
    except ValueError as e:
        return {'erro': str(e)}
    partes = partes_do_texto(montadas['texto'])
    total = len(partes)
    try:
        parte = int(parte or 1)
    except (TypeError, ValueError):
        parte = 0
    if not 1 <= parte <= total:
        return {'erro': f'A parte {parte} não existe: as instruções têm {total} partes (1 a {total}).'}

    resposta = {
        'modo': modo,
        'parte': parte,
        'total_partes': total,
        'peticao': _peticao_resumo(montadas['peticao']),
        'revisao_focada': montadas['revisao_focada'],
    }
    if montadas['aviso']:
        resposta['aviso'] = montadas['aviso']
    resposta['conteudo'] = partes[parte - 1]

    referencia = []
    if montadas['peticao']:
        referencia.append(f"peticao_id={montadas['peticao'].id}")
    elif montadas['identificador']:
        referencia.append(f"identificador_documento=\"{montadas['identificador']}\"")
    argumentos = ', '.join([f'modo="{modo}"'] + referencia)
    if parte < total:
        resposta['proximo_passo'] = (
            f'Chame de novo com parte={parte + 1} (de {total}), com os mesmos argumentos. '
            'Não comece a revisar antes de ler todas as partes.'
        )
    else:
        resposta['proximo_passo'] = (
            'Você leu todas as partes. Agora: (1) revise a petição anexada seguindo as instruções; '
            f'(2) mande o JSON do contrato de saída para conferir_revisao_peticao(resultado_json=..., {argumentos}); '
            '(3) mostre ao usuário os achados que a conferência devolver e pergunte se ele quer gravar. '
            'Se esta conversa já tiver outra revisão, sugira abrir uma conversa nova: o contexto acumulado '
            'gasta o limite do plano do Claude do usuário.'
        )
    return resposta


# ── Planilha de benefícios ───────────────────────────────────────────

_SCRIPT_PRINCIPAL = """
if __name__ == '__main__':
    import json
    import sys
    if len(sys.argv) != 3:
        sys.exit('uso: python conferir_planilha.py PLANILHA PETICAO')
    try:
        resultado = conferir_planilha(sys.argv[1], Path(sys.argv[1]).name,
                                      texto_do_documento(sys.argv[2]), Path(sys.argv[2]).name)
    except (ValueError, ImportError) as erro:
        sys.exit(str(erro))
    resultado['script_versao'] = VERSAO
    print(json.dumps(resultado, ensure_ascii=False))
"""


def _codigo_compacto(fonte: str) -> str:
    """Módulo sem docstring, comentário nem anotação de tipo.

    O Claude copia o script para um arquivo: texto menor é menos tempo e menos
    chance de errar na cópia. Sem anotação, também roda em Python mais antigo.
    """
    arvore = ast.parse(fonte)
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            corpo = no.body
            if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], 'value', None), ast.Constant) \
                    and isinstance(corpo[0].value.value, str):
                no.body = corpo[1:] or [ast.Pass()]
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            no.returns = None
            for arg in no.args.args + no.args.kwonlyargs + no.args.posonlyargs:
                arg.annotation = None
    return ast.unparse(arvore)


def script_planilha() -> dict:
    """O script que o Claude roda no ambiente dele: o módulo da tela + a chamada.

    A versão é o hash do código; a conferência só aceita resultado com a versão
    atual — o que garante que veio deste script, e não de uma comparação de olho.
    """
    codigo = _codigo_compacto(Path(_planilha.__file__).read_text(encoding='utf-8'))
    versao = hashlib.sha256(codigo.encode('utf-8')).hexdigest()[:12]
    return {
        'versao': versao,
        'script': f"VERSAO = '{versao}'\n" + codigo + '\n' + _SCRIPT_PRINCIPAL,
        'como_rodar': (
            'Grave o "script" num arquivo, sem mudar nada (ex.: conferir_planilha.py), e rode no seu ambiente '
            'de código: python conferir_planilha.py <planilha .xlsx ou .csv> <petição .docx, .pdf ou .txt>. '
            + _arquivos.ONDE_ESTAO_OS_ANEXOS + ' Na comparação de versões, use a versão revisada. Ele imprime um JSON com cada benefício da '
            'planilha que tem tese e se ele foi citado na petição (qualquer pontuação entre os dígitos vale). '
            'Erro de coluna: o script diz o que faltou em cada aba — repasse ao usuário.'
        ),
        'sem_ambiente_de_codigo': (
            'Se você não conseguir rodar código nesta conversa, NÃO compare de olho: diga ao usuário que a '
            'checagem da planilha não foi feita (a tela do Revisor faz) e siga a revisão.'
        ),
        'proximo_passo': (
            'Mostre ao usuário quantos benefícios da planilha foram citados e a tabela, com os que faltam '
            'primeiro (veja a seção 📊 de "como_mostrar" na conferência). Numa revisão, mande o JSON impresso, '
            'inteiro e sem mudar, em conferir_revisao_peticao(planilha_beneficios=...): ele fica gravado com a '
            'revisão e aparece na tela como na revisão da web.'
        ),
    }


def _texto(valor, limite: int) -> str:
    return ' '.join(str(valor if valor is not None else '').split())[:limite]


def _checagem_da_planilha(bruto) -> tuple[dict | None, str | None]:
    """(bloco para o resultado, aviso). O bloco tem o formato da revisão da tela."""
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto)
        except json.JSONDecodeError:
            return None, 'A checagem da planilha não é um JSON válido: mande o que o script imprimiu, sem mudar.'
    if not isinstance(bruto, dict) or bruto.get('script_versao') != script_planilha()['versao']:
        return None, ('A checagem da planilha não veio do script atual de conferir_planilha_beneficios, então '
                      'ficou fora: chame a ferramenta, rode o script e mande o JSON que ele imprimir.')
    itens_brutos = bruto.get('items')
    if not isinstance(itens_brutos, list) or not all(
            isinstance(i, dict) and isinstance(i.get('found_in_document'), bool) for i in itens_brutos):
        return None, 'A checagem da planilha veio fora do formato do script e ficou fora: mande a saída sem mudar.'
    itens = [{
        'benefit_number': _texto(i.get('benefit_number'), 40),
        'thesis': _texto(i.get('thesis'), 300),
        'sheet_name': _texto(i.get('sheet_name'), 100),
        'found_in_document': i['found_in_document'],
    } for i in itens_brutos]
    citados = sum(1 for i in itens if i['found_in_document'])
    return {
        'source_filename': _texto(bruto.get('source_filename'), 200) or 'Planilha enviada',
        'checked_document_label': _texto(bruto.get('checked_document_label'), 200),
        'total_rows_with_theses': len(itens),
        'found_count': citados,
        'missing_count': len(itens) - citados,
        'items': itens,
    }, None


_TOTAIS_DOS_DADOS = ('total', 'conferem', 'com_divergencia', 'nao_encontrados', 'invalidos', 'com_alerta')


def _tabela_dos_dados(law_firm_id: int, beneficios) -> tuple[dict | None, str | None]:
    """(tabela para o resultado, aviso). Refaz conferir_dados_beneficios com a lista do Claude.

    A conferência roda aqui, contra a base, e não é copiada do que o Claude
    mostrou: o gravado é o que a base diz. Fica de fora o nome do segurado (já
    está na Central para quem pode ver) e as linhas inteiras da base.
    """
    from app.services import conferencia_beneficios_service as _conf

    try:
        r = _conf.conferir(law_firm_id, beneficios)
    except ValueError as e:
        return None, (f'A tabela dos dados dos benefícios ficou fora: {e} Mande em beneficios_conferidos a mesma '
                      'lista que foi para conferir_dados_beneficios.')
    itens = [{
        'numero': i['numero_normalizado'] or str(i['numero'])[:40],
        'situacao': i['situacao'],
        'divergencias': [{'campo': d['campo'], 'peticao': _texto(d['peticao'], 120),
                          'base': [_texto(b, 120) for b in d['base'][:3]]} for d in i['divergencias']],
        'alertas': [{'codigo': a['codigo'], 'vigencia': a.get('vigencia'), 'mensagem': _texto(a['mensagem'], 300)}
                    for a in i['alertas']],
    } for i in r['itens']]
    return {**{k: r[k] for k in _TOTAIS_DOS_DADOS}, 'itens': itens}, None


# ── Conferência ──────────────────────────────────────────────────────


def _problemas_do_contrato(dados, modo: str) -> list[str]:
    if not isinstance(dados, dict):
        return ['o resultado precisa ser um objeto JSON com as chaves do contrato de saída']
    esperadas = CHAVES_DO_CONTRATO[modo]
    problemas = []
    faltando = [chave for chave in esperadas if chave not in dados]
    if faltando:
        recebidas = ', '.join(sorted(map(str, dados))) or 'nenhuma'
        problemas.append(f'faltam as chaves {", ".join(faltando)} (chaves recebidas: {recebidas})')
    for chave in esperadas:
        if chave not in dados:
            continue
        if not isinstance(dados[chave], list):
            problemas.append(f'"{chave}" tem de ser uma lista')
    return problemas


def _achado_para_exibir(numero: int, achado: dict, ignorados: set[str]) -> dict:
    item = {
        'numero': numero,
        'gravidade': achado.get('severity'),
        'categoria': achado.get('category'),
        'descricao': achado.get('description'),
        'local': achado.get('location'),
        'trecho': achado.get('location_excerpt'),
        'correcao_sugerida': achado.get('correction'),
        'referencia_manual': achado.get('manual_reference'),
    }
    correcao = achado.get('sanitizer_fix')
    if isinstance(correcao, dict) and correcao.get('motivo'):
        item['corrigido_pelo_saneador'] = correcao['motivo']
    if _svc.build_finding_fingerprint(achado) in ignorados:
        item['ja_marcado_nao_pertinente'] = True
    if achado.get('is_new_pattern'):
        item['padrao_novo'] = True
    return item


def _exibicao(payload: dict, ignorados: set[str]) -> dict:
    resumo = payload.get('executive_summary') or {}
    exibicao = {
        'achados': [_achado_para_exibir(i, a, ignorados)
                    for i, a in enumerate(payload.get('findings') or [], start=1)],
        'resumo': {
            'total_achados': resumo.get('total_findings'),
            'criticos': resumo.get('critical_findings'),
            'moderados': resumo.get('moderate_findings'),
            'formais': resumo.get('formal_findings'),
            'riscos': resumo.get('main_legal_risks') or [],
            'prioridade_de_correcao': resumo.get('correction_priority'),
        },
        'descartados_pelo_saneador': [
            {'regra': d.get('regra'), 'motivo': d.get('motivo'),
             'descricao': (d.get('achado') or {}).get('description')}
            for d in payload.get('sanitizer_discards') or []
        ],
    }
    if payload.get('analysis_type') == 'comparative':
        exibicao['mudancas_comparativas'] = [
            {'trecho_original': c.get('original_excerpt'), 'trecho_corrigido': c.get('corrected_excerpt'),
             'motivo': c.get('correction_reason'), 'secao_do_manual': c.get('manual_section')}
            for c in payload.get('comparative_changes') or []
        ]
    else:
        exibicao['documentos_em_falta'] = [
            {'tipo_documento': d.get('document_type'), 'tese': d.get('thesis'),
             'referencia_manual': d.get('manual_reference')}
            for d in payload.get('missing_documents') or []
        ]
        exibicao['teses'] = [
            {'tese': t.get('thesis'), 'numero_beneficio': t.get('benefit_number'),
             'enquadramento': t.get('classification')}
            for t in payload.get('theses') or []
        ]
    return exibicao


def _ignorados(law_firm_id: int, identificador: str) -> set[str]:
    from app.blueprints.fap_review import _get_ignored_finding_fingerprints

    return _get_ignored_finding_fingerprints(law_firm_id, identificador) if identificador else set()


def conferir(law_firm_id: int, user_id: int, resultado_json, modo: str = MODO_REVISAO, *,
             identificador: str | None = None, peticao_id: int | None = None,
             planilha_beneficios=None, beneficios_conferidos=None) -> dict:
    """Confere o JSON da revisão feita no Claude e guarda o rascunho saneado.

    Mesmo parse e mesmo saneador do agente (`montar_resultado`), sem o texto
    da petição — as regras que dependem dele (R1, R3) ficam desligadas, como o
    saneador prevê. O que volta é o que o Claude mostra e o que fica gravado se
    o usuário quiser.
    """
    if modo not in MODOS:
        return {'erro': f'Modo inválido: use {" ou ".join(MODOS)}.'}
    dados = resultado_json
    if isinstance(dados, str):
        try:
            dados = json.loads(dados)
        except json.JSONDecodeError as e:
            return {'erro': f'O resultado não é um JSON válido ({e.msg}, posição {e.pos}). Corrija e mande de novo.'}
    problemas = _problemas_do_contrato(dados, modo)
    if problemas:
        return {'erro': 'O resultado não segue o contrato de saída: ' + '; '.join(problemas)
                        + '. Corrija seguindo o formato_esperado e mande de novo.',
                'formato_esperado': formato_esperado(modo)}
    try:
        petition, identificador = _localizar_peticao(law_firm_id, identificador, peticao_id)
    except ValueError as e:
        return {'erro': str(e)}

    focada = bool(_pontos_de_atencao(law_firm_id, petition, identificador))
    try:
        resultado, erros = FapPetitionReviewerAgent.montar_resultado(
            dados, comparativa=modo == MODO_COMPARACAO, revisao_focada=focada)
    except ReviewOutputParseError as e:
        return {'erro': f'{e} Corrija seguindo o formato_esperado e mande de novo.',
                'formato_esperado': formato_esperado(modo)}
    payload = resultado.model_dump(mode='json')
    planilha, aviso_planilha = (None, None)
    if planilha_beneficios not in (None, '', {}):
        planilha, aviso_planilha = _checagem_da_planilha(planilha_beneficios)
    if planilha:
        payload['benefits_spreadsheet_review'] = planilha
    dados_beneficios, aviso_beneficios = (None, None)
    if beneficios_conferidos not in (None, '', [], {}):
        dados_beneficios, aviso_beneficios = _tabela_dos_dados(law_firm_id, beneficios_conferidos)
    if dados_beneficios:
        payload['benefits_data_check'] = dados_beneficios
    # Compacto, sem indentação: o mesmo resultado ocupa ~25% menos e cabe mais
    # achado no limite do TEXT. Quem lê é json.loads, o formato não importa.
    result_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    exibicao = _exibicao(payload, _ignorados(law_firm_id, identificador))
    tamanho = len(result_json.encode('utf-8'))
    if tamanho > LIMITE_RESULTADO_BYTES:
        return {
            'modo': modo,
            'peticao': _peticao_resumo(petition),
            'revisao_focada': focada,
            **exibicao,
            'aviso': (f'O resultado tem {tamanho // 1024} KB e o histórico do Revisor guarda até '
                      f'{(LIMITE_RESULTADO_BYTES + 1) // 1024} KB por revisão: dá para ver os achados aqui, '
                      'mas esta revisão não pode ser gravada.'),
            'proximo_passo': (
                'Mostre ao usuário ESTES achados, e não os do seu JSON, e explique que a revisão ficou grande '
                'demais para gravar no histórico do Revisor. Não chame gravar_revisao_peticao.'
            ),
        }

    agora = _utcnow()
    FapReviewDraft.query.filter(
        FapReviewDraft.law_firm_id == law_firm_id,
        FapReviewDraft.expires_at <= agora,
    ).delete(synchronize_session=False)
    rascunho = FapReviewDraft(
        law_firm_id=law_firm_id,
        user_id=user_id,
        mode=modo,
        petition_id=petition.id if petition else None,
        identifier=identificador or None,
        result_json=result_json,
        used_versions_json=json.dumps(_svc.collect_active_versions(law_firm_id), ensure_ascii=False),
        created_at=agora,
        expires_at=agora + VALIDADE_RASCUNHO,
    )
    db.session.add(rascunho)
    db.session.commit()

    resposta = {
        'rascunho_id': rascunho.id,
        'vale_ate': f'{_sp(rascunho.expires_at):%d/%m %H:%M}',
        'modo': modo,
        'peticao': _peticao_resumo(petition),
        'revisao_focada': focada,
        **exibicao,
        'como_mostrar': _COMO_MOSTRAR,
    }
    if planilha:
        resposta['planilha_beneficios'] = {
            'arquivo': planilha['source_filename'],
            'total': planilha['total_rows_with_theses'],
            'citados': planilha['found_count'],
            'faltando': planilha['missing_count'],
            'faltantes': [i for i in planilha['items'] if not i['found_in_document']],
        }
    if aviso_planilha:
        resposta['aviso_planilha'] = aviso_planilha
    if dados_beneficios:
        resposta['dados_beneficios'] = {k: dados_beneficios[k] for k in _TOTAIS_DOS_DADOS}
    if aviso_beneficios:
        resposta['aviso_beneficios'] = aviso_beneficios
    if erros:
        resposta['avisos'] = [str(e)[:300] for e in erros]
        resposta['formato_esperado'] = formato_esperado(modo)
    bloqueio = _svc.describe_new_revision_block(petition)
    if bloqueio:
        resposta['aviso'] = f'{bloqueio} Esta revisão não poderá ser gravada no histórico.'
    resposta['proximo_passo'] = (
        (f'ANTES DE MOSTRAR: a conferência deixou de fora {len(erros)} item(ns) por formato (veja "avisos"). '
         'Corrija esses itens seguindo "formato_esperado" e mande de novo para conferir_revisao_peticao o '
         'resultado inteiro; mostre ao usuário só o que a nova conferência devolver. ' if erros else '')
        + 'Mostre ao usuário ESTES achados, e não os do seu JSON, seguindo o modelo de "como_mostrar" '
        '(cores por gravidade, numeração da conferência, trecho em citação, ajustes do saneador e o que já '
        'tinha sido marcado como "não pertinente" nesta petição). Depois pergunte se ele quer gravar esta revisão no histórico do '
        'Revisor do IntellexIA — ela fica com o selo "Feita no Claude", fora da pontuação, e não envia a '
        f'petição para aprovação. Só chame gravar_revisao_peticao(rascunho_id={rascunho.id}, ...) se ele '
        'disser que sim. Para petição nova, peça o Id Wrike (só números) antes de gravar.'
    )
    return resposta


# ── Gravação ─────────────────────────────────────────────────────────


def _rotulo_modelo(modelo: str) -> str:
    modelo = ' '.join(str(modelo or '').split())[:80]
    return f'Claude · {modelo}' if modelo else 'Claude · modelo não informado'


def _ja_gravada(rascunho: FapReviewDraft) -> dict:
    execution = FapReviewExecution.query.get(rascunho.saved_execution_id)
    petition = execution.petition if execution else None
    link = _svc.revision_result_url(execution.id) if execution else None
    return {
        'ja_gravada': True,
        'revisao_id': execution.id if execution else None,
        'numero_revisao': execution.revision_number if execution else None,
        'peticao_id': petition.id if petition else None,
        'titulo': petition.title if petition else None,
        'link': link,
        'mensagem_para_usuario': f'Esta revisão já estava gravada no histórico: {link}',
        **(_envio_dos_arquivos(execution) if execution else {}),
    }


def _envio_dos_arquivos(execution: FapReviewExecution) -> dict:
    """Link para anexar os arquivos à revisão gravada, e o que fazer com ele."""
    return {
        'envio_dos_arquivos': _arquivos.envio_para_o_claude(execution),
        'proximo_passo': ('Mostre a mensagem_para_usuario. Depois anexe os arquivos à revisão seguindo '
                          '"envio_dos_arquivos": uma tentativa com o curl e, se falhar, o link para o usuário.'),
    }


def _peticao_para_gravar(law_firm_id: int, rascunho: FapReviewDraft, identificador: str | None,
                         peticao_id: int | None) -> tuple[FapReviewPetition | None, str]:
    """(petição existente ou None para criar, Id Wrike). Levanta ValueError com o motivo."""
    identificador = str(identificador or '').strip()
    if rascunho.petition_id:
        petition = FapReviewPetition.query.filter_by(id=rascunho.petition_id, law_firm_id=law_firm_id).first()
        if petition:
            outra = ((peticao_id and int(peticao_id) != petition.id)
                     or (identificador and identificador != petition.office_document_identifier))
            if outra:
                raise ValueError(
                    f'Este resultado foi conferido para a petição "{petition.title}" '
                    f'(Id Wrike {petition.office_document_identifier}). Grave nela, ou mande o resultado de '
                    'novo para conferir_revisao_peticao com a petição certa.')
            return petition, petition.office_document_identifier
    if rascunho.identifier:
        if identificador and identificador != rascunho.identifier:
            raise ValueError(
                f'Este resultado foi conferido para o Id Wrike {rascunho.identifier}. Grave nele, ou mande o '
                'resultado de novo para conferir_revisao_peticao com o Id certo.')
        identificador = rascunho.identifier
    petition, identificador = _localizar_peticao(law_firm_id, identificador, peticao_id)
    if petition:
        return petition, identificador
    if not identificador:
        raise ValueError('Informe a petição: o peticao_id de uma petição existente, ou o Id Wrike (só números) '
                         'para criar a petição nova. Pergunte ao usuário.')
    identificador, erro = _svc.validate_wrike_identifier(identificador)
    if erro:
        raise ValueError(erro)
    return None, identificador


def gravar(law_firm_id: int, user_id: int, rascunho_id: int, *, identificador: str | None = None,
           peticao_id: int | None = None, titulo: str = '', nome_arquivo: str = '',
           modelo: str = '') -> dict:
    """Grava o rascunho conferido como revisão da petição, com o selo "Feita no Claude".

    Grava exatamente o resultado conferido. Petição existente recebe a próxima
    revisão; petição nova exige o Id Wrike. Recusa petição travada e petição
    com revisão do IntellexIA em processamento — o rascunho continua valendo.
    """
    rascunho = FapReviewDraft.query.filter_by(id=rascunho_id, law_firm_id=law_firm_id, user_id=user_id).first()
    if not rascunho:
        return {'erro': f'Rascunho {rascunho_id} não encontrado. Mande o resultado para conferir_revisao_peticao.'}
    if rascunho.saved_execution_id:
        return _ja_gravada(rascunho)
    if rascunho.expires_at <= _utcnow():
        return {'erro': 'O rascunho venceu (vale 24 h). Mande o resultado de novo para conferir_revisao_peticao.'}

    try:
        petition, identificador = _peticao_para_gravar(law_firm_id, rascunho, identificador, peticao_id)
    except ValueError as e:
        return {'erro': str(e)}
    vale_ate = f'{_sp(rascunho.expires_at):%d/%m %H:%M}'
    bloqueio = _svc.describe_new_revision_block(petition)
    if bloqueio:
        return {'erro': f'{bloqueio} O rascunho continua valendo até {vale_ate}.'}
    rodando = _svc.running_revision(petition)
    if rodando:
        return {'erro': f'A revisão {rodando.revision_number} desta petição está rodando no IntellexIA. Espere '
                        f'terminar e peça para gravar de novo — o rascunho vale até {vale_ate}.'}

    peticao_criada = petition is None
    if peticao_criada:
        petition = FapReviewPetition(
            law_firm_id=law_firm_id,
            created_by_id=user_id,
            office_document_identifier=identificador,
            title=_svc.build_petition_title(titulo, fallback_filename=nome_arquivo,
                                            fallback_identifier=identificador),
            workflow_status='in_review',
        )
        db.session.add(petition)
        db.session.flush()

    numero = _svc._next_revision_number(petition)
    agora = datetime.now()
    execution = FapReviewExecution(
        law_firm_id=law_firm_id,
        user_id=user_id,
        petition_id=petition.id,
        execution_type='revision',
        status='completed',
        revision_number=numero,
        main_document_filename=str(nome_arquivo or '').strip()[:255] or None,
        law_firm_document_identifier=identificador,
        auxiliary_documents_count=0,
        auxiliary_documents_json=json.dumps([]),
        comparative_analysis=rascunho.mode == MODO_COMPARACAO,
        result_json=rascunho.result_json,
        used_versions_json=rascunho.used_versions_json,
        model_name=_rotulo_modelo(modelo),
        review_origin=_svc.REVIEW_ORIGIN_CLAUDE,
        completed_at=agora,
    )
    db.session.add(execution)
    db.session.flush()
    # Duas gravações simultâneas do mesmo rascunho: só uma passa.
    marcado = db.session.execute(
        update(FapReviewDraft)
        .where(FapReviewDraft.id == rascunho.id, FapReviewDraft.saved_execution_id.is_(None))
        .values(saved_execution_id=execution.id, saved_at=_utcnow())
    )
    if marcado.rowcount == 0:
        db.session.rollback()
        return _ja_gravada(FapReviewDraft.query.get(rascunho_id))
    _svc.sync_petition_after_revision(execution)
    db.session.commit()

    if peticao_criada:
        _svc.log_audit(law_firm_id, user_id, 'petition_created', 'petition', petition.id,
                       f'Petição criada via Claude: {petition.title}')
    _svc.log_audit(law_firm_id, user_id, 'revision_completed', 'execution', execution.id,
                   f'Revisão feita no Claude gravada: {identificador} (revisão {numero})')

    link = _svc.revision_result_url(execution.id)
    return {
        'revisao_id': execution.id,
        'numero_revisao': numero,
        'peticao_id': petition.id,
        'peticao_criada': peticao_criada,
        'titulo': petition.title,
        'origem': _svc.REVIEW_ORIGIN_CLAUDE_LABEL,
        'link': link,
        'mensagem_para_usuario': (
            f'Gravei como revisão {numero} da petição "{petition.title}", com o selo "Feita no Claude": {link}. '
            'Ela fica fora da pontuação e não envia a petição para aprovação — para isso, a última revisão '
            'precisa ser feita pela tela do Revisor.'
        ),
        **_envio_dos_arquivos(execution),
    }
