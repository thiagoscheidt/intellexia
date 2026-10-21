#!/usr/bin/env python3
"""Importa para as bases as petições protocoladas compartilhadas pelo Google Drive.

O escritório compartilha cada PDF com a conta de serviço; este script lista o
que está compartilhado e, para o que ainda não entrou, lê a ficha com IA e
grava como o lote .md: Base de Conhecimento ("Petições protocoladas", indexada
no Qdrant e no Meilisearch, com o link do Drive) e, se for impugnação, também
Peças-modelo. O que já veio pelo lote só é registrado na tela do Drive.
Ver app/services/drive_peticao_service.py.

Sem --gravar só confere (lista o Drive e mostra o que faria — sem baixar e sem IA).

    uv run python scripts/importar_peticoes_drive.py
    uv run python scripts/importar_peticoes_drive.py --gravar
    uv run python scripts/importar_peticoes_drive.py --gravar --limite 3

No cron, de hora em hora (seguro rodar de novo: o que já entrou é pulado):
    0 * * * * cd /sites/intellexia && uv run python scripts/importar_peticoes_drive.py --gravar
"""
import argparse
import fcntl
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.services import drive_peticao_service as svc  # noqa: E402
from app.services import google_drive_client as gdrive  # noqa: E402

TRAVA = Path(__file__).resolve().parent.parent / 'instance' / '.importar_peticoes_drive.lock'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--gravar', action='store_true', help='grava de fato (sem ele, só confere)')
    parser.add_argument('--limite', type=int, help='lê com IA no máximo N arquivos novos nesta rodada')
    args = parser.parse_args()

    TRAVA.parent.mkdir(exist_ok=True)
    with open(TRAVA, 'w') as trava:
        try:
            # Uma rodada por vez: a anterior pode estar lendo petições longas com a IA.
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Outra importação ainda está rodando; esta rodada foi pulada.')
            return 0

        with app.app_context():
            law_firm_id = gdrive.law_firm_id_configurado()
            if not gdrive.configurado() or not law_firm_id:
                print('Google Drive não configurado (GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE / GOOGLE_DRIVE_LAW_FIRM_ID).')
                return 0
            try:
                planos = svc.planejar(law_firm_id)
            except gdrive.DriveErro as erro:
                print(f'Google Drive indisponível: {erro}')
                return 1

            contagem = Counter(p.acao for p in planos)
            print(f'{len(planos)} arquivo(s) compartilhado(s): {contagem[svc.IMPORTAR]} novo(s), '
                  f'{contagem[svc.REGISTRAR]} já na base (só registrar), {contagem[svc.PULAR]} já registrado(s).')
            if not args.gravar:
                for p in planos:
                    if p.acao != svc.PULAR:
                        print(f'  [{p.acao}] {p.nome} — {p.motivo}')
                print('Nada gravado (use --gravar).')
                return 0

            svc.executar(law_firm_id, planos, limite=args.limite)
            for p in planos:
                if p.acao != svc.PULAR:
                    marca = {True: '✓', False: '✗', None: '·'}[p.ok]
                    print(f'  {marca} {p.nome}: {p.resultado}')
            return 0


if __name__ == '__main__':
    sys.exit(main())
