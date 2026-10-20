"""Sincronização da Consulta do FAP, um estabelecimento por vez.

Duas metades de propósito: ``buscar_estabelecimento`` só faz rede (segura em
thread) e ``gravar_estabelecimento`` só mexe no banco (fluxo principal).

Regras: nada é apagado por ausência; 401/403/erro de um estabelecimento só
registra a situação e **não** sobrescreve ``calculo_atual_id`` — assim a próxima
execução tenta de novo. Nada de CPF em log.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.models import db, FapCalculoEstabelecimento, FapCalculoItem
from app.services import fap_calculo_client as client
from app.services import fap_calculo_parser as parser

SITUACOES_QUE_GRAVAM_ITENS = ('ok', 'sem_calculo')
_TAM_ERRO = 255


def _utcnow() -> datetime:
    """Agora em UTC, naive (``TZ=America/Sao_Paulo`` faz ``now()`` vir local)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class BuscaEstabelecimento:
    ano: int
    cnpj: str
    situacao: str  # ok | sem_calculo | sem_acesso | erro | expirada
    resumo: dict | None = None
    itens_atual: list[dict] | None = None  # None = não buscou
    estados_original: dict[tuple[str, str], str] = field(default_factory=dict)
    erro: str = ''


def _situacao_da_falha(r) -> str:
    if r.expired:
        return 'expirada'
    if r.status_code == 403:
        return 'sem_acesso'
    return 'erro'


def _itens(svc, ano: int, cnpj: str, calculo_id: int):
    """Benefícios + CATs normalizados de um cálculo: ``(itens, None)`` ou ``(None, falha)``."""
    rb = client.listar_beneficios(svc, ano, cnpj, calculo_id)
    if not rb.ok:
        return None, rb
    rc = client.listar_cats(svc, ano, cnpj, calculo_id)
    if not rc.ok:
        return None, rc
    itens = [parser.normalizar_beneficio(d) for d in (rb.data or [])]
    itens += [parser.normalizar_cat(d) for d in (rc.data or [])]
    return [i for i in itens if i.get('identificador')], None


def _falha(ano: int, cnpj: str, r) -> BuscaEstabelecimento:
    return BuscaEstabelecimento(ano, cnpj, _situacao_da_falha(r), erro=r.message or '')


def buscar_estabelecimento(svc, ano: int, cnpj14: str,
                           calculo_atual_id_gravado: int | None) -> BuscaEstabelecimento:
    """Só rede. Busca os itens apenas quando o cálculo atual mudou."""
    r = client.listar_calculos(svc, ano, cnpj14)
    if not r.ok:
        return _falha(ano, cnpj14, r)
    resumo = parser.resumir_calculos(r.data or [])
    if not resumo['atual_id']:
        return BuscaEstabelecimento(ano, cnpj14, 'sem_calculo', resumo=resumo)

    busca = BuscaEstabelecimento(ano, cnpj14, 'ok', resumo=resumo)
    if not resumo['tem_itens']:
        busca.itens_atual = []
        return busca
    if calculo_atual_id_gravado == resumo['atual_id']:
        return busca

    itens, falha = _itens(svc, ano, cnpj14, resumo['atual_id'])
    if falha:
        return _falha(ano, cnpj14, falha)
    if resumo['original_id'] != resumo['atual_id']:
        originais, falha = _itens(svc, ano, cnpj14, resumo['original_id'])
        if falha:
            return _falha(ano, cnpj14, falha)
        busca.estados_original = {
            (i['tipo'], i['identificador']): i['estado_atual'] for i in originais
        }
    busca.itens_atual = itens
    return busca


def _historico_json(historico: list[dict]) -> str:
    return json.dumps([
        {**h, 'data': h['data'].isoformat() if isinstance(h.get('data'), date) else h.get('data')}
        for h in historico
    ], ensure_ascii=False)


