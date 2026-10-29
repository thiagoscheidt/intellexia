"""Campos de resposta da API do IntellexIA (``/api/v1``), rota a rota.

A documentação (página, OpenAPI e a ferramenta ``documentacao_api`` do MCP) sai
daqui, e ``conferir`` compara a resposta real com o que está declarado: campo
que o handler passou a devolver sem estar aqui, campo declarado que sumiu ou
tipo trocado viram falha em ``tests/test_api_campos.py``. É isso que impede a
documentação de envelhecer em silêncio — quem mexe no handler do MCP descobre
no teste que a API também mudou.

Valor ``null`` é sempre aceito: quase todo campo vem vazio em algum registro
(o portal não informa, a IA não leu), e declarar isso campo a campo só
esconderia o que importa.
"""
from __future__ import annotations

from dataclasses import dataclass

TIPOS = ('texto', 'inteiro', 'numero', 'booleano', 'data', 'objeto', 'lista', 'mapa')


@dataclass(frozen=True)
class Campo:
    nome: str
    tipo: str
    descricao: str
    # objeto: os campos dele; lista: os campos de cada item (vazio = lista de
    # valores ``de``); mapa: os campos de cada valor (vazio = valores ``de``).
    campos: tuple['Campo', ...] = ()
    de: str = 'texto'
    opcional: bool = False        # só vem em alguns casos (explicado na descrição)
    extras: str = ''              # chaves que variam além dos campos fixos (no objeto ou em cada item)


def _t(nome, descricao, **kw):
    return Campo(nome, 'texto', descricao, **kw)


def _i(nome, descricao, **kw):
    return Campo(nome, 'inteiro', descricao, **kw)


def _n(nome, descricao, **kw):
    return Campo(nome, 'numero', descricao, **kw)


def _b(nome, descricao, **kw):
    return Campo(nome, 'booleano', descricao, **kw)


def _d(nome, descricao, **kw):
    return Campo(nome, 'data', descricao, **kw)


def _o(nome, descricao, *campos, **kw):
    return Campo(nome, 'objeto', descricao, campos=tuple(campos), **kw)


def _l(nome, descricao, *campos, de='texto', **kw):
    return Campo(nome, 'lista', descricao, campos=tuple(campos), de=de, **kw)


def _m(nome, descricao, *campos, de='inteiro', **kw):
    return Campo(nome, 'mapa', descricao, campos=tuple(campos), de=de, **kw)


def envelope(*itens: Campo, extra: tuple[Campo, ...] = ()) -> tuple[Campo, ...]:
    """Resposta de lista paginada: o envelope de paginação + os itens."""
    return (
        _i('total_encontrado', 'Total de registros que atendem aos filtros, somando todas as páginas.'),
        _i('retornados', 'Quantos registros vieram nesta página.'),
        _i('deslocamento', 'Posição do primeiro registro desta página.'),
        _b('tem_mais', 'Há registros depois desta página.'),
        _i('proximo_deslocamento', 'Valor de "deslocamento" para pedir a próxima página. Só vem quando '
           'tem_mais é true.', opcional=True),
        _l('itens', 'Registros desta página.', *itens),
        *extra,
    )


# ── blocos repetidos ─────────────────────────────────────────────────────────

_ID = _i('id', 'Identificador do registro no IntellexIA (use nas rotas de detalhe).')
_CPF_RECEITA = _t('consulta_cpf_receita', 'Link da consulta gratuita de CPF da Receita, já preenchido '
                  '(falta o captcha). Vazio sem CPF ou nascimento.')
_TOPICOS = _l('topicos_contestacao', 'Tópicos jurídicos da contestação (ex.: ACIDENTE DE TRAJETO).')
_STATUS_1A = _t('status_primeira_instancia', 'Resultado na 1ª instância administrativa, como veio do '
                'relatório (ex.: Deferido, Indeferido, analyzing).')
_STATUS_2A = _t('status_segunda_instancia', 'Resultado na 2ª instância (recurso), mesmos valores.')
_TOTAL_PAGO = _n('total_pago', 'Total pago no benefício, em reais.')
_SEGURADO = (
    _t('segurado_nome', 'Nome do segurado: o cadastrado ou o já revelado pela consulta de CPF. O FAP não '
       'informa nome.'),
    _t('segurado_nit', 'NIT do segurado.'),
    _t('segurado_cpf', 'CPF do segurado, como veio do relatório.'),
    _d('segurado_data_nascimento', 'Data de nascimento (AAAA-MM-DD).'),
    _CPF_RECEITA,
)

BENEFICIO_ITEM = (
    _ID,
    _t('numero_beneficio', 'Número do benefício (NB).'),
    _t('tipo_beneficio', 'Espécie: B91, B92, B93 ou B94.'),
    _t('tipo_pedido', 'exclusao, inclusao ou revisao.'),
    _t('status', 'Status geral do benefício na Central (pending, approved, rejected...).'),
    *_SEGURADO,
    _t('empregador_cnpj', 'CNPJ do estabelecimento empregador.'),
    _t('empregador_nome', 'Nome do empregador.'),
    _d('data_inicio_beneficio', 'Início do benefício.'),
    _d('data_fim_beneficio', 'Fim do benefício.'),
    _d('data_acidente', 'Data do acidente.'),
    _t('empresa_acidente', 'Empresa onde ocorreu o acidente.'),
    _t('numero_cat', 'Número da CAT ligada ao benefício.'),
    _t('vigencias_fap', 'Vigências FAP em que o benefício entrou (texto, ex.: "2023").'),
    _TOPICOS,
    _STATUS_1A,
    _STATUS_2A,
    _n('mensalidade_inicial', 'Renda mensal inicial (RMI), em reais.'),
    _TOTAL_PAGO,
)

