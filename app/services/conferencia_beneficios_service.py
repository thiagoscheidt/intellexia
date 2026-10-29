"""Conferência dos dados de benefícios contra a base do escritório — fonte única.

Quem chama (o Claude lendo uma petição, um script pela API) diz o que sabe de
cada benefício: número e, se tiver, CPF, NIT, espécie, DIB, DCB, nascimento,
CNPJ, vigência, nome e CAT. O número é procurado na Central de contestações
(``benefits``) e no cálculo FAP (``fap_calculo_itens``) do escritório, e cada
campo informado é comparado, sem IA, com o que a base tem.

Além da comparação, devolve o que só a base sabe: item já excluído do cálculo
(a contestação ganhou), fora do cálculo sincronizado, não contestado, deferido
ou indeferido nas duas instâncias.

Nada do que chega é gravado. Nome só do que já foi revelado (ou cadastrado):
a consulta paga por CPF nunca é disparada daqui.
"""
import json
import re
import unicodedata
from datetime import date, datetime

from sqlalchemy.orm import load_only

from app.models import Benefit, FapCalculoEstabelecimento as Estab, FapCalculoItem as Item, FapVigenciaCnpj, db
from app.utils.cnpj import apenas_digitos, completar_zeros, formatar_cnpj, formatar_cpf

LIMITE = 500
TAMANHO_NB = 10

CAMPOS = ('cpf', 'nit', 'especie', 'dib', 'dcb', 'nascimento', 'cnpj', 'vigencia', 'nome', 'cat')
_ROTULOS = {
    'cpf': 'CPF', 'nit': 'NIT', 'especie': 'espécie', 'dib': 'DIB', 'dcb': 'DCB',
    'nascimento': 'nascimento', 'cnpj': 'CNPJ', 'vigencia': 'vigência', 'nome': 'nome', 'cat': 'CAT',
}
_PALAVRAS_FRACAS = {'de', 'da', 'do', 'das', 'dos', 'e'}


# ── normalização do que chega ────────────────────────────────────────────────

