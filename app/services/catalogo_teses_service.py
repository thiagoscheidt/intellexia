"""Catálogo de teses do escritório (PRC-23): carga da planilha e junção de teses.

O escritório mantém o catálogo numa planilha ("Catálogo de teses - Adv
Rodriguez.xlsx") com duas abas que importam aqui:

- **CATÁLOGO**: a tese oficial com código fixo (T-FAP-001), área, descrição,
  situação e, quando inativa, "Juntar com" — a tese ativa que a substitui;
- **EQUIVALÊNCIAS**: cada grafia com que a tese apareceu nas decisões
  ("ERRO NO CUSTO") e a tese do catálogo a que pertence. É por grafia
  inteira, não por termo (resposta do escritório em 23/11/2026).

O catálogo é o mesmo `judicial_legal_theses` do Painel de Processos: a carga
**amplia** as 51 teses que já existiam (casadas pelo código e, na primeira vez,
pelo nome) e cria as que faltam. Equivalência vira ligação da tese da base
(`JurisprudenceThesis`) com o catálogo, pela mesma regra da tela
"Correspondência de teses".

**Juntar uma tese do catálogo não é só desativá-la.** "Sem decisões ligadas",
na planilha, fala só da Jurisprudência: a tese pode estar em benefícios do
Painel, em análises da contestação e nas peças-modelo — e a geração da
impugnação ignora tese inativa, então desativar sozinho a faria sumir da peça
sem aviso. `juntar_tese` leva tudo para a tese de destino (banco, Qdrant e
Meilisearch das peças-modelo) e só então desativa a de origem, guardando em
`merged_into_id` para onde ela foi.

Fonte única do script `scripts/importar_catalogo_teses.py`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from app.models import (
    db,
    ImpugnacaoReferenceChunk,
    ImpugnacaoReferenceModel,
    JudicialLegalThesis,
    JudicialProcessBenefitThesisContestation,
    JurisprudenceThesis,
    judicial_process_benefit_legal_theses as beneficio_tese,
    jurisprudence_decision_theses,
)
from app.services import jurisprudence_index_service as indice_juris
from app.services import jurisprudence_normalizer as norm

ABA_CATALOGO = 'CATALOGO'
ABA_EQUIVALENCIAS = 'EQUIVALENCIAS'

# Grafia da planilha → valor gravado (a tela e os filtros usam estes).
AREAS = {norm.chave(a): a for a in JudicialLegalThesis.AREAS}
CODIGO_RE = re.compile(r'^T-[A-Z]{3}-\d{3}$')


# ── Leitura da planilha ───────────────────────────────────────────────

@dataclass
class TeseDaPlanilha:
    linha: int
    codigo: str
    nome: str
    area: str
    descricao: str
    ativa: bool
    juntar_com: str


@dataclass
class Equivalencia:
    linha: int
    grafia: str
    tese: str
    decisoes: int


@dataclass
class Planilha:
    teses: list[TeseDaPlanilha] = field(default_factory=list)
    equivalencias: list[Equivalencia] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


def _texto(valor) -> str:
    return re.sub(r'\s+', ' ', str(valor or '')).strip()


def _colunas(cabecalho, exigidas: dict[str, str]) -> tuple[dict[str, int], list[str]]:
    """Posição de cada coluna pelo começo do título (sem acento/caixa)."""
    titulos = [norm.chave(c) for c in cabecalho]
    posicoes, faltando = {}, []
    for nome, prefixo in exigidas.items():
        pos = next((i for i, t in enumerate(titulos) if t.startswith(prefixo)), None)
        if pos is None:
            faltando.append(prefixo)
        else:
            posicoes[nome] = pos
    return posicoes, faltando


def ler_planilha(caminho: str) -> Planilha:
    """Lê CATÁLOGO e EQUIVALÊNCIAS e confere a consistência entre elas."""
    import openpyxl

    planilha = Planilha()
    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    abas = {norm.chave(ws.title): ws for ws in wb.worksheets}
    for aba in (ABA_CATALOGO, ABA_EQUIVALENCIAS):
        if aba not in abas:
            planilha.erros.append(f'A planilha não tem a aba {aba}.')
    if planilha.erros:
        return planilha

    linhas = list(abas[ABA_CATALOGO].iter_rows(values_only=True))
    col, faltando = _colunas(linhas[0] if linhas else [], {
        'codigo': 'CODIGO', 'nome': 'TESE DO CATALOGO', 'area': 'AREA',
        'descricao': 'DESCRICAO', 'situacao': 'SITUACAO', 'juntar': 'JUNTAR COM'})
    if faltando:
        planilha.erros.append(f"CATÁLOGO sem as colunas: {', '.join(faltando)}.")
        return planilha
    for n, row in enumerate(linhas[1:], start=2):
        nome = _texto(row[col['nome']])
        if not nome:
            continue
        area = _texto(row[col['area']])
        situacao = norm.chave(row[col['situacao']])
        planilha.teses.append(TeseDaPlanilha(
            linha=n,
            codigo=_texto(row[col['codigo']]).upper(),
            nome=nome,
            area=AREAS.get(norm.chave(area), area),
            descricao=_texto(row[col['descricao']]),
            ativa=situacao != 'INATIVA',
            juntar_com=_texto(row[col['juntar']]),
        ))

    linhas = list(abas[ABA_EQUIVALENCIAS].iter_rows(values_only=True))
    col, faltando = _colunas(linhas[0] if linhas else [], {
        'grafia': 'TESE ORIGINAL', 'tese': 'TESE DO CATALOGO', 'decisoes': 'DECISOES'})
    if faltando:
        planilha.erros.append(f"EQUIVALÊNCIAS sem as colunas: {', '.join(faltando)}.")
        return planilha
    for n, row in enumerate(linhas[1:], start=2):
        grafia = _texto(row[col['grafia']])
        if not grafia:
            continue
        try:
            decisoes = int(row[col['decisoes']] or 0)
        except (TypeError, ValueError):
            decisoes = 0
        planilha.equivalencias.append(Equivalencia(
            linha=n, grafia=grafia, tese=_texto(row[col['tese']]), decisoes=decisoes))

    _conferir(planilha)
    return planilha


def _conferir(planilha: Planilha) -> None:
    erros = planilha.erros
    por_nome: dict[str, TeseDaPlanilha] = {}
    codigos: dict[str, int] = {}
    for t in planilha.teses:
        if not CODIGO_RE.match(t.codigo):
            erros.append(f'CATÁLOGO linha {t.linha}: código "{t.codigo}" fora do padrão T-XXX-000.')
        if t.codigo in codigos:
            erros.append(f'CATÁLOGO linha {t.linha}: código {t.codigo} repetido (linha {codigos[t.codigo]}).')
        codigos[t.codigo] = t.linha
        if norm.chave(t.nome) in por_nome:
            erros.append(f'CATÁLOGO linha {t.linha}: tese "{t.nome}" repetida.')
        por_nome[norm.chave(t.nome)] = t
        if t.area not in JudicialLegalThesis.AREAS:
            erros.append(f'CATÁLOGO linha {t.linha}: área "{t.area}" desconhecida.')
        if not t.ativa and not t.juntar_com:
            erros.append(f'CATÁLOGO linha {t.linha}: "{t.nome}" está inativa sem dizer com qual juntar.')
    for t in planilha.teses:
        if t.ativa or not t.juntar_com:
            continue
        destino = por_nome.get(norm.chave(t.juntar_com))
        if destino is None:
            erros.append(f'CATÁLOGO linha {t.linha}: "Juntar com" aponta para "{t.juntar_com}", '
                         'que não está no catálogo.')
        elif not destino.ativa:
            erros.append(f'CATÁLOGO linha {t.linha}: "Juntar com" aponta para "{t.juntar_com}", '
                         'que também está inativa.')

    grafias: dict[str, int] = {}
    for e in planilha.equivalencias:
        chave = norm.chave(e.grafia)
        if chave in grafias:
            erros.append(f'EQUIVALÊNCIAS linha {e.linha}: "{e.grafia}" repetida (linha {grafias[chave]}).')
        grafias[chave] = e.linha
        alvo = por_nome.get(norm.chave(e.tese))
        if alvo is None:
            erros.append(f'EQUIVALÊNCIAS linha {e.linha}: tese "{e.tese}" não está no catálogo.')
        elif not alvo.ativa:
            erros.append(f'EQUIVALÊNCIAS linha {e.linha}: tese "{e.tese}" está inativa.')


# ── Plano (simulação) ─────────────────────────────────────────────────

def _chave_nova(law_firm_id: int, nome: str, usadas: set[str]) -> str:
    base = re.sub(r'[^a-z0-9]+', '_', norm.sem_acento(nome).lower()).strip('_')[:110] or 'tese'
    chave, n = base, 2
    while chave in usadas or JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, key=chave).first():
        chave, n = f'{base}_{n}', n + 1
    usadas.add(chave)
    return chave


def _uso_da_tese(law_firm_id: int, tese: JudicialLegalThesis, pecas: list) -> dict:
    """Onde a tese do catálogo aparece fora da Jurisprudência."""
    return {
        'beneficios': db.session.query(beneficio_tese.c.id)
        .filter(beneficio_tese.c.legal_thesis_id == tese.id).count(),
        'contestacoes': JudicialProcessBenefitThesisContestation.query
        .filter_by(law_firm_id=law_firm_id, legal_thesis_id=tese.id).count(),
        'pecas': sum(1 for p in pecas if tese.key in (p.thesis_catalog_ids or [])),
        'trechos': ImpugnacaoReferenceChunk.query
        .filter_by(law_firm_id=law_firm_id, thesis_catalog_id=tese.key).count(),
        'teses_da_base': JurisprudenceThesis.query
        .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                JurisprudenceThesis.catalog_theses.any(JudicialLegalThesis.id == tese.id)).count(),
    }


def planejar(law_firm_id: int, planilha: Planilha, *, descricoes: bool = False) -> dict:
    """O que a carga faria, sem gravar nada."""
    catalogo = JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id).all()
    por_codigo = {t.code: t for t in catalogo if t.code}
    por_nome = {norm.chave(t.name): t for t in catalogo}
    pecas = (ImpugnacaoReferenceModel.query
             .filter(ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
                     ImpugnacaoReferenceModel.thesis_catalog_ids.isnot(None)).all())

    plano = {'law_firm_id': law_firm_id, 'criar': [], 'atualizar': [], 'sem_mudanca': 0,
             'juntar': [], 'erros': list(planilha.erros), 'fora_da_planilha': [],
             'ligar': [], 'ligacao_igual': 0, 'trocar_ligacao': [], 'grafia_fora_da_base': [],
             'teses_da_base_sem_equivalencia': [], 'beneficios_fora_da_area': []}
    usadas: set[str] = set()
    alvo_por_nome: dict[str, dict] = {}  # nome normalizado → {'id' ou 'key'} da tese de destino

    for t in planilha.teses:
        atual = por_codigo.get(t.codigo) or por_nome.get(norm.chave(t.nome))
        if atual is not None and atual.code and atual.code != t.codigo:
            plano['erros'].append(f'"{t.nome}" já tem o código {atual.code} no sistema; '
                                  f'a planilha diz {t.codigo}. Código não se troca.')
            continue
        if atual is None:
            chave = _chave_nova(law_firm_id, t.nome, usadas)
            plano['criar'].append({'codigo': t.codigo, 'nome': t.nome, 'area': t.area,
                                   'descricao': t.descricao, 'ativa': t.ativa, 'key': chave})
            alvo_por_nome[norm.chave(t.nome)] = {'key': chave, 'nome': t.nome}
            continue
        alvo_por_nome[norm.chave(t.nome)] = {'id': atual.id, 'key': atual.key, 'nome': t.nome}
        mudancas = {}
        if atual.code != t.codigo:
            mudancas['code'] = t.codigo
        if (atual.area or None) != t.area:
            mudancas['area'] = t.area
        if atual.name != t.nome:
            mudancas['name'] = t.nome
        if t.descricao and (descricoes or not (atual.description or '').strip()) \
                and (atual.description or '').strip() != t.descricao:
            mudancas['description'] = t.descricao
        if t.ativa and not atual.is_active and not atual.merged_into_id:
            mudancas['is_active'] = True
        if mudancas:
            plano['atualizar'].append({'id': atual.id, 'nome': atual.name, 'mudancas': mudancas})
        else:
            plano['sem_mudanca'] += 1

    for t in planilha.teses:
        if t.ativa:
            continue
        origem = alvo_por_nome.get(norm.chave(t.nome))
        destino = alvo_por_nome.get(norm.chave(t.juntar_com))
        if not origem or not destino:
            continue
        if 'id' not in origem:
            # Tese nova que já nasce inativa: não há nada a levar, só registrar o destino.
            next(c for c in plano['criar'] if c['key'] == origem['key'])['juntar_em'] = destino['key']
            continue
        atual = db.session.get(JudicialLegalThesis, origem['id'])
        uso = _uso_da_tese(law_firm_id, atual, pecas)
        if atual.merged_into_id and atual.merged_into_id == destino.get('id') \
                and not atual.is_active and not any(uso.values()):
            continue  # já juntada e sem resto
        plano['juntar'].append({
            'origem': t.nome, 'origem_id': origem['id'], 'origem_key': origem['key'],
            'destino': destino['nome'], 'destino_id': destino.get('id'), 'destino_key': destino['key'],
            'uso': uso,
        })

    nomes_planilha = {norm.chave(t.nome) for t in planilha.teses}
    for t in catalogo:
        if norm.chave(t.name) not in nomes_planilha and not (t.code and t.code in
                                                              {x.codigo for x in planilha.teses}):
            plano['fora_da_planilha'].append({'id': t.id, 'nome': t.name, 'ativa': bool(t.is_active)})

    # Equivalências → ligações da tese da base.
    teses_base = {t.key: t for t in JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).all()}
    cobertas: set[int] = set()
    for e in planilha.equivalencias:
        alvo = alvo_por_nome.get(norm.chave(e.tese))
        if alvo is None:
            continue
        tese = teses_base.get(norm.chave(e.grafia))
        if tese is None:
            plano['grafia_fora_da_base'].append({'grafia': e.grafia, 'tese': e.tese})
            continue
        canonica = tese
        while canonica.merged_into_id and canonica.merged_into is not None:
            canonica = canonica.merged_into
        cobertas.update({tese.id, canonica.id})
        atuais = sorted(c.name for c in canonica.catalog_theses)
        item = {'tese_id': canonica.id, 'grafia': e.grafia, 'tese': alvo['nome'],
                'alvo_id': alvo.get('id'), 'alvo_key': alvo['key'], 'antes': atuais,
                'mesclada_em': canonica.name if canonica.id != tese.id else None}
        mesma = [norm.chave(n) for n in atuais] == [norm.chave(alvo['nome'])]
        if mesma and canonica.status == canonica.STATUS_LIGADA:
            plano['ligacao_igual'] += 1
        elif atuais and not mesma:
            plano['trocar_ligacao'].append(item)
        else:
            plano['ligar'].append(item)

    contagem = dict(db.session.query(jurisprudence_decision_theses.c.thesis_id,
                                     db.func.count()).group_by(jurisprudence_decision_theses.c.thesis_id).all())
    for t in teses_base.values():
        if t.id in cobertas or t.merged_into_id or t.status != t.STATUS_PENDENTE:
            continue
        plano['teses_da_base_sem_equivalencia'].append({'id': t.id, 'nome': t.name,
                                                         'decisoes': int(contagem.get(t.id, 0))})
    plano['teses_da_base_sem_equivalencia'].sort(key=lambda x: (-x['decisoes'], x['nome']))

    # Benefícios ligados a teses que, pela área, saem do seletor do benefício.
    area_nova = {norm.chave(t.nome): t.area for t in planilha.teses}
    for t in catalogo:
        area = area_nova.get(norm.chave(t.name), t.area)
        if area in (None, '', JudicialLegalThesis.AREA_FAP):
            continue
        n = db.session.query(beneficio_tese.c.id).filter(beneficio_tese.c.legal_thesis_id == t.id).count()
        if n:
            plano['beneficios_fora_da_area'].append({'nome': t.name, 'area': area, 'beneficios': n})
    return plano


# ── Aplicação ─────────────────────────────────────────────────────────

def executar(plano: dict, *, juntar: bool = False) -> dict:
    """Grava o plano: cria/atualiza o catálogo, liga as equivalências e, com
    `juntar=True`, junta as teses inativas na de destino."""
    if plano['erros']:
        raise ValueError('A planilha tem erros; corrija antes de aplicar.')
    law_firm_id = plano['law_firm_id']
    resultado = {'criadas': 0, 'atualizadas': 0, 'ligadas': 0, 'juntadas': [], 'avisos': []}

    criadas: dict[str, JudicialLegalThesis] = {}
    for c in plano['criar']:
        nova = JudicialLegalThesis(law_firm_id=law_firm_id, key=c['key'], name=c['nome'], code=c['codigo'],
                                   area=c['area'], description=c['descricao'] or None, is_active=c['ativa'])
        db.session.add(nova)
        criadas[c['key']] = nova
        resultado['criadas'] += 1
    for a in plano['atualizar']:
        tese = JudicialLegalThesis.query.filter_by(id=a['id'], law_firm_id=law_firm_id).first()
        for campo, valor in a['mudancas'].items():
            setattr(tese, campo, valor)
        resultado['atualizadas'] += 1
    db.session.flush()

    def _alvo(item_id, item_key):
        if item_id:
            return JudicialLegalThesis.query.filter_by(id=item_id, law_firm_id=law_firm_id).first()
        return criadas.get(item_key) or JudicialLegalThesis.query.filter_by(
            law_firm_id=law_firm_id, key=item_key).first()

    for c in plano['criar']:
        if c.get('juntar_em'):
            destino = _alvo(None, c['juntar_em'])
            if destino is not None:
                criadas[c['key']].merged_into_id = destino.id

    teses_tocadas = []
    for item in plano['ligar'] + plano['trocar_ligacao']:
        tese = JurisprudenceThesis.query.filter_by(id=item['tese_id'], law_firm_id=law_firm_id).first()
        alvo = _alvo(item['alvo_id'], item['alvo_key'])
        if tese is None or alvo is None:
            continue
        tese.catalog_theses = [alvo]
        tese.status = tese.STATUS_LIGADA
        tese.suggestion_json = None
        teses_tocadas.append(tese.id)
        resultado['ligadas'] += 1
    db.session.commit()
    _reindexar_decisoes(law_firm_id, teses_tocadas)

    if juntar:
        for j in plano['juntar']:
            origem = _alvo(j['origem_id'], j['origem_key'])
            destino = _alvo(j['destino_id'], j['destino_key'])
            if origem is None or destino is None:
                continue
            feito = juntar_tese(law_firm_id, origem.id, destino.id)
            resultado['juntadas'].append({'origem': origem.name, 'destino': destino.name, **feito})
            if feito.get('aviso'):
                resultado['avisos'].append(f"{origem.name}: {feito['aviso']}")
    return resultado


def _reindexar_decisoes(law_firm_id: int, thesis_ids) -> None:
    ids = [t for t in dict.fromkeys(thesis_ids) if t]
    if not ids:
        return
    decisoes = [r[0] for r in db.session.query(jurisprudence_decision_theses.c.decision_id)
                .filter(jurisprudence_decision_theses.c.thesis_id.in_(ids)).all()]
    indice_juris.agendar(law_firm_id, decisoes, somente_metadados=True)


def _trocar(lista, origem: str, destino: str) -> list:
    novo = []
    for k in lista or []:
        k = destino if k == origem else k
        if k not in novo:
            novo.append(k)
    return novo


def juntar_tese(law_firm_id: int, origem_id: int, destino_id: int) -> dict:
    """Leva tudo o que usa a tese de origem para a de destino e desativa a origem.

    Rodar de novo é seguro: o que já foi levado não é achado de novo, e a
    atualização dos índices das peças-modelo (que pode falhar sozinha) refaz.
    """
    if origem_id == destino_id:
        raise ValueError('Escolha outra tese para juntar.')
    origem = JudicialLegalThesis.query.filter_by(id=origem_id, law_firm_id=law_firm_id).first()
    destino = JudicialLegalThesis.query.filter_by(id=destino_id, law_firm_id=law_firm_id).first()
    if origem is None or destino is None:
        raise LookupError('Tese não encontrada.')
    if destino.merged_into_id or not destino.is_active:
        raise ValueError(f'"{destino.name}" não está ativa; junte numa tese ativa.')
    feito = {'beneficios': 0, 'contestacoes': 0, 'pecas': 0, 'trechos': 0, 'teses_da_base': 0}

    # Benefícios do Painel: o vínculo (benefício, tese) é único.
    ja_no_destino = {r[0] for r in db.session.query(beneficio_tese.c.benefit_id)
                     .filter(beneficio_tese.c.legal_thesis_id == destino.id).all()}
    for row_id, benefit_id in db.session.query(beneficio_tese.c.id, beneficio_tese.c.benefit_id) \
            .filter(beneficio_tese.c.legal_thesis_id == origem.id).all():
        if benefit_id in ja_no_destino:
            db.session.execute(beneficio_tese.delete().where(beneficio_tese.c.id == row_id))
        else:
            db.session.execute(beneficio_tese.update().where(beneficio_tese.c.id == row_id)
                               .values(legal_thesis_id=destino.id))
            ja_no_destino.add(benefit_id)
        feito['beneficios'] += 1

    # Análise da contestação por (benefício, tese): vale a que já existe no destino.
    com_destino = {r.process_benefit_id for r in JudicialProcessBenefitThesisContestation.query
                   .filter_by(law_firm_id=law_firm_id, legal_thesis_id=destino.id).all()}
    for analise in JudicialProcessBenefitThesisContestation.query.filter_by(
            law_firm_id=law_firm_id, legal_thesis_id=origem.id).all():
        if analise.process_benefit_id in com_destino:
            db.session.delete(analise)
        else:
            analise.legal_thesis_id = destino.id
            com_destino.add(analise.process_benefit_id)
        feito['contestacoes'] += 1

    # Peças-modelo (lista de chaves) e trechos (chave principal).
    for peca in ImpugnacaoReferenceModel.query.filter(
            ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
            ImpugnacaoReferenceModel.thesis_catalog_ids.isnot(None)).all():
        if origem.key in (peca.thesis_catalog_ids or []):
            peca.thesis_catalog_ids = _trocar(peca.thesis_catalog_ids, origem.key, destino.key)
            feito['pecas'] += 1
    for trecho in ImpugnacaoReferenceChunk.query.filter_by(
            law_firm_id=law_firm_id, thesis_catalog_id=origem.key).all():
        trecho.thesis_catalog_id = destino.key
        feito['trechos'] += 1

    # Teses da base ligadas à origem passam para o destino.
    teses_base = (JurisprudenceThesis.query
                  .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                          JurisprudenceThesis.catalog_theses.any(JudicialLegalThesis.id == origem.id)).all())
    for tese in teses_base:
        ligadas = [c for c in tese.catalog_theses if c.id != origem.id]
        if destino not in ligadas:
            ligadas.append(destino)
        tese.catalog_theses = ligadas
        tese.status = tese.STATUS_LIGADA
        feito['teses_da_base'] += 1

    # Quem já tinha sido juntado na origem passa a apontar para o destino.
    for filha in JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, merged_into_id=origem.id).all():
        filha.merged_into_id = destino.id
    origem.is_active = False
    origem.merged_into_id = destino.id
    db.session.commit()

    _reindexar_decisoes(law_firm_id, [t.id for t in teses_base])
    # Meilisearch: todos os trechos que hoje estão no destino (de novo, se a
    # junção for repetida — atualizar com o mesmo valor não muda nada).
    pontos_meili = [str(pid).replace('-', '') for (pid,) in db.session.query(ImpugnacaoReferenceChunk.qdrant_point_id)
                    .filter(ImpugnacaoReferenceChunk.law_firm_id == law_firm_id,
                            ImpugnacaoReferenceChunk.thesis_catalog_id == destino.key,
                            ImpugnacaoReferenceChunk.qdrant_point_id.isnot(None)).all()]
    aviso = _trocar_nos_indices_das_pecas(law_firm_id, origem.key, destino.key, pontos_meili)
    if aviso:
        feito['aviso'] = aviso
    return feito


# Substituíveis no teste: o teste usa Qdrant em memória e não toca a busca real.
COLECAO_PECAS = os.getenv('IMPUGNACAO_REFERENCES_COLLECTION', 'impugnacao_models')


def _cliente_qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(host=os.getenv('QDRANT_HOST', 'localhost'),
                        port=int(os.getenv('QDRANT_PORT', '6333')), timeout=60)


def _atualizar_busca_das_pecas(pontos: list[str], destino: str) -> None:
    from app.services import impugnacao_reference_search as busca
    cliente, indice = busca._get_index()
    for i in range(0, len(pontos), 500):
        tarefa = indice.update_documents([{'id': pid, 'thesis_catalog_id': destino} for pid in pontos[i:i + 500]])
        cliente.wait_for_task(tarefa.task_uid, timeout_in_ms=busca.MEILI_WAIT_MS)


def _trocar_nos_indices_das_pecas(law_firm_id: int, origem: str, destino: str,
                                  pontos_meili: list[str]) -> Optional[str]:
    """Troca a chave no payload do Qdrant (a geração filtra por ela) e no
    Meilisearch das peças. Falha aqui não desfaz o banco: o aviso manda rodar
    de novo, e a junção é segura de repetir."""
    from qdrant_client.http import models as rest

    campos = ('thesis_catalog_id', 'thesis_catalog_ids', 'document_thesis_catalog_ids')
    avisos = []
    try:
        cliente = _cliente_qdrant()
        if cliente.collection_exists(COLECAO_PECAS):
            filtro = rest.Filter(
                must=[rest.FieldCondition(key='law_firm_id', match=rest.MatchValue(value=int(law_firm_id)))],
                should=[rest.FieldCondition(key=campo, match=rest.MatchAny(any=[origem])) for campo in campos],
            )
            grupos: dict[tuple, list] = {}
            proximo = None
            while True:
                pontos, proximo = cliente.scroll(COLECAO_PECAS, scroll_filter=filtro, limit=256, offset=proximo,
                                                 with_payload=list(campos), with_vectors=False)
                for p in pontos:
                    pl = p.payload or {}
                    principal = pl.get('thesis_catalog_id')
                    novo = (destino if principal == origem else principal,
                            tuple(_trocar(pl.get('thesis_catalog_ids'), origem, destino)),
                            tuple(_trocar(pl.get('document_thesis_catalog_ids'), origem, destino)))
                    grupos.setdefault(novo, []).append(p.id)
                if proximo is None:
                    break
            for (principal, ids, doc_ids), pontos in grupos.items():
                cliente.set_payload(COLECAO_PECAS, payload={'thesis_catalog_id': principal,
                                                            'thesis_catalog_ids': list(ids),
                                                            'document_thesis_catalog_ids': list(doc_ids)},
                                    points=pontos, wait=True)
    except Exception as e:  # noqa: BLE001 — índice nunca derruba a junção
        avisos.append(f'Qdrant das peças-modelo não atualizado ({e}); rode a junção de novo.')

    if pontos_meili:
        try:
            _atualizar_busca_das_pecas(pontos_meili, destino)
        except Exception as e:  # noqa: BLE001
            avisos.append(f'Busca das peças-modelo não atualizada ({e}); rode a junção de novo.')
    return ' '.join(avisos) or None
