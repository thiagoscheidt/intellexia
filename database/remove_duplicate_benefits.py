"""
Mescla benefícios FAP duplicados — o mesmo NB, do mesmo CNPJ, na mesma vigência.

As duplicatas vieram de dois defeitos já corrigidos no processamento de
relatórios (`fap_contestation_judgment_report_service`):

- até 11/08/2026, linha sem `fap_vigencia_years` não era reconhecida pela
  importação seguinte, que inseria outra;
- até 23/09/2026, dois relatórios com os mesmos NBs processados ao mesmo tempo
  (a linha de 1ª e a de 2ª instância do portal baixam o mesmo PDF) inseriam
  cada um a sua — ex.: relatórios 33389 e 33390, 27/08/2026.

Depois da duplicata, todo relatório seguinte atualizava só a linha de menor id;
a outra ficava congelada. Por isso a linha que fica é a MAIS ADIANTADA, não a
mais antiga: 2ª instância (decidida > em análise > nada), depois 1ª instância,
depois a data do documento FAP mais recente (a mesma régua que o processamento
usa para decidir se um relatório sobrescreve o benefício), depois a última
atualização. Da duplicata aproveita-se:

- campo vazio na sobrevivente é preenchido com o da duplicata;
- vigências são unidas;
- histórico de origem (arquivos FAP) e histórico manual vão para a sobrevivente;
- decisões por análise (`benefit_contestation_decisions`) só vão quando a
  sobrevivente não tem nenhuma naquela instância — se tem, a dela é a versão
  mais nova do mesmo documento.

Linha sem vigência ou sem CNPJ entra no grupo só quando há um único candidato
compatível; havendo mais de um, ela é listada como ambígua e não é tocada.

Uso:
    uv run python database/remove_duplicate_benefits.py                 # só lista
    uv run python database/remove_duplicate_benefits.py --apply         # mescla
    uv run python database/remove_duplicate_benefits.py --law-firm-id 1 [--apply]
"""

import argparse
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.models import (  # noqa: E402
    Benefit,
    BenefitContestationDecision,
    BenefitFapSourceHistory,
    BenefitManualHistory,
    db,
)

# Colunas de dado copiadas da duplicata quando vazias na sobrevivente.
CAMPOS_COMPLEMENTARES = (
    'client_id', 'fap_vigencia_cnpj_id', 'benefit_type', 'insured_name', 'insured_nit',
    'insured_cpf', 'insured_date_of_birth', 'employer_cnpj', 'employer_name',
    'benefit_start_date', 'benefit_end_date', 'initial_monthly_benefit', 'total_paid',
    'accident_date', 'accident_company_name', 'accident_summary', 'cat_number', 'bo_number',
    'request_type', 'notes', 'first_instance_status', 'first_instance_status_raw',
    'first_instance_justification', 'first_instance_opinion', 'second_instance_status',
    'second_instance_status_raw', 'second_instance_justification', 'second_instance_opinion',
    'fap_contestation_topic', 'fap_contestation_topics_json', 'justification', 'opinion',
)



def peso_status(valor) -> int:
    """Quanto maior, mais adiantada a instância.

    O banco tem os dois vocabulários: o código normalizado ('rejected',
    'analyzing') e o rótulo em português que a importação grava ('Indeferido',
    'Em análise', 'Deferimento Parcial'). Por palavra-chave e sem acento, como o
    `_map_status` do serviço — "indeferido" contém "deferido", mas os dois são
    decisão, então a ordem não importa aqui.
    """
    texto = unicodedata.normalize('NFKD', str(valor or '')).encode('ascii', 'ignore').decode().lower()
    if not texto.strip():
        return 0
    if any(p in texto for p in ('defer', 'approved', 'rejected', 'prejudic')):
        return 3
    if any(p in texto for p in ('analis', 'analy', 'review')):
        return 2
    if 'pend' in texto:
        return 1
    return 2  # status desconhecido mas preenchido: algo aconteceu na instância


