# 📁 Database - Scripts de Manipulação do Banco de Dados

Esta pasta contém todos os scripts para manipulação do banco de dados do sistema IntellexIA.

## 📂 Estrutura

```
database/
├── README.md                           # Este arquivo
├── recreate_database.py                # Recria o banco (APAGA TUDO)
├── add_fap_reason_column.py            # Adiciona coluna fap_reason
├── add_petition_file_path.py           # Adiciona coluna file_path
├── add_ai_document_summaries_table.py  # Adiciona tabela ai_document_summaries
└── [futuros scripts de migração]
```

## 🎯 Tipos de Scripts

### 1️⃣ Scripts de Migração (Alterações Incrementais)
Arquivos que começam com `add_*` ou `alter_*`:
- **Propósito:** Adicionar colunas, tabelas ou modificar estruturas existentes
- **Característica:** NÃO apagam dados
- **Quando usar:** Para atualizar banco em produção ou desenvolvimento

### 2️⃣ Script de Recriação
Arquivo `recreate_database.py`:
- **Propósito:** Recriar todo o banco do zero
- **Característica:** ⚠️ **APAGA TODOS OS DADOS**
- **Quando usar:** Apenas em desenvolvimento local

## 🚀 Como Executar os Scripts

### Executar do Diretório Raiz do Projeto
```bash
# A partir da raiz do projeto (intellexia/)
python database/nome_do_script.py
```

### Executar de Dentro da Pasta database/
```bash
# A partir da pasta database/
cd database
python nome_do_script.py
```

Os scripts já estão configurados para funcionar de ambas as formas.

## 📝 Exemplos de Uso

### Adicionar Nova Coluna
```bash
python database/add_fap_reason_column.py
```

### Adicionar Nova Tabela
```bash
python database/add_ai_document_summaries_table.py
```

### Recriar Banco (⚠️ CUIDADO)
```bash
python database/recreate_database.py
python main.py  # Recria as tabelas
```

## 🤖 INSTRUÇÕES PARA IA (GitHub Copilot / Claude / ChatGPT)

### ⚠️ REGRAS OBRIGATÓRIAS

Quando precisar criar ou modificar scripts de banco de dados:

1. **SEMPRE criar scripts na pasta `database/`**
   - ✅ Correto: `database/add_nova_coluna.py`
   - ❌ Errado: `add_nova_coluna.py` (na raiz)

2. **SEMPRE adicionar o import path no início do script:**
   ```python
   import sys
   from pathlib import Path
   
   # Adicionar o diretório raiz ao path
   sys.path.insert(0, str(Path(__file__).parent.parent))
   
   from main import app
   from app.models import db
   ```

3. **SEMPRE seguir convenção de nomenclatura:**
   - Adicionar coluna: `add_[nome_coluna]_column.py`
   - Adicionar tabela: `add_[nome_tabela]_table.py`
   - Alterar estrutura: `alter_[nome_tabela]_[descricao].py`
   - Remover algo: `remove_[nome]_[tipo].py`

4. **SEMPRE incluir verificação antes de alterar:**
   ```python
   # Verificar se já existe
   inspector = db.inspect(db.engine)
   columns = [col['name'] for col in inspector.get_columns('tabela')]
   
   if 'coluna' in columns:
       print("✓ Já existe")
       return
   ```

5. **SEMPRE usar mensagens claras:**
   ```python
   print("✓ Sucesso")
   print("✗ Erro")
   print("ℹ️ Informação")
   print("⚠️ Atenção")
   print("🔄 Processando")
   ```

6. **SEMPRE documentar no docstring:**
   ```python
   """
   Script para [ação] [o que faz]
   Execute este script para [quando usar]
   """
   ```

7. **SEMPRE atualizar este README quando criar novo script:**
   - Adicionar à lista de scripts
   - Adicionar exemplo de uso se necessário

## 📋 Template para Novos Scripts

### Template: Adicionar Coluna
```python
"""
Script para adicionar a coluna [nome] na tabela [tabela]
Execute este script para atualizar o banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

def add_[nome]_column():
    """Adiciona a coluna [nome] na tabela [tabela]"""
    with app.app_context():
        try:
            # Verificar se a coluna já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('[tabela]')]
            
            if '[nome]' in columns:
                print("✓ A coluna '[nome]' já existe na tabela '[tabela]'")
                return
            
            # Adicionar a coluna
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE [tabela] ADD COLUMN [nome] [TIPO] [NULL/NOT NULL]"
                ))
                conn.commit()
            
            print("✓ Coluna '[nome]' adicionada com sucesso à tabela '[tabela]'")
            
        except Exception as e:
            print(f"✗ Erro ao adicionar coluna: {str(e)}")
            raise

if __name__ == '__main__':
    print("Adicionando coluna '[nome]' na tabela '[tabela]'...")
    add_[nome]_column()
    print("Migração concluída!")
```

### Template: Adicionar Tabela
```python
"""
Script para adicionar a tabela [nome_tabela] ao banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, [NomeModelo]

def add_[nome_tabela]_table():
    """Adiciona a tabela [nome_tabela] ao banco"""
    with app.app_context():
        print("🔄 Criando tabela [nome_tabela]...")
        
        # Criar apenas a tabela nova (se não existir)
        db.create_all()
        
        print("✅ Tabela [nome_tabela] criada com sucesso!")
        print("")
        print("📊 Estrutura da tabela:")
        print("  - campo1 (Tipo)")
        print("  - campo2 (Tipo)")
        print("")
        print("✅ Migração concluída!")

if __name__ == '__main__':
    add_[nome_tabela]_table()
```

## 🔍 Verificação de Scripts

Antes de executar um script de migração, verifique:

- [ ] Script está na pasta `database/`
- [ ] Imports do path configurados corretamente
- [ ] Docstring descritivo presente
- [ ] Verificação de existência implementada
- [ ] Mensagens de log claras
- [ ] Testado em ambiente local primeiro
- [ ] README atualizado (se aplicável)

## 🐛 Troubleshooting

### Erro: "No module named 'main'"
**Solução:** Execute a partir da raiz do projeto:
```bash
cd /caminho/para/intellexia
python database/nome_script.py
```

### Erro: "No module named 'app'"
**Solução:** Verifique se o import path está correto:
```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Coluna/Tabela já existe
**Solução:** Isso é normal! O script detecta e informa que já existe.

## 📊 Histórico de Migrações

| Data | Script | Descrição |
|------|--------|-----------|
| 2026-01-07 | `add_fap_reason_column.py` | Adiciona campo fap_reason na tabela cases |
| 2026-01-07 | `add_petition_file_path.py` | Adiciona campo file_path na tabela petitions |
| 2026-01-07 | `add_ai_document_summaries_table.py` | Cria tabela ai_document_summaries |

## 📞 Suporte

Para mais informações sobre o banco de dados, consulte:
- `app/models.py` - Definição dos modelos
- `main.py` - Configuração do banco
- Este README - Instruções de uso

---

**Importante:** Sempre faça backup do banco de dados antes de executar scripts de migração em produção!
