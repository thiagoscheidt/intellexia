"""Importação da base estruturada (planilha no formato do Banco Mestre FAP).

Duas etapas, como na tela: `conferir` lê a planilha e diz o que vai acontecer
(sem gravar nada); `importar` grava. Reimportar a mesma planilha não duplica:
a chave é processo + instância + data de julgamento.

Só a aba de decisões entra. ERROS_LOG, RESULTADOS, DOCUMENTO_TESE e
ARGUMENTOS_VENCEDORES são log e agregados da ferramenta anterior — aqui eles
saem das próprias decisões (ARGUMENTOS_VENCEDORES, medido: só 31 das 1.294
linhas passavam de 1, porque o contador comparava o texto exato).
"""
from __future__ import annotations

import os
import re
import uuid
from collections import Counter
from typing import Optional

from openpyxl import load_workbook

from app.models import db, JurisprudenceDecision
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as svc

UPLOAD_BASE_DIR = os.path.join('uploads', 'jurisprudence')
_TOKEN = re.compile(r'^[0-9a-f]{32}$')

# Cabeçalho da planilha → chave do registro bruto. As chaves do Banco Mestre
# já são as do registro; os apelidos cobrem planilha exportada à mão.
_APELIDOS = {
    'numero do processo': 'processo', 'n do processo': 'processo', 'processo': 'processo',
    'tipo': 'tipo_documento', 'instancia': 'tipo_documento', 'tipo documento': 'tipo_documento',
    'vigencia': 'vigencia_fap', 'vigencia fap': 'vigencia_fap',
    'orgao': 'orgao_julgador', 'orgao julgador': 'orgao_julgador',
    'link': 'link_drive', 'link drive': 'link_drive',
    'data': 'data_julgamento', 'data do julgamento': 'data_julgamento',
}
_OBRIGATORIAS = ('processo', 'tipo_documento', 'resultado')


class PlanilhaInvalida(ValueError):
    pass


def _coluna(cabecalho) -> str:
    k = norm.texto_de_busca(cabecalho).replace('_', ' ').strip()
    return _APELIDOS.get(k, k.replace(' ', '_'))


def caminho_da_importacao(law_firm_id: int, token: str) -> str:
    if not _TOKEN.match(token or ''):
        raise PlanilhaInvalida('Importação não encontrada.')
    return os.path.join(UPLOAD_BASE_DIR, str(law_firm_id), 'imports', f'{token}.xlsx')


def guardar_arquivo(law_firm_id: int, arquivo) -> str:
    """Salva o .xlsx enviado e devolve o token da importação."""
    token = uuid.uuid4().hex
    caminho = caminho_da_importacao(law_firm_id, token)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    arquivo.save(caminho)
    return token


def ler_planilha(caminho: str) -> dict:
    """Acha a aba de decisões e devolve {aba, colunas, linhas, outras_abas}.

    A aba é a DOCUMENTOS ou, na falta dela, a primeira que tenha as colunas
    obrigatórias — planilha exportada pode ter trocado o nome.
    """
    try:
        wb = load_workbook(caminho, read_only=True, data_only=True)
    except Exception as erro:
        raise PlanilhaInvalida('O arquivo não é uma planilha .xlsx válida.') from erro
    try:
        abas = list(wb.worksheets)
        abas.sort(key=lambda a: a.title.upper() != 'DOCUMENTOS')
        for aba in abas:
            linhas = aba.iter_rows(values_only=True)
            cabecalho = next(linhas, None)
            if not cabecalho:
                continue
            colunas = [_coluna(c) if c is not None else '' for c in cabecalho]
            if not all(obrig in colunas for obrig in _OBRIGATORIAS):
                continue
            registros = []
            for linha in linhas:
                if not linha or all(v in (None, '') for v in linha):
                    continue
                registros.append({col: (linha[i] if i < len(linha) else None)
                                  for i, col in enumerate(colunas) if col})
            return {
                'aba': aba.title,
                'colunas': [c for c in colunas if c],
                'linhas': registros,
                'outras_abas': [a.title for a in wb.worksheets if a.title != aba.title],
            }
    finally:
        wb.close()
    raise PlanilhaInvalida(
        'Nenhuma aba tem as colunas processo, tipo_documento e resultado. '
        'Use a planilha no formato do Banco Mestre FAP.')


def _chave_duplicata(campos: dict):
    if not campos['processo_digits']:
        return None
    return (campos['processo_digits'], campos['tipo_documento'], campos['data_julgamento'])


def _existentes(law_firm_id: int) -> set:
    return {
        (d, t, dj) for d, t, dj in db.session.query(
            JurisprudenceDecision.processo_digits,
            JurisprudenceDecision.tipo_documento,
            JurisprudenceDecision.data_julgamento,
        ).filter(JurisprudenceDecision.law_firm_id == law_firm_id,
                 JurisprudenceDecision.processo_digits.isnot(None)).all()
    }


