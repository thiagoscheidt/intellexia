"""Registro das rotas da API do IntellexIA (``/api/v1``) — fonte única das rotas,
do OpenAPI, da página de documentação e da ferramenta ``documentacao_api`` do MCP.

Cada ``Rota`` chama o **handler da ferramenta MCP** equivalente, com os mesmos
nomes de parâmetro da ferramenta: os números da API, do Claude e das telas não
podem divergir. Rota nova = uma linha aqui; o blueprint ``public_api`` monta a
view, e a documentação sai sozinha.

**A consulta é compartilhada, a apresentação não.** Filtros, escritório,
ordenação e total são do handler — é ali que duas implementações divergiriam.
O que é do canal fica na API:

- **teto da página** por rota (``TETO_PAGINA``; o MCP para em 200 porque enche
  o contexto do agente, uma tela só faz menos requisições). Pedir acima é 400,
  nunca corte calado;
- **textos escritos para a IA** saem da resposta (``para_api``): a ``dica`` e o
  ``proximo_passo`` mandam chamar ferramentas do MCP, que quem programa não tem;
- **campos de resposta declarados** (``public_api_campos``), conferidos contra a
  resposta real no teste — é a documentação do que volta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from app.services import public_api_campos as C

# Página máxima das listas da API. Com 120 requisições por minuto por token,
# dá para uma tela carregar a base inteira sem virar extração em massa.
TETO_PAGINA = 1000

TIPOS = ('string', 'integer', 'boolean', 'lista', 'objetos')  # objetos: lista JSON no corpo
_VERDADEIRO = {'true', '1', 'sim', 's', 'yes'}
_FALSO = {'false', '0', 'nao', 'não', 'n', 'no'}


@dataclass(frozen=True)
class Param:
    nome: str
    tipo: str
    descricao: str
    obrigatorio: bool = False
    local: str = 'query'           # query | path | body
    padrao: Any = None
    minimo: int | None = None      # só inteiro
    maximo: int | None = None      # só inteiro


@dataclass(frozen=True)
class Rota:
    metodo: str
    caminho: str                   # formato OpenAPI: /fap/beneficios/{id}
    modulo: str | None             # None = a rota confere por conta própria (ex.: numero-processo)
    resumo: str
    params: tuple[Param, ...]
    chamar: Callable[[Any, dict], dict] = field(compare=False)
    detalhe: bool = False          # resposta {"erro": "... não encontrado ..."} vira 404
    grupo: str = ''
    resposta: tuple = ()           # campos devolvidos (public_api_campos)

    @property
    def teto(self) -> int:
        """Teto da página desta rota (o máximo do ``limite``)."""
        return next((p.maximo for p in self.params if p.nome == 'limite' and p.maximo), TETO_PAGINA)

    @property
    def nome_uso(self) -> str:
        return f'{self.metodo} {self.caminho}'


def _erro(mensagem: str):
    from app.blueprints.public_api import ErroApi

    return ErroApi(mensagem, 400)


def _converter(p: Param, valores: list) -> Any:
    if p.tipo == 'objetos':
        # Só no corpo: a lista inteira, cada item um objeto ou um valor simples.
        if len(valores) != 1 or not isinstance(valores[0], list):
            raise _erro(f'O parâmetro "{p.nome}" precisa ser uma lista JSON.')
        itens = valores[0]
        if any(not isinstance(i, (dict, str, int)) or isinstance(i, bool) for i in itens):
            raise _erro(f'Cada item de "{p.nome}" precisa ser um objeto ou um texto.')
        return itens or None
    if p.tipo == 'lista':
        itens = [v.strip() for bruto in valores for v in str(bruto).split(',')]
        return [v for v in itens if v] or None
    if len(valores) > 1:
        raise _erro(f'O parâmetro "{p.nome}" foi enviado mais de uma vez; envie um valor só.')
    bruto = valores[0]
    if p.tipo == 'integer':
        if isinstance(bruto, bool):
            raise _erro(f'O parâmetro "{p.nome}" precisa ser um número inteiro.')
        try:
            numero = int(str(bruto).strip())
        except ValueError:
            raise _erro(f'O parâmetro "{p.nome}" precisa ser um número inteiro (recebido: "{bruto}").')
        if p.minimo is not None and numero < p.minimo:
            raise _erro(f'O parâmetro "{p.nome}" precisa ser pelo menos {p.minimo} (recebido: {numero}).')
        if p.maximo is not None and numero > p.maximo:
            mais = ' Para mais registros, pagine com "deslocamento".' if p.nome == 'limite' else ''
            raise _erro(f'O parâmetro "{p.nome}" aceita no máximo {p.maximo} (recebido: {numero}).{mais}')
        return numero
    if p.tipo == 'boolean':
        if isinstance(bruto, bool):
            return bruto
        texto = str(bruto).strip().lower()
        if texto in _VERDADEIRO:
            return True
        if texto in _FALSO:
            return False
        raise _erro(f'O parâmetro "{p.nome}" aceita true ou false (recebido: "{bruto}").')
    texto = str(bruto).strip()
    return texto or None


def ler_parametros(rota: Rota, args: Mapping, corpo: dict | None, caminho: dict) -> dict:
    """Parâmetros da requisição, convertidos e com os padrões. Nome desconhecido,
    tipo inválido ou obrigatório faltando → ``ErroApi`` 400."""
    por_local = {loc: {p.nome: p for p in rota.params if p.local == loc} for loc in ('query', 'body', 'path')}

    desconhecidos = [n for n in args.keys() if n not in por_local['query']]
    if corpo is not None:
        desconhecidos += [n for n in corpo.keys() if n not in por_local['body']]
    if desconhecidos:
        validos = ', '.join(sorted(por_local['query']) + sorted(por_local['body'])) or 'nenhum'
        raise _erro(f'Parâmetro(s) desconhecido(s): {", ".join(desconhecidos)}. '
                    f'Esta rota aceita: {validos}.')

    resultado = {}
    for p in rota.params:
        if p.local == 'path':
            valores = [caminho[p.nome]] if p.nome in caminho else []
        elif p.local == 'body':
            valores = [] if corpo is None or corpo.get(p.nome) is None else [corpo[p.nome]]
            if p.tipo == 'lista' and valores and isinstance(valores[0], list):
                valores = valores[0]
        else:
            valores = args.getlist(p.nome) if hasattr(args, 'getlist') else (
                [args[p.nome]] if p.nome in args else [])
        valor = _converter(p, valores) if valores else None
        if valor is None:
            if p.obrigatorio:
                raise _erro(f'O parâmetro "{p.nome}" é obrigatório.')
            valor = p.padrao
        resultado[p.nome] = valor
    return resultado


# ── parâmetros repetidos entre rotas ─────────────────────────────────────────

def _limite(padrao: int, maximo: int = TETO_PAGINA) -> Param:
    return Param('limite', 'integer', f'Registros por página (padrão {padrao}, máximo {maximo}).',
                 padrao=padrao, minimo=1, maximo=maximo)


DESLOCAMENTO = Param('deslocamento', 'integer',
                     'Pula os N primeiros resultados (paginação): repasse o "proximo_deslocamento" '
                     'da resposta anterior.', padrao=0, minimo=0)
ID = Param('id', 'integer', 'Identificador do registro.', obrigatorio=True, local='path')
CNPJ = Param('cnpj', 'string', 'CNPJ (com ou sem pontuação; aceita a raiz de 8 dígitos).')
EMPRESA = Param('empresa', 'string', 'Nome ou parte do nome da empresa.')
GRUPO = Param('grupo', 'string', 'Grupo empresarial cadastrado (nomes em /fap/filtros).')
STATUS_1A = Param('status_1a_instancia', 'string',
                  'Resultado na 1ª instância: deferido, indeferido, em_analise ou pendente.')
STATUS_2A = Param('status_2a_instancia', 'string', 'Resultado na 2ª instância (recurso), mesmos valores.')
CALC_VIGENCIA = Param('vigencia', 'integer', 'Ano de vigência.')
CALC_TIPO = Param('tipo', 'lista', 'B91, B92, B93, B94 ou CAT — um ou vários (B91,B94).')
CALC_SITUACAO = Param('situacao', 'string', 'conta (no cálculo) ou excluido (tirado no recálculo).')
CALC_CONTESTADO = Param('contestado', 'boolean', 'true = existe na Central na mesma vigência.')
CALC_SEGURADO = (
    Param('cpf', 'string', 'CPF do segurado.'),
    Param('nit', 'string', 'NIT do segurado.'),
    Param('numero', 'string', 'Número do benefício ou da CAT.'),
)
CALC_CNPJ_DIVERGENTE = Param('cnpj_divergente', 'boolean', 'true = atribuído a CNPJ diferente do original.')
CALC_EXTRA = (
    Param('nome', 'string', 'Nome do segurado (só nomes já revelados).'),
    CALC_CNPJ_DIVERGENTE,
    Param('ausente_no_calculo_atual', 'boolean', 'true = saiu num recálculo mais novo.'),
    Param('inicio_de', 'string', 'Início do benefício a partir de (AAAA-MM-DD).'),
    Param('inicio_ate', 'string', 'Início do benefício até (AAAA-MM-DD).'),
    Param('cessacao_de', 'string', 'Cessação a partir de (AAAA-MM-DD).'),
    Param('cessacao_ate', 'string', 'Cessação até (AAAA-MM-DD).'),
    Param('com_obito', 'boolean', 'true = só com data de óbito; false = só sem.'),
)
CALC_ORDEM = Param('ordem', 'string', 'padrao, total_pago, valor_mensal, meses_contabilizacao, '
                   'data_inicio ou data_cessacao (do maior para o menor).')


# ── adaptadores: API → handler do MCP ────────────────────────────────────────

def _fap():
    from mcp_server.tools import fap
    return fap


def _beneficios(ctx, p):
    return _fap().list_fap_benefits_handler(
        ctx.law_firm_id, p['cnpj'], p['status'], p['tipo_pedido'], p['tipo_beneficio'],
        p['topico_contestacao'], p['segurado'], p['nit'], p['cpf'], p['numero_beneficio'],
        p['ano_vigencia'], p['empresa'], p['limite'], p['deslocamento'], protocolo=p['protocolo'],
        grupo=p['grupo'], status_1a_instancia=p['status_1a_instancia'],
        status_2a_instancia=p['status_2a_instancia'])


# Chaves que só fazem sentido para o agente do MCP: mandam chamar ferramentas
# ("repita com deslocamento=…", "detalhar_decisao(…)"). A paginação da API está
# em tem_mais/proximo_deslocamento e o próximo passo na documentação da rota.
_SO_PARA_IA = frozenset({'dica', 'proximo_passo'})


def para_api(valor):
    """Resposta do handler sem os textos escritos para a IA."""
    if isinstance(valor, dict):
        return {k: para_api(v) for k, v in valor.items() if k not in _SO_PARA_IA}
    if isinstance(valor, list):
        return [para_api(v) for v in valor]
    return valor


def _contestacao(ctx, p):
    r = _fap().get_contestacao_detail_handler(p['id'], ctx.law_firm_id, app_public_url=ctx.app_public_url)
    vinculados = r.get('beneficios_vinculados') if isinstance(r, dict) else None
    if vinculados and vinculados.get('ver_todos'):
        # No MCP é a chamada da ferramenta; aqui, a rota da API.
        from urllib.parse import quote
        vinculados['ver_todos'] = f'/api/v1/fap/beneficios?protocolo={quote(r["protocolo"])}'
    return r


_FILTROS_CALCULO_EXTRA = ('nome', 'cnpj_divergente', 'ausente_no_calculo_atual', 'inicio_de',
                          'inicio_ate', 'cessacao_de', 'cessacao_ate', 'com_obito')


def _calculo_lista(ctx, p):
    from mcp_server.tools.fap_calculo import listar_beneficios_calculo_fap_handler
    return listar_beneficios_calculo_fap_handler(
        ctx.law_firm_id, p['vigencia'], p['empresa'], p['grupo'], p['cnpj'], p['cpf'], p['nit'],
        p['numero'], p['tipo'], p['situacao'], p['contestado'], p['limite'], p['deslocamento'],
        ordem=p['ordem'], **{k: p[k] for k in _FILTROS_CALCULO_EXTRA})


def _calculo_resumo(ctx, p):
    from mcp_server.tools.fap_calculo import resumo_beneficios_calculo_fap_handler
    return resumo_beneficios_calculo_fap_handler(
        ctx.law_firm_id, p['vigencia'], p['empresa'], p['grupo'], p['cnpj'], p['tipo'],
        situacao=p['situacao'], contestado=p['contestado'], cpf=p['cpf'], nit=p['nit'],
        numero=p['numero'], **{k: p[k] for k in _FILTROS_CALCULO_EXTRA})


def _calculo_ranking(ctx, p):
    from mcp_server.tools.fap_calculo import ranking_calculo_fap_handler
    return ranking_calculo_fap_handler(
        ctx.law_firm_id, p['agrupar_por'], p['ordenar_por'], p['vigencia'], p['empresa'], p['grupo'],
        p['cnpj'], p['tipo'], p['situacao'], p['contestado'], p['cnpj_divergente'], p['limite'],
        p['deslocamento'])


def _calculo_cruzamento(ctx, p):
    from mcp_server.tools.fap_calculo import cruzamento_vigencias_calculo_fap_handler
    return cruzamento_vigencias_calculo_fap_handler(
        ctx.law_firm_id, p['vigencia'], p['empresa'], p['grupo'], p['cnpj'], p['tipo'], p['criterio'],
        p['ordem'], p['limite'], p['deslocamento'])


def _calculo_estabelecimento(ctx, p):
    from mcp_server.tools.fap_calculo import detalhar_estabelecimento_calculo_fap_handler
    return detalhar_estabelecimento_calculo_fap_handler(ctx.law_firm_id, p['cnpj'], p['vigencia'])


def _segurados(ctx, p):
    from mcp_server.tools.insights import buscar_por_segurado_handler
    return buscar_por_segurado_handler(ctx.law_firm_id, ctx.modulos, p['nit'], p['cpf'], p['nome'])


def _revelar(ctx, p):
    from app.services.segurado_nome_service import ORIGEM_API
    r = _fap().revelar_nome_segurado_handler(ctx.law_firm_id, ctx.user_id, p['cpf'], origem=ORIGEM_API)
    if r.get('aviso'):
        r['aviso'] = r['aviso'].replace(' Diga isso ao usuário junto com o nome.', '')
    return r


def _conferir_beneficios(ctx, p):
    return _fap().conferir_dados_beneficios_handler(ctx.law_firm_id, p['beneficios'])


def _consultar_cpf(ctx, p):
    return _fap().consultar_cpf_handler(ctx.law_firm_id, ctx.user_id, p['cpf'])


def _kb():
    from mcp_server.tools import knowledge
    return knowledge


def _juris():
    from mcp_server.tools import jurisprudence
    return jurisprudence


_FILTROS_JURIS = (
    Param('termo', 'string', 'Texto livre; número de processo com ou sem pontuação.'),
    Param('teses_catalogo', 'lista', 'Teses do catálogo (nome, sem acento serve).'),
    Param('teses_originais', 'lista', 'Teses como vieram na decisão.'),
    Param('tribunais', 'lista', 'Siglas: TRF4, TRF3...'),
    Param('instancias', 'lista', 'sentença, acórdão, embargos...'),
    Param('uf', 'string', 'UF do processo.'),
    Param('vigencia', 'integer', 'Vigência do FAP discutida.'),
    Param('julgada_de', 'string', 'Julgada a partir de (AAAA-MM-DD).'),
    Param('julgada_ate', 'string', 'Julgada até (AAAA-MM-DD).'),
)


def _juris_pesquisa(ctx, p):
    return _juris().search_jurisprudence_handler(
        ctx.law_firm_id, ctx.app_public_url, modo=p['modo'], limite=p['limite'],
        deslocamento=p['deslocamento'], termo=p['termo'], teses_catalogo=p['teses_catalogo'],
        teses_originais=p['teses_originais'], resultados=p['resultados'], tribunais=p['tribunais'],
        instancias=p['instancias'], uf=p['uf'], vigencia=p['vigencia'], julgada_de=p['julgada_de'],
        julgada_ate=p['julgada_ate'], ordem=p['ordem'])


def _juris_panorama(ctx, p):
    r = _juris().jurisprudence_overview_handler(
        ctx.law_firm_id, ctx.app_public_url, termo=p['termo'], teses_catalogo=p['teses_catalogo'],
        teses_originais=p['teses_originais'], tribunais=p['tribunais'], instancias=p['instancias'],
        uf=p['uf'], vigencia=p['vigencia'], julgada_de=p['julgada_de'], julgada_ate=p['julgada_ate'])
    if not isinstance(r.get('recorte'), dict):
        r['recorte'] = {}  # o MCP escreve "toda a base"; na API o tipo não muda conforme o filtro
    return r


def _numero_processo(ctx, p):
    from mcp_server.tools.numero_processo import search_by_process_number_handler
    return search_by_process_number_handler(
        ctx.law_firm_id, ctx.modulos, p['numero'], bases=p['bases'], limite=p['limite'],
        deslocamento=p['deslocamento'], app_public_url=ctx.app_public_url)


def _processos():
    from mcp_server.tools import process_panel
    return process_panel


# Fora da API de propósito: POST /base-conhecimento/perguntar (o
# consultar_base_conhecimento do MCP). A busca do agente no Qdrant/Meilisearch
# não filtra escritório — pendência conhecida da base — e a API a tornaria
# scriptável. A pesquisa (/base-conhecimento/pesquisa) filtra pelos arquivos do
# escritório e fica. Volta quando o agente filtrar por tenant.

ROTAS: tuple[Rota, ...] = (
    # ── FAP ──────────────────────────────────────────────────────────────────
    Rota('GET', '/fap/empresas', 'fap_panel', 'Empresas do Painel FAP (procurações).', (
        Param('nome', 'string', 'Nome ou parte do nome; partes em qualquer ordem.'),
        CNPJ,
        Param('tipo_procuracao', 'string', 'Tipo de procuração (busca parcial).'),
        _limite(100), DESLOCAMENTO,
    ), lambda ctx, p: _fap().list_fap_companies_handler(
        ctx.law_firm_id, p['nome'], p['cnpj'], p['tipo_procuracao'], p['limite'], p['deslocamento']),
        resposta=C.EMPRESAS, grupo='fap'),
    Rota('GET', '/fap/contestacoes', 'fap_panel', 'Contestações FAP sincronizadas do portal.', (
        CNPJ,
        Param('cnpj_raiz', 'string', 'Raiz do CNPJ (8 dígitos): todos os estabelecimentos.'),
        Param('ano_vigencia', 'integer', 'Ano de vigência FAP (ex.: 2023).'),
        Param('situacao_codigo', 'string', 'Código de situação (ex.: DEFERIDO, INDEFERIDO).'),
        Param('instancia_codigo', 'string', 'Código de instância (ex.: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).'),
        Param('protocolo', 'string', 'Protocolo administrativo, com ou sem pontuação, completo ou trecho.'),
        _limite(100), DESLOCAMENTO,
    ), lambda ctx, p: _fap().list_fap_contestacoes_handler(
        ctx.law_firm_id, p['cnpj'], p['cnpj_raiz'], p['ano_vigencia'], p['situacao_codigo'],
        p['instancia_codigo'], p['limite'], p['deslocamento'], app_public_url=ctx.app_public_url,
        protocolo=p['protocolo']), resposta=C.CONTESTACOES, grupo='fap'),
    Rota('GET', '/fap/contestacoes/{id}', 'fap_panel', 'Detalhe de uma contestação FAP.', (ID,),
         _contestacao, detalhe=True, resposta=C.CONTESTACAO_DETALHE, grupo='fap'),
    Rota('GET', '/fap/beneficios', 'fap_panel',
         'Benefícios contestados (Central), com status por instância.', (
             CNPJ,
             Param('status', 'string', 'Status geral do benefício (pending, approved, rejected...).'),
             Param('tipo_pedido', 'string', 'exclusao, inclusao ou revisao.'),
             Param('tipo_beneficio', 'string', 'Espécie: B91, B92, B93, B94.'),
             Param('topico_contestacao', 'string', 'Tópico jurídico (ex.: ACIDENTE DE TRAJETO).'),
             Param('segurado', 'string', 'Nome do segurado (só acha nomes já revelados).'),
             Param('nit', 'string', 'NIT do segurado (exato).'),
             Param('cpf', 'string', 'CPF do segurado, com ou sem pontuação.'),
             Param('numero_beneficio', 'string', 'Número do benefício (exato).'),
             Param('ano_vigencia', 'string', 'Ano de vigência FAP (ex.: 2023).'),
             EMPRESA, GRUPO,
             Param('protocolo', 'string', 'Protocolo da contestação: traz os benefícios dela.'),
             STATUS_1A, STATUS_2A, _limite(50), DESLOCAMENTO,
         ), _beneficios, resposta=C.BENEFICIOS, grupo='fap'),
    Rota('GET', '/fap/beneficios/{id}', 'fap_panel', 'Detalhe de um benefício contestado.', (ID,),
         lambda ctx, p: _fap().get_benefit_detail_handler(p['id'], ctx.law_firm_id),
         detalhe=True, resposta=C.BENEFICIO_DETALHE, grupo='fap'),
    Rota('POST', '/fap/beneficios/conferir', 'fap_panel',
         'Confere o que uma petição (ou planilha) diz de cada benefício contra a Central e o cálculo FAP: '
         'divergências campo a campo e alertas (já excluído do cálculo, fora do cálculo, não contestado...). '
         'Sem IA; nada fica salvo.', (
             Param('beneficios', 'objetos',
                   'Lista de números ou de objetos com "numero" e, se tiver: cpf, nit, especie, dib, dcb, '
                   'nascimento, cnpj, vigencia, nome, cat (qualquer pontuação e formato de data). Até 500.',
                   obrigatorio=True, local='body'),
         ), _conferir_beneficios, resposta=C.CONFERIR_BENEFICIOS, grupo='fap'),
    Rota('GET', '/fap/resumo', 'fap_panel',
         'Contagens: contestações e benefícios por ano, situação, instância, tipo e empresa.', (
             Param('ano_vigencia', 'integer', 'Ano de vigência FAP.'),
             CNPJ, EMPRESA, GRUPO,
             Param('tipo_beneficio', 'string', 'Restringe os benefícios a uma espécie.'),
             STATUS_1A, STATUS_2A,
         ), lambda ctx, p: _fap().fap_summary_handler(
             ctx.law_firm_id, p['ano_vigencia'], p['cnpj'], p['empresa'], grupo=p['grupo'],
             tipo_beneficio=p['tipo_beneficio'], status_1a_instancia=p['status_1a_instancia'],
             status_2a_instancia=p['status_2a_instancia']), resposta=C.RESUMO, grupo='fap'),
    Rota('GET', '/fap/filtros', 'fap_panel',
         'Valores aceitos nos filtros: situações, instâncias, anos, tipos, tópicos, grupos.', (),
         lambda ctx, p: _fap().fap_filter_values_handler(ctx.law_firm_id), resposta=C.FILTROS, grupo='fap'),
    Rota('GET', '/fap/procuracoes', 'fap_panel', 'Procurações do portal FAP.', (
        Param('cnpj_raiz', 'string', 'Raiz do CNPJ da empresa outorgante (8 dígitos).'),
        Param('situacao_codigo', 'string', 'Código de situação da procuração.'),
        _limite(100), DESLOCAMENTO,
    ), lambda ctx, p: _fap().list_fap_procuracoes_handler(
        ctx.law_firm_id, p['cnpj_raiz'], p['situacao_codigo'], p['limite'], p['deslocamento']),
        resposta=C.PROCURACOES, grupo='fap'),
    Rota('GET', '/fap/calculo/beneficios', 'fap_panel',
         'Benefícios e CATs do cálculo FAP (Consulta do portal), contestados ou não.', (
             CALC_VIGENCIA, EMPRESA, GRUPO, CNPJ, *CALC_SEGURADO, CALC_TIPO, CALC_SITUACAO,
             CALC_CONTESTADO, *CALC_EXTRA, CALC_ORDEM, _limite(50), DESLOCAMENTO,
         ), _calculo_lista, resposta=C.CALCULO_BENEFICIOS, grupo='fap'),
    Rota('GET', '/fap/calculo/resumo', 'fap_panel',
         'Contagens do cálculo FAP: tipo × situação × contestado, com as somas de total pago.', (
             CALC_VIGENCIA, EMPRESA, GRUPO, CNPJ, *CALC_SEGURADO, CALC_TIPO, CALC_SITUACAO,
             CALC_CONTESTADO, *CALC_EXTRA,
         ), _calculo_resumo, resposta=C.CALCULO_RESUMO, grupo='fap'),
    Rota('GET', '/fap/calculo/ranking', 'fap_panel',
         'Contagens do cálculo FAP por empresa, estabelecimento, vigência ou grupo, do maior para o menor.', (
             Param('agrupar_por', 'string', 'empresa (padrão), estabelecimento, vigencia ou grupo.'),
             Param('ordenar_por', 'string',
                   'total, conta, excluidos, contestados, nao_contestados, conta_nao_contestados, '
                   'total_pago, total_pago_nao_contestado, total_pago_excluido ou '
                   'total_pago_conta_nao_contestado (padrão).'),
             CALC_VIGENCIA, EMPRESA, GRUPO, CNPJ, CALC_TIPO, CALC_SITUACAO, CALC_CONTESTADO,
             CALC_CNPJ_DIVERGENTE, _limite(20), DESLOCAMENTO,
         ), _calculo_ranking, resposta=C.CALCULO_RANKING, grupo='fap'),
    Rota('GET', '/fap/calculo/cruzamento-vigencias', 'fap_panel',
         'Itens que contam sem contestação numa vigência e foram excluídos (ou contestados) em outra.', (
             Param('vigencia', 'integer', 'Vigência onde o item ainda conta sem contestação.'),
             EMPRESA, GRUPO, CNPJ, CALC_TIPO,
             Param('criterio', 'string', 'excluido (padrão), contestado ou qualquer — o que aconteceu '
                   'na outra vigência.'),
             CALC_ORDEM, _limite(50), DESLOCAMENTO,
         ), _calculo_cruzamento, resposta=C.CALCULO_CRUZAMENTO, grupo='fap'),
    Rota('GET', '/fap/calculo/estabelecimento', 'fap_panel',
         'Um estabelecimento no cálculo FAP: cálculo atual e original, protocolo, histórico, '
         'contadores e os itens excluídos e ausentes.', (
             Param('cnpj', 'string', 'CNPJ do estabelecimento (14 dígitos, com ou sem pontuação).',
                   obrigatorio=True),
             Param('vigencia', 'integer', 'Ano de vigência (padrão: a mais recente).'),
         ), _calculo_estabelecimento, detalhe=True, resposta=C.CALCULO_ESTABELECIMENTO, grupo='fap'),
    # ── Segurados ────────────────────────────────────────────────────────────
    Rota('GET', '/segurados', 'fap_panel',
         'Visão de um segurado: benefícios, CATs, processos e o cálculo FAP. Informe cpf, nit ou nome.', (
             Param('cpf', 'string', 'CPF, com ou sem pontuação.'),
             Param('nit', 'string', 'NIT.'),
             Param('nome', 'string', 'Nome ou parte (só nomes já revelados ou cadastrados).'),
         ), _segurados, resposta=C.SEGURADOS, grupo='segurados'),
    Rota('POST', '/segurados/revelar-nome', 'fap_panel',
         'Revela o nome de UM segurado pelo CPF (consulta paga, cota diária por usuário somada ao Claude).', (
             Param('cpf', 'string', 'CPF de um segurado da base do escritório.', obrigatorio=True, local='body'),
         ), _revelar, resposta=C.REVELAR_NOME, grupo='segurados'),
    Rota('POST', '/segurados/consultar-cpf', 'fap_panel',
         'Consulta completa de UM CPF (qualquer CPF válido): tudo o que o serviço devolve — nome, nascimento, '
         'sexo, nome da mãe. Paga, nada fica salvo, mesma cota diária do revelar nome.', (
             Param('cpf', 'string', 'CPF com ou sem pontuação.', obrigatorio=True, local='body'),
         ), _consultar_cpf, resposta=C.CONSULTA_CPF, grupo='segurados'),
    # ── Base de conhecimento ─────────────────────────────────────────────────
    Rota('GET', '/base-conhecimento/pesquisa', 'knowledge_base',
         'Pesquisa na Base de Conhecimento: trechos com o arquivo de origem.', (
             Param('pergunta', 'string', 'O que procurar.', obrigatorio=True),
             Param('modo_busca', 'string', 'semantico ou textual; sem ele, a IA escolhe.'),
             _limite(20, maximo=50),
         ), lambda ctx, p: _kb().kb_search_handler(
             p['pergunta'], ctx.law_firm_id, p['modo_busca'], p['limite'], app_public_url=ctx.app_public_url),
        resposta=C.KB_PESQUISA, grupo='base-conhecimento'),
    Rota('GET', '/base-conhecimento/arquivos/{id}', 'knowledge_base',
         'Texto de um arquivo da Base de Conhecimento, em partes.', (
             ID,
             Param('deslocamento', 'integer', 'Posição do texto a partir da qual ler (paginação).', padrao=0),
         ), lambda ctx, p: _kb().read_kb_file_handler(
             p['id'], ctx.law_firm_id, p['deslocamento'], app_public_url=ctx.app_public_url),
        detalhe=True, resposta=C.KB_ARQUIVO, grupo='base-conhecimento'),
    # ── Jurisprudência ───────────────────────────────────────────────────────
    Rota('GET', '/jurisprudencia', 'process_panel',
         'Pesquisa na Base de Jurisprudência (sem termo, lista tudo paginado).', (
             _FILTROS_JURIS[0],
             Param('modo', 'string', 'campos (ficha) ou inteiro_teor.', padrao='campos'),
             *_FILTROS_JURIS[1:3],
             Param('resultados', 'lista', 'favorável, desfavorável, parcial...'),
             *_FILTROS_JURIS[3:],
             Param('ordem', 'string', 'recentes (padrão) ou outra ordem aceita pela tela.', padrao='recentes'),
             _limite(20), DESLOCAMENTO,
         ), _juris_pesquisa, resposta=C.JURIS_PESQUISA, grupo='jurisprudencia'),
    Rota('GET', '/jurisprudencia/panorama', 'process_panel',
         'Resultado por tribunal e instância, viradas no acórdão e favoráveis recentes.', _FILTROS_JURIS,
         _juris_panorama, resposta=C.JURIS_PANORAMA, grupo='jurisprudencia'),
    Rota('GET', '/jurisprudencia/filtros', 'process_panel', 'Valores aceitos nos filtros da jurisprudência.', (),
         lambda ctx, p: _juris().jurisprudence_filter_values_handler(ctx.law_firm_id), resposta=C.JURIS_FILTROS, grupo='jurisprudencia'),
    Rota('GET', '/jurisprudencia/{id}', 'process_panel', 'Detalhe de uma decisão.', (ID,),
         lambda ctx, p: _juris().decision_detail_handler(p['id'], ctx.law_firm_id, ctx.app_public_url),
         detalhe=True, resposta=C.JURIS_DETALHE, grupo='jurisprudencia'),
    Rota('GET', '/jurisprudencia/{id}/parecidas', 'process_panel', 'Decisões parecidas com uma decisão.', (
        ID, _limite(6, maximo=20),
    ), lambda ctx, p: _juris().similar_decisions_handler(p['id'], ctx.law_firm_id, ctx.app_public_url, p['limite']),
        detalhe=True, resposta=C.JURIS_PARECIDAS, grupo='jurisprudencia'),
    # ── Processos ────────────────────────────────────────────────────────────
    Rota('GET', '/processos', 'process_panel', 'Processos judiciais do Painel de Processos.', (
        Param('status', 'string', 'Status do processo.'),
        Param('numero_processo', 'string', 'Número completo ou parte (mínimo 7 dígitos).'),
        _limite(50), DESLOCAMENTO,
    ), lambda ctx, p: _processos().list_processes_handler(
        ctx.law_firm_id, p['status'], p['numero_processo'], p['limite'], p['deslocamento']),
        resposta=C.PROCESSOS, grupo='processos'),
    Rota('GET', '/processos/{id}', 'process_panel', 'Detalhe de um processo judicial.', (ID,),
         lambda ctx, p: _processos().get_process_detail_handler(p['id'], ctx.law_firm_id),
         detalhe=True, resposta=C.PROCESSO_DETALHE, grupo='processos'),
    Rota('GET', '/numero-processo/{numero}', None,
         'Procura um número de processo em todas as bases que o usuário pode ver.', (
             Param('numero', 'string', 'Número do processo, com ou sem pontuação (mínimo 7 dígitos).',
                   obrigatorio=True, local='path'),
             Param('bases', 'lista', 'base_conhecimento, jurisprudencia, pecas_modelo, processos.'),
             _limite(20), DESLOCAMENTO,
         ), _numero_processo, resposta=C.NUMERO_PROCESSO, grupo='processos'),
)


# ── documentação ─────────────────────────────────────────────────────────────

GRUPOS = {
    'conta': 'Conta',
    'fap': 'Painel FAP',
    'segurados': 'Segurados',
    'base-conhecimento': 'Base de Conhecimento',
    'jurisprudencia': 'Jurisprudência',
    'processos': 'Processos',
}

# /eu e /openapi.json são escritas à mão no blueprint; entram na documentação daqui.
_ROTAS_PROPRIAS = (
    ('GET', '/eu', 'Quem sou eu: usuário, escritório, módulos, validade do token e cota de nomes.'),
)


def _schema(p: Param) -> dict:
    if p.tipo == 'objetos':
        return {'type': 'array', 'items': {'oneOf': [{'type': 'object'}, {'type': 'string'}]}}
    if p.tipo == 'lista':
        return {'type': 'array', 'items': {'type': 'string'}}
    schema = {'type': p.tipo}
    if p.padrao is not None:
        schema['default'] = p.padrao
    if p.minimo is not None:
        schema['minimum'] = p.minimo
    if p.maximo is not None:
        schema['maximum'] = p.maximo
    return schema


def _resposta_200(campos: tuple) -> dict:
    return {'description': 'OK', 'content': {'application/json': {'schema': C.schema(campos)}}}


def _operacao(rota: Rota) -> dict:
    op = {
        'summary': rota.resumo,
        'operationId': (rota.metodo.lower() + rota.caminho.replace('/', '_').replace('-', '_')
                        .replace('{', '').replace('}', '')),
        'tags': [GRUPOS.get(rota.grupo, rota.grupo)],
        'x-modulo': rota.modulo,
        'parameters': [
            {'name': p.nome, 'in': p.local, 'required': p.obrigatorio or p.local == 'path',
             'description': p.descricao, 'schema': _schema(p)}
            for p in rota.params if p.local in ('query', 'path')
        ],
        'responses': {
            '200': _resposta_200(rota.resposta),
            '400': {'description': 'Parâmetro inválido ({"erro": "..."})'},
            '401': {'description': 'Token ausente, inválido, vencido ou revogado'},
            '403': {'description': 'Sem o módulo exigido'},
            '404': {'description': 'Não encontrado neste escritório'},
            '429': {'description': 'Limite atingido (veja Retry-After)'},
        },
    }
    corpo = [p for p in rota.params if p.local == 'body']
    if corpo:
        op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {
            'type': 'object',
            'properties': {p.nome: {**_schema(p), 'description': p.descricao} for p in corpo},
            'required': [p.nome for p in corpo if p.obrigatorio],
        }}}}
    return op


def openapi(base_url: str) -> dict:
    """OpenAPI 3.1 da API, gerado do registro. ``base_url`` = endereço do app, sem barra final."""
    paths: dict = {}
    for metodo, caminho, resumo in _ROTAS_PROPRIAS:
        paths.setdefault(caminho, {})[metodo.lower()] = {
            'summary': resumo, 'operationId': 'eu', 'tags': [GRUPOS['conta']],
            'responses': {'200': _resposta_200(C.EU), '401': {'description': 'Token inválido'}},
        }
    for rota in ROTAS:
        paths.setdefault(rota.caminho, {})[rota.metodo.lower()] = _operacao(rota)
    return {
        'openapi': '3.1.0',
        'info': {
            'title': 'API do IntellexIA',
            'version': '1',
            'description': ('Dados do escritório para telas e automações próprias. Mesmas regras e '
                            'mesmos números das ferramentas do conector MCP. Respostas e parâmetros '
                            f'em português; paginação por limite/deslocamento (até {TETO_PAGINA} '
                            'por página). Campo sem valor vem null.'),
        },
        'servers': [{'url': base_url.rstrip('/') + '/api/v1'}],
        'security': [{'bearer': []}],
        'components': {'securitySchemes': {'bearer': {'type': 'http', 'scheme': 'bearer'}}},
        'paths': paths,
    }


_ENVELOPE = ('total_encontrado', 'retornados', 'deslocamento', 'tem_mais', 'proximo_deslocamento')


def _campos_resumidos(campos: tuple) -> str:
    """``a, b, itens[id, nome]`` — os nomes dos campos, um nível de aninhamento por
    colchete; o envelope de paginação vira "lista paginada"."""
    nomes = {c.nome for c in campos}
    partes = []
    if 'itens' in nomes and set(_ENVELOPE) <= nomes:
        partes.append('lista paginada (total_encontrado, tem_mais, proximo_deslocamento)')
        campos = tuple(c for c in campos if c.nome not in _ENVELOPE)
    for c in campos:
        if c.campos and c.tipo in ('objeto', 'lista', 'mapa'):
            partes.append(f'{c.nome}[{_campos_resumidos(c.campos)}]')
        else:
            partes.append(c.nome)
    return ', '.join(partes)


def resumo_markdown(grupo: str | None = None) -> str:
    """Uma linha por rota, com parâmetros e campos devolvidos — para a IA montar a
    integração sem ler o OpenAPI inteiro."""
    linhas = ([f'GET /eu — {_ROTAS_PROPRIAS[0][2]} Devolve: {_campos_resumidos(C.EU)}.']
              if grupo in (None, 'conta') else [])
    for rota in ROTAS:
        if grupo and rota.grupo != grupo:
            continue
        params = ', '.join(
            f'{p.nome}{"*" if p.obrigatorio else ""}' + (' (corpo JSON)' if p.local == 'body' else '')
            for p in rota.params if p.local != 'path')
        linha = f'{rota.metodo} {rota.caminho} — {rota.resumo}' + (f' Parâmetros: {params}.' if params else '')
        if rota.resposta:
            linha += f' Devolve: {_campos_resumidos(rota.resposta)}.'
        linhas.append(linha)
    return '\n'.join(linhas)


def exemplo_curl(rota: Rota, base: str) -> str:
    caminho = rota.caminho.replace('{id}', '123').replace('{numero}', '5001234-56.2024.4.04.7000')
    url = base.rstrip('/') + '/api/v1' + caminho
    if rota.metodo == 'POST':
        corpo = ', '.join(f'"{p.nome}": ' + ('[{"numero": "..."}]' if p.tipo == 'objetos' else '"..."')
                          for p in rota.params if p.local == 'body')
        return (f'curl -X POST -H "Authorization: Bearer $INTELLEXIA_TOKEN" '
                f'-H "Content-Type: application/json" -d \'{{{corpo}}}\' "{url}"')
    return f'curl -H "Authorization: Bearer $INTELLEXIA_TOKEN" "{url}"'