def _digitos(valor) -> str:
    return re.sub(r'\D', '', str(valor or ''))


def _vigencias(valor) -> frozenset:
    return frozenset(p.strip() for p in str(valor or '').split(',') if p.strip())


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _referencias(ids) -> dict:
    """Data do documento FAP mais recente de cada benefício."""
    data_doc = func.coalesce(
        BenefitFapSourceHistory.publication_datetime,
        BenefitFapSourceHistory.transmission_datetime,
    )
    linhas = (
        db.session.query(BenefitFapSourceHistory.benefit_id, func.max(data_doc))
        .filter(BenefitFapSourceHistory.benefit_id.in_(ids))
        .group_by(BenefitFapSourceHistory.benefit_id)
        .all()
    )
    return dict(linhas)


def chave_de_adiantamento(beneficio, referencia):
    """Ordena do menos para o mais adiantado; o último da lista fica."""
    return (
        peso_status(beneficio.second_instance_status),
        peso_status(beneficio.first_instance_status),
        referencia or datetime.min,
        beneficio.updated_at or datetime.min,
        -beneficio.id,  # empate total: fica o de menor id
    )


def agrupar(linhas: list) -> tuple[list, list]:
    """Separa as linhas de um mesmo NB em grupos de duplicatas.

    Devolve (grupos com 2+ linhas, linhas ambíguas).
    """
    definidas: dict = {}
    soltas = []
    for b in linhas:
        cnpj, vig = _digitos(b.employer_cnpj), _vigencias(b.fap_vigencia_years)
        if cnpj and vig:
            definidas.setdefault((cnpj, vig), []).append(b)
        else:
            soltas.append(b)

    ambiguas = []
    sem_par: dict = {}
    for b in soltas:
        cnpj, vig = _digitos(b.employer_cnpj), _vigencias(b.fap_vigencia_years)
        compativeis = [
            k for k in definidas
            if (not cnpj or k[0] == cnpj) and (not vig or k[1] == vig)
        ]
        if len(compativeis) == 1:
            definidas[compativeis[0]].append(b)
        elif not compativeis:
            sem_par.setdefault((cnpj, vig), []).append(b)
        else:
            ambiguas.append(b)

    grupos = [g for g in list(definidas.values()) + list(sem_par.values()) if len(g) > 1]
    return grupos, ambiguas


def mesclar(grupo: list, referencias: dict) -> tuple:
    """Mescla o grupo na linha mais adiantada. Não faz commit."""
    ordenados = sorted(grupo, key=lambda b: chave_de_adiantamento(b, referencias.get(b.id)))
    fica = ordenados[-1]
    saem = list(reversed(ordenados[:-1]))  # da mais adiantada para a menos

    for b in saem:
        for campo in CAMPOS_COMPLEMENTARES:
            if _vazio(getattr(fica, campo)) and not _vazio(getattr(b, campo)):
                setattr(fica, campo, getattr(b, campo))

    anos = set(_vigencias(fica.fap_vigencia_years))
    for b in saem:
        anos |= _vigencias(b.fap_vigencia_years)
    if anos:
        fica.fap_vigencia_years = ','.join(sorted(anos))

    ids_saem = [b.id for b in saem]

    relatorios_da_que_fica = {
        h.report_id for h in
        BenefitFapSourceHistory.query.filter_by(benefit_id=fica.id).all()
    }
    for h in BenefitFapSourceHistory.query.filter(
        BenefitFapSourceHistory.benefit_id.in_(ids_saem)
    ).all():
        if h.report_id in relatorios_da_que_fica:
            db.session.delete(h)
        else:
            h.benefit_id = fica.id
            relatorios_da_que_fica.add(h.report_id)

    # Instância em que a sobrevivente já tem análise fica com a dela. Nas outras,
    # a instância vem inteira da duplicata mais adiantada que a tenha —
    # misturar análises de duas cópias repetiria a mesma sequência.
    instancias_ocupadas = {
        d.instancia for d in
        BenefitContestationDecision.query.filter_by(benefit_id=fica.id).all()
    }
    decisoes_movidas = 0
    for b in saem:
        decisoes = BenefitContestationDecision.query.filter_by(benefit_id=b.id).all()
        trazidas = set()
        for d in decisoes:
            if d.instancia in instancias_ocupadas:
                db.session.delete(d)
                continue
            d.benefit_id = fica.id
            trazidas.add(d.instancia)
            decisoes_movidas += 1
        instancias_ocupadas |= trazidas

    BenefitManualHistory.query.filter(
        BenefitManualHistory.benefit_id.in_(ids_saem)
    ).update({'benefit_id': fica.id}, synchronize_session=False)

    db.session.flush()
    for b in saem:
        db.session.expire(b, ['fap_source_history', 'manual_history', 'contestation_decisions'])
        db.session.delete(b)

    return fica, saem, decisoes_movidas


