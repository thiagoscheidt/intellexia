# 🤖 INSTRUÇÕES PARA IA - IntellexIA Project

## 📋 Convenções do Projeto

Este documento contém instruções para assistentes de IA (GitHub Copilot, Claude, ChatGPT, etc.) que trabalharão neste projeto.

---

## 📁 Estrutura de Pastas

```
intellexia/
├── app/                      # Aplicação principal
│   ├── models.py            # Modelos do banco de dados
│   ├── routes.py            # Rotas/endpoints
│   ├── form.py              # Formulários WTForms
│   ├── agents/              # Agentes de IA
│   └── prompts/             # Prompts para IA
├── database/                # ⭐ Scripts de banco de dados
│   ├── README.md            # Instruções completas
│   ├── add_*.py             # Scripts de migração
│   └── recreate_database.py # Recriação completa
├── templates/               # Templates HTML
│   ├── layout/              # Layouts base
│   ├── partials/            # Componentes reutilizáveis
│   └── [modulos]/           # Templates por módulo
├── static/                  # Arquivos estáticos
├── uploads/                 # Arquivos enviados
└── instance/                # Banco de dados SQLite
```

---

## 🗄️ REGRA #1: Scripts de Banco de Dados

### ⚠️ SEMPRE criar scripts na pasta `database/`

**❌ NÃO FAZER:**
```python
# add_nova_coluna.py (na raiz do projeto)
from main import app
...
```

**✅ FAZER:**
```python
# database/add_nova_coluna.py
import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
```

### Convenção de Nomenclatura

| Ação | Nomenclatura | Exemplo |
|------|--------------|---------|
| Adicionar coluna | `add_[nome]_column.py` | `add_status_column.py` |
| Adicionar tabela | `add_[tabela]_table.py` | `add_users_table.py` |
| Alterar estrutura | `alter_[tabela]_[desc].py` | `alter_cases_add_index.py` |
| Remover algo | `remove_[nome]_[tipo].py` | `remove_old_column.py` |

### Template Obrigatório

```python
"""
Script para [ação] [descrição]
Execute este script para [quando usar]
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

def [nome_funcao]():
    """[Descrição da função]"""
    with app.app_context():
        try:
            # Verificar se já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('[tabela]')]
            
            if '[campo]' in columns:
                print("✓ Já existe")
                return
            
            # Executar alteração
            with db.engine.connect() as conn:
                conn.execute(text("..."))
                conn.commit()
            
            print("✓ Sucesso")
            
        except Exception as e:
            print(f"✗ Erro: {str(e)}")
            raise

if __name__ == '__main__':
    print("🔄 Iniciando migração...")
    [nome_funcao]()
    print("✅ Migração concluída!")
```

### Checklist Antes de Criar Script

- [ ] Arquivo na pasta `database/`
- [ ] Import path configurado (`sys.path.insert`)
- [ ] Docstring descritivo
- [ ] Verificação de existência
- [ ] Mensagens de log com emojis (✓, ✗, 🔄, ⚠️)
- [ ] Try/except com tratamento de erro
- [ ] Atualizar `database/README.md` se necessário

---

## 📝 REGRA #2: Modelos de Dados

### Localização
- **Arquivo:** `app/models.py`
- **Padrão:** SQLAlchemy com Flask-SQLAlchemy

### Convenções

1. **Nomes de Tabelas:** snake_case
   ```python
   __tablename__ = 'ai_document_summaries'
   ```

2. **Nomes de Classes:** PascalCase
   ```python
   class AiDocumentSummary(db.Model):
   ```

3. **Campos Obrigatórios:**
   ```python
   id = db.Column(db.Integer, primary_key=True)
   created_at = db.Column(db.DateTime, default=datetime.utcnow)
   updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
   ```

4. **Foreign Keys:**
   ```python
   user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
   law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
   ```

5. **Relacionamentos:**
   ```python
   user = db.relationship('User')
   law_firm = db.relationship('LawFirm')
   ```

6. **Método `__repr__`:**
   ```python
   def __repr__(self):
       return f'<AiDocumentSummary {self.original_filename}>'
   ```

---

## 🛣️ REGRA #3: Rotas

### Localização
- **Arquivo:** `app/routes.py`

### Convenções

1. **Nomenclatura de Funções:**
   - Lista: `[modulo]_list()`
   - Novo: `[modulo]_new()`
   - Editar: `[modulo]_edit(id)`
   - Detalhe: `[modulo]_detail(id)`
   - Deletar: `[modulo]_delete(id)`

2. **Decorators Obrigatórios:**
   ```python
   @app.route('/caminho')
   @require_law_firm  # Para rotas que precisam de autenticação
   def funcao():
       ...
   ```

3. **Estrutura Padrão:**
   ```python
   @app.route('/modulo')
   @require_law_firm
   def modulo_list():
       law_firm_id = get_current_law_firm_id()
       items = Model.query.filter_by(law_firm_id=law_firm_id).order_by(...).all()
       return render_template('modulo/list.html', items=items)
   ```

