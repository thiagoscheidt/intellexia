"""Atualiza os snapshots DataJud dos processos ativos (cron diário).

Consulta a API pública do DataJud (CNJ) para cada processo ativo com número
CNJ completo cujo snapshot esteja ausente ou mais velho que --idade-horas,
com pausa entre consultas (cortesia com a API pública). Falha em um processo
não interrompe os demais.

Agenda sugerida (crontab, madrugada — 1x/dia basta, o DataJud tem defasagem própria):
    30 4 * * * cd /sites/intellexia && uv run python scripts/sync_datajud_snapshots.py >> logs/datajud_sync.log 2>&1

Uso manual:
    uv run python scripts/sync_datajud_snapshots.py [--law-firm ID] [--max N] [--idade-horas H]
"""
import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import JudicialProcess
from app.services import datajud_snapshot_service

PAUSA_ENTRE_CONSULTAS = 1.5  # segundos


def main():
    parser = argparse.ArgumentParser(description='Sincroniza snapshots DataJud dos processos ativos.')
    parser.add_argument('--law-firm', type=int, help='Restringir a um escritório (law_firm_id)')
    parser.add_argument('--max', type=int, default=200, help='Máximo de consultas à API nesta execução')
    parser.add_argument('--idade-horas', type=int, default=20,
                        help='Só reconsulta snapshots mais velhos que N horas (padrão: 20)')
    args = parser.parse_args()

    with app.app_context():
        cutoff = datetime.now() - timedelta(hours=args.idade_horas)

        query = JudicialProcess.query.filter(JudicialProcess.status == 'ativo')
        if args.law_firm:
            query = query.filter(JudicialProcess.law_firm_id == args.law_firm)
        processos = query.order_by(JudicialProcess.id.asc()).all()

        atualizados = pulados = falhas = consultas = 0
        for process in processos:
            ok, _motivo = datajud_snapshot_service.can_query(process)
            if not ok:
                pulados += 1
                continue

            snapshot = datajud_snapshot_service.get_snapshot(process.id, process.law_firm_id)
            if snapshot and snapshot.fetched_at and snapshot.fetched_at > cutoff:
                pulados += 1
                continue

            if consultas >= args.max:
                print(f'[AVISO] Limite de {args.max} consultas atingido — o restante fica para a próxima execução.')
                break

            consultas += 1
            snapshot, error = datajud_snapshot_service.refresh_snapshot(process)
            if error:
                falhas += 1
                print(f'[ERRO] processo {process.id} ({process.process_number}): {error}')
            else:
                atualizados += 1
                print(f'[OK] processo {process.id} ({process.process_number}) — '
                      f'{len((snapshot.payload_json or {}).get("instancias", []))} instância(s)')
            time.sleep(PAUSA_ENTRE_CONSULTAS)

        print(f'[RESUMO] {atualizados} atualizado(s), {falhas} falha(s), '
              f'{pulados} pulado(s) (sem número CNJ/tribunal ou snapshot recente).')


if __name__ == '__main__':
    main()
