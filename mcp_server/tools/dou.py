"""
Tools: Diário Oficial da União
==============================
O acervo do DOU capturado do INLABS e os alertas do escritório. Só leitura.

Dois tipos de dado, com regras de tenant diferentes (como na tela):
  - **acervo** (edições e matérias): catálogo público federal, sem
    ``law_firm_id`` — pesquisa, leitura, edições e sumário;
  - **alertas e regras** ("O que vigiar"): nascem da carteira de clientes e
    das regras do escritório, e são sempre filtrados pelo ``law_firm_id``.

Tudo passa pelos serviços das telas, para o agente ver o que a pessoa vê:
``dou_search_service`` (a mesma busca, com CNPJ e processo reconhecidos),
``dou_edicao_service`` (o mesmo sumário), ``dou_alert_service`` (a mesma
listagem, o mesmo "ver trecho" e o mesmo resumo do e-mail diário) e
``dou_rule_service`` (o mesmo teste antes de salvar uma regra).
"""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import date

from fastmcp.exceptions import ToolError

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope

TEOR_MAX_CHARS = 20000
IDENTIFICADORES_MAX = 30
FACETAS_MAX = 15


# ── Utilidades ───────────────────────────────────────────────────────

def _iso(value):
    return value.isoformat() if value else None


def _chave(valor) -> str:
    """Comparação tolerante: sem acento, minúsculas, espaços simples."""
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return ' '.join(texto.lower().split())


def _texto_puro(trecho_html: str | None) -> str | None:
    """Trecho grifado da tela (<mark>, escapado) → texto com «» no achado."""
    if not trecho_html:
        return None
    texto = trecho_html.replace('<mark>', '«').replace('</mark>', '»')
    return html.unescape(re.sub(r'<[^>]+>', '', texto)).strip() or None


def _sem_grifo(trecho_html: str | None) -> str | None:
    texto = _texto_puro(trecho_html)
    return texto.replace('«', '').replace('»', '') if texto else texto


def _curto(texto, tamanho=300):
    texto = ' '.join((texto or '').split())
    return texto if len(texto) <= tamanho else texto[:tamanho].rsplit(' ', 1)[0] + '…'


def _url(app_public_url: str | None, caminho: str) -> str | None:
    return f"{app_public_url.rstrip('/')}{caminho}" if app_public_url else None


def _lista(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, str):
        valor = re.split(r'[;\n]', valor)
    return [str(v).strip() for v in valor if str(v).strip()]


def _data(valor, campo):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except ValueError:
        raise ToolError(f"{campo} inválida: use o formato YYYY-MM-DD (ex.: 2026-08-11).")


def _cnpj_formatado(d: str) -> str:
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}' if len(d) == 14 else d


def _secao_nome(codigo):
    from app.services.dou_edicao_service import SECAO_LABELS
    return SECAO_LABELS.get(codigo or '', codigo)


def _links(artigo, app_public_url) -> dict:
    """Onde abrir a matéria: no sistema, na folha assinada e no portal oficial."""
    edicao = artigo.edition
    pagina_pdf = bool(artigo.pagina_num and edicao and edicao.pdf_disponivel)
    return {
        'url': _url(app_public_url, f'/dou/materia/{artigo.id}'),
        # A folha do PDF assinado é o documento oficial para citar.
        'url_pagina_pdf': _url(app_public_url, f'/dou/materia/{artigo.id}/pagina.pdf') if pagina_pdf else None,
        'url_oficial': artigo.pdf_page or None,
    }


# ── Resolução de filtros (texto livre do agente → valores do acervo) ─────────

def _resolver_secoes(valor) -> list[str]:
    """"1", "DO1", "Seção 1", "seção 1 extra", "DO3E" → códigos do acervo."""
    codigos = []
    for item in _lista(valor):
        k = _chave(item).replace('secao', '').replace('do', '').strip()
        extra = 'extra' in k or k.endswith('e')
        numero = re.sub(r'\D', '', k)
        if numero not in ('1', '2', '3'):
            raise ToolError(f"Seção '{item}' não reconhecida. Use 1, 2 ou 3 (ou 'seção 1 extra').")
        codigo = f'DO{numero}' + ('E' if extra else '')
        if codigo not in codigos:
            codigos.append(codigo)
    return codigos


def _resolver(valor: str, disponiveis, campo: str, onde: str) -> str:
    """Um valor digitado → o valor exato do acervo (sem acento/caixa; trecho único)."""
    alvo = _chave(valor)
    exatos = [d for d in disponiveis if _chave(d) == alvo]
    if exatos:
        return exatos[0]
    candidatos = [d for d in disponiveis if alvo and alvo in _chave(d)]
    if len(candidatos) == 1:
        return candidatos[0]
    if candidatos:
        nomes = '; '.join(candidatos[:12])
        raise ToolError(f"Mais de um {campo} casa com '{valor}': {nomes}. Informe o nome exato.")
    raise ToolError(f"{campo.capitalize()} '{valor}' não encontrado {onde}. "
                    "Os valores existentes estão em valores_de_filtro_dou.")