CONTESTACAO_CAMPOS = (
    _ID,
    _i('contestacao_id', 'Identificador da contestação no portal FAP.'),
    _t('empresa_nome', 'Nome da empresa.'),
    _t('cnpj', 'CNPJ do estabelecimento contestado (só dígitos).'),
    _t('cnpj_raiz', 'Raiz do CNPJ (8 dígitos).'),
    _i('ano_vigencia', 'Ano de vigência do FAP.'),
    _t('instancia_codigo', 'Código da instância (ex.: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).'),
    _t('instancia_descricao', 'Instância por extenso.'),
    _t('situacao_codigo', 'Código da situação no portal.'),
    _t('situacao_descricao', 'Situação por extenso.'),
    _t('protocolo', 'Protocolo administrativo.'),
    _d('data_transmissao', 'Quando foi transmitida ao portal.'),
    _d('data_dou', 'Data do resultado no Diário Oficial.'),
    _b('pdf_baixado', 'O relatório de julgamento em PDF já foi baixado.'),
    _t('url_abrir_pdf', 'Endereço do PDF no IntellexIA (abre com o login do app).'),
    _d('ultima_sincronizacao', 'Última sincronização com o portal.'),
)

DECISAO_ITEM = (
    _ID,
    _t('processo', 'Número do processo.'),
    _t('parte_autora', 'Empresa autora.'),
    _t('instancia', 'Sentença, Acórdão, Embargos...'),
    _t('tribunal', 'Sigla do tribunal (TRF4, TRF3...).'),
    _t('orgao_julgador', 'Vara ou turma.'),
    _t('uf', 'UF do processo.'),
    _d('data_julgamento', 'Data do julgamento.'),
    _t('resultado', 'Favorável, Desfavorável, Parcialmente favorável...'),
    _t('vigencia_fap', 'Vigências do FAP discutidas.'),
    _l('teses_originais', 'Teses como vieram escritas na decisão.'),
    _l('teses_catalogo', 'Teses padronizadas do catálogo ligadas à decisão.'),
    _t('motivo_resultado', 'Por que a decisão saiu assim (resumido).'),
    _t('trecho', 'Trecho onde o termo pesquisado aparece; vazio sem termo.'),
    _t('citacao', 'Citação pronta para a peça.'),
    _t('url', 'Endereço da decisão no IntellexIA.'),
)

_COMO_TEM_DECIDIDO = _m(
    'como_tem_decidido', 'Por resultado (chave = rótulo, ex.: "Favorável"): quantas decisões e o percentual.',
    _i('decisoes', 'Decisões com esse resultado.'),
    _n('percentual', 'Percentual do recorte.'))

CALCULO_ITEM = (
    _ID,
    _i('law_firm_id', 'Escritório dono do registro (sempre o seu).'),
    _i('ano_vigencia', 'Vigência do cálculo.'),
    _t('cnpj', 'CNPJ do estabelecimento (só dígitos).'),
    _t('cnpj_raiz', 'Raiz do CNPJ.'),
    _t('empresa_nome', 'Nome da empresa.'),
    _t('tipo', 'B91, B92, B93, B94 ou CAT.'),
    _t('identificador', 'Número do benefício ou da CAT.'),
    _t('nit', 'NIT do segurado.'),
    _t('cpf', 'CPF do segurado (11 dígitos).'),
    _d('data_nascimento', 'Nascimento do segurado.'),
    _CPF_RECEITA,
    _o('nome_revelado', 'Registro da consulta de nome por CPF, se alguém já revelou.',
       _t('cpf', 'CPF consultado.'),
       _t('status', 'encontrado ou nao_encontrado.'),
       _t('nome', 'Nome devolvido pela consulta.'),
       _b('nascimento_diverge', 'O nascimento da consulta não bate com o do FAP (pode ser outra pessoa).'),
       _d('consultado_em', 'Quando foi consultado.')),
    _t('segurado_nome', 'Nome revelado (atalho para nome_revelado.nome).'),
    _b('cpf_revelavel', 'O CPF é válido e pode ter o nome revelado.'),
    _n('valor_mensal', 'Valor mensal do benefício, em reais.'),
    _n('total_pago', 'Total pago, em reais.'),
    _d('data_despacho', 'Data do despacho do benefício.'),
    _d('data_inicio', 'Início do benefício.'),
    _d('data_cessacao', 'Cessação do benefício.'),
    _d('data_inicio_contabilizacao', 'Início do período contado no cálculo.'),
    _d('data_fim_contabilizacao', 'Fim do período contado no cálculo.'),
    _n('meses_contabilizacao', 'Meses contados no cálculo.'),
    _b('bloqueio', 'Bloqueio informado pelo portal.'),
    _t('estado_atual', 'Situação no cálculo atual (ex.: EXCLUIDO = tirado no recálculo).'),
    _t('estado_original', 'Situação no cálculo original.'),
    _i('calculo_id', 'Cálculo do portal de onde veio o item.'),
    _t('cnpj_original', 'CNPJ original informado pelo portal.'),
    _t('cnpj_atribuido', 'CNPJ a que o item foi atribuído.'),
    _d('data_acidente', 'Data do acidente (CAT).'),
    _d('data_cadastro_cat', 'Cadastro da CAT.'),
    _d('data_obito', 'Data do óbito, se houver.'),
    _t('recibo_esocial', 'Recibo do eSocial (CAT).'),
    _d('first_seen_at', 'Primeira vez que o item foi visto no portal (UTC).'),
    _d('last_seen_at', 'Última vez que o item foi visto no portal (UTC).'),
    _b('contestado', 'Existe na Central com o mesmo número e a mesma vigência.'),
    _i('beneficio_central_id', 'id do benefício na Central (rota /fap/beneficios/{id}), se contestado.'),
    _i('cat_central_id', 'id da CAT na Central, se contestada.'),
    _t('calculo_tipo', 'Tipo do cálculo atual do estabelecimento (original, recálculo...).'),
    _t('calculo_data', 'Data do cálculo atual (DD/MM/AAAA).'),
    _t('protocolo', 'Protocolo da contestação do estabelecimento.'),
    _l('historico', 'Cálculos do estabelecimento nessa vigência.',
       _i('id', 'Cálculo no portal.'), _t('tipo', 'Código do tipo.'), _t('rotulo', 'Tipo por extenso.'),
       _t('data', 'Data (DD/MM/AAAA).')),
    _b('ausente_no_calculo_atual', 'O item saiu de um cálculo mais novo do estabelecimento.'),
)


# ── respostas por rota ───────────────────────────────────────────────────────

