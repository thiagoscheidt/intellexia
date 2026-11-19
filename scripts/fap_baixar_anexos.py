#!/usr/bin/env python3
"""
Baixa os anexos das contestações administrativas do FAP (FB-08): os documentos
que o escritório juntou a cada contestação, por benefício ("Visualizar Anexos"
da Consulta do FAP, em cada recálculo).

Só leitura no portal (GETs). Parte dos recálculos já sincronizados por
``scripts/fap_calculo_sync.py``. Simula por padrão: lista e soma o tamanho sem
gravar nada; ``--baixar`` grava em ``instance/fap_anexos/<escritório>/`` (ou
``--pasta``) e em seguida registra no banco (``fap_contestacao_anexos``: liga
ao benefício da Central, lê o texto e indexa para a busca), salvo
``--sem-registrar``. ``--registrar`` só faz o registro do que já está na pasta,
sem ir ao portal. Retomável: anexo já no disco não é baixado de novo, e o
registro só completa o que faltava.

Uso:
  uv run python scripts/fap_baixar_anexos.py --vigencia 2026 --limite 50       # quanto tem
  uv run python scripts/fap_baixar_anexos.py --empresa 00025841 --baixar
  uv run python scripts/fap_baixar_anexos.py --estabelecimento 00025841000105 --baixar
  uv run python scripts/fap_baixar_anexos.py --baixar                          # tudo
  uv run python scripts/fap_baixar_anexos.py --registrar                       # só o banco
  uv run python scripts/fap_baixar_anexos.py --ocr --minutos 180               # digitalizados, aos poucos

Variáveis (.env):
  FAP_AUTH_JSON               — sessão do portal
  FAP_SYNC_LAW_FIRM_ID        — escritório (ou --escritorio)

Códigos de saída: 0 ok, 1 erro de configuração, 2 sessão FAP expirada,
3 execução incompleta (erros acima; rode de novo, o que já foi baixado fica).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env

EXIT_OK, EXIT_ERRO, EXIT_EXPIRADA, EXIT_INCOMPLETA = 0, 1, 2, 3
WORKERS_PADRAO, WORKERS_MAX = 8, 16


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _mb(n: int) -> str:
    return f'{n / 1024 / 1024:,.1f} MB'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _registrar(anexos, law_firm_id: int, pasta: Path) -> int:
    if not pasta.is_dir():
        _log(f'ERRO: pasta {pasta} não existe.')
        return EXIT_ERRO
    _log(f'Registrando no banco o que está em {pasta}…')
    t0 = time.time()
    r = anexos.registrar(law_firm_id, pasta, log=_log)
    _log(f"  listas lidas: {r['listas']} · anexos novos: {r['novos']} · atualizados: {r['atualizados']}"
         f" · ligados a benefício da Central: {r['ligados_a_beneficio']}")
    _log(f"  texto lido: {r['textos_lidos']} · sem texto: {r['sem_texto']} · erro de leitura: {r['erros_leitura']}")
    for tipo, n in r['por_tipo'].most_common():
        _log(f'    {n}× {tipo}')
    ind = r.get('indice') or {}
    _log(f"  índice da busca: {ind.get('indexados', 0)} indexados"
         + (f", fora do ar ({ind.get('erro')}) — a busca usa o banco até a próxima rodada" if ind.get('erros') else ''))
    _log(f'  tempo do registro: {time.time() - t0:.0f}s')
    return EXIT_OK


def _ocr(anexos, law_firm_id: int, pasta: Path, minutos, limite) -> int:
    t0 = time.time()
    r = anexos.aplicar_ocr(law_firm_id, pasta, minutos=minutos, limite=limite, log=_log)
    _log(f"  OCR: {r['lidos']} lido(s) · {r['sem_texto_mesmo_assim']} sem texto mesmo assim · {r['erros']} erro(s)"
         f" · {r['candidatos'] - r['lidos'] - r['sem_texto_mesmo_assim'] - r['erros']} ficam para a próxima rodada")
    for tipo, n in r['por_tipo'].most_common():
        _log(f'    {n}× {tipo}')
    if r['parou_por_tempo']:
        _log(f'  parou no limite de {minutos:g} min; a próxima rodada continua de onde parou.')
    _log(f'  tempo: {time.time() - t0:.0f}s')
    return EXIT_OK


def main(argv=None, svc=None) -> int:
    ap = argparse.ArgumentParser(description='Baixa os anexos das contestações do FAP.')
    ap.add_argument('--vigencia', type=int, action='append', default=[], help='ano (repetível)')
    ap.add_argument('--empresa', action='append', default=[], help='CNPJ raiz de 8 dígitos (repetível)')
    ap.add_argument('--estabelecimento', action='append', default=[], help='CNPJ de 14 dígitos (repetível)')
    ap.add_argument('--limite', type=int, default=None, help='só os N primeiros recálculos')
    ap.add_argument('--baixar', action='store_true', help='grava os arquivos (sem ele, só conta)')
    ap.add_argument('--registrar', action='store_true', help='só registra no banco o que já está na pasta')
    ap.add_argument('--sem-registrar', action='store_true', help='com --baixar, não registra no banco')
    ap.add_argument('--ocr', action='store_true',
                    help='lê por OCR os PDFs digitalizados já registrados (sem ir ao portal)')
    ap.add_argument('--minutos', type=float, default=None, help='com --ocr, para depois de N minutos')
    ap.add_argument('--pasta', default=None, help='pasta de destino (padrão instance/fap_anexos/<escritório>)')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    ap.add_argument('--workers', type=int, default=WORKERS_PADRAO, help=f'consultas em paralelo (máx {WORKERS_MAX})')
    args = ap.parse_args(argv)

    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        _log('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return EXIT_ERRO

    from app.services import fap_anexos_service as anexos

    pasta = Path(args.pasta) if args.pasta else anexos.PASTA_PADRAO / str(law_firm_id)
    if args.registrar:
        with app.app_context():
            return _registrar(anexos, law_firm_id, pasta)
    if args.ocr:
        with app.app_context():
            return _ocr(anexos, law_firm_id, pasta, args.minutos, args.limite)

    if svc is None:
        from app.services.fap_web_service import FapWebAuthPayload, FapWebService
        try:
            auth = FapWebAuthPayload.from_env()
        except Exception as e:
            _log(f'ERRO: FAP_AUTH_JSON inválido: {e}')
            return EXIT_ERRO
        if auth is None or not auth.cookies:
            _log('ERRO: FAP_AUTH_JSON ausente ou sem cookies no .env.')
            return EXIT_ERRO
        svc = FapWebService(auth)

    workers = max(1, min(args.workers, WORKERS_MAX))
    t0 = time.time()
    with app.app_context():
        _log(f'{"Baixando" if args.baixar else "Simulação (nada é gravado)"} com {workers} consulta(s) '
             f'em paralelo{" para " + str(pasta) if args.baixar else ""}…')
        r = anexos.executar(law_firm_id, svc, pasta=pasta, baixar=args.baixar,
                            anos=args.vigencia or None, raizes=args.empresa or None,
                            cnpjs=args.estabelecimento or None, limite=args.limite,
                            workers=workers, log=_log)

    _log('Resumo:')
    _log(f"  recálculos consultados: {r['consultados']} de {r['recalculos']}")
    _log(f"  com anexo: {r['com_anexo']} · anexos: {r['anexos']} · {_mb(r['bytes'])}")
    for elemento, n in r['por_elemento'].most_common():
        _log(f'    {n}× {elemento}')
    if args.baixar:
        _log(f"  baixados agora: {r['baixados']} ({_mb(r['bytes_baixados'])}) · já estavam no disco: {r['ja_no_disco']}")
        _log(f"  índice: {r.get('indice', 0)} linha(s) em {pasta / anexos.INDICE}")
    _log(f"  sem acesso (403, sessão parcial ou sem procuração): {r['sem_acesso']}")
    _log(f"  erros: {r['erros']}")
    for motivo, n in r['motivos_erro'].most_common(20):
        _log(f'    {n}× {motivo}')
    _log(f'  tempo: {time.time() - t0:.0f}s')

    if args.baixar and not args.sem_registrar:
        with app.app_context():
            _registrar(anexos, law_firm_id, pasta)

    if r['expirada']:
        _log('ERRO: sessão FAP expirada no meio. Faça login, atualize o FAP_AUTH_JSON e rode de novo '
             '(o que já foi baixado fica).')
        return EXIT_EXPIRADA
    if not args.baixar:
        _log('Simulação: nada foi gravado. Rode com --baixar para gravar os arquivos.')
    if r['incompleta']:
        _log('AVISO: execução incompleta (erros acima). Rode de novo; o que já foi baixado fica.')
        return EXIT_INCOMPLETA
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
