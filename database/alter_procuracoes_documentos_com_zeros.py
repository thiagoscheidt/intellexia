#!/usr/bin/env python3
"""
Devolve os zeros à esquerda ao CNPJ raiz e ao CPF das procurações FAP já gravadas.

O portal manda esses campos como NÚMERO — 00.482.840 chega como 482840 — e a
ingestão gravava ``str(valor)``. O código novo grava com os 8 (raiz) e 11 (CPF)
dígitos; este script corrige o que foi gravado antes dele.

É normalização de identificador, não conteúdo de negócio: não cria versão, não
gera histórico de mudança, não dispara alerta. Mexe só em linhas com menos
dígitos que o documento, e só completando zeros — nunca corta nem troca dígito.

Sem ele o sistema também funciona: a tela, o Excel, os e-mails e o MCP completam
os zeros na leitura, e a sincronização cura cada procuração que o portal voltar
a listar. O script existe para as que o portal não lista mais (vencidas,
excluídas, ou fora de uma lista parcial) e para o filtro por raiz exata.

Idempotente. Uso:
  uv run python database/alter_procuracoes_documentos_com_zeros.py [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

from main import app
from app.models import db, FapWebProcuracao, FapWebProcuracaoChangeHistory
from app.utils.cnpj import TAMANHO_CNPJ_RAIZ, TAMANHO_CPF, completar_zeros

ALVOS = (
    (FapWebProcuracao, 'cnpj_raiz_outorgante', TAMANHO_CNPJ_RAIZ),
    (FapWebProcuracao, 'cpf_outorgado', TAMANHO_CPF),
    (FapWebProcuracao, 'cnpj_raiz_outorgado', TAMANHO_CNPJ_RAIZ),
    (FapWebProcuracaoChangeHistory, 'cnpj_raiz_outorgante', TAMANHO_CNPJ_RAIZ),
)


def corrigir(dry_run: bool) -> int:
    total = 0
    for modelo, campo, tamanho in ALVOS:
        coluna = getattr(modelo, campo)
        linhas = modelo.query.filter(coluna.isnot(None), func.length(coluna) < tamanho).all()
        alterados = 0
        for linha in linhas:
            novo = completar_zeros(getattr(linha, campo), tamanho)
            if novo and novo != getattr(linha, campo):
                if not dry_run:
                    setattr(linha, campo, novo)
                alterados += 1
        verbo = 'seriam corrigidas' if dry_run else 'corrigidas'
        print(f'  {modelo.__tablename__}.{campo}: {alterados} linha(s) {verbo}')
        total += alterados
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='mostra o que faria, sem gravar')
    args = parser.parse_args()

    with app.app_context():
        try:
            print('Procurações FAP — zeros à esquerda em CNPJ raiz e CPF')
            total = corrigir(args.dry_run)
            if args.dry_run:
                db.session.rollback()
                print(f'\n✓ Simulação: {total} valor(es) seriam corrigidos.')
            else:
                db.session.commit()
                print(f'\n✓ Concluído: {total} valor(es) corrigido(s).')
        except Exception as e:
            db.session.rollback()
            print(f'\n✗ Erro: {e}')
            sys.exit(1)