EMPRESAS = envelope(
    _ID,
    _t('cnpj', 'Raiz do CNPJ da empresa (8 dígitos).'),
    _t('nome', 'Nome da empresa.'),
    _t('tipo_procuracao_descricao', 'Tipo de procuração.'),
    _d('sincronizada_em', 'Última sincronização com o portal.'),
)

CONTESTACOES = envelope(
    *CONTESTACAO_CAMPOS,
    _t('resultado_deferimento', 'Resultado do deferimento informado pelo portal.'),
)

CONTESTACAO_DETALHE = (
    *CONTESTACAO_CAMPOS,
    _o('beneficios_vinculados', 'Benefícios da mesma vigência e CNPJ (até 50 aqui).',
       _i('total', 'Total de benefícios vinculados.'),
       _t('ver_todos', 'Rota da API com a lista inteira desses benefícios.'),
       _m('por_status_primeira_instancia', 'Contagem por status da 1ª instância, entre os listados.'),
       _l('itens', 'Até 50 benefícios.',
          _ID, _t('numero_beneficio', 'NB.'), _t('tipo_beneficio', 'Espécie.'),
          _t('segurado_nome', 'Nome cadastrado.'), _TOPICOS, _STATUS_1A, _STATUS_2A, _TOTAL_PAGO)),
    _l('alteracoes_recentes', 'Últimas 10 mudanças vistas na sincronização.',
       _t('tipo_mudanca', 'Tipo da mudança.'),
       Campo('campos_alterados', 'objeto', 'Campos que mudaram (antes/depois), como vieram do portal.',
             extras='chave = campo alterado'),
       _d('sincronizado_em', 'Quando a mudança foi vista.')),
)

BENEFICIOS = envelope(
    *BENEFICIO_ITEM,
    extra=(_t('aviso', 'Só com o filtro "segurado": a busca por nome só acha nomes já revelados.',
              opcional=True),),
)

BENEFICIO_DETALHE = (
    *[c for c in BENEFICIO_ITEM],
    _t('resumo_acidente', 'Resumo do acidente.'),
    _t('numero_bo', 'Número do boletim de ocorrência.'),
    _t('status_primeira_instancia_bruto', 'Status da 1ª instância como veio do portal, antes da normalização.'),
    _t('justificativa_primeira_instancia', 'Justificativa da empresa na 1ª instância.'),
    _t('parecer_primeira_instancia', 'Parecer do julgador na 1ª instância.'),
    _t('status_segunda_instancia_bruto', 'Status da 2ª instância como veio do portal.'),
    _t('justificativa_segunda_instancia', 'Justificativa da empresa no recurso.'),
    _t('parecer_segunda_instancia', 'Parecer do julgador no recurso.'),
    _t('justificativa', 'Justificativa geral (campo legado).'),
    _t('parecer', 'Parecer geral (campo legado).'),
    _t('notas', 'Notas internas.'),
    _l('decisoes_julgamento', 'Decisões extraídas dos relatórios de julgamento.',
       _t('instancia', 'Instância.'), _i('sequencia', 'Ordem dentro da instância.'),
       _t('status', 'Resultado.'), _t('justificativa', 'Justificativa da empresa.'),
       _t('parecer', 'Parecer do julgador.')),
    _d('criado_em', 'Quando entrou no IntellexIA.'),
    _d('atualizado_em', 'Última alteração.'),
)

_MAPA_CONTAGEM = 'Contagem por valor (chave = valor, "(vazio)" quando não informado).'
_CRUZADO = 'Por espécie (chave = B91...), contagem por status normalizado (deferido, indeferido, em_analise...).'

RESUMO = (
    _o('filtros', 'Filtros aplicados.', _t('ano_vigencia', 'Ano pedido.'), _t('cnpj', 'CNPJ pedido.'),
       extras='também grupo, tipo_beneficio e status por instância, quando pedidos'),
    _o('contestacoes', 'Contestações do recorte.',
       _i('total', 'Total de contestações.'),
       _m('por_ano_vigencia', _MAPA_CONTAGEM), _m('por_situacao', _MAPA_CONTAGEM),
       _m('por_instancia', _MAPA_CONTAGEM), _m('por_empresa', _MAPA_CONTAGEM)),
    _o('beneficios', 'Benefícios do recorte.',
       _i('total', 'Total de benefícios.'),
       _m('por_tipo', _MAPA_CONTAGEM), _m('por_tipo_pedido', _MAPA_CONTAGEM),
       _m('por_status_primeira_instancia', _MAPA_CONTAGEM), _m('por_status_segunda_instancia', _MAPA_CONTAGEM),
       Campo('por_tipo_x_status_primeira_instancia', 'mapa', _CRUZADO, de='mapa'),
       Campo('por_tipo_x_status_segunda_instancia', 'mapa', _CRUZADO, de='mapa'),
       _m('por_topico_contestacao', 'Contagem por tópico jurídico, do maior para o menor.'),
       _i('com_topico_contestacao', 'Benefícios com algum tópico.'),
       _o('financeiro', 'Valores.', _n('total_pago_soma', 'Soma do total pago, em reais.'),
          _i('beneficios_com_valor_informado', 'Benefícios com total pago informado.')),
       _i('com_cat', 'Benefícios com CAT.'), _i('sem_cat', 'Benefícios sem CAT.'),
       _o('por_estabelecimento', 'Ranking de estabelecimentos por número de benefícios.',
          _i('total_estabelecimentos', 'Estabelecimentos no recorte.'),
          _l('ranking', 'Os 20 com mais benefícios.', _t('cnpj', 'CNPJ formatado.'), _t('nome', 'Empresa.'),
             _t('tipo', 'Matriz ou Filial.'), _i('beneficios', 'Benefícios.')))),
    _t('aviso_filtros', 'Quando há filtro de benefício: os números de contestações não mudam com ele.',
       opcional=True),
    _l('empresas_na_conta', 'Com filtro de empresa ou grupo: as empresas (raízes) que entraram na conta.',
       _t('cnpj_raiz', 'Raiz do CNPJ.'), _t('nome', 'Empresa.'), _i('beneficios', 'Benefícios.'),
       opcional=True),
    _t('aviso_empresas', 'O nome de empresa pedido casou mais de uma raiz de CNPJ.', opcional=True),
)

