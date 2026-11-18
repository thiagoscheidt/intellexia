#!/usr/bin/env python3
"""
Print da Consulta do FAP (`fap_portal_print_service`, `print_consulta_fap`).

1. Pedido: só o escritório da sessão do portal, CNPJ válido e da base (cálculo
   FAP ou raiz do Painel FAP, mesmo sem os zeros da frente), tela, número e
   cálculo conferidos.
2. Captura com o navegador substituído: imagens vão para a pasta do escritório,
   ficha .json ao lado, erro do portal vira status, imagem fora da pasta
   temporária é ignorada, trava de um navegador por vez, poda dos antigos.
3. Subprocesso de verdade sem FAP_AUTH_JSON: responde "sessao_expirada" em JSON.
4. Ferramenta e rota da imagem (dono 200, outro escritório 404, nome inválido 404).

Não abre o portal. Escritórios descartáveis, removidos no fim.

    uv run python tests/test_fap_portal_print.py
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, FapCalculoEstabelecimento, FapCompany, LawFirm, User, UserPageVisit
from app.services import fap_portal_print_service as svc

CNPJS_FIRMA = ('00000000002373', '00000000002454')
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _com_dv(base12: str) -> str:
    d = base12
    for pesos in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        resto = sum(int(x) * p for x, p in zip(d, pesos)) % 11
        d += str(0 if resto < 2 else 11 - resto)
    return d


EST_CALCULO = _com_dv('112223330001')          # estabelecimento do cálculo FAP
EST_RAIZ = _com_dv('004828400003')             # raiz 00482840, gravada no Painel como "482840"
EST_FORA = _com_dv('998877660001')             # não é do escritório

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82')


def _cleanup():
    for cnpj in CNPJS_FIRMA:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm.id).delete()
        FapCompany.query.filter_by(law_firm_id=firm.id).delete()
        for u in User.query.filter_by(law_firm_id=firm.id).all():
            UserPageVisit.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        shutil.rmtree(svc.DIR_PRINTS / str(firm.id), ignore_errors=True)
        db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    usuarios = []
    for i, cnpj in enumerate(CNPJS_FIRMA):
        firm = LawFirm(name=f'Escritório Teste Print FAP {i}', cnpj=cnpj)
        db.session.add(firm)
        db.session.flush()
        u = User(law_firm_id=firm.id, name=f'adv {i}', role='admin', is_active=True,
                 email=f'adv{i}__test_print_fap@example.com')
        u.set_password('x')
        db.session.add(u)
        db.session.flush()
        usuarios.append(u)
    a = usuarios[0].law_firm_id
    db.session.add(FapCalculoEstabelecimento(law_firm_id=a, ano_vigencia=2026, cnpj=EST_CALCULO,
                                             cnpj_raiz=EST_CALCULO[:8], situacao='ok'))
    db.session.add(FapCompany(law_firm_id=a, cnpj='482840', nome='EMPRESA SÓ NO PAINEL', synced_at=datetime.utcnow()))
    db.session.commit()
    return usuarios


def _recusa(nome, status, *args, **kw):
    try:
        svc.validar(*args, **kw)
        check(nome, False, 'aceitou')
    except svc.PrintFapIndisponivel as e:
        check(nome, e.status_http == status, f'{e.status_http} {e}')


def test_pedido(a, b):
    print('\n1. Pedido')
    os.environ['FAP_SYNC_LAW_FIRM_ID'] = str(a)
    _recusa('outro escritório: 403', 403, b, EST_CALCULO, 2026, 'calculo')
    _recusa('CNPJ com DV inválido: 400', 400, a, EST_CALCULO[:-1] + '9', 2026, 'calculo')
    _recusa('tela desconhecida: 400', 400, a, EST_CALCULO, 2026, 'contestacoes')
    _recusa('número na massa salarial: 400', 400, a, EST_CALCULO, 2026, 'massa_salarial', '123')
    _recusa('cálculo inválido: 400', 400, a, EST_CALCULO, 2026, 'B91', None, 'penultimo')
    _recusa('vigência que não é ano: 400', 400, a, EST_CALCULO, 'dois mil', 'calculo')
    _recusa('CNPJ fora da base do escritório: 404', 404, a, EST_FORA, 2026, 'calculo')
    p = svc.validar(a, svc_fmt(EST_CALCULO), '2026', 'b91', 'NB 123.456.789-0', None)
    check('CNPJ com pontuação, tela sem caixa e número só com dígitos',
          p == {'cnpj': EST_CALCULO, 'vigencia': 2026, 'tela': 'B91', 'numero': '1234567890', 'calculo': 'atual'},
          str(p))
    check('raiz do Painel FAP gravada sem os zeros da frente vale',
          svc.validar(a, EST_RAIZ, 2025, 'calculo')['cnpj'] == EST_RAIZ)
    check('CNPJ que perdeu os zeros (veio como número) é completado',
          svc.validar(a, EST_RAIZ.lstrip('0'), 2025, 'calculo')['cnpj'] == EST_RAIZ)
    os.environ.pop('FAP_SYNC_LAW_FIRM_ID', None)
    _recusa('instalação sem escritório da sessão configurado: 403', 403, a, EST_CALCULO, 2026, 'calculo')


def svc_fmt(c):
    return f'{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}'


def _navegador_falso(partes=2, fora=False):
    chamadas = []

    def nav(pedido, pasta):
        chamadas.append(pedido)
        arquivos = []
        for i in range(1, partes + 1):
            alvo = (pasta.parent if fora else pasta) / f'tela_{i}.png'
            alvo.write_bytes(PNG)
            arquivos.append({'arquivo': str(alvo), 'descricao': f'parte {i}'})
        return {'ok': True, 'empresa': '11.222.333 - EMPRESA TESTE', 'fap': 'FAP 2026 1,0461',
                'calculo': 'Cálculo Original 1,0461 30/09/2025', 'linhas': 1, 'linhas_omitidas': 0,
                'sessao_parcial': False, 'partes': arquivos}
    nav.chamadas = chamadas
    return nav


def test_captura(a, user_id):
    print('\n2. Captura (navegador substituído)')
    os.environ['FAP_SYNC_LAW_FIRM_ID'] = str(a)
    nav = _navegador_falso()
    p = svc.capturar(a, user_id, EST_CALCULO, 2026, 'B91', '1234567890', 'original', navegador=nav)
    check('o navegador recebe o pedido normalizado',
          nav.chamadas == [{'cnpj': EST_CALCULO, 'vigencia': 2026, 'tela': 'B91', 'numero': '1234567890',
                            'calculo': 'original'}], str(nav.chamadas))
    pasta = svc.DIR_PRINTS / str(a)
    check('duas imagens na pasta do escritório', [x['nome'] for x in p.partes] == [f'{p.id}_1.png', f'{p.id}_2.png']
          and all((pasta / x['nome']).is_file() for x in p.partes))
    meta = json.loads((pasta / f'{p.id}.json').read_text(encoding='utf-8'))
    check('ficha .json com quem e quando capturou', meta['user_id'] == user_id and meta['capturado_em']
          and meta['calculo_rotulo'].startswith('Cálculo Original'), str(meta)[:200])
    check('arquivo_da_imagem acha a do escritório', svc.arquivo_da_imagem(a, p.partes[0]['nome']) is not None)
    check('nome fora do padrão não lê nada (../)', svc.arquivo_da_imagem(a, f'../{p.id}.json') is None
          and svc.arquivo_da_imagem(a, f'{p.id}.json') is None)
    check('as pastas temporárias somem', not list(svc.DIR_PRINTS.glob('print_fap_*')))

    def falha(pedido, pasta):
        return {'ok': False, 'codigo': 'sessao_expirada', 'mensagem': 'A sessão do portal FAP expirou'}
    try:
        svc.capturar(a, user_id, EST_CALCULO, 2026, 'calculo', navegador=falha)
        check('sessão expirada vira erro 503', False)
    except svc.PrintFapIndisponivel as e:
        check('sessão expirada vira erro 503', e.status_http == 503 and e.codigo == 'sessao_expirada', str(e))
    try:
        svc.capturar(a, user_id, EST_CALCULO, 2026, 'calculo', navegador=_navegador_falso(fora=True))
        check('imagem fora da pasta temporária é ignorada (502)', False)
    except svc.PrintFapIndisponivel as e:
        check('imagem fora da pasta temporária é ignorada (502)', e.status_http == 502, str(e))
    for sobra in svc.DIR_PRINTS.glob('tela_*.png'):
        sobra.unlink()

    velho = pasta / ('0' * 32 + '_1.png')
    velho.write_bytes(PNG)
    antigo = time.time() - (svc.RETENCAO_DIAS + 1) * 86400
    os.utime(velho, (antigo, antigo))
    svc.capturar(a, user_id, EST_CALCULO, 2026, 'calculo', navegador=_navegador_falso(partes=1))
    check(f'print com mais de {svc.RETENCAO_DIAS} dias é apagado na captura seguinte', not velho.exists())

    import fcntl
    espera = svc.ESPERA_TRAVA_S
    svc.ESPERA_TRAVA_S = 1
    with open(svc.ARQUIVO_TRAVA, 'w') as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        try:
            svc.capturar(a, user_id, EST_CALCULO, 2026, 'calculo', navegador=_navegador_falso())
            check('com outro navegador aberto: 503 "ocupado"', False)
        except svc.PrintFapIndisponivel as e:
            check('com outro navegador aberto: 503 "ocupado"', e.status_http == 503 and e.codigo == 'ocupado')
        finally:
            fcntl.flock(trava, fcntl.LOCK_UN)
            svc.ESPERA_TRAVA_S = espera
    return p


def test_subprocesso():
    print('\n3. Subprocesso do navegador')
    guardado = os.environ.pop('FAP_AUTH_JSON', None)
    try:
        pasta = svc.DIR_PRINTS / 'teste_subprocesso'
        r = svc._rodar_navegador({'cnpj': EST_CALCULO, 'vigencia': 2026, 'tela': 'calculo'}, pasta)
        check('sem FAP_AUTH_JSON: responde sessao_expirada em JSON, sem abrir o portal',
              r.get('ok') is False and r.get('codigo') == 'sessao_expirada', str(r))
        shutil.rmtree(pasta, ignore_errors=True)
    finally:
        if guardado is not None:
            os.environ['FAP_AUTH_JSON'] = guardado


def test_ferramenta_e_rota(usuarios, a):
    print('\n4. Ferramenta e rota da imagem')
    from fastmcp.exceptions import ToolError
    from mcp_server.tools.fap_portal_print import fap_portal_print_handler

    original = svc._rodar_navegador
    svc._rodar_navegador = _navegador_falso()
    try:
        r = fap_portal_print_handler(a, usuarios[0].id, EST_CALCULO, 2026, 'B91', '1234567890',
                                     app_public_url='https://exemplo.test')
    finally:
        svc._rodar_navegador = original
    check('duas partes com link na rota do Painel FAP',
          [i['url_imagem'].split('print-portal/')[0] for i in r['imagens']]
          == ['https://exemplo.test/fap-panel/'] * 2, str(r['imagens']))
    check('aviso explica a segunda parte', 'parte 2' in r.get('aviso', ''))
    check('CNPJ formatado, cálculo e data da captura', r['cnpj'] == svc_fmt(EST_CALCULO)
          and r['calculo'].startswith('Cálculo Original') and len(r['capturado_em']) == 19, str(r)[:300])
    try:
        fap_portal_print_handler(usuarios[1].law_firm_id, usuarios[1].id, EST_CALCULO, 2026)
        check('outro escritório: ToolError', False)
    except ToolError as e:
        check('outro escritório: ToolError com status 403 na causa', getattr(e.__cause__, 'status_http', 0) == 403)

    nome = r['imagens'][0]['url_imagem'].rsplit('/', 1)[1]
    c = app.test_client()
    for u, url, esperado, rotulo in (
            (usuarios[0], nome, 200, 'dono'),
            (usuarios[1], nome, 404, 'outro escritório'),
            (usuarios[0], 'x' * 32 + '_1.png', 404, 'nome inexistente'),
            (usuarios[0], '..%2F..%2Fmain.py', 404, 'caminho para fora')):
        with c.session_transaction() as s:
            s.clear()
            s['user_id'], s['law_firm_id'], s['user_role'] = u.id, u.law_firm_id, u.role
        resp = c.get(f'/fap-panel/print-portal/{url}')
        check(f'rota: {rotulo} → {esperado}', resp.status_code == esperado, f'{resp.status_code}')
        if esperado == 200:
            check('rota entrega PNG', resp.mimetype == 'image/png' and resp.data.startswith(b'\x89PNG'))


def main():
    guardado = os.environ.get('FAP_SYNC_LAW_FIRM_ID')
    with app.app_context():
        try:
            usuarios = _setup()
            a = usuarios[0].law_firm_id
            test_pedido(a, usuarios[1].law_firm_id)
            test_captura(a, usuarios[0].id)
            test_subprocesso()
            os.environ['FAP_SYNC_LAW_FIRM_ID'] = str(a)
            test_ferramenta_e_rota(usuarios, a)
        finally:
            db.session.rollback()
            _cleanup()
            if guardado is None:
                os.environ.pop('FAP_SYNC_LAW_FIRM_ID', None)
            else:
                os.environ['FAP_SYNC_LAW_FIRM_ID'] = guardado
    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        sys.exit(1)
    print('✅ Tudo verde')


if __name__ == '__main__':
    main()