def _descrever(b, referencia) -> str:
    doc = f'{referencia:%d/%m/%Y}' if referencia else '-'
    return (f'#{b.id} criado {b.created_at:%d/%m/%Y %H:%M} | '
            f'1ª={b.first_instance_status or "-"} 2ª={b.second_instance_status or "-"} | '
            f'doc FAP={doc}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('--apply', action='store_true', help='Grava a mesclagem (sem isso, só lista)')
    parser.add_argument('--law-firm-id', type=int, default=None)
    args = parser.parse_args()

    with app.app_context():
        repetidos = db.session.query(Benefit.law_firm_id, Benefit.benefit_number).group_by(
            Benefit.law_firm_id, Benefit.benefit_number
        ).having(func.count(Benefit.id) > 1)
        if args.law_firm_id:
            repetidos = repetidos.filter(Benefit.law_firm_id == args.law_firm_id)
        repetidos = repetidos.all()

        print(f'{len(repetidos)} NB(s) com mais de uma linha (inclui vigências diferentes, que são legítimas).')
        total_grupos = total_removidas = 0
        ambiguas_total = []

        for law_firm_id, numero in repetidos:
            linhas = (
                Benefit.query.filter_by(law_firm_id=law_firm_id, benefit_number=numero)
                .order_by(Benefit.id).all()
            )
            grupos, ambiguas = agrupar(linhas)
            ambiguas_total.extend(ambiguas)
            if not grupos:
                continue

            for grupo in grupos:
                referencias = _referencias([b.id for b in grupo])
                ordenados = sorted(grupo, key=lambda b: chave_de_adiantamento(b, referencias.get(b.id)))
                fica = ordenados[-1]
                print(f'\nNB {numero} (escritório {law_firm_id}, CNPJ {fica.employer_cnpj or "-"}, '
                      f'vigência {fica.fap_vigencia_years or "-"})')
                print(f'  fica  {_descrever(fica, referencias.get(fica.id))}')
                for b in reversed(ordenados[:-1]):
                    print(f'  sai   {_descrever(b, referencias.get(b.id))}')

                total_grupos += 1
                total_removidas += len(grupo) - 1

                if args.apply:
                    try:
                        _, _, movidas = mesclar(grupo, referencias)
                        db.session.commit()
                        print(f'  ✓ mesclado ({movidas} decisão(ões) trazida(s) da duplicata)')
                    except Exception as exc:
                        db.session.rollback()
                        print(f'  ✗ ERRO — nada gravado neste grupo: {exc}')

        if ambiguas_total:
            print(f'\n{len(ambiguas_total)} linha(s) sem vigência/CNPJ com mais de um grupo possível '
                  f'(não tocadas, conferir à mão):')
            for b in ambiguas_total:
                print(f'  #{b.id} NB {b.benefit_number} escritório {b.law_firm_id}')

        print('\n' + '=' * 62)
        verbo = 'mesclados' if args.apply else 'a mesclar (rode com --apply para gravar)'
        print(f'{total_grupos} grupo(s) {verbo}; {total_removidas} linha(s) duplicada(s).')


if __name__ == '__main__':
    main()