FILTROS = (
    _o('contestacoes', 'Valores dos filtros de contestação.',
       _l('anos_vigencia', 'Anos com contestação.'),
       _m('situacoes', 'código → descrição.', de='texto'),
       _m('instancias', 'código → descrição.', de='texto')),
    _o('beneficios', 'Valores dos filtros de benefício.',
       _l('status', 'Status gerais.'), _l('status_primeira_instancia', 'Status da 1ª instância.'),
       _l('status_segunda_instancia', 'Status da 2ª instância.'),
       _l('status_instancia_filtro', 'Valores aceitos em status_1a_instancia/status_2a_instancia.'),
       _l('tipos_beneficio', 'Espécies.'), _l('tipos_pedido', 'Tipos de pedido.'),
       _l('topicos_contestacao', 'Tópicos jurídicos.')),
    _o('procuracoes', 'Valores do filtro de procurações.', _m('situacoes', 'código → descrição.', de='texto')),
    _l('grupos_empresariais', 'Grupos empresariais aceitos no filtro "grupo".'),
    _l('motivos_fap_catalogo', 'Motivos FAP do catálogo do escritório.'),
)

PROCURACOES = envelope(
    _t('cnpj_raiz_outorgante', 'Raiz do CNPJ da empresa outorgante.'),
    _t('empresa_outorgante', 'Empresa outorgante.'),
    _t('tipo', 'Tipo de procuração.'),
    _t('situacao', 'Situação por extenso.'),
    _t('situacao_codigo', 'Código da situação.'),
    _t('protocolo', 'Protocolo da procuração.'),
    _d('data_inicio', 'Início da vigência.'),
    _d('data_fim', 'Fim da vigência.'),
    _d('ultima_sincronizacao', 'Última sincronização com o portal.'),
)

CALCULO_BENEFICIOS = envelope(*CALCULO_ITEM)

_CONTA = _o('conta', 'Itens que contam no cálculo.', _i('contestado', 'Contestados.'),
            _i('nao_contestado', 'Não contestados.'))
CALCULO_RESUMO = (
    _i('total', 'Itens no recorte.'),
    _m('por_tipo', 'Itens por tipo (B91...CAT).'),
    _i('excluidos', 'Itens tirados no recálculo (contestação ganha).'),
    _i('nao_contestados', 'Itens sem contestação na Central.'),
    _i('contestados', 'Itens com contestação na Central.'),
    _t('total_pago', 'Soma do total pago, em reais (decimal em texto, ex.: "1234.56").'),
    _t('total_pago_nao_contestado', 'Soma do total pago dos não contestados (decimal em texto).'),
    _t('total_pago_excluido', 'Soma do total pago dos excluídos (decimal em texto).'),
    _m('cruzamento', 'Por tipo (chave = B91...CAT): situação × contestado.',
       _CONTA, _o('excluido', 'Itens excluídos do cálculo.', _i('contestado', 'Contestados.'),
                  _i('nao_contestado', 'Não contestados.'))),
)

SEGURADOS = (
    _o('identificadores', 'O que foi pesquisado.', _t('nit', 'NIT.'), _t('cpf', 'CPF.'), _t('nome', 'Nome.')),
    _o('beneficios', 'Benefícios da Central.', _i('total', 'Quantos.'),
       _l('itens', 'Benefícios.', _ID, _t('numero_beneficio', 'NB.'), _t('tipo_beneficio', 'Espécie.'),
          *_SEGURADO, _t('empregador_nome', 'Empregador.'), _t('empregador_cnpj', 'CNPJ do empregador.'),
          _t('vigencias_fap', 'Vigências FAP.'), _TOPICOS, _STATUS_1A, _STATUS_2A, _TOTAL_PAGO)),
    _o('cats', 'CATs contestadas.', _i('total', 'Quantas.'),
       _l('itens', 'CATs.', _t('numero_cat', 'Número da CAT.'), _t('empregador_nome', 'Empregador.'),
          _d('data_acidente', 'Data do acidente.'), _STATUS_1A)),
    _o('processos', 'Processos judiciais com benefício do segurado.', _i('total', 'Quantos.'),
       _l('itens', 'Processos.', _i('processo_id', 'id do processo (rota /processos/{id}).'),
          _t('numero_processo', 'Número do processo.'), _t('titulo', 'Título.'), _t('status', 'Status.'),
          _t('numero_beneficio', 'NB do segurado no processo.'))),
    _o('beneficios_calculo_fap', 'Itens do cálculo FAP (até 30). Só na busca por CPF ou NIT.',
       _i('total', 'Quantos no total.'), _l('itens', 'Itens do cálculo.', *CALCULO_ITEM), opcional=True),
    _t('aviso', 'Só na busca por nome: só acha nomes já revelados ou cadastrados.', opcional=True),
)

REVELAR_NOME = (
    _t('cpf', 'CPF consultado (11 dígitos).'),
    _b('encontrado', 'A consulta achou nome.'),
    _t('nome', 'Nome devolvido.'),
    _b('ja_estava_salvo', 'O nome já tinha sido revelado: não gastou consulta.'),
    _i('consultas_restantes_hoje', 'Consultas pagas que ainda cabem hoje (Claude + API somados).'),
    _t('aviso', 'Nascimento divergente (pode ser outra pessoa) ou nome não encontrado.', opcional=True),
)

CONSULTA_CPF = (
    _t('cpf', 'CPF consultado (11 dígitos).'),
    _t('cpf_formatado', 'O mesmo CPF com pontuação (000.000.000-00).'),
    _b('encontrado', 'O serviço achou o CPF.'),
    Campo('dados', 'objeto', 'A resposta do serviço de consulta, inteira e como ele manda — hoje NOME, NASC '
          '(dd/mm/aaaa), SEXO e NOME_MAE. Vazio quando não encontrou.', extras='campos como o serviço devolve'),
    _t('fonte', 'Serviço consultado (hoje cpf_brasil).'),
    _b('segurado_da_base', 'O CPF aparece em benefício ou no cálculo FAP do escritório.'),
    _b('nascimento_diverge', 'Segurado da base cujo nascimento no serviço não bate com o do FAP '
       '(pode ser outra pessoa).'),
    _i('consultas_restantes_hoje', 'Consultas pagas que ainda cabem hoje (revelar nome + consulta completa, '
       'Claude + API somados).'),
    _t('aviso', 'CPF não encontrado, ou nascimento divergente do FAP.', opcional=True),
)