def _data(valor) -> date | None:
    """dd/mm/aaaa, dd.mm.aa, dd-mm-aaaa ou aaaa-mm-dd (com ou sem hora)."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or '').strip()
    try:
        m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', texto)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r'^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})$', texto)
        if m:
            ano = int(m[3])
            if len(m[3]) == 2:
                ano += 2000 if ano <= date.today().year % 100 else 1900
            return date(ano, int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


def _especie(valor) -> str | None:
    """B91, "91", "B-94", "B94 - auxílio-doença acidentário" → B91/B94."""
    texto = str(valor or '').strip()
    m = re.match(r'^\s*b?\s*[-.]?\s*(\d{2})\s*$', texto, re.IGNORECASE) or \
        re.search(r'\bb\s*[-.]?\s*(\d{2})\b', texto, re.IGNORECASE)
    return f'B{m[1]}' if m else None


def _nome_tokens(valor) -> set[str]:
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = texto.encode('ascii', 'ignore').decode('ascii').lower()
    return {t for t in re.split(r'[^a-z]+', texto) if t and t not in _PALAVRAS_FRACAS}


def _br(d: date | None) -> str | None:
    return d.strftime('%d/%m/%Y') if d else None


def _cpf(valor) -> str | None:
    d = completar_zeros(valor, 11)
    return d if d and len(d) == 11 else None


def _entrada(beneficios) -> list:
    if isinstance(beneficios, str):
        try:
            beneficios = json.loads(beneficios)
        except ValueError:
            raise ValueError('"beneficios" tem de ser uma lista (ou o texto JSON de uma lista) de números '
                             'ou de objetos com "numero" e os dados que a petição traz.')
    if isinstance(beneficios, dict):
        beneficios = [beneficios]
    if not isinstance(beneficios, list) or not beneficios:
        raise ValueError('Mande ao menos um benefício: lista de números ou de objetos com "numero".')
    if len(beneficios) > LIMITE:
        raise ValueError(f'No máximo {LIMITE} benefícios por chamada (vieram {len(beneficios)}); '
                         'divida em partes.')
    entradas = []
    for i, b in enumerate(beneficios, start=1):
        if isinstance(b, (str, int)):
            b = {'numero': str(b)}
        if not isinstance(b, dict) or b.get('numero') in (None, ''):
            raise ValueError(f'Benefício {i} sem "numero": cada item é um número ou um objeto com "numero".')
        entradas.append({k: (str(v).strip() if v is not None and not isinstance(v, str) else (v or '').strip())
                         for k, v in b.items() if k == 'numero' or k in CAMPOS})
    return entradas


# ── leitura da base ──────────────────────────────────────────────────────────

def _vigencias_central(b, vig_ano) -> list[int]:
    if vig_ano and str(vig_ano).strip().isdigit():
        return [int(vig_ano)]
    return sorted({int(a) for a in re.findall(r'\d{4}', b.fap_vigencia_years or '')})


def _central(law_firm_id, numeros) -> dict[str, list[dict]]:
    from mcp_server.tools.fap import _parse_topics, _status_instancia_exprs

    s1, s2 = _status_instancia_exprs()
    linhas = (
        db.session.query(Benefit, FapVigenciaCnpj.vigencia_year, FapVigenciaCnpj.employer_cnpj, s1, s2)
        # O benefício tem 8 colunas de texto longo (parecer, justificativa, notas) que não entram aqui.
        .options(load_only(
            Benefit.id, Benefit.benefit_number, Benefit.benefit_type, Benefit.insured_name, Benefit.insured_cpf,
            Benefit.insured_nit, Benefit.insured_date_of_birth, Benefit.employer_cnpj, Benefit.benefit_start_date,
            Benefit.benefit_end_date, Benefit.cat_number, Benefit.fap_vigencia_years,
            Benefit.fap_contestation_topics_json, Benefit.fap_contestation_topic))
        .outerjoin(FapVigenciaCnpj, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
        .filter(Benefit.law_firm_id == law_firm_id, Benefit.benefit_number.in_(numeros))
        .order_by(Benefit.id).all()
    )
    out: dict[str, list[dict]] = {}
    for b, vig_ano, vig_cnpj, st1, st2 in linhas:
        cnpj = completar_zeros(vig_cnpj or b.employer_cnpj, 14)
        out.setdefault(apenas_digitos(b.benefit_number), []).append({
            'id': b.id,
            'vigencias': _vigencias_central(b, vig_ano),
            'cnpj': cnpj,
            'especie': (b.benefit_type or '').upper() or None,
            'cpf': _cpf(b.insured_cpf),
            'nit': apenas_digitos(b.insured_nit) or None,
            'nascimento': b.insured_date_of_birth,
            'dib': b.benefit_start_date,
            'dcb': b.benefit_end_date,
            'cat': apenas_digitos(b.cat_number) or None,
            'nome': b.insured_name,
            'status_1a_instancia': st1,
            'status_2a_instancia': st2,
            'topicos': _parse_topics(b),
        })
    return out


def _calculo(law_firm_id, numeros) -> dict[str, list[dict]]:
    from app.services import fap_calculo_query_service as calc

    q = Item.query.filter(Item.law_firm_id == law_firm_id, Item.identificador.in_(numeros), Item.tipo != 'CAT')
    out: dict[str, list[dict]] = {}
    for d in calc.todos(q, law_firm_id=law_firm_id):
        out.setdefault(d['identificador'], []).append({
            'vigencia': d['ano_vigencia'],
            'cnpj': d['cnpj'],
            'empresa': d['empresa_nome'],
            'especie': d['tipo'],
            'cpf': _cpf(d['cpf']),
            'nit': apenas_digitos(d['nit']) or None,
            'nascimento': d['data_nascimento'],
            'dib': d['data_inicio'],
            'dcb': d['data_cessacao'],
            'situacao': 'excluido' if d['estado_atual'] == 'EXCLUIDO' else 'conta',
            'contestado': d['contestado'],
            'ausente_no_calculo_atual': d['ausente_no_calculo_atual'],
            'cnpj_original': d['cnpj_original'],
            'cnpj_atribuido': d['cnpj_atribuido'],
            'protocolo': d['protocolo'],
        })
    return out


def _estabelecimentos_sincronizados(law_firm_id, pares) -> set[tuple[int, str]]:
    """(vigência, CNPJ) cujo cálculo foi lido do portal com itens — só nesses a
    ausência de um número quer dizer alguma coisa ("nunca apagar por ausência")."""
    if not pares:
        return set()
    linhas = Estab.query.filter(
        Estab.law_firm_id == law_firm_id, Estab.situacao == 'ok', Estab.tem_itens.is_(True),
        Estab.cnpj.in_({c for _, c in pares}), Estab.ano_vigencia.in_({v for v, _ in pares}),
    ).with_entities(Estab.ano_vigencia, Estab.cnpj).all()
    return {(v, c) for v, c in linhas} & pares


# ── comparação ───────────────────────────────────────────────────────────────

def _valores_base(campo, central, calculo, nomes) -> set:
    registros = central + calculo
    if campo == 'vigencia':
        return {v for r in central for v in r['vigencias']} | {r['vigencia'] for r in calculo}
    if campo == 'cat':
        return {r['cat'] for r in central if r['cat']}
    if campo == 'nome':
        return {n for n in nomes if n}
    return {r[campo] for r in registros if r.get(campo)}


def _exibir(campo, valor) -> str:
    if campo == 'cpf':
        return formatar_cpf(valor)
    if campo == 'cnpj':
        return formatar_cnpj(valor)
    if isinstance(valor, date):
        return _br(valor)
    return str(valor)


def _comparar(campo, bruto, base: set):
    """(confere?, valor exibido da petição) ou (None, motivo) quando não dá para comparar."""
    if campo in ('dib', 'dcb', 'nascimento'):
        d = _data(bruto)
        return (d in base, bruto) if d else (None, f'data não reconhecida ("{bruto}")')
    if campo == 'especie':
        e = _especie(bruto)
        return (e in base, e) if e else (None, f'espécie não reconhecida ("{bruto}")')
    if campo == 'cpf':
        c = _cpf(bruto)
        return (c in base, bruto) if c else (None, f'CPF com {len(apenas_digitos(bruto))} dígitos')
    if campo == 'cnpj':
        d = apenas_digitos(bruto)
        if len(d) == 14:
            return d in base, bruto
        if len(d) == 8:
            return d in {c[:8] for c in base}, bruto
        return None, f'CNPJ com {len(d)} dígitos (esperado 14, ou 8 da raiz)'
    if campo == 'vigencia':
        d = apenas_digitos(bruto)
        return (int(d) in base, bruto) if len(d) == 4 else (None, f'vigência não reconhecida ("{bruto}")')
    if campo == 'nome':
        pet = _nome_tokens(bruto)
        if not pet:
            return None, 'nome vazio'
        return any(pet <= _nome_tokens(n) or _nome_tokens(n) <= pet for n in base), bruto
    d = apenas_digitos(bruto)  # nit, cat
    return (d in base, bruto) if d else (None, f'{_ROTULOS[campo]} sem dígitos')


def _alertas(central, calculo, sincronizados, vigencia_pedida) -> list[dict]:
    alertas = []
    if vigencia_pedida is not None:
        so_da_vigencia = [r for r in calculo if r['vigencia'] == vigencia_pedida]
        central_vig = [r for r in central if vigencia_pedida in r['vigencias']]
        if so_da_vigencia or central_vig:
            calculo, central = so_da_vigencia, central_vig

    for r in calculo:
        vig = r['vigencia']
        if r['situacao'] == 'excluido':
            alertas.append({'codigo': 'excluido_do_calculo', 'vigencia': vig, 'mensagem': (
                f'Já excluído do cálculo FAP {vig} (estabelecimento {formatar_cnpj(r["cnpj"])}) no recálculo — '
                'a contestação ganhou; contestar de novo não muda o FAP.')})
        if r['ausente_no_calculo_atual']:
            alertas.append({'codigo': 'ausente_no_calculo_atual', 'vigencia': vig, 'mensagem': (
                f'Não aparece no cálculo atual da vigência {vig}: saiu num recálculo mais novo.')})
        if not r['contestado']:
            alertas.append({'codigo': 'nao_contestado', 'vigencia': vig, 'mensagem': (
                f'Está no cálculo FAP {vig}, mas não foi contestado administrativamente nessa vigência.')})
        if r['cnpj_original'] and r['cnpj_atribuido'] and r['cnpj_original'] != r['cnpj_atribuido']:
            alertas.append({'codigo': 'cnpj_atribuido_diferente', 'vigencia': vig, 'mensagem': (
                f'No cálculo {vig} o benefício foi atribuído ao CNPJ {formatar_cnpj(r["cnpj_atribuido"])}, '
                f'mas o original é {formatar_cnpj(r["cnpj_original"])} — possível erro de estabelecimento.')})

    no_calculo = {(r['vigencia'], r['cnpj']) for r in calculo}
    for r in central:
        for vig in r['vigencias']:
            par = (vig, r['cnpj'])
            if r['cnpj'] and par in sincronizados and par not in no_calculo:
                alertas.append({'codigo': 'fora_do_calculo', 'vigencia': vig, 'mensagem': (
                    f'Contestado na vigência {vig}, mas não está no cálculo FAP desse estabelecimento '
                    f'({formatar_cnpj(r["cnpj"])}) lido do portal — não pesa no FAP dessa vigência.')})
        st1, st2 = r['status_1a_instancia'], r['status_2a_instancia']
        vigs = ', '.join(str(v) for v in r['vigencias']) or 'sem vigência'
        if st1 == 'deferido' or st2 == 'deferido':
            instancia = '1ª' if st1 == 'deferido' else '2ª'
            alertas.append({'codigo': 'deferido', 'vigencia': (r['vigencias'] or [None])[0], 'mensagem': (
                f'Já deferido na {instancia} instância administrativa (vigência {vigs}).')})
        elif st1 == 'indeferido' and st2 == 'indeferido':
            alertas.append({'codigo': 'indeferido_nas_duas_instancias', 'vigencia': (r['vigencias'] or [None])[0],
                            'mensagem': f'Indeferido nas duas instâncias administrativas (vigência {vigs}).'})
    return alertas


def _registro_central(r) -> dict:
    return {
        'id': r['id'], 'vigencias': [str(v) for v in r['vigencias']],
        'cnpj': formatar_cnpj(r['cnpj']) if r['cnpj'] else None, 'especie': r['especie'],
        'cpf': formatar_cpf(r['cpf']) if r['cpf'] else None, 'nit': r['nit'],
        'nascimento': _br(r['nascimento']), 'dib': _br(r['dib']), 'dcb': _br(r['dcb']), 'cat': r['cat'],
        'status_1a_instancia': r['status_1a_instancia'], 'status_2a_instancia': r['status_2a_instancia'],
        'topicos': r['topicos'],
    }


def _registro_calculo(r) -> dict:
    return {
        'vigencia': str(r['vigencia']), 'cnpj': formatar_cnpj(r['cnpj']), 'empresa': r['empresa'],
        'especie': r['especie'], 'cpf': formatar_cpf(r['cpf']) if r['cpf'] else None, 'nit': r['nit'],
        'nascimento': _br(r['nascimento']), 'dib': _br(r['dib']), 'dcb': _br(r['dcb']),
        'situacao': r['situacao'], 'contestado': r['contestado'],
        'ausente_no_calculo_atual': r['ausente_no_calculo_atual'], 'protocolo': r['protocolo'],
    }


def conferir(law_firm_id: int, beneficios) -> dict:
    """Cada benefício informado contra a Central e o cálculo FAP do escritório.

    ``beneficios``: lista (ou texto JSON de uma lista) de números ou de objetos
    com ``numero`` e qualquer um de ``CAMPOS``. Entrada inválida → ``ValueError``.
    """
    from app.services import segurado_nome_service

    entradas = _entrada(beneficios)
    numeros = {apenas_digitos(e['numero']) for e in entradas} - {''}
    central = _central(law_firm_id, numeros) if numeros else {}
    calculo = _calculo(law_firm_id, numeros) if numeros else {}
    pares = {(v, r['cnpj']) for regs in central.values() for r in regs for v in r['vigencias'] if r['cnpj']}
    sincronizados = _estabelecimentos_sincronizados(law_firm_id, pares)
    cpfs = {r['cpf'] for regs in (*central.values(), *calculo.values()) for r in regs if r['cpf']}
    revelados = segurado_nome_service.nomes_conhecidos(law_firm_id, cpfs)

    itens = []
    for posicao, e in enumerate(entradas, start=1):
        numero = apenas_digitos(e['numero'])
        item = {'posicao': posicao, 'numero': e['numero'], 'numero_normalizado': numero or None,
                'situacao': 'confere', 'divergencias': [], 'alertas': [], 'conferidos': [],
                'nao_conferidos': [], 'segurado_nome': None, 'central': [], 'calculo': []}
        itens.append(item)
        if not numero:
            item['situacao'] = 'invalido'
            item['alertas'].append({'codigo': 'numero_invalido', 'vigencia': None,
                                    'mensagem': f'"{e["numero"]}" não tem dígitos de número de benefício.'})
            continue
        regs_central, regs_calculo = central.get(numero, []), calculo.get(numero, [])
        if not regs_central and not regs_calculo:
            item['situacao'] = 'nao_encontrado'
            mensagem = 'Não está na Central de contestações nem no cálculo FAP do escritório — confira a digitação.'
            if len(numero) != TAMANHO_NB:
                mensagem += f' O número do benefício tem {TAMANHO_NB} dígitos; este tem {len(numero)}.'
            item['alertas'].append({'codigo': 'nao_encontrado', 'vigencia': None, 'mensagem': mensagem})
            continue

        nomes = {r['nome'] for r in regs_central if r['nome']}
        for r in regs_central + regs_calculo:
            reg = revelados.get(r['cpf'] or '')
            if reg and reg.get('status') == 'encontrado' and reg.get('nome'):
                nomes.add(reg['nome'])
        item['segurado_nome'] = sorted(nomes)[0] if nomes else None

        for campo in CAMPOS:
            bruto = e.get(campo)
            if not bruto:
                continue
            base = _valores_base(campo, regs_central, regs_calculo, nomes)
            if not base:
                item['nao_conferidos'].append({'campo': campo, 'motivo': f'a base não tem {_ROTULOS[campo]}'})
                continue
            confere, exibido = _comparar(campo, bruto, base)
            if confere is None:
                item['nao_conferidos'].append({'campo': campo, 'motivo': exibido})
                continue
            item['conferidos'].append(campo)
            if not confere:
                item['divergencias'].append({
                    'campo': campo, 'peticao': exibido,
                    'base': sorted(_exibir(campo, v) for v in base),
                })
        if item['divergencias']:
            item['situacao'] = 'divergente'

        vig = apenas_digitos(e.get('vigencia'))
        item['alertas'] = _alertas(regs_central, regs_calculo, sincronizados,
                                   int(vig) if len(vig) == 4 else None)
        item['central'] = [_registro_central(r) for r in regs_central]
        item['calculo'] = [_registro_calculo(r) for r in regs_calculo]

    contar = lambda s: sum(1 for i in itens if i['situacao'] == s)  # noqa: E731
    return {
        'total': len(itens),
        'conferem': contar('confere'),
        'com_divergencia': contar('divergente'),
        'nao_encontrados': contar('nao_encontrado'),
        'invalidos': contar('invalido'),
        'com_alerta': sum(1 for i in itens if i['alertas'] and i['situacao'] != 'nao_encontrado'),
        'itens': itens,
        'dica': ('Divergência é dado da petição que não bate com a base (mostre os dois valores). '
                 '"nao_conferidos" é o que não deu para comparar — não trate como erro. Os alertas '
                 'vêm da base (cálculo FAP e Central) e valem mesmo quando os dados conferem. O nome '
                 'só existe se já foi revelado; não chame revelar_nome_segurado em lote.'),
    }