def gravar_estabelecimento(law_firm_id: int, busca: BuscaEstabelecimento) -> dict:
    """Só banco. Devolve ``{'itens_novos': n, 'itens_atualizados': n}``."""
    agora = _utcnow()
    estab = FapCalculoEstabelecimento.query.filter_by(
        law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj).first()
    if estab is None:
        estab = FapCalculoEstabelecimento(
            law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj,
            cnpj_raiz=busca.cnpj[:8], tem_itens=False)
        db.session.add(estab)

    estab.situacao = busca.situacao
    estab.erro = (busca.erro or '')[:_TAM_ERRO] or None
    estab.synced_at = agora
    contagem = {'itens_novos': 0, 'itens_atualizados': 0}

    if busca.situacao not in SITUACOES_QUE_GRAVAM_ITENS:
        db.session.commit()
        return contagem

    resumo = busca.resumo or {}
    estab.calculo_atual_id = resumo.get('atual_id')
    estab.calculo_atual_tipo = resumo.get('atual_tipo')
    estab.calculo_atual_data = resumo.get('atual_data')
    estab.calculo_original_id = resumo.get('original_id')
    estab.tem_itens = bool(resumo.get('tem_itens'))
    estab.historico_json = _historico_json(resumo.get('historico') or [])
    estab.protocolo = resumo.get('protocolo')

    if busca.itens_atual is not None:
        mesmo = resumo.get('atual_id') == resumo.get('original_id')
        existentes = {
            (i.tipo, i.identificador): i
            for i in FapCalculoItem.query.filter_by(
                law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj)
        }
        for dados in busca.itens_atual:
            chave = (dados['tipo'], dados['identificador'])
            campos = {k: v for k, v in dados.items()
                      if k not in ('cnpj', 'tipo', 'identificador')}
            campos['estado_original'] = (
                'ORIGINAL' if mesmo else busca.estados_original.get(chave))
            campos['calculo_id'] = resumo.get('atual_id')
            item = existentes.get(chave)
            if item is None:
                item = FapCalculoItem(
                    law_firm_id=law_firm_id, ano_vigencia=busca.ano, cnpj=busca.cnpj,
                    cnpj_raiz=busca.cnpj[:8], tipo=chave[0], identificador=chave[1],
                    first_seen_at=agora)
                db.session.add(item)
                existentes[chave] = item
                contagem['itens_novos'] += 1
            else:
                contagem['itens_atualizados'] += 1
            for k, v in campos.items():
                setattr(item, k, v)
            item.last_seen_at = agora

    db.session.commit()
    return contagem