_DADOS_DO_REGISTRO = (
    _t('especie', 'Espécie (B91...B94).'), _t('cpf', 'CPF formatado.'), _t('nit', 'NIT.'),
    _d('nascimento', 'Nascimento (dd/mm/aaaa).'), _d('dib', 'DIB (dd/mm/aaaa).'), _d('dcb', 'DCB (dd/mm/aaaa).'),
)

CONFERIR_BENEFICIOS = (
    _i('total', 'Benefícios recebidos.'),
    _i('conferem', 'Achados na base, sem divergência no que foi informado.'),
    _i('com_divergencia', 'Achados na base com ao menos um campo divergente.'),
    _i('nao_encontrados', 'Número fora da Central e do cálculo FAP do escritório.'),
    _i('invalidos', 'Item sem dígitos de número.'),
    _i('com_alerta', 'Achados na base com ao menos um alerta.'),
    _l('itens', 'Um por benefício recebido, na ordem enviada.',
       _i('posicao', 'Posição na lista enviada (começa em 1).'),
       _t('numero', 'Número como veio.'),
       _t('numero_normalizado', 'Só os dígitos.'),
       _t('situacao', 'confere, divergente, nao_encontrado ou invalido.'),
       _l('divergencias', 'Campos que não batem.',
          _t('campo', 'cpf, nit, especie, dib, dcb, nascimento, cnpj, vigencia, nome ou cat.'),
          _t('peticao', 'Valor informado (espécie já normalizada).'),
          _l('base', 'Valores que a base tem para o campo.')),
       _l('alertas', 'O que a base diz do benefício, mesmo com os dados conferindo.',
          _t('codigo', 'excluido_do_calculo, ausente_no_calculo_atual, nao_contestado, fora_do_calculo, '
             'cnpj_atribuido_diferente, deferido, indeferido_nas_duas_instancias, nao_encontrado ou '
             'numero_invalido.'),
          _i('vigencia', 'Vigência a que o alerta se refere.'),
          _t('mensagem', 'O alerta por extenso.')),
       _l('conferidos', 'Campos informados que foram comparados.'),
       _l('nao_conferidos', 'Campos informados que não deu para comparar.',
          _t('campo', 'Campo.'), _t('motivo', 'A base não tem o dado, ou o valor não foi reconhecido.')),
       _t('segurado_nome', 'Nome já revelado ou cadastrado (nunca consulta paga).'),
       _l('central', 'Registros na Central de contestações.',
          _i('id', 'Benefício na Central.'), _l('vigencias', 'Vigências FAP.'), _t('cnpj', 'CNPJ do empregador.'),
          *_DADOS_DO_REGISTRO, _t('cat', 'Número da CAT (só dígitos).'),
          _t('status_1a_instancia', 'deferido, indeferido, em_analise ou pendente.'),
          _t('status_2a_instancia', 'Os mesmos valores, ou nao_se_aplica.'),
          _l('topicos', 'Tópicos de contestação.')),
       _l('calculo', 'Itens no cálculo FAP.',
          _t('vigencia', 'Vigência.'), _t('cnpj', 'Estabelecimento.'), _t('empresa', 'Empresa.'),
          *_DADOS_DO_REGISTRO,
          _t('situacao', 'conta (no cálculo) ou excluido (tirado no recálculo).'),
          _b('contestado', 'Contestado na Central nessa vigência.'),
          _b('ausente_no_calculo_atual', 'Saiu num recálculo mais novo.'),
          _t('protocolo', 'Protocolo do cálculo do estabelecimento.'))),
)

KB_PESQUISA = (
    _t('modo_busca', 'semantic ou full_text.'),
    _t('modo_decidido_por', 'usuario (veio no parâmetro) ou roteador_llm.'),
    _t('pergunta_melhorada', 'A pergunta como foi usada na busca.'),
    _i('total_resultados', 'Trechos devolvidos.'),
    _l('resultados', 'Trechos, do mais relevante para o menos.',
       _t('trecho', 'Texto do trecho (até 1.200 caracteres).'),
       _t('fonte', 'Documento de origem.'),
       _i('pagina', 'Página no documento.'),
       _t('categoria', 'Categoria do arquivo.'),
       _l('tags', 'Tags do arquivo.'),
       _t('numero_processo', 'Número de processo do arquivo.'),
       _n('relevancia_percentual', 'Relevância (0–100).'),
       _b('match_literal', 'O termo aparece literalmente no trecho.'),
       _o('arquivo', 'Arquivo de origem.', _ID, _t('nome', 'Nome do arquivo.'), _t('descricao', 'Descrição.'),
          _t('tipo', 'Tipo do arquivo.')),
       _t('url_abrir', 'Endereço do arquivo no IntellexIA.'),
       _t('url_original', 'Link do original (ex.: Google Drive), quando houver.', opcional=True)),
    _t('aviso', 'Quando a busca caiu para outro modo.', opcional=True),
)

KB_ARQUIVO = (
    _o('arquivo', 'O arquivo.', _ID, _t('nome', 'Nome.'), _t('tipo', 'Tipo.'), _t('descricao', 'Descrição.'),
       _t('categoria', 'Categoria.'), _t('numero_processo', 'Número de processo.'),
       _t('status_processamento', 'Situação do processamento.')),
    _t('texto', 'O texto desta parte do arquivo.'),
    _i('total_caracteres', 'Tamanho do texto inteiro.'),
    _t('origem_texto', 'De onde veio o texto (arquivo original ou trechos indexados). Ausente sem texto.',
       opcional=True),
    _i('deslocamento', 'Posição desta parte no texto. Ausente sem texto.', opcional=True),
    _i('retornados', 'Caracteres desta parte. Ausente sem texto.', opcional=True),
    _b('tem_mais', 'Há texto depois desta parte. Ausente sem texto.', opcional=True),
    _i('proximo_deslocamento', 'Valor de "deslocamento" para a próxima parte.', opcional=True),
    _t('url_abrir', 'Endereço do arquivo no IntellexIA.', opcional=True),
    _t('url_original', 'Link do original, quando houver.', opcional=True),
    _t('observacao', 'Quando o texto foi remontado dos trechos indexados.', opcional=True),
    _t('aviso', 'Quando não há texto (arquivo não processado ou sem camada de texto).', opcional=True),
)