def conferir(law_firm_id: int, caminho: str, nome_arquivo: Optional[str] = None) -> dict:
    """O que a importação faria — sem gravar nada."""
    planilha = ler_planilha(caminho)
    linhas = planilha['linhas']
    existentes = _existentes(law_firm_id)
    resolvedor = svc.ResolvedorDeTeses(law_firm_id)

    vistos = set()
    novas = ja_existem = repetidas = com_aviso = 0
    avisos = Counter()
    tipos_brutos, tipos = Counter(), Counter()
    resultados_brutos, resultados = Counter(), Counter()
    tribunais_brutos, siglas, orgaos = set(), Counter(), set()
    teses_brutas, teses_chaves = set(), set()
    vigencias_convertidas = 0
    amostra = []

    for bruto in linhas:
        campos = svc.normalizar_registro(bruto)
        chave = _chave_duplicata(campos)
        if chave and chave in existentes:
            ja_existem += 1
        elif chave and chave in vistos:
            repetidas += 1
        else:
            novas += 1
        if chave:
            vistos.add(chave)

        if not campos['processo_digits']:
            avisos['sem número de processo'] += 1
        if not campos['vigencia_texto']:
            avisos['sem vigência FAP: não aparecem no filtro de vigência'] += 1
        if not campos['data_julgamento']:
            avisos['sem data de julgamento'] += 1
        if not campos['parte_autora']:
            avisos['sem parte autora'] += 1
        if not campos['resultado']:
            avisos['sem resultado reconhecido'] += 1
        if (not campos['processo_digits'] or not campos['vigencia_texto'] or not campos['data_julgamento']
                or not campos['parte_autora'] or not campos['resultado']):
            com_aviso += 1

        if bruto.get('tipo_documento'):
            tipos_brutos[str(bruto['tipo_documento']).strip()] += 1
        tipos[campos['tipo_documento']] += 1
        if bruto.get('resultado'):
            resultados_brutos[str(bruto['resultado']).strip()] += 1
        resultados[campos['resultado']] += 1
        if bruto.get('tribunal'):
            tribunais_brutos.add(str(bruto['tribunal']).strip())
        if campos['tribunal']:
            siglas[campos['tribunal']] += 1
        if campos['orgao_julgador']:
            orgaos.add(campos['orgao_julgador'])
        for tese in norm.para_lista(bruto.get('teses')):
            teses_brutas.add(tese.strip())
            teses_chaves.add(norm.chave(tese))
        if bruto.get('vigencia_fap') not in (None, '') and campos['vigencia_texto'] != str(bruto['vigencia_fap']).strip():
            vigencias_convertidas += 1

        if len(amostra) < 6:
            amostra.append({**campos, 'citacao': norm.citacao(campos),
                            'aviso': not campos['vigencia_texto'] or not campos['data_julgamento']})

    ligadas = sum(1 for k in teses_chaves if resolvedor.ligaria_sozinha(k))
    teses_novas = sum(1 for k in teses_chaves if not resolvedor.existe(k))

    return {
        'arquivo': nome_arquivo or os.path.basename(caminho),
        'aba': planilha['aba'],
        'colunas': len(planilha['colunas']),
        'lidas': len(linhas),
        'novas': novas,
        'ja_existem': ja_existem,
        'repetidas_na_planilha': repetidas,
        'com_aviso': com_aviso,
        'avisos': sorted(avisos.items(), key=lambda kv: -kv[1]),
        'padronizacao': {
            'tipos_brutos': len(tipos_brutos),
            'tipos': {k: v for k, v in tipos.items() if k},
            'tipos_unificados': sum(n for bruto, n in tipos_brutos.items()
                                    if bruto != bruto.upper() or norm.sem_acento(bruto) != bruto),
            'resultados_brutos': len(resultados_brutos),
            'resultados_unificados': sum(n for bruto, n in resultados_brutos.items()
                                         if norm.sem_acento(bruto) != bruto),
            'tribunais_brutos': len(tribunais_brutos),
            'siglas': dict(siglas.most_common()),
            'orgaos': len(orgaos),
            'teses_brutas': len(teses_brutas),
            'teses': len(teses_chaves),
            'vigencias_convertidas': vigencias_convertidas,
        },
        'teses': {'total': len(teses_chaves), 'novas': teses_novas,
                  'ligadas': ligadas, 'pendentes': len(teses_chaves) - ligadas},
        'outras_abas': planilha['outras_abas'],
        'amostra': amostra,
    }


def importar(law_firm_id: int, caminho: str, *, user_id: Optional[int] = None,
             nome_arquivo: Optional[str] = None) -> dict:
    """Grava as decisões novas. Devolve as contagens do que aconteceu."""
    planilha = ler_planilha(caminho)
    existentes = _existentes(law_firm_id)
    resolvedor = svc.ResolvedorDeTeses(law_firm_id)
    criadas = puladas = 0

    for i, bruto in enumerate(planilha['linhas'], start=1):
        campos = svc.normalizar_registro(bruto)
        chave = _chave_duplicata(campos)
        if chave and chave in existentes:
            puladas += 1
            continue
        svc.criar_decisao(
            law_firm_id, bruto,
            source=JurisprudenceDecision.SOURCE_PLANILHA,
            resolvedor=resolvedor,
            user_id=user_id,
            drive_link=norm.texto_limpo(bruto.get('link_drive'), 500),
            original_filename=norm.texto_limpo(bruto.get('nome_arquivo'), 255) or nome_arquivo,
        )
        if chave:
            existentes.add(chave)
        criadas += 1
        if i % 100 == 0:
            db.session.flush()

    db.session.commit()
    return {
        'criadas': criadas,
        'puladas': puladas,
        'teses_criadas': resolvedor.criadas,
        'teses_ligadas_sozinhas': resolvedor.ligadas_sozinhas,
    }
