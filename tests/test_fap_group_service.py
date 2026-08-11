"""
Testes do serviço de grupos empresariais do FAP.

Roda contra um SQLite descartável, NUNCA contra o banco configurado: o teste
grava dados, e o `.env` do checkout pode apontar para uma base real.

Executar:
    uv run python tests/test_fap_group_service.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

# Banco descartável — trocado ANTES de qualquer uso do engine.
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_fap_groups.db')
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'

from app.models import db  # noqa: E402

# O main.py já criou o engine no import; reconstrói apontando para o descartável.
app.extensions.pop('sqlalchemy', None)
try:
    db._app_engines.pop(app, None)
except Exception:
    pass
db.init_app(app)

from app.services import fap_group_service as svc  # noqa: E402

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def main():
    with app.app_context():
        from datetime import datetime
        from app.models import (
            LawFirm, FapCompanyGroup, FapWebContestacao, Benefit,
        )

        assert DB_FILE in str(db.engine.url), 'ABORTADO: engine fora do sandbox'
        db.metadata.create_all(db.engine, tables=[
            LawFirm.__table__, FapCompanyGroup.__table__,
            FapWebContestacao.__table__, Benefit.__table__,
        ])
        db.session.add(LawFirm(id=1, name='Escritório A', cnpj='00000000000191'))
        db.session.add(LawFirm(id=2, name='Escritório B', cnpj='00000000000272'))
        db.session.commit()

        # ── normalização da chave ────────────────────────────────────────
        print('\n1. normalize_group_key')
        check('acento não cria grupo novo',
              svc.normalize_group_key('ÁGUIA SISTEMAS') == svc.normalize_group_key('Águia Sistemas'))
        check('caixa não cria grupo novo',
              svc.normalize_group_key('adservi') == svc.normalize_group_key('ADSERVI'))
        check('espaço duplo e sobra colapsam',
              svc.normalize_group_key('  ADSERVI   MULTI  ') == 'ADSERVI MULTI',
              repr(svc.normalize_group_key('  ADSERVI   MULTI  ')))
        check('vazio vira chave vazia', svc.normalize_group_key('   ') == '')

        # ── raiz do CNPJ em qualquer formato ─────────────────────────────
        print('\n2. cnpj_root')
        for entrada, esperado in [
            ('60.659.463/', '60659463'),      # como vem na planilha
            ('01.007.510/0001-53', '01007510'),
            ('06261771000380', '06261771'),
            ('11312620', '11312620'),
        ]:
            check(f'{entrada!r} → {esperado}', svc.cnpj_root(entrada) == esperado,
                  svc.cnpj_root(entrada))

        # ── cadastro ─────────────────────────────────────────────────────
        print('\n3. assign_group')
        acao, _ = svc.assign_group(1, '11312620', 'ADSERVI', svc.ORIGEM_PLANILHA)
        check('primeiro cadastro = criado', acao == 'criado', acao)
        db.session.commit()

        acao, _ = svc.assign_group(1, '11312620', 'ADSERVI', svc.ORIGEM_PLANILHA)
        check('mesmo valor = inalterado', acao == 'inalterado', acao)

        acao, _ = svc.assign_group(1, '11312620', 'ADSERVI GRUPO', svc.ORIGEM_PLANILHA)
        check('nome diferente = alterado', acao == 'alterado', acao)
        db.session.commit()
        svc.assign_group(1, '11312620', 'ADSERVI', svc.ORIGEM_PLANILHA)
        db.session.commit()

        erro = None
        try:
            svc.assign_group(1, '123', 'X')
        except ValueError as e:
            erro = str(e)
        check('CNPJ raiz curto é recusado', erro is not None, erro)

        erro = None
        try:
            svc.assign_group(1, '11312620', '   ')
        except ValueError as e:
            erro = str(e)
        check('grupo em branco é recusado', erro is not None, erro)

        # grupo ADSERVI com 3 raízes; ACHE com 1; uma raiz sem grupo
        for raiz in ('11312655', '01007510'):
            svc.assign_group(1, raiz, 'Adservi', svc.ORIGEM_PLANILHA)  # grafia diferente
        svc.assign_group(1, '60659463', 'ACHE', svc.ORIGEM_PLANILHA)
        # outro escritório, mesmo nome de grupo e mesma raiz
        svc.assign_group(2, '99999999', 'ADSERVI', svc.ORIGEM_MANUAL)
        db.session.commit()

        # ── opções e resolução ───────────────────────────────────────────
        print('\n4. group_options / roots_for_group')
        opcoes = svc.group_options(1)
        check('2 grupos no escritório 1', len(opcoes) == 2, [o['nome'] for o in opcoes])
        adservi = next((o for o in opcoes if o['chave'] == 'ADSERVI'), None)
        check('ADSERVI agrega as 3 raízes apesar da grafia diferente',
              adservi and adservi['total_empresas'] == 3,
              adservi['total_empresas'] if adservi else None)
        check('ordenado por nome', [o['nome'] for o in opcoes] == sorted(
            [o['nome'] for o in opcoes], key=str.lower), [o['nome'] for o in opcoes])

        raizes = sorted(svc.roots_for_group(1, 'adservi'))  # busca aceita qualquer grafia
        check('roots_for_group é insensível à grafia',
              raizes == ['01007510', '11312620', '11312655'], raizes)
        check('grupo inexistente devolve vazio', svc.roots_for_group(1, 'NAO EXISTE') == [])

        # ── filtro sobre coluna de raiz limpa (FapWebContestacao) ────────
        print('\n5. apply_group_filter em coluna de raiz (cnpj_raiz)')
        for i, raiz in enumerate(['11312620', '11312655', '01007510', '60659463', '77777777'], start=1):
            db.session.add(FapWebContestacao(
                id=i, law_firm_id=1, contestacao_id=1000 + i,
                cnpj=(raiz + '000100'), cnpj_raiz=raiz, ano_vigencia=2024,
            ))
        db.session.commit()

        def filtrar_contestacoes(grupo):
            q = svc.apply_group_filter(
                FapWebContestacao.query.filter_by(law_firm_id=1), 1, grupo,
                FapWebContestacao.cnpj_raiz, coluna_e_raiz=True)
            return sorted(r.cnpj_raiz for r in q.all())

        check('ADSERVI traz as 3 raízes do grupo',
              filtrar_contestacoes('ADSERVI') == ['01007510', '11312620', '11312655'],
              filtrar_contestacoes('ADSERVI'))
        check('ACHE traz só a dele', filtrar_contestacoes('ACHE') == ['60659463'])
        check('filtro vazio não filtra', len(filtrar_contestacoes('')) == 5)
        check('grupo inexistente filtra para vazio', filtrar_contestacoes('NAO EXISTE') == [])
        check('sem grupo traz só a raiz não mapeada',
              filtrar_contestacoes(svc.SEM_GRUPO) == ['77777777'],
              filtrar_contestacoes(svc.SEM_GRUPO))

        # ── filtro sobre employer_cnpj (mascarado e só dígitos) ──────────
        print('\n6. apply_group_filter em coluna employer_cnpj')
        amostras = [
            (1, '11.312.620/0001-53'),   # mascarado, grupo ADSERVI
            (2, '01007510000153'),       # só dígitos, grupo ADSERVI
            (3, '60.659.463/0001-04'),   # ACHE
            (4, '77777777000100'),       # sem grupo
            (5, None),                   # sem CNPJ nenhum
        ]
        for bid, cnpj in amostras:
            db.session.add(Benefit(
                id=bid, law_firm_id=1, benefit_number=f'B{bid}',
                employer_cnpj=cnpj, created_at=datetime(2026, 1, 1),
            ))
        db.session.commit()

        def filtrar_beneficios(grupo):
            q = svc.apply_group_filter(
                Benefit.query.filter_by(law_firm_id=1), 1, grupo, Benefit.employer_cnpj)
            return sorted(b.id for b in q.all())

        check('ADSERVI casa mascarado e só-dígitos juntos',
              filtrar_beneficios('ADSERVI') == [1, 2], filtrar_beneficios('ADSERVI'))
        check('ACHE traz só o dele', filtrar_beneficios('ACHE') == [3])
        check('sem grupo traz não-mapeado E sem CNPJ',
              filtrar_beneficios(svc.SEM_GRUPO) == [4, 5], filtrar_beneficios(svc.SEM_GRUPO))

        # ── multi-tenancy ────────────────────────────────────────────────
        print('\n7. multi-tenancy')
        check('escritório 2 vê só o próprio grupo',
              [o['chave'] for o in svc.group_options(2)] == ['ADSERVI'])
        check('ADSERVI do escritório 2 tem outra raiz',
              svc.roots_for_group(2, 'ADSERVI') == ['99999999'],
              svc.roots_for_group(2, 'ADSERVI'))
        check('raiz do escritório 1 não vaza para o 2',
              '11312620' not in svc.roots_for_group(2, 'ADSERVI'))

        # ── remoção ──────────────────────────────────────────────────────
        print('\n8. remove_group')
        check('remove existente', svc.remove_group(1, '01007510') is True)
        db.session.commit()
        check('grupo perde a raiz removida',
              sorted(svc.roots_for_group(1, 'ADSERVI')) == ['11312620', '11312655'],
              svc.roots_for_group(1, 'ADSERVI'))
        check('remover inexistente devolve False', svc.remove_group(1, '12121212') is False)

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