JURIS_PESQUISA = envelope(
    *DECISAO_ITEM,
    _i('pagina', 'Página do inteiro teor onde casou (modo inteiro_teor).', opcional=True),
    extra=(
        _i('processos_distintos', 'Processos distintos no recorte (modo campos).', opcional=True),
        Campo(_COMO_TEM_DECIDIDO.nome, 'mapa', _COMO_TEM_DECIDIDO.descricao + ' Modo campos.',
              campos=_COMO_TEM_DECIDIDO.campos, opcional=True),
        _b('total_e_minimo', 'Modo inteiro_teor: o total é "pelo menos".', opcional=True),
        _o('cobertura_inteiro_teor', 'Modo inteiro_teor: quantas decisões têm o PDF indexado.',
           _i('decisoes_na_base', 'Decisões na base.'), _i('com_inteiro_teor_indexado', 'Com PDF indexado.'),
           _t('aviso', 'Quando nem todas estão indexadas.'), opcional=True),
        _t('filtros_ignorados', 'Modo inteiro_teor: filtros que não valem nele.', opcional=True),
    ),
)

_TABELA_RESULTADO = ('Uma linha por grupo; além de "grupo" e "decisoes", uma chave por resultado '
                     '(ex.: "Favorável": 12).')
JURIS_PANORAMA = (
    Campo('recorte', 'objeto', 'Filtros aplicados (vazio = toda a base).', extras='chave = filtro'),
    _i('decisoes', 'Decisões no recorte.'),
    _i('processos', 'Processos distintos no recorte.'),
    _COMO_TEM_DECIDIDO,
    _l('por_tribunal', _TABELA_RESULTADO,
       _t('grupo', 'Tribunal.'), _i('decisoes', 'Decisões.'), extras='uma chave por resultado'),
    _l('por_instancia', _TABELA_RESULTADO,
       _t('grupo', 'Instância.'), _i('decisoes', 'Decisões.'), extras='uma chave por resultado'),
    _l('viradas_no_acordao', 'Até 10 processos em que a sentença perdeu e o acórdão melhorou.',
       _t('processo', 'Número do processo.'), _t('parte_autora', 'Empresa autora.'),
       _i('acordao_id', 'id do acórdão (rota /jurisprudencia/{id}).'), _t('tribunal', 'Tribunal.'),
       _t('resultado_do_acordao', 'Resultado do acórdão.'), _t('citacao', 'Citação pronta.'),
       _t('url', 'Endereço no IntellexIA.')),
    _i('total_viradas', 'Total de viradas no acórdão.'),
    _l('favoraveis_mais_recentes', 'As 8 favoráveis (ou parciais) mais recentes.', *DECISAO_ITEM),
    _t('observacao', 'Como as teses do catálogo são contadas.'),
)

_FACETA = (_i('decisoes', 'Decisões com esse valor.'),)
JURIS_FILTROS = (
    _l('teses_catalogo', 'Teses do catálogo.', _t('nome', 'Tese.'), *_FACETA),
    _l('teses_originais', 'Teses como vieram nas decisões.', _t('nome', 'Tese.'), *_FACETA),
    _l('tribunais', 'Tribunais.', _t('sigla', 'Sigla.'), *_FACETA),
    _l('instancias', 'Instâncias.', _t('valor', 'Valor do filtro.'), _t('rotulo', 'Por extenso.'), *_FACETA),
    _l('resultados', 'Resultados.', _t('valor', 'Valor do filtro.'), _t('rotulo', 'Por extenso.'), *_FACETA),
    _l('ufs', 'UFs.', _t('uf', 'UF.'), *_FACETA),
    _l('anos_de_vigencia', 'Vigências discutidas.', de='inteiro'),
    _o('periodo_de_julgamento', 'Primeira e última data de julgamento.', _d('de', 'Mais antiga.'),
       _d('ate', 'Mais recente.')),
    _i('total_decisoes', 'Decisões na base.'),
)

JURIS_DETALHE = (
    *DECISAO_ITEM,
    _t('classe_processual', 'Classe processual.'),
    _t('relator', 'Relator(a) ou juiz(a).'),
    _t('resumo', 'Resumo executivo do caso.'),
    _t('ementa', 'Ementa.'),
    _t('ementa_tipo', '"transcrição" ou "resumo — não citar como transcrição".'),
    _l('fundamentos', 'Fundamentos da decisão.'),
    _l('argumentos_acolhidos', 'Argumentos acolhidos.'),
    _l('argumentos_rejeitados', 'Argumentos rejeitados.'),
    _l('precedentes_citados', 'Precedentes citados na decisão.',
       _t('texto', 'Precedente como citado.'),
       _i('decisao_na_base_id', 'id do precedente nesta base, quando está nela.')),
    _b('pdf_disponivel', 'O PDF da decisão está no IntellexIA.'),
    _t('origem', 'planilha importada ou PDF lido pela IA.'),
    _l('outras_decisoes_do_processo', 'Outras peças do mesmo processo (sentença, acórdão...).',
       _ID, _t('instancia', 'Instância.'), _d('data_julgamento', 'Data.'), _t('resultado', 'Resultado.')),
)

JURIS_PARECIDAS = (
    _o('decisao_de_referencia', 'A decisão pedida.', *DECISAO_ITEM),
    _l('parecidas', 'Decisões parecidas, da mais para a menos semelhante.', *DECISAO_ITEM,
       _n('semelhanca', 'Semelhança (0–1).')),
    _t('criterio', 'Como a semelhança é medida.'),
)

