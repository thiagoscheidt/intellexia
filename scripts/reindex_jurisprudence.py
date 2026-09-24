#!/usr/bin/env python3
"""Reconstrói o índice da Base de Jurisprudência (coleção Qdrant + índice
Meilisearch "jurisprudence") a partir do banco, que é a fonte da verdade.

Extrai o inteiro teor do PDF quando a decisão tem PDF e ainda não tem texto
(sem IA: pdfplumber, Docling se escaneado). O custo é só o do embedding.

    uv run python scripts/reindex_jurisprudence.py                  # tudo
    uv run python scripts/reindex_jurisprudence.py --pendentes      # só o que não está indexado
    uv run python scripts/reindex_jurisprudence.py --escritorio 1
    uv run python scripts/reindex_jurisprudence.py --recriar        # apaga coleção e índice antes
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import db, JurisprudenceDecision as D  # noqa: E402
from app.services import jurisprudence_index_service as indice  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--escritorio', type=int, help='só este law_firm_id')
    parser.add_argument('--pendentes', action='store_true', help='só decisões ainda não indexadas')
    parser.add_argument('--recriar', action='store_true', help='apaga a coleção e o índice antes')
    args = parser.parse_args()

    with app.app_context():
        alvo = indice.indice_padrao()
        if args.recriar:
            if args.escritorio:
                print('--recriar apaga o índice de todos os escritórios; não combine com --escritorio.')
                return 2
            if alvo.qdrant.collection_exists(alvo.colecao):
                alvo.qdrant.delete_collection(alvo.colecao)
            alvo.meili.delete_index_if_exists(alvo.indice_meili)
            print(f'Coleção "{alvo.colecao}" e índice "{alvo.indice_meili}" apagados.')

        consulta = D.query
        if args.escritorio:
            consulta = consulta.filter(D.law_firm_id == args.escritorio)
        if args.pendentes and not args.recriar:
            consulta = consulta.filter(db.or_(D.index_status.is_(None), D.index_status != D.INDEX_INDEXADA))
        ids = [i for (i,) in consulta.with_entities(D.id).order_by(D.id).all()]
        print(f'{len(ids)} decisão(ões) a indexar.')

        inicio, ok, erros = time.time(), 0, 0
        for n, decision_id in enumerate(ids, start=1):
            decisao = db.session.get(D, decision_id)
            indice.preparar_e_indexar(decisao, indice=alvo)
            db.session.commit()
            if decisao.index_status == D.INDEX_INDEXADA:
                ok += 1
            else:
                erros += 1
                print(f'  ✗ {decision_id} {decisao.processo or ""}: {decisao.index_error}')
            if n % 25 == 0:
                print(f'  {n}/{len(ids)} · {time.time() - inicio:.0f}s')
            db.session.expire_all()
        print(f'\n✓ {ok} indexada(s), {erros} com erro, em {time.time() - inicio:.0f}s.')
        return 1 if erros else 0


if __name__ == '__main__':
    sys.exit(main())
