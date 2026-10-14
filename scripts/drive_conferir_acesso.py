"""
Confere, contra o Google Drive real, o acesso da conta de serviço.

Lista tudo o que foi compartilhado com a conta e baixa um arquivo para provar
que o download funciona — o teste de uma instalação nova, ou de quando o
escritório disser "já compartilhei". Não grava nada no banco; o arquivo baixado
vai para uma pasta temporária e é apagado em seguida.

    uv run python scripts/drive_conferir_acesso.py
    uv run python scripts/drive_conferir_acesso.py --baixar <file_id>
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: F401  carrega o .env
from app.services import google_drive_client as gdrive


def main_():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--baixar', help='id do arquivo a baixar (padrão: o primeiro da lista)')
    args = parser.parse_args()

    try:
        drive = gdrive.cliente()
        itens = drive.listar()
    except gdrive.DriveErro as erro:
        print(f'✗ {erro}')
        return 1

    print(f'Conta: {drive.conta}')
    print(f'Escritório configurado: {gdrive.law_firm_id_configurado() or "— (GOOGLE_DRIVE_LAW_FIRM_ID vazio)"}')
    pastas = [i for i in itens if i.get('mimeType') == gdrive.MIME_PASTA]
    arquivos = [i for i in itens if i.get('mimeType') != gdrive.MIME_PASTA]
    print(f'\n{len(arquivos)} arquivo(s), {len(pastas)} pasta(s) visíveis\n')
    for p in pastas:
        print(f'  [pasta] {p["name"]}  ({p["id"]})')
    for a in arquivos:
        quem = (a.get('sharingUser') or {}).get('emailAddress') or '—'
        tipo = gdrive.tipo_do_arquivo(a.get('mimeType')) or a.get('mimeType')
        print(f'  {a.get("sharedWithMeTime", "")[:16]}  {tipo:<5} {a["name"]}  — por {quem}  ({a["id"]})')

    alvo = args.baixar or (arquivos[0]['id'] if arquivos else None)
    if not alvo:
        print('\nNada para baixar.')
        return 0
    with tempfile.TemporaryDirectory() as pasta:
        try:
            caminho, nome, sha = drive.baixar(alvo, pasta)
        except gdrive.DriveErro as erro:
            print(f'\n✗ Download de {alvo}: {erro}')
            return 1
        tamanho = Path(caminho).stat().st_size
        cabeca = Path(caminho).read_bytes()[:5]
    print(f'\n✓ Baixou "{nome}": {tamanho} bytes, começa com {cabeca!r}, sha256 {sha[:16]}…')
    return 0


if __name__ == '__main__':
    sys.exit(main_())
