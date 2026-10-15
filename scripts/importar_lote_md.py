#!/usr/bin/env python3
"""Importa o lote de Markdown (petições protocoladas + decisões) para as bases.

A pasta tem a estrutura entregue pelo escritório — `decisoes/` e
`peticoes_protocoladas/`, cada uma com o seu `_INDICE_*.csv` e os `.md`. Os
arquivos entram como vieram, e a pasta de origem não é alterada.

    decisões   → Base de Jurisprudência (anexa à decisão que já existe; a nova
                 vai para a fila de leitura da IA)
    petições   → Base de Conhecimento, já indexada e concluída (categoria e tags
                 do índice; não passa pelo process_knowledge_base); impugnação
                 à contestação também vira peça-modelo

Sem --gravar só confere: mostra o que cada linha vai virar e grava o relatório.

    uv run python scripts/importar_lote_md.py --escritorio 1
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar --limite 10
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar --so peticoes --limite 5
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar --paralelo 4
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar --paralelo 4 --sem-pecas   # rápido
    uv run python scripts/importar_lote_md.py --escritorio 1 --gravar --paralelo 4 --so-pecas    # o lento, à parte

Depois de gravar, as decisões novas ficam na fila da IA:
    uv run python scripts/process_jurisprudence_uploads.py
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import db, LawFirm, User  # noqa: E402
from app.services import lote_md_import_service as lote  # noqa: E402


def _usuario(law_firm_id: int, user_id):
    if user_id:
        return User.query.filter_by(id=user_id, law_firm_id=law_firm_id).first()
    return (User.query.filter_by(law_firm_id=law_firm_id, role='admin')
            .order_by(User.id).first())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pasta', default=lote.PASTA_PADRAO, help=f'padrão: {lote.PASTA_PADRAO}')
    parser.add_argument('--escritorio', type=int, required=True, help='law_firm_id dono dos arquivos')
    parser.add_argument('--usuario', type=int, help='user_id registrado como autor (padrão: 1º admin)')
    parser.add_argument('--gravar', action='store_true', help='grava de fato (sem ele, só confere)')
    parser.add_argument('--limite', type=int, help='grava só as N primeiras ações (para testar)')
    parser.add_argument('--so', choices=('decisoes', 'peticoes'), help='só uma das pastas do lote')
    pecas = parser.add_mutually_exclusive_group()
    pecas.add_argument('--sem-pecas', action='store_true',
                       help='não cria peças-modelo (a etapa lenta); as impugnações vão só para a Base de Conhecimento')
    pecas.add_argument('--so-pecas', action='store_true', help='só as peças-modelo, para rodar à parte')
    parser.add_argument('--paralelo', type=int, default=1,
                        help='documentos processados ao mesmo tempo (ex.: 4); recusa por limite da IA é retomada na próxima rodada')
    parser.add_argument('--sem-indexar', action='store_true',
                        help='não indexa as decisões anexadas agora (fica para reindex_jurisprudence --pendentes)')
    parser.add_argument('--relatorio', help='CSV do relatório (padrão: instance/importacao/relatorios/)')
    args = parser.parse_args()

    with app.app_context():
        if db.session.get(LawFirm, args.escritorio) is None:
            print(f'Escritório {args.escritorio} não existe.')
            return 2
        usuario = _usuario(args.escritorio, args.usuario)
        if usuario is None:
            print('Nenhum usuário encontrado para registrar como autor (use --usuario).')
            return 2

        try:
            itens = lote.planejar(args.pasta, args.escritorio)
        except lote.LoteInvalido as erro:
            print(erro)
            return 2

        itens = lote.filtrar(itens, so=args.so, sem_pecas=args.sem_pecas, so_pecas=args.so_pecas)
        recorte = [r for r, ligado in ((f'só {args.so}', args.so), ('sem peças-modelo', args.sem_pecas),
                                       ('só peças-modelo', args.so_pecas)) if ligado]
        print(f'Pasta: {os.path.abspath(args.pasta)}' + (f' ({", ".join(recorte)})' if recorte else '') + '\n')
        for acao, total in sorted(lote.resumo(itens).items(), key=lambda par: par[0] == lote.PULAR):
            print(f'  {total:5d}  {lote.ROTULOS[acao]}')
        motivos: dict[str, int] = {}
        for item in itens:
            if item.acao == lote.PULAR:
                chave = item.motivo.split(' (')[0]  # detalhes ficam entre parênteses, no relatório
                motivos[chave] = motivos.get(chave, 0) + 1
        for motivo, total in sorted(motivos.items(), key=lambda par: -par[1]):
            print(f'         {total:5d} × {motivo}')
        for marca, rotulo in (('completar_link', 'link do Drive'), ('completar_processo', 'número do processo')):
            faltam = sum(1 for i in itens if i.dados.get(marca))
            if faltam:
                print(f'  {faltam:5d}  já na Base sem o {rotulo} (só o campo é gravado)')

        if args.gravar:
            acionaveis = [i for i in itens if i.acao != lote.PULAR]
            if args.limite is not None:
                for item in acionaveis[args.limite:]:
                    item.motivo, item.acao = 'além do --limite desta execução', lote.PULAR
            print('\nGravando…')

            def progresso(posicao, total, item):
                print(f'  {datetime.now():%H:%M:%S} [{posicao}/{total}] {item.arquivo} → {item.resultado}', flush=True)

            lote.executar(itens, args.escritorio, usuario.id, indexar=not args.sem_indexar,
                          paralelo=max(1, args.paralelo), progresso=progresso)

        carimbo = datetime.now().strftime('%Y%m%d_%H%M%S')
        relatorio = args.relatorio or os.path.join(
            'instance', 'importacao', 'relatorios',
            f'lote_md_{"gravado" if args.gravar else "conferencia"}_{carimbo}.csv')
        lote.gravar_relatorio(itens, relatorio)
        print(f'\nRelatório linha a linha: {relatorio}')

        if not args.gravar:
            print('Nada foi gravado. Para importar, rode de novo com --gravar.')
            return 0
        erros = sum(1 for i in itens if i.resultado.startswith('ERRO'))
        if erros:
            print(f'{erros} linha(s) com erro — veja a coluna Resultado do relatório.')
        if any(i.acao == lote.LER_IA and i.resultado and not i.resultado.startswith('ERRO') for i in itens):
            print('\nDecisões novas na fila da IA: uv run python scripts/process_jurisprudence_uploads.py')
        return 1 if erros else 0


if __name__ == '__main__':
    sys.exit(main())
