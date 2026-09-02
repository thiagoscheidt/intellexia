"""Teste standalone: PDF defasado entra na fila de download; NULL não entra.

O relatório da DATAPREV muda de conteúdo conforme o estágio — enquanto
"Transmitida" traz só as justificativas; publicado, traz Status, Parecer e o
Sumário dos Elementos Contestados. As três filas de download olhavam apenas
`file_path IS NULL`, então o arquivo capturado em voo nunca era rebaixado depois
do julgamento: o banco dizia "Indeferimento Total" com um PDF de meses antes.

Caso real: protocolo 10128.056943/2025-71 (CARBONIFERA METROPOLITANA, vigência
2026) — situação virou PUBLICADA em 08/08/2026 e o arquivo em disco continuou o
de 27/11/2025, que só tem Justificativa.

Três regras verificadas contra o banco de verdade (dentro de transação
revertida), porque a sutileza está na semântica de NULL do SQL:

  1. arquivo na mesma situação do registro  → NÃO baixa
  2. situação avançou depois do download    → BAIXA
  3. `file_situacao_codigo` NULL            → NÃO baixa (origem desconhecida:
     tratar como defasado rebaixaria o acervo inteiro de uma vez)

Rode com: uv run python tests/test_fap_download_arquivo_defasado.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import FapWebContestacao, db


def _esta_na_fila(rec_id: int) -> bool:
    return db.session.query(
        FapWebContestacao.query
        .filter(
            FapWebContestacao.id == rec_id,
            FapWebContestacao.filtro_pendente_download(),
        )
        .exists()
    ).scalar()


def _esta_defasado(rec_id: int) -> bool:
    return db.session.query(
        FapWebContestacao.query
        .filter(
            FapWebContestacao.id == rec_id,
            FapWebContestacao.filtro_arquivo_defasado(),
        )
        .exists()
    ).scalar()


def main() -> int:
    falhas: list[str] = []

    with app.app_context():
        rec = (
            FapWebContestacao.query
            .filter(FapWebContestacao.file_path.isnot(None))
            .first()
        )
        if rec is None:
            print('PULADO: nenhuma contestação com arquivo local neste banco.')
            return 0

        original = (rec.file_situacao_codigo, rec.situacao_codigo, rec.file_path)
        try:
            # 1) arquivo na mesma situação do registro → não baixa
            rec.file_situacao_codigo = 'LIBERADA_PARA_ANALISE'
            rec.situacao_codigo = 'LIBERADA_PARA_ANALISE'
            db.session.flush()
            if _esta_defasado(rec.id):
                falhas.append('Arquivo na mesma situação foi marcado como defasado.')
            if _esta_na_fila(rec.id):
                falhas.append('Arquivo em dia entrou na fila de download.')

            # 2) situação avançou depois do download → baixa
            rec.situacao_codigo = 'PUBLICADA'
            db.session.flush()
            if not _esta_defasado(rec.id):
                falhas.append(
                    'Situação avançou para PUBLICADA e o arquivo NÃO foi marcado como defasado.'
                )
            if not _esta_na_fila(rec.id):
                falhas.append('Arquivo defasado não entrou na fila de download.')

            # 3) origem desconhecida (NULL) → não baixa
            rec.file_situacao_codigo = None
            db.session.flush()
            if _esta_defasado(rec.id):
                falhas.append(
                    'file_situacao_codigo NULL foi tratado como defasado — '
                    'isso rebaixaria o acervo inteiro.'
                )
            if _esta_na_fila(rec.id):
                falhas.append('Registro com origem desconhecida entrou na fila.')

            # 4) sem arquivo → baixa (comportamento antigo, preservado)
            rec.file_path = None
            db.session.flush()
            if not _esta_na_fila(rec.id):
                falhas.append('Contestação sem arquivo deixou de entrar na fila.')
        finally:
            rec.file_situacao_codigo, rec.situacao_codigo, rec.file_path = original
            db.session.rollback()

    if falhas:
        print('FALHOU:')
        for f in falhas:
            print(f'  - {f}')
        return 1

    print('OK: fila rebaixa o defasado, ignora o de origem desconhecida e mantém o resto.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