def completar_central(law_firm_id: int, ano: int | None = None) -> dict:
    """Preenche CPF, nascimento, RMI e total pago dos benefícios da Central.

    Lê de ``fap_calculo_itens`` (sem rede): casa NB sem zeros à esquerda e a
    mesma vigência (``vigencia_year`` da FK do benefício == ``ano_vigencia``),
    nunca CAT. Com mais de uma linha, prefere a do CNPJ do benefício. Regras de
    campo em ``fap_beneficio_portal_service.aplicar_item``. Commit por ano.
    """
    from app.models import Benefit, FapVigenciaCnpj
    from app.services.fap_beneficio_portal_service import aplicar_item, chave_nb

    from app.utils.cnpj import completar_zeros

    conta = {'beneficios_vistos': 0, 'cpf': 0, 'nascimento': 0, 'rmi': 0, 'total_pago': 0}

    q_anos = (db.session.query(FapVigenciaCnpj.vigencia_year)
              .join(Benefit, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
              .filter(Benefit.law_firm_id == law_firm_id))
    if ano is not None:
        q_anos = q_anos.filter(FapVigenciaCnpj.vigencia_year == str(ano))
    anos = {}
    for (v,) in q_anos.distinct().all():
        try:
            anos[int(v)] = v
        except (TypeError, ValueError):
            continue

    colunas = (FapCalculoItem.identificador, FapCalculoItem.cnpj, FapCalculoItem.cpf,
               FapCalculoItem.data_nascimento, FapCalculoItem.valor_mensal, FapCalculoItem.total_pago)
    for ano_vig in sorted(anos):
        itens: dict[str, list] = {}
        linhas = (db.session.query(*colunas)
                  .filter(FapCalculoItem.law_firm_id == law_firm_id,
                          FapCalculoItem.ano_vigencia == ano_vig,
                          FapCalculoItem.tipo != 'CAT')
                  .order_by(FapCalculoItem.id).all())
        for ident, cnpj, cpf, nasc, rmi, total in linhas:
            itens.setdefault(chave_nb(ident), []).append((cnpj, cpf, nasc, rmi, total))
        if not itens:
            conta['beneficios_vistos'] += (db.session.query(Benefit.id)
                                           .join(FapVigenciaCnpj, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
                                           .filter(Benefit.law_firm_id == law_firm_id,
                                                   FapVigenciaCnpj.vigencia_year == anos[ano_vig]).count())
            continue
        beneficios = (db.session.query(Benefit, FapVigenciaCnpj.employer_cnpj)
                      .join(FapVigenciaCnpj, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
                      .filter(Benefit.law_firm_id == law_firm_id,
                              FapVigenciaCnpj.vigencia_year == anos[ano_vig])
                      .order_by(Benefit.id).all())
        for b, cnpj_vig in beneficios:
            conta['beneficios_vistos'] += 1
            candidatos = itens.get(chave_nb(b.benefit_number))
            if not candidatos:
                continue
            alvo = completar_zeros(cnpj_vig, 14)
            escolhido = next((c for c in candidatos if c[0] == alvo), candidatos[0])
            dados = dict(zip(('cpf', 'data_nascimento', 'valor_mensal', 'total_pago'), escolhido[1:]))
            for campo in aplicar_item(b, dados):
                conta[campo] += 1
        db.session.commit()
    return conta


_LOG_A_CADA = 200


def _raizes_do_escritorio(law_firm_id: int) -> list[str]:
    from app.models import FapCompany
    from app.utils.cnpj import TAMANHO_CNPJ_RAIZ, completar_zeros

    raizes = {completar_zeros(c, TAMANHO_CNPJ_RAIZ)
              for (c,) in db.session.query(FapCompany.cnpj).filter(FapCompany.law_firm_id == law_firm_id)}
    return sorted(r for r in raizes if r and len(r) == TAMANHO_CNPJ_RAIZ)


def sincronizar(law_firm_id: int, svc, anos: list[int] | None = None,
                raizes: list[str] | None = None, cnpjs: list[str] | None = None,
                workers: int = 8, somente_novos: bool = False, log=print) -> dict:
    """Consulta do FAP de todas as vigências, empresas e estabelecimentos.

    Rede em ``ThreadPoolExecutor``; banco só no fluxo principal, um commit por
    estabelecimento. Nunca apaga por ausência. Sessão expirada interrompe tudo
    (``expirada=True``); o que já foi gravado fica.
    """
    from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CNPJ_RAIZ, completar_zeros

    conta = {'estabelecimentos': 0, 'com_itens': 0, 'itens_novos': 0, 'itens_atualizados': 0,
             'sem_acesso': 0, 'erros': 0, 'expirada': False}

    if anos is None:
        r = client.listar_anos(svc)
        if not r.ok:
            conta['expirada'] = bool(r.expired)
            conta['erros'] += 0 if r.expired else 1
            return conta
        anos = [int(a) for a in (r.data or [])]
    anos = sorted(set(anos), reverse=True)

    filtro_cnpjs: dict[str, set] = {}
    for c in cnpjs or []:
        c14 = completar_zeros(c, TAMANHO_CNPJ)
        filtro_cnpjs.setdefault(c14[:TAMANHO_CNPJ_RAIZ], set()).add(c14)
    if raizes is None:
        raizes = list(filtro_cnpjs) if filtro_cnpjs else _raizes_do_escritorio(law_firm_id)
    raizes = [completar_zeros(r, TAMANHO_CNPJ_RAIZ) for r in raizes]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for ano in anos:
            for raiz in raizes:
                re = client.listar_estabelecimentos(svc, ano, raiz)
                if not re.ok:
                    if re.expired:
                        conta['expirada'] = True
                        return conta
                    if re.status_code == 403:
                        conta['sem_acesso'] += 1
                    elif re.status_code != 404:
                        conta['erros'] += 1
                    continue
                estabs = list(re.data or [])
                if filtro_cnpjs.get(raiz):
                    estabs = [c for c in estabs if c in filtro_cnpjs[raiz]]
                if not estabs:
                    continue

                gravados = {
                    c: (cal, sit) for c, cal, sit in db.session.query(
                        FapCalculoEstabelecimento.cnpj, FapCalculoEstabelecimento.calculo_atual_id,
                        FapCalculoEstabelecimento.situacao).filter(
                        FapCalculoEstabelecimento.law_firm_id == law_firm_id,
                        FapCalculoEstabelecimento.ano_vigencia == ano,
                        FapCalculoEstabelecimento.cnpj.in_(estabs))
                }
                if somente_novos:
                    estabs = [c for c in estabs
                              if gravados.get(c, (None, None))[1] not in SITUACOES_QUE_GRAVAM_ITENS]

                futuros = {pool.submit(buscar_estabelecimento, svc, ano, c,
                                       gravados.get(c, (None, None))[0]): c for c in estabs}
                for futuro in as_completed(futuros):
                    cnpj = futuros[futuro]
                    try:
                        busca = futuro.result()
                    except Exception as e:
                        conta['erros'] += 1
                        log(f'  ERRO {ano} {cnpj}: {type(e).__name__}')
                        continue
                    if busca.situacao == 'expirada':
                        for f in futuros:
                            f.cancel()
                        conta['expirada'] = True
                        return conta
                    conta['estabelecimentos'] += 1
                    if busca.situacao == 'sem_acesso':
                        conta['sem_acesso'] += 1
                    elif busca.situacao == 'erro':
                        conta['erros'] += 1
                    try:
                        cont = gravar_estabelecimento(law_firm_id, busca)
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        conta['erros'] += 1
                        log(f'  ERRO ao gravar {ano} {cnpj}: {type(e).__name__}')
                        continue
                    conta['itens_novos'] += cont['itens_novos']
                    conta['itens_atualizados'] += cont['itens_atualizados']
                    if busca.situacao == 'ok' and (busca.resumo or {}).get('tem_itens'):
                        conta['com_itens'] += 1
                    if conta['estabelecimentos'] % _LOG_A_CADA == 0:
                        log(f"  {conta['estabelecimentos']} estabelecimentos ({time.time() - t0:.0f}s) — "
                            f"itens novos {conta['itens_novos']}, sem acesso {conta['sem_acesso']}, "
                            f"erros {conta['erros']}")
    return conta
