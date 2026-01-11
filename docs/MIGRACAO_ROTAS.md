# 🔄 Guia de Migração - Do routes.py para Blueprints

## Situação Atual

Seu projeto Intellexia passou por uma reorganização de rotas usando **Blueprints do Flask**. Isso foi feito de forma **não-intrusiva**, mantendo total compatibilidade.

## O que Mudou?

### ✅ Mantido Igual
- ✅ Todas as URLs funcionam normalmente
- ✅ Banco de dados intacto
- ✅ Funcionalidades inalteradas
- ✅ Banco de dados continua funcionando

### 🆕 Adicionado
- 🆕 Pasta `app/blueprints/` com 12 arquivos modulares
- 🆕 Arquivo `app/middlewares.py` com lógica centralizada
- 🆕 Documentação em `ESTRUTURA_BLUEPRINTS.md`
- 🆕 Sistema melhor organizado

## Estrutura de Diretórios

```
app/
├── blueprints/                # 🆕 NOVO
│   ├── __init__.py
│   ├── auth.py               # Autenticação
│   ├── dashboard.py          # Dashboard
│   ├── cases.py              # 🌟 PRINCIPAL - Casos
│   ├── clients.py            # Clientes
│   ├── lawyers.py            # Advogados
│   ├── courts.py             # Varas
│   ├── benefits.py           # Benefícios
│   ├── documents.py          # Documentos
│   ├── petitions.py          # Petições
│   ├── assistant.py          # Assistente
│   ├── tools.py              # Ferramentas
│   └── settings.py           # Configurações
├── middlewares.py            # 🆕 NOVO - Autenticação centralizada
├── routes.py                 # ⚠️ DEPRECIADO (mantido temporariamente)
├── models.py
├── agents/
├── prompts/
├── utils/
└── forms.py
```

## Como Adicionar Novas Rotas

### Opção 1: Adicionar ao Blueprint Existente

Se a rota é de um tipo que já existe (ex: um novo endpoint de Casos):

**Arquivo: `app/blueprints/cases.py`**
```python
@cases_bp.route('/novo-endpoint')
def novo_endpoint():
    """Descrição da funcionalidade"""
    return render_template('template.html')
```

### Opção 2: Criar Novo Blueprint

Se a rota é de uma nova funcionalidade:

**1. Criar arquivo: `app/blueprints/nova_funcao.py`**
```python
from flask import Blueprint

nova_funcao_bp = Blueprint('nova_funcao', __name__, url_prefix='/nova-funcao')

@nova_funcao_bp.route('/')
def index():
    return render_template('nova_funcao/index.html')

@nova_funcao_bp.route('/new', methods=['GET', 'POST'])
def new():
    return render_template('nova_funcao/form.html')
```

**2. Atualizar `app/blueprints/__init__.py`:**
```python
from app.blueprints.nova_funcao import nova_funcao_bp

__all__ = [
    # ... outros blueprints
    'nova_funcao_bp'
]
```

**3. Atualizar `main.py`:**
```python
from app.blueprints import (
    # ... outros imports
    nova_funcao_bp
)

# Registrar blueprint
app.register_blueprint(nova_funcao_bp)
```

## Rotas Principais por Categoria

### 🔐 Autenticação
- `/login` - Login
- `/register` - Registro
- `/logout` - Logout

### 🏠 Dashboard
- `/` - Home/Redireciona
- `/dashboard` - Dashboard principal

### 📋 Casos (PRINCIPAL)
- `/cases/` - Listar
- `/cases/new` - Criar
- `/cases/<id>` - Ver detalhes
- `/cases/<id>/edit` - Editar
- `/cases/<id>/delete` - Excluir

### 👥 Clientes
- `/clients/` - Listar
- `/clients/new` - Criar
- `/clients/<id>` - Ver detalhes
- `/clients/<id>/edit` - Editar

### ⚖️ Advogados
- `/lawyers/` - Listar
- `/lawyers/new` - Criar
- `/lawyers/<id>/edit` - Editar