4. **Flash Messages:**
   ```python
   flash('Mensagem de sucesso', 'success')
   flash('Mensagem de erro', 'danger')
   flash('Aviso', 'warning')
   flash('Informação', 'info')
   ```

5. **Comentários de Seção:**
   ```python
   # ========================
   # Nome do Módulo
   # ========================
   ```

---

## 🎨 REGRA #4: Templates

### Estrutura

```
templates/
├── layout/
│   └── base.html              # Layout base
├── partials/
│   ├── sidebar.html           # Menu lateral
│   ├── navbar.html            # Barra superior
│   └── footer.html            # Rodapé
└── [modulo]/
    ├── list.html              # Lista
    ├── form.html              # Formulário (new/edit)
    ├── detail.html            # Detalhes
    └── [outras_views].html
```

### Convenções

1. **Extends:**
   ```html
   {% extends "layout/base.html" %}
   ```

2. **Blocks:**
   ```html
   {% block title %}Título - IntellexIA{% endblock %}
   {% block content %}...{% endblock %}
   ```

3. **Breadcrumbs:**
   ```html
   <ol class="breadcrumb float-sm-end">
     <li class="breadcrumb-item"><a href="{{ url_for('index') }}">Home</a></li>
     <li class="breadcrumb-item active">Página Atual</li>
   </ol>
   ```

4. **Cards:**
   ```html
   <div class="card card-primary card-outline">
     <div class="card-header">
       <h3 class="card-title">Título</h3>
     </div>
     <div class="card-body">
       ...
     </div>
   </div>
   ```

5. **Ícones Bootstrap:**
   ```html
   <i class="bi bi-[nome]"></i>
   ```

---

## 📋 REGRA #5: Formulários

### Localização
- **Arquivo:** `app/form.py`

### Convenções

1. **Nomenclatura:** `[Modelo]Form`
   ```python
   class ClientForm(FlaskForm):
   ```

2. **Estrutura Padrão:**
   ```python
   class ExemploForm(FlaskForm):
       campo = StringField('Label', validators=[DataRequired(), Length(max=255)])
       submit = SubmitField('Salvar')
   ```

3. **Comentários de Seção:**
   ```python
   # ========================
   # Formulário: Nome do Módulo
   # ========================
   ```

---

## 🎯 REGRA #6: Isolamento Multi-Tenant

### Sempre Filtrar por law_firm_id

**❌ NÃO FAZER:**
```python
items = Model.query.all()
```

**✅ FAZER:**
```python
law_firm_id = get_current_law_firm_id()
items = Model.query.filter_by(law_firm_id=law_firm_id).all()
```

### Sempre Incluir law_firm_id ao Criar

```python
item = Model(
    law_firm_id=get_current_law_firm_id(),
    user_id=session.get('user_id'),
    ...
)
```

---

## 📖 REGRA #7: Documentação

### Quando Criar Novo Módulo

1. Criar arquivo `[MODULO]_README.md` com:
   - Descrição do módulo
   - Funcionalidades implementadas
   - Estrutura de arquivos
   - Como usar
   - Exemplos

2. Atualizar README principal se necessário

3. Adicionar instruções específicas

---

## 🔍 REGRA #8: Nomenclatura Geral

### Python
- **Variáveis/Funções:** `snake_case`
- **Classes:** `PascalCase`
- **Constantes:** `UPPER_SNAKE_CASE`

### HTML/CSS
- **Classes CSS:** `kebab-case`
- **IDs:** `camelCase` ou `kebab-case`

### SQL
- **Tabelas:** `snake_case` (plural)
- **Colunas:** `snake_case`

---

## ✅ Checklist de Verificação

Antes de finalizar qualquer alteração:

- [ ] Código segue convenções do projeto
- [ ] Scripts de DB na pasta `database/`
- [ ] Filtros de `law_firm_id` aplicados
- [ ] Templates seguem estrutura padrão
- [ ] Formulários validados
- [ ] Flash messages apropriadas
- [ ] Comentários de seção adicionados
- [ ] Documentação atualizada
- [ ] Testado localmente

---

## 🚨 IMPORTANTE

### NÃO fazer sem consultar:

1. ❌ Remover tabelas ou colunas existentes
2. ❌ Alterar estrutura de tabelas em produção sem backup
3. ❌ Criar rotas sem `@require_law_firm` quando necessário
4. ❌ Ignorar filtros de `law_firm_id`
5. ❌ Criar scripts de DB fora da pasta `database/`

### SEMPRE fazer:

1. ✅ Verificar se já existe antes de criar
2. ✅ Incluir tratamento de erros
3. ✅ Adicionar mensagens de log claras
4. ✅ Seguir convenções de nomenclatura
5. ✅ Documentar alterações importantes

---

## 📚 Referências Rápidas

- **Models:** `app/models.py`
- **Routes:** `app/routes.py`
- **Forms:** `app/form.py`
- **Database Scripts:** `database/` + `database/README.md`
- **Templates:** `templates/`
- **Documentação:** `*.md` na raiz

---

**Última atualização:** 2026-01-07
**Versão:** 1.0
