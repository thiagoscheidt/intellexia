"""
Script para recriar o banco de dados do zero
ATENÇÃO: Apaga todos os dados!
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent.parent / 'instance' / 'intellexia.db'

if DB_PATH.exists():
    print(f"🗑️  Removendo banco existente: {DB_PATH}")
    DB_PATH.unlink()
    print("✅ Banco removido!")
else:
    print("ℹ️  Banco não existe, nada a remover.")

print("""
Próximo passo:
Execute a aplicação normalmente:
    python main.py

O SQLAlchemy criará o banco com todas as colunas novas!
""")