_FASE = _o('fase_atual', 'Fase atual do processo.', _t('fase', 'Fase.'), _d('desde', 'Desde quando.'))
PROCESSO_ITEM = (
    _ID,
    _t('numero_processo', 'Número do processo.'),
    _t('titulo', 'Título.'),
    _t('status', 'Status.'),
    _t('tribunal', 'Tribunal.'),
    _t('juiz', 'Juiz(a).'),
    _t('autor', 'Autor (cliente).'),
    _t('reu', 'Réu.'),
    _n('valor_causa', 'Valor da causa, em reais.'),
    _d('data_ajuizamento', 'Data do ajuizamento.'),
    _FASE,
)

PROCESSOS = envelope(*PROCESSO_ITEM, _i('qtd_beneficios', 'Benefícios discutidos no processo.'))

PROCESSO_DETALHE = (
    *PROCESSO_ITEM,
    _t('descricao', 'Descrição (resumida).'),
    _t('classe_processual', 'Classe processual.'),
    _l('assuntos', 'Assuntos do processo.'),
    _t('secao', 'Seção judiciária.'),
    _t('unidade_origem', 'Unidade de origem.'),
    _b('segredo_justica', 'Segredo de justiça.'),
    _b('justica_gratuita', 'Justiça gratuita.'),
    _b('liminar_tutela', 'Liminar ou tutela.'),
    _l('historico_fases', 'Fases pelas quais passou.', _t('fase', 'Fase.'), _d('ocorrida_em', 'Quando.'),
       _t('observacoes', 'Observações (resumidas).')),
    _l('beneficios', 'Benefícios discutidos.',
       _t('numero_beneficio', 'NB.'), _t('segurado_nome', 'Segurado.'), _t('nit', 'NIT.'),
       _t('tipo_beneficio', 'Espécie.'), _t('tipo_pedido', 'Tipo de pedido.'), _t('vigencia_fap', 'Vigência FAP.'),
       _l('teses', 'Teses do benefício.'),
       _t('status_contestacao_uniao', 'Situação da contestação da União.'),
       _t('decisao_primeira_instancia', 'Decisão de 1ª instância (resumida).'),
       _t('decisao_segunda_instancia', 'Decisão de 2ª instância (resumida).')),
    _l('notas_recentes', 'Notas mais recentes.', _t('conteudo', 'Texto (resumido).'),
       _d('criada_em', 'Quando.')),
    _d('ultima_atualizacao', 'Última atualização do processo.'),
    _d('criado_em', 'Quando entrou no IntellexIA.'),
)


def _base_numero(rotulo: str, *itens: Campo) -> Campo:
    return _o(rotulo, f'Achados em {rotulo}. Só vem se a base foi pedida e o usuário tem acesso a ela.',
              *envelope(*itens), _t('base', 'Nome da base por extenso.'), opcional=True)


_URL_ORIGINAL = _t('url_original', 'Link do original, quando houver.', opcional=True)
NUMERO_PROCESSO = (
    _t('numero_buscado', 'O número como foi pedido.'),
    _t('digitos', 'Só os dígitos usados na busca.'),
    _t('comparacao', 'número completo (igual) ou parte do número (contém).'),
    _o('bases', 'Resultado por base.',
       _base_numero('base_conhecimento', _ID, _t('numero_processo', 'Número no arquivo.'),
                    _t('arquivo', 'Nome do arquivo.'), _t('categoria', 'Categoria.'), _l('tags', 'Tags.'),
                    _t('tipo', 'Tipo do arquivo.'), _t('situacao', 'Situação do processamento.'),
                    _d('enviado_em', 'Quando foi enviado.'), _t('url_abrir', 'Endereço no IntellexIA.'),
                    _URL_ORIGINAL),
       _base_numero('jurisprudencia', _ID, _t('numero_processo', 'Processo.'), _t('instancia', 'Instância.'),
                    _d('data_julgamento', 'Data.'), _t('tribunal', 'Tribunal.'), _t('orgao_julgador', 'Órgão.'),
                    _t('resultado', 'Resultado.'), _t('parte_autora', 'Empresa autora.'),
                    _l('teses_originais', 'Teses.'), _t('url', 'Endereço no IntellexIA.'), _URL_ORIGINAL),
       _base_numero('pecas_modelo', _ID, _t('numero_processo', 'Processo.'), _t('titulo', 'Título.'),
                    _t('tribunal', 'Região do TRF.'), _t('orgao_julgador', 'Órgão.'), _t('situacao', 'Situação.'),
                    _l('teses', 'Teses.'), _t('url', 'Endereço no IntellexIA.'), _URL_ORIGINAL),
       _base_numero('processos', _ID, _t('numero_processo', 'Número.'), _t('titulo', 'Título.'),
                    _t('status', 'Status.'), _t('tribunal', 'Tribunal.'), _t('autor', 'Autor.'), _t('reu', 'Réu.'),
                    _t('url', 'Endereço no IntellexIA.'))),
    _i('total_encontrado', 'Soma dos achados de todas as bases.'),
    _l('sem_permissao', 'Bases pedidas a que o usuário não tem acesso.', opcional=True),
    _t('aviso', 'Quando nada foi achado.', opcional=True),
)

EU = (
    _o('usuario', 'Dono do token.', _ID, _t('nome', 'Nome.'), _t('email', 'E-mail.'), _t('papel', 'Papel.')),
    _o('escritorio', 'Escritório.', _ID, _t('nome', 'Nome.')),
    _l('modulos', 'Módulos liberados para o usuário agora.'),
    _o('token', 'Token usado na chamada.', _t('nome', 'Nome dado ao token.'), _t('final', 'Últimos 4 caracteres.'),
       _d('expira_em', 'Validade (vazio = sem validade).')),
    _i('consultas_nome_restantes_hoje', 'Consultas de nome que cabem hoje. Só com o módulo do Painel FAP.',
       opcional=True),
)


# ── conferência, schema e exemplo ────────────────────────────────────────────

def _confere_escalar(tipo: str, valor) -> bool:
    if tipo == 'texto' or tipo == 'data':
        return isinstance(valor, str)
    if tipo == 'inteiro':
        return isinstance(valor, int) and not isinstance(valor, bool)
    if tipo == 'numero':
        return isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if tipo == 'booleano':
        return isinstance(valor, bool)
    if tipo in ('objeto', 'mapa'):
        return isinstance(valor, dict)
    if tipo == 'lista':
        return isinstance(valor, list)
    return False