def _facetas_do_acervo() -> dict:
    from app.services import dou_search_service as busca

    facetas = busca.valores_das_facetas()
    if facetas is None:
        raise ToolError('A busca do Diário Oficial está indisponível agora (índice fora do ar). '
                        'Tente de novo em instantes.')
    return facetas


def _tipos_do_acervo() -> list[str]:
    """Todos os tipos de ato (a faceta do índice para nos 100 mais frequentes)."""
    from app.models import DouArticle, db

    return [t for (t,) in db.session.query(DouArticle.art_type)
            .filter(DouArticle.art_type.isnot(None)).distinct().all()]


def _top(distribuicao: dict | None, limite=FACETAS_MAX) -> dict:
    itens = sorted((distribuicao or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    return dict(itens[:limite])


# ── A. Pesquisa no acervo ────────────────────────────────────────────

def search_dou_handler(
    termo: str | None = None,
    secao=None,
    orgao=None,
    tipo=None,
    data_de: str | None = None,
    data_ate: str | None = None,
    ordem: str | None = None,
    limit: int = 20,
    offset: int = 0,
    app_public_url: str | None = None,
) -> dict:
    """Busca no acervo pelo mesmo índice da tela de busca do Diário Oficial."""
    from sqlalchemy.orm import joinedload

    from app.models import DouArticle
    from app.services import dou_search_service as busca

    termo = (termo or '').strip()
    filtros: dict = {}
    if secao:
        filtros['pub_name'] = _resolver_secoes(secao)
    if orgao:
        orgaos = list((_facetas_do_acervo().get('orgao_raiz') or {}).keys())
        filtros['orgao_raiz'] = [_resolver(o, orgaos, 'órgão', 'no acervo') for o in _lista(orgao)]
    if tipo:
        tipos = _tipos_do_acervo()
        filtros['art_type'] = [_resolver(t, tipos, 'tipo de ato', 'no acervo') for t in _lista(tipo)]
    de, ate = _data(data_de, 'data_de'), _data(data_ate, 'data_ate')
    if de:
        filtros['de'] = de
    if ate:
        filtros['ate'] = ate
    if not termo and not filtros:
        raise ToolError('Informe um termo ou ao menos um filtro (seção, órgão, tipo ou período). '
                        'Para ver o que saiu num dia, use sumario_edicao_dou.')

    ordem = 'data' if _chave(ordem).startswith('data') or _chave(ordem).startswith('recente') else 'relevancia'
    limit = clamp_limit(limit, 20)
    offset = clamp_offset(offset)
    if offset >= busca.MAX_TOTAL_HITS:
        raise ToolError(f'A busca alcança só os primeiros {busca.MAX_TOTAL_HITS} resultados. '
                        'Refine com período, seção, órgão ou tipo de ato.')
    limit = min(limit, busca.MAX_TOTAL_HITS - offset)

    r = busca.search(termo, filtros, ordem=ordem, por_pagina=limit,
                     deslocamento=offset, sem_termo=True)
    if r['indisponivel']:
        raise ToolError('A busca do Diário Oficial está indisponível agora (índice fora do ar). '
                        'Tente de novo em instantes.')

    ids = [h['id'] for h in r['hits']]
    artigos = {a.id: a for a in DouArticle.query.options(joinedload(DouArticle.edition))
               .filter(DouArticle.id.in_(ids)).all()} if ids else {}

    itens = []
    for h in r['hits']:
        artigo = artigos.get(h['id'])
        item = {
            'id': h['id'],
            'data': _iso(artigo.pub_date) if artigo else None,
            'secao': _secao_nome(h['pub_name']),
            'orgao': h['orgao_raiz'] or None,
            'orgao_completo': h['orgao_hierarquia'] or None,
            'tipo': h['art_type'] or None,
            # Grifo só no trecho: no título o índice marca até o "de" da data.
            'identificacao': _sem_grifo(h['identifica']),
            'ementa': _sem_grifo(h['ementa']),
            'trecho': _texto_puro(h['trecho']),
            'pagina': h['pagina'] or None,
        }
        if artigo:
            item.update(_links(artigo, app_public_url))
        itens.append(item)

    envelope = page_envelope(r['total_navegavel'], offset, itens)
    facetas = r['facetas'] or {}
    envelope.update({
        'total_de_materias': r['total'],
        'tipo_de_busca': ('sem termo (só filtros)' if not termo else
                          {'cnpj': 'CNPJ exato', 'processo': 'número de processo exato'}
                          .get(r['tipo_consulta'], 'texto')),
        'ordem': ordem,
        'por_secao': {_secao_nome(k): v for k, v in _top(facetas.get('pub_name')).items()},
        'por_orgao': _top(facetas.get('orgao_raiz')),
        'por_tipo': _top(facetas.get('art_type')),
        'filtros_aplicados': {
            'secao': filtros.get('pub_name'), 'orgao': filtros.get('orgao_raiz'),
            'tipo': filtros.get('art_type'), 'data_de': _iso(de), 'data_ate': _iso(ate),
        },
    })
    if termo and r['tipo_consulta'] == 'texto' and '"' not in termo and len(termo.split()) > 1:
        # Sem aspas o índice procura as palavras soltas e com tolerância a erro:
        # "fator acidentário de prevenção" dá 748 matérias; entre aspas, 7.
        envelope['dica'] = ('Sem aspas, as palavras são procuradas separadas e o total infla. '
                            'Para a expressão exata, repita a busca com o termo entre aspas '
                            'duplas, ex.: "fator acidentário de prevenção".')
    if r['total'] > r['total_navegavel']:
        envelope['aviso'] = (f"São {r['total']} matérias; a busca pagina só as "
                             f"{r['total_navegavel']} primeiras. Para o número, use os totais "
                             "por seção/órgão/tipo; para ler, refine os filtros.")
    return envelope


def get_dou_article_handler(article_id: int, law_firm_id: int,
                            app_public_url: str | None = None,
                            max_caracteres: int = TEOR_MAX_CHARS) -> dict:
    """O inteiro teor de uma matéria, e o alerta do escritório nela, se houver."""
    from sqlalchemy.orm import joinedload

    from app.models import DouArticle, DouClientAlert
    from app.services import dou_search_service as busca

    artigo = (DouArticle.query.options(joinedload(DouArticle.edition))
              .filter_by(id=article_id).first())
    if artigo is None:
        raise ToolError(f'Matéria {article_id} não encontrada no acervo do Diário Oficial.')

    texto = artigo.texto or ''
    max_caracteres = max(1000, min(int(max_caracteres or TEOR_MAX_CHARS), 60000))
    cnpjs = busca.extrair_cnpjs(texto)
    processos = busca.extrair_processos(texto)

    alerta = (DouClientAlert.query
              .filter_by(law_firm_id=law_firm_id, article_id=artigo.id).first())

    return {
        'id': artigo.id,
        'data': _iso(artigo.pub_date),
        'secao': _secao_nome(artigo.pub_name),
        'edicao': artigo.edicao or None,
        'pagina': artigo.pagina or None,
        'orgao': busca.orgao_raiz(artigo.orgao_hierarquia),
        'orgao_completo': artigo.orgao_hierarquia,
        'tipo': artigo.art_type,
        'identificacao': artigo.identifica,
        'titulo': artigo.titulo or None,
        'ementa': artigo.ementa or None,
        'texto': texto[:max_caracteres],
        'texto_truncado': len(texto) > max_caracteres,
        'total_caracteres': len(texto),
        'cnpjs_citados': {'total': len(cnpjs),
                          'primeiros': [_cnpj_formatado(c) for c in cnpjs[:IDENTIFICADORES_MAX]]},
        'processos_citados': {'total': len(processos), 'primeiros': processos[:IDENTIFICADORES_MAX]},
        **_links(artigo, app_public_url),
        'alerta_do_escritorio': _resumo_do_alerta(alerta) if alerta else None,
    }


def dou_filter_values_handler() -> dict:
    """Seções, órgãos e tipos de ato que existem no acervo, com contagem."""
    from sqlalchemy import func

    from app.models import DouEdition, db
    from app.services import dou_edicao_service as edicoes

    secoes = dict(db.session.query(DouEdition.secao, func.sum(DouEdition.qtd_materias))
                  .filter(DouEdition.status == DouEdition.STATUS_PARSED)
                  .group_by(DouEdition.secao).all())
    inicio, fim = edicoes.periodo_do_acervo()
    facetas = _facetas_do_acervo()
    return {
        'periodo_do_acervo': {'de': _iso(inicio), 'ate': _iso(fim)},
        'total_de_materias': int(sum(v or 0 for v in secoes.values())),
        'secoes': {_secao_nome(k): int(v or 0) for k, v in sorted(secoes.items())},
        'orgaos': _top(facetas.get('orgao_raiz'), limite=500),
        'tipos_de_ato_mais_frequentes': _top(facetas.get('art_type'), limite=100),
        'observacao': ('Órgão é sempre a raiz da hierarquia (ex.: "Ministério da Previdência '
                       'Social"). Os filtros aceitam o nome sem acento e sem maiúsculas.'),
    }


# ── B. Edições ───────────────────────────────────────────────────────

def latest_editions_handler(quantas: int = 5, app_public_url: str | None = None) -> dict:
    """As últimas edições capturadas e a saúde da captura."""
    from app.models import DouEdition
    from app.services import dou_edicao_service as edicoes
    from app.services import dou_ingestion_service as ingestao

    quantas = max(1, min(int(quantas or 5), 30))
    datas = edicoes.ultimas_datas(quantas)
    por_data: dict = {}
    for e in (DouEdition.query.filter(DouEdition.data_publicacao.in_(datas))
              .order_by(DouEdition.secao).all() if datas else []):
        por_data.setdefault(e.data_publicacao, []).append(e)

    lista = []
    for d in datas:
        eds = por_data.get(d, [])
        publicadas = [e for e in eds if e.status == DouEdition.STATUS_PARSED]
        lista.append({
            'data': _iso(d),
            'total_de_materias': sum(e.qtd_materias or 0 for e in publicadas),
            'secoes': [{
                'secao': _secao_nome(e.secao),
                'edicao_extra': e.secao.endswith('E'),
                'materias': e.qtd_materias or 0,
                'pdf_assinado': e.pdf_disponivel,
            } for e in publicadas],
            'nao_publicadas': [_secao_nome(e.secao) for e in eds
                               if e.status == DouEdition.STATUS_NOT_PUBLISHED],
            'com_falha_na_captura': [_secao_nome(e.secao) for e in eds
                                     if e.status == DouEdition.STATUS_ERROR],
            'url': _url(app_public_url, f'/dou/edicao/{d.isoformat()}'),
        })

    saude = ingestao.health_counters()
    inicio, fim = edicoes.periodo_do_acervo()
    resposta = {
        'ultimas_edicoes': lista,
        'periodo_do_acervo': {'de': _iso(inicio), 'ate': _iso(fim)},
        'captura': {
            'ultima_edicao_capturada': _iso(saude.get('ultima_data')),
            'parada': bool(saude.get('parada')),
            'edicoes_com_falha': saude.get('com_erro') or 0,
        },
    }
    if saude.get('parada'):
        resposta['aviso'] = (f"A captura está parada desde {_iso(saude.get('ultima_data'))}: "
                             "o que saiu depois disso ainda não está no sistema. Não conclua "
                             "que 'nada foi publicado' nesse intervalo.")
    elif saude.get('com_erro'):
        resposta['aviso'] = (f"{saude['com_erro']} edição(ões) falharam na captura e podem estar "
                             "incompletas — veja com_falha_na_captura em cada data.")
    return resposta


def edition_summary_handler(
    data: str | None = None,
    secao=None,
    orgao: str | None = None,
    limit: int = 50,
    offset: int = 0,
    app_public_url: str | None = None,
) -> dict:
    """Sumário da edição de um dia; com órgão, as matérias dele naquele dia."""
    from sqlalchemy import or_

    from app.models import DouArticle, DouEdition, db
    from app.services import dou_edicao_service as edicoes
    from app.services import dou_search_service as busca

    dia = _data(data, 'data')
    if dia is None:
        ultimas = edicoes.ultimas_datas(1)
        if not ultimas:
            raise ToolError('O acervo do Diário Oficial ainda não tem nenhuma edição capturada.')
        dia = ultimas[0]

    eds = (DouEdition.query
           .filter(DouEdition.data_publicacao == dia,
                   DouEdition.status == DouEdition.STATUS_PARSED,
                   DouEdition.qtd_materias > 0)
           .order_by(DouEdition.secao).all())
    if not eds:
        base = (db.session.query(DouEdition.data_publicacao)
                .filter(DouEdition.status == DouEdition.STATUS_PARSED))
        antes = base.filter(DouEdition.data_publicacao < dia).order_by(DouEdition.data_publicacao.desc()).first()
        depois = base.filter(DouEdition.data_publicacao > dia).order_by(DouEdition.data_publicacao.asc()).first()
        vizinhas = ', '.join(_iso(x[0]) for x in (antes, depois) if x) or 'nenhuma'
        raise ToolError(f'Não há edição de {dia.isoformat()} no acervo (fim de semana, feriado '
                        f'ou dia ainda não capturado). Edições mais próximas: {vizinhas}.')
    if secao:
        codigos = _resolver_secoes(secao)
        eds = [e for e in eds if e.secao in codigos]
        if not eds:
            raise ToolError(f"A edição de {dia.isoformat()} não tem {', '.join(map(_secao_nome, codigos))}.")

    if not orgao:
        secoes = []
        for e in eds:
            sumario = edicoes.sumario_com_contagem(e.id)
            for linha in sumario:
                if linha['primeira_pagina'] and e.pdf_disponivel and not e.secao.endswith('E'):
                    linha['url_leitor'] = _url(app_public_url,
                                               f"/dou/edicao/{dia.isoformat()}/pagina/"
                                               f"{linha['primeira_pagina']}?secao={e.secao}")
            secoes.append({
                'secao': _secao_nome(e.secao),
                'materias': e.qtd_materias or 0,
                'pdf_assinado': e.pdf_disponivel,
                'sumario': sumario,
                'tipos_mais_frequentes': dict(edicoes.tipos_da_secao(e.id)),
                'url': _url(app_public_url, f'/dou/edicao/{dia.isoformat()}?secao={e.secao}'),
            })
        return {'data': dia.isoformat(), 'secoes': secoes,
                'dica': 'Para as matérias de um órgão, chame de novo com orgao="<nome>".'}

    orgaos: dict = {}
    for e in eds:
        for nome, qtd in edicoes.orgaos_da_secao(e.id):
            orgaos[nome] = orgaos.get(nome, 0) + qtd
    raiz = _resolver(orgao, list(orgaos), 'órgão', f'na edição de {dia.isoformat()}')

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)
    query = (DouArticle.query
             .filter(DouArticle.edition_id.in_([e.id for e in eds]),
                     or_(DouArticle.orgao_hierarquia == raiz,
                         DouArticle.orgao_hierarquia.startswith(raiz + '/', autoescape=True)))
             .order_by(DouArticle.edition_id, DouArticle.pagina_num.is_(None),
                       DouArticle.pagina_num, DouArticle.id))
    total = query.count()
    itens = []
    for a in fetch_page(query, limit, offset):
        hierarquia = a.orgao_hierarquia or ''
        unidade = hierarquia[len(raiz):].lstrip('/').strip() if hierarquia.startswith(raiz) else hierarquia
        itens.append({
            'id': a.id,
            'secao': _secao_nome(a.pub_name),
            'pagina': a.pagina or None,
            'tipo': a.art_type,
            'identificacao': a.identifica or '(sem identificação)',
            'unidade': unidade or None,
            'ementa': _curto(a.ementa, 300) or None,
            'inicio_do_texto': None if a.ementa else _curto(a.texto, 300) or None,
            'url': _url(app_public_url, f'/dou/materia/{a.id}'),
        })
    envelope = page_envelope(total, offset, itens)
    envelope.update({'data': dia.isoformat(), 'orgao': raiz,
                     'secoes': [_secao_nome(e.secao) for e in eds]})
    return envelope


# ── C. O que é do escritório ─────────────────────────────────────────

def _resumo_do_alerta(alerta) -> dict:
    """O que o alerta diz, em poucas linhas: quem foi citado e o que se decidiu."""
    from app.models import DouClientAlert

    return {
        'alerta_id': alerta.id,
        'lido': alerta.status == DouClientAlert.STATUS_READ,
        'clientes_citados': [{
            'cliente': c.name if c else '—',
            'estabelecimentos': qtd,
            'como': ('CNPJ cadastrado' if tipo == DouClientAlert.MATCH_EXACT
                     else 'outro estabelecimento do grupo (mesma raiz de CNPJ)'),
        } for c, tipo, qtd in alerta.clientes_citados],
        'resultados_fap': [{'decisao': d, 'estabelecimentos': q, 'favoravel': fav}
                           for d, q, fav in alerta.resultados],
        'palavras_chave': [r.nome for r in alerta.regras_citadas],
    }


def firm_digest_handler(law_firm_id: int, edicoes: int = 3,
                        app_public_url: str | None = None) -> dict:
    """O mesmo conteúdo do e-mail diário do DOU, nas últimas N edições."""
    from app.services import dou_alert_service as alertas

    edicoes = max(1, min(int(edicoes or 3), 10))
    d = alertas.build_digest(law_firm_id, since=None, quantas_edicoes=edicoes)

    def _exemplo(e):
        return {'materia_id': e['article_id'], 'identificacao': e['identifica'],
                'secao': _secao_nome(e['pub_name']), 'pagina': e['pagina'],
                'data': _iso(e['pub_date']),
                'url': _url(app_public_url, f"/dou/materia/{e['article_id']}")}

    resposta = {
        'edicoes_consideradas': [_iso(x) for x in d['datas']],
        'alertas': d['total'],
        'nao_lidos_no_total': alertas.contar_nao_lidos(law_firm_id),
        'recursos_fap': {
            'clientes_com_recurso_julgado': d['clientes_com_fap'],
            'clientes_com_algum_deferimento': d['clientes_com_deferimento'],
            'estabelecimentos_com_deferimento': d['deferimentos'],
            'estabelecimentos_com_indeferimento': d['indeferimentos'],
            'como_ler': ('Cada linha de edital do CRPS é o recurso de um estabelecimento. '
                         'Deferimento é ganho de causa (o FAP da empresa cai); indeferimento '
                         'abre prazo para recorrer.'),
        },
        'empresas': [{
            'empresa': e['nome'],
            'materias': e['materias'],
            'estabelecimentos_citados': e['cnpjs'],
            'decisoes_fap': [{'decisao': dec, 'estabelecimentos': q, 'favoravel': fav}
                             for dec, q, fav in e['decisoes']],
            'exemplos': [_exemplo(x) for x in e['exemplos']],
            'outras_materias': e['restantes'],
        } for e in d['empresas']],
        'palavras_chave': [{
            'regra': r['nome'], 'materias': r['materias'],
            'exemplos': [_exemplo(x) for x in r['exemplos']],
        } for r in d['regras']],
        'url': _url(app_public_url, '/dou/alertas'),
    }
    if not d['datas']:
        resposta['aviso'] = 'O acervo ainda não tem edição capturada.'
    elif not d['total']:
        resposta['aviso'] = ('Nenhum cliente foi citado e nenhuma regra de "O que vigiar" casou '
                             'nessas edições.')
    return resposta


def _resolver_clientes(law_firm_id: int, cliente: str) -> list[int]:
    """Nome ou CNPJ (completo ou raiz) → ids de cliente com alerta."""
    from app.services import dou_alert_service as alertas

    opcoes = alertas.clientes_com_alerta(law_firm_id)
    digitos = re.sub(r'\D', '', cliente or '')
    if len(digitos) >= 8:
        ids = [cid for cid, _, cnpj, _ in opcoes
               if re.sub(r'\D', '', cnpj or '').startswith(digitos[:14])]
    else:
        alvo = _chave(cliente)
        ids = [cid for cid, nome, _, _ in opcoes if alvo and alvo in _chave(nome)]
    if not ids:
        nomes = sorted({nome for _, nome, _, _ in opcoes})
        raise ToolError(f"Nenhum alerta do DOU para o cliente '{cliente}'. Clientes com alerta: "
                        f"{'; '.join(nomes[:20]) or 'nenhum'}.")
    return ids


def _resolver_fap(law_firm_id: int, valor: str) -> str:
    from app.services import dou_alert_service as alertas

    k = _chave(valor)
    if k in ('com', 'sim', 'qualquer', 'com decisao', 'houve decisao', 'julgado', 'julgados'):
        return alertas.FAP_QUALQUER
    if k.startswith(('deferi', 'favor', 'ganh')):
        return alertas.FAP_FAVORAVEL
    if k.startswith(('indefer', 'contra', 'desfavor', 'perd', 'prazo')):
        return alertas.FAP_CONTRA
    decisoes = [d for d, _ in alertas.resultados_disponiveis(law_firm_id)]
    try:
        return _resolver(valor, decisoes, 'resultado FAP', 'nos alertas do escritório')
    except ToolError:
        raise ToolError(f"Resultado FAP '{valor}' não reconhecido. Use 'com' (houve decisão), "
                        "'deferimento' (ganho de causa), 'indeferimento' (prazo para recorrer) "
                        f"ou uma decisão exata: {'; '.join(decisoes) or 'nenhuma nos alertas'}.")


def list_alerts_handler(
    law_firm_id: int,
    status: str | None = None,
    cliente: str | None = None,
    resultado_fap: str | None = None,
    origem: str | None = None,
    secao=None,
    regra: str | None = None,
    data_de: str | None = None,
    data_ate: str | None = None,
    limit: int = 30,
    offset: int = 0,
    app_public_url: str | None = None,
) -> dict:
    """Alertas do escritório com os filtros da tela /dou/alertas."""
    from app.models import DouAlertRule, DouClientAlert
    from app.services import dou_alert_service as alertas
    from app.services import dou_search_service as busca

    k = _chave(status)
    if not k or k.startswith('tod'):
        status_db = None
    elif 'nao' in k or k.startswith('nov') or 'pendente' in k:
        status_db = DouClientAlert.STATUS_NEW
    elif k.startswith('lid'):
        status_db = DouClientAlert.STATUS_READ
    else:
        raise ToolError("status inválido: use 'nao_lidos', 'lidos' ou 'todos'.")

    origem_db = None
    if origem:
        ko = _chave(origem)
        if ko.startswith(('cliente', 'cnpj', 'carteira')):
            origem_db = alertas.ORIGEM_CLIENTE
        elif ko.startswith(('regra', 'palavra', 'termo', 'vigi')):
            origem_db = alertas.ORIGEM_REGRA
        else:
            raise ToolError("origem inválida: use 'cliente' (CNPJ da carteira) ou 'regra' (palavra-chave).")

    secoes = _resolver_secoes(secao) if secao else []
    if len(secoes) > 1:
        raise ToolError('Filtre uma seção por vez (ex.: 3 ou "seção 1 extra").')

    rule_id = None
    if regra:
        regras = {r.nome: r.id for r in DouAlertRule.query.filter_by(law_firm_id=law_firm_id)}
        rule_id = regras[_resolver(regra, list(regras), 'regra', 'em "O que vigiar"')]

    query = alertas.consulta_alertas(
        law_firm_id, status=status_db, secao=secoes[0] if secoes else None,
        client_ids=_resolver_clientes(law_firm_id, cliente) if cliente else None,
        fap=_resolver_fap(law_firm_id, resultado_fap) if resultado_fap else None,
        origem=origem_db, rule_id=rule_id,
        de=_data(data_de, 'data_de'), ate=_data(data_ate, 'data_ate'))

    limit = clamp_limit(limit, 30)
    offset = clamp_offset(offset)
    total = query.order_by(None).count()
    itens = []
    for a in fetch_page(query, limit, offset):
        artigo = a.article
        item = {
            'data': _iso(a.pub_date),
            'secao': _secao_nome(a.pub_name),
            'pagina': artigo.pagina if artigo else None,
            'identificacao': (artigo.identifica if artigo else None) or '(sem identificação)',
            'orgao': busca.orgao_raiz(artigo.orgao_hierarquia) if artigo else None,
            'materia_id': a.article_id,
            **_resumo_do_alerta(a),
        }
        if artigo:
            item.update(_links(artigo, app_public_url))
        itens.append(item)

    envelope = page_envelope(total, offset, itens)
    envelope['resumo_do_escritorio'] = alertas.resumo(law_firm_id)
    envelope['url'] = _url(app_public_url, '/dou/alertas')
    return envelope


def _linhas_do_trecho(trecho: dict) -> list[str]:
    """O recorte do "ver trecho" em linhas de texto: uma por linha de tabela."""
    from bs4 import BeautifulSoup

    if trecho.get('modo') == 'html' and trecho.get('html'):
        sopa = BeautifulSoup(trecho['html'], 'html.parser')
        linhas = []
        for no in sopa.find_all(['tr', 'p', 'li']):
            if no.name != 'tr' and no.find_parent('tr'):
                continue
            if no.name == 'tr':
                celulas = [c.get_text(' ', strip=True) for c in no.find_all(['td', 'th'])]
                texto = ' | '.join(c for c in celulas if c)
            else:
                texto = no.get_text(' ', strip=True)
            if texto:
                linhas.append(texto)
        return linhas
    if trecho.get('modo') == 'trechos':
        return [_texto_puro(i['html']) for i in trecho.get('itens', []) if i.get('html')]
    if trecho.get('modo') == 'inteiro':
        return [_curto(_texto_puro(trecho.get('inteiro')), 4000)]
    return []


_PARECE_DADO = re.compile(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{5}\.\d{6}/\d{4}|\d{10,}')

COLUNAS_EDITAL_CRPS = ('Nos editais de julgamento do CRPS cada linha é o recurso de um '
                       'estabelecimento: nº de ordem | processo | ano da vigência FAP | CNPJ | '
                       'instância | resultado.')


def _cabecalho_da_tabela(artigo) -> str | None:
    """A 1ª linha da 1ª tabela do edital — os nomes das colunas das linhas do trecho."""
    from bs4 import BeautifulSoup

    from app.services.dou_xml_parser import sanitizar_html

    if not (artigo and artigo.texto_html and '<table' in artigo.texto_html.lower()):
        return None
    tabela = BeautifulSoup(sanitizar_html(artigo.texto_html), 'html.parser').find('table')
    linha = tabela.find('tr') if tabela else None
    if not linha:
        return None
    celulas = [c.get_text(' ', strip=True) for c in linha.find_all(['td', 'th'])]
    # Os editais do CRPS não têm cabeçalho: a 1ª linha já é um recurso. Linha
    # com CNPJ ou número longo é dado, não nome de coluna.
    if not linha.find('th') and any(_PARECE_DADO.search(c) for c in celulas):
        return None
    return ' | '.join(c for c in celulas if c) or None


def alert_detail_handler(law_firm_id: int, alerta_id: int,
                         app_public_url: str | None = None, max_linhas: int = 200) -> dict:
    """Um alerta por inteiro: cada estabelecimento citado e as linhas do edital."""
    from app.models import DouClientAlert
    from app.services import dou_alert_service as alertas
    from app.services import dou_search_service as busca

    alerta = DouClientAlert.query.filter_by(id=alerta_id, law_firm_id=law_firm_id).first()
    if alerta is None:
        raise ToolError(f'Alerta {alerta_id} não encontrado entre os alertas do escritório.')

    max_linhas = max(10, min(int(max_linhas or 200), 400))
    artigo = alerta.article
    trecho = alertas.trechos_do_alerta(alerta, maximo=max_linhas)
    estabelecimentos = [{
        'cnpj': m.cnpj_formatado,
        'cliente': m.client.name if m.client else None,
        'como': 'CNPJ cadastrado' if m.match_type == DouClientAlert.MATCH_EXACT
                else 'outro estabelecimento do grupo',
        'resultado_fap': m.resultado,
        'favoravel': m.resultado_favoravel if m.resultado else None,
    } for m in alerta.matches_ordenados]

    resposta = {
        'data': _iso(alerta.pub_date),
        'secao': _secao_nome(alerta.pub_name),
        'identificacao': (artigo.identifica if artigo else None) or '(sem identificação)',
        'orgao': busca.orgao_raiz(artigo.orgao_hierarquia) if artigo else None,
        'materia_id': alerta.article_id,
        **_resumo_do_alerta(alerta),
        'estabelecimentos': estabelecimentos[:max_linhas],
        'total_de_estabelecimentos': len(estabelecimentos),
        'regras': [{'nome': r.nome, 'termo': r.termo} for r in alerta.regras_citadas],
        'cabecalho_da_tabela': _cabecalho_da_tabela(artigo),
        'como_ler_as_linhas': COLUNAS_EDITAL_CRPS if alerta.tem_resultado else None,
        'linhas_do_edital': _linhas_do_trecho(trecho),
        'linhas_nao_mostradas': trecho.get('restantes', 0),
    }
    if artigo:
        resposta.update(_links(artigo, app_public_url))
    return resposta


# ── D. Vigilância ("O que vigiar") ─────────────────────────────────

def rules_handler(law_firm_id: int, app_public_url: str | None = None) -> dict:
    """As regras de palavra-chave do escritório e quanto cada uma rendeu."""
    from sqlalchemy import func

    from app.models import DouAlertRule, DouAlertRuleHit, db
    from app.services import dou_rule_service as regras_svc

    regras = (DouAlertRule.query.filter_by(law_firm_id=law_firm_id)
              .order_by(DouAlertRule.ativo.desc(), DouAlertRule.nome, DouAlertRule.id).all())
    contagem = dict(db.session.query(DouAlertRuleHit.rule_id, func.count())
                    .filter(DouAlertRuleHit.law_firm_id == law_firm_id)
                    .group_by(DouAlertRuleHit.rule_id).all())
    return {
        'total': len(regras),
        'ativas': sum(1 for r in regras if r.ativo),
        'regras': [{
            'nome': r.nome,
            'termo': r.termo,
            'modo': regras_svc.MODO_LABELS.get(r.modo, r.modo) if r.termo else None,
            'secoes': [_secao_nome(s) for s in r.lista_secoes] or 'todas',
            'orgao': r.orgao_raiz or 'todos',
            'ativa': r.ativo,
            'criada_por': r.created_by.name if r.created_by else None,
            'alertas_gerados': contagem.get(r.id, 0),
            'ultimo_casamento': _iso(r.last_match_at),
        } for r in regras],
        'url': _url(app_public_url, '/dou/regras'),
    }


_EXPLICACAO_NIVEL = {
    'vazio': 'Não teria gerado nenhum alerta nas últimas edições.',
    'ok': 'Volume administrável.',
    'alto': 'Volume alto: mais do que toda a carteira de clientes gera hoje.',
    'ruidoso': 'Ruidoso: o volume vai esconder o que importa. Restrinja por órgão ou seção, ou use frase exata.',
    'sem_acervo': 'Não há edição capturada para testar.',
}


def test_term_handler(termo: str | None = None, modo: str | None = None, secao=None,
                      orgao: str | None = None, app_public_url: str | None = None) -> dict:
    """O teste da tela antes de salvar uma regra — só consulta, não cria nada."""
    from app.services import dou_rule_service as regras_svc

    km = _chave(modo)
    modo_db = (regras_svc.MODO_PALAVRAS if km.startswith(('palavra', 'toda', 'qualquer'))
               else regras_svc.MODO_FRASE)
    secoes = _resolver_secoes(secao) if secao else []
    raiz = None
    if orgao:
        orgaos = list((_facetas_do_acervo().get('orgao_raiz') or {}).keys())
        raiz = _resolver(orgao, orgaos, 'órgão', 'no acervo')
    erros = regras_svc.validar('teste', termo, modo_db, secoes, raiz)
    if erros:
        raise ToolError(' '.join(erros))

    r = regras_svc.testar((termo or '').strip(), modo_db, secoes, raiz)
    return {
        'termo': termo, 'modo': regras_svc.MODO_LABELS[modo_db],
        'secoes': [_secao_nome(s) for s in secoes] or 'todas', 'orgao': raiz or 'todos',
        'edicoes_testadas': r['dias'],
        'alertas_no_periodo': r['total'],
        'alertas_por_edicao': r['por_dia'],
        'avaliacao': r['nivel'],
        'explicacao': _EXPLICACAO_NIVEL.get(r['nivel']),
        'vezes_o_volume_da_carteira': r['vezes_carteira'] or None,
        'exemplos': [{
            'materia_id': e['id'], 'data': e['pub_date'], 'secao': _secao_nome(e['pub_name']),
            'pagina': e['pagina'], 'orgao': e['orgao'], 'identificacao': e['identifica'],
            'trecho': _texto_puro(e['trecho']),
            'url': _url(app_public_url, f"/dou/materia/{e['id']}"),
        } for e in r['exemplos']],
        'como_criar': ('Para vigiar esse termo, crie a regra na tela "O que vigiar": '
                       f"{_url(app_public_url, '/dou/regras/nova') or '/dou/regras/nova'}"),
    }