### 🏛️ Varas
- `/courts/` - Listar
- `/courts/new` - Criar
- `/courts/<id>/edit` - Editar

### 💰 Benefícios
- `/benefits/` - Listar todos
- `/benefits/<id>` - Ver detalhes
- `/benefits/case/<case_id>` - Benefícios de um caso

### 📄 Documentos
- `/cases/<case_id>/documents/` - Listar
- `/cases/<case_id>/documents/new` - Upload
- `/cases/<case_id>/documents/<id>/view` - Ver
- `/cases/<case_id>/documents/<id>/delete` - Excluir

### 📑 Petições
- `/cases/<case_id>/petitions/` - Listar
- `/cases/<case_id>/petitions/generate` - Gerar com IA
- `/cases/<case_id>/petitions/<id>` - Ver
- `/cases/<case_id>/petitions/<id>/download` - Download

### 🤖 Assistente
- `/assistente-juridico/` - Interface
- `/assistente-juridico/api` - API para chat

### 🛠️ Ferramentas
- `/tools/document-summary` - Resumos
- `/tools/document-summary/upload` - Upload

### ⚙️ Configurações
- `/settings/law-firm` - Config do escritório

## Usando Middlewares

Proteja rotas que precisam de autenticação:

```python
from app.middlewares import require_law_firm

@meu_bp.route('/protegido')
@require_law_firm
def rota_protegida():
    law_firm_id = session.get('law_firm_id')
    return render_template('protegido.html')
```

## Padrão de Código

Todos os blueprints seguem este padrão:

```python
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.models import db, Model
from datetime import datetime
from functools import wraps

# Criar blueprint
meu_bp = Blueprint('meu', __name__, url_prefix='/meu')

# Definir helpers e decoradores
def get_current_law_firm_id():
    return session.get('law_firm_id')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# Definir rotas
@meu_bp.route('/')
@require_law_firm
def meu_index():
    return render_template('meu/index.html')

# Mais rotas...
```

## Testando

Para testar se tudo está funcionando:

```bash
cd /Users/thiagoscheidt/Projects/intellexia

# Ativar venv
source .venv/bin/activate

# Testar importação
python -c "from main import app; print('✓ OK')"

# Rodar servidor
python main.py
```

## Troubleshooting

### Erro: "Blueprint not registered"
- Verifique se o blueprint foi adicionado em `__init__.py`
- Verifique se foi registrado em `main.py`

### Erro: "Route not found"
- Certifique-se de usar o prefixo URL correto (ex: `/cases/`)
- Verifique o nome do blueprint em `url_for()`

### Templates não encontram rotas
- Use `url_for()` com o nome do blueprint: `url_for('cases.case_detail', case_id=1)`
- Formato: `url_for('blueprint_name.function_name', **args)`

## ✅ Checklist de Migração

- [x] Blueprints criados
- [x] Middlewares centralizados
- [x] `main.py` atualizado
- [x] Sem quebras no sistema
- [x] Documentação criada
- [ ] (Futuro) Remover `app/routes.py`
- [ ] (Futuro) Adicionar testes
- [ ] (Futuro) Documentar com Swagger

## 📞 Suporte

### Documentação Completa
Veja `ESTRUTURA_BLUEPRINTS.md` para:
- Lista completa de rotas
- Exemplos de código
- Como estender o sistema

### FAQ

**P: Preciso mudar meu código?**
R: Não! Tudo funciona igual. Apenas novas rotas devem ir nos blueprints.

**P: E o arquivo routes.py?**
R: Está depreciado. Use os blueprints para código novo.

**P: Como eu adiciono uma nova feature?**
R: Crie um novo blueprint ou estenda um existente (veja "Como Adicionar Novas Rotas").

**P: Preciso recompilar algo?**
R: Não! O Flask descobre tudo automaticamente.

---

✨ **Sistema reorganizado com sucesso!**

Você agora tem uma base profissional, escalável e fácil de manter.

Data: 11 de janeiro de 2026