def _conferir_valor(campo: Campo, valor, caminho: str, problemas: list[str]) -> None:
    if valor is None:
        return
    if not _confere_escalar(campo.tipo, valor):
        problemas.append(f'{caminho}: esperado {campo.tipo}, veio {type(valor).__name__}')
        return
    if campo.tipo == 'objeto' and (campo.campos or not campo.extras):
        conferir(valor, campo.campos, problemas, caminho, aceita_extras=bool(campo.extras))
    elif campo.tipo == 'lista':
        for i, item in enumerate(valor[:20]):
            _conferir_item(campo, item, f'{caminho}[{i}]', problemas)
    elif campo.tipo == 'mapa':
        for k, item in list(valor.items())[:20]:
            _conferir_item(campo, item, f'{caminho}.{k}', problemas)


def _conferir_item(campo: Campo, item, caminho: str, problemas: list[str]) -> None:
    if campo.campos:
        if not isinstance(item, dict):
            problemas.append(f'{caminho}: esperado objeto, veio {type(item).__name__}')
            return
        conferir(item, campo.campos, problemas, caminho, aceita_extras=bool(campo.extras))
    elif item is not None and not _confere_escalar(campo.de, item):
        problemas.append(f'{caminho}: esperado {campo.de}, veio {type(item).__name__}')


def conferir(valor: dict, campos: tuple[Campo, ...], problemas: list[str] | None = None,
             caminho: str = '', aceita_extras: bool = False) -> list[str]:
    """Diferenças entre a resposta e a declaração: campo não documentado,
    campo obrigatório ausente, tipo trocado. Lista vazia = confere."""
    problemas = [] if problemas is None else problemas
    declarados = {c.nome: c for c in campos}
    for nome in valor:
        if nome not in declarados and not aceita_extras:
            problemas.append(f'{caminho}.{nome}'.lstrip('.') + ': campo não documentado')
    for c in campos:
        onde = f'{caminho}.{c.nome}'.lstrip('.')
        if c.nome not in valor:
            if not c.opcional:
                problemas.append(f'{onde}: campo documentado ausente')
            continue
        _conferir_valor(c, valor[c.nome], onde, problemas)
    return problemas


_OPENAPI_TIPO = {'texto': 'string', 'data': 'string', 'inteiro': 'integer', 'numero': 'number',
                 'booleano': 'boolean', 'objeto': 'object', 'lista': 'array', 'mapa': 'object'}


def _schema_item(campo: Campo) -> dict:
    if campo.campos:
        return schema(campo.campos, aceita_extras=bool(campo.extras))
    return {'type': [_OPENAPI_TIPO[campo.de], 'null']}


def _schema_campo(campo: Campo) -> dict:
    s: dict = {'description': campo.descricao}
    if campo.tipo == 'objeto':
        s.update(schema(campo.campos, aceita_extras=bool(campo.extras) or not campo.campos))
        s['type'] = ['object', 'null']
    elif campo.tipo == 'lista':
        s.update({'type': ['array', 'null'], 'items': _schema_item(campo)})
    elif campo.tipo == 'mapa':
        s.update({'type': ['object', 'null'], 'additionalProperties': _schema_item(campo)})
    else:
        s['type'] = [_OPENAPI_TIPO[campo.tipo], 'null']
        if campo.tipo == 'data':
            s['description'] += ' Formato ISO 8601.'
    return s


def schema(campos: tuple[Campo, ...], aceita_extras: bool = False) -> dict:
    """JSON Schema (OpenAPI 3.1) de um objeto declarado."""
    s = {
        'type': 'object',
        'properties': {c.nome: _schema_campo(c) for c in campos},
        'required': [c.nome for c in campos if not c.opcional],
    }
    if not aceita_extras:
        s['additionalProperties'] = False
    return s


_EXEMPLO_ESCALAR = {'texto': '...', 'data': '2026-01-31', 'inteiro': 0, 'numero': 0.0, 'booleano': False}


def _exemplo_item(campo: Campo, prof: int):
    if campo.campos:
        return exemplo(campo.campos, prof + 1)
    if campo.de == 'mapa':
        return {'...': 0}
    return _EXEMPLO_ESCALAR.get(campo.de, '...')


def exemplo(campos: tuple[Campo, ...], prof: int = 0) -> dict:
    """Exemplo de resposta montado da declaração — sem dado de ninguém."""
    out = {}
    for c in campos:
        if c.tipo == 'objeto':
            out[c.nome] = exemplo(c.campos, prof + 1) if c.campos else {'...': '...'}
        elif c.tipo == 'lista':
            out[c.nome] = [_exemplo_item(c, prof)]
        elif c.tipo == 'mapa':
            out[c.nome] = {'<chave>': _exemplo_item(c, prof)}
        else:
            out[c.nome] = _EXEMPLO_ESCALAR[c.tipo]
    return out


_ROTULO = {'texto': 'texto', 'inteiro': 'inteiro', 'numero': 'número', 'booleano': 'true/false',
           'data': 'data ISO', 'objeto': 'objeto', 'mapa': 'objeto'}


def linhas(campos: tuple[Campo, ...], prefixo: str = '') -> list[tuple[str, str, str, bool]]:
    """(caminho, tipo, descrição, opcional) achatado — para a tabela da página.
    Item de lista aparece como ``itens[].id``; valor de mapa como ``por_tipo.<chave>``."""
    out = []
    for c in campos:
        nome = prefixo + c.nome
        tipo = _ROTULO.get(c.tipo, c.tipo)
        if c.tipo == 'lista':
            tipo = 'lista de objetos' if c.campos else f'lista de {_ROTULO.get(c.de, c.de)}'
        elif c.tipo == 'mapa':
            tipo = 'objeto (chaves variáveis)'
        out.append((nome, tipo, c.descricao, c.opcional))
        if c.campos:
            filho = nome + ('[].' if c.tipo == 'lista' else '.<chave>.' if c.tipo == 'mapa' else '.')
            out.extend(linhas(c.campos, filho))
    return out
