# 📂 Estrutura de Rotas - Blueprints do Flask

## Visão Geral

As rotas foram organizadas em **Blueprints** do Flask, seguindo o padrão modular recomendado. Cada categoria de funcionalidade tem seu próprio arquivo e rota prefixada.

## 📁 Estrutura de Pastas

```
app/
├── blueprints/
│   ├── __init__.py           # Importa e exporta todos os blueprints
│   ├── auth.py               # Autenticação (login, registro, logout)
│   ├── dashboard.py          # Dashboard e home
│   ├── cases.py              # Casos/Processos
│   ├── clients.py            # Clientes
│   ├── lawyers.py            # Advogados
│   ├── courts.py             # Varas/Tribunais
│   ├── benefits.py           # Benefícios
│   ├── documents.py          # Documentos de casos
│   ├── petitions.py          # Petições com IA
│   ├── assistant.py          # Assistente Jurídico
│   ├── tools.py              # Ferramentas (resumo de docs)
│   └── settings.py           # Configurações (escritório)
├── middlewares.py            # Middlewares e decoradores
├── models.py
├── routes.py                 # ⚠️ DEPRECIADO (mantido para compatibilidade)
└── ...
```

## 🔗 Blueprints e Suas Rotas

### 1. **auth_bp** - Autenticação
```python
# Arquivo: app/blueprints/auth.py
/login              (GET/POST)   - Login
/register           (GET/POST)   - Registro
/forgot-password    (GET/POST)   - Recuperar senha
/logout             (GET)        - Logout
```

### 2. **dashboard_bp** - Dashboard
```python
# Arquivo: app/blueprints/dashboard.py
/                   (GET)        - Redireciona para dashboard
/dashboard          (GET)        - Dashboard principal
/api/health         (GET)        - Health check
```

### 3. **cases_bp** - Casos
```python
# Arquivo: app/blueprints/cases.py
# Prefixo: /cases

/                              (GET)        - Lista casos
/new                           (GET/POST)   - Novo caso
/<int:case_id>                 (GET)        - Detalhes do caso
/<int:case_id>/edit            (GET/POST)   - Editar caso
/<int:case_id>/delete          (POST)       - Excluir caso
/<int:case_id>/lawyers/add     (POST)       - Adicionar advogado
/<int:case_id>/lawyers/<int:case_lawyer_id>/remove (POST) - Remover advogado
```

### 4. **clients_bp** - Clientes
```python
# Arquivo: app/blueprints/clients.py
# Prefixo: /clients

/                   (GET)        - Lista clientes
/new                (GET/POST)   - Novo cliente
/<int:client_id>    (GET)        - Detalhes do cliente
/<int:client_id>/edit (GET/POST) - Editar cliente
/<int:client_id>/delete (POST)   - Excluir cliente
```

### 5. **lawyers_bp** - Advogados
```python
# Arquivo: app/blueprints/lawyers.py
# Prefixo: /lawyers

/                   (GET)        - Lista advogados
/new                (GET/POST)   - Novo advogado
/<int:lawyer_id>/edit (GET/POST) - Editar advogado
/<int:lawyer_id>/delete (POST)   - Excluir advogado
```

### 6. **courts_bp** - Varas
```python
# Arquivo: app/blueprints/courts.py
# Prefixo: /courts

/                   (GET)        - Lista varas
/new                (GET/POST)   - Nova vara
/<int:court_id>/edit (GET/POST)  - Editar vara
/<int:court_id>/delete (POST)    - Excluir vara
```

### 7. **benefits_bp** - Benefícios
```python
# Arquivo: app/blueprints/benefits.py
# Prefixo: /benefits

/                                (GET)        - Lista benefícios gerais
/<int:benefit_id>                (GET)        - Detalhes do benefício
/case/<int:case_id>              (GET)        - Lista benefícios do caso
/case/<int:case_id>/new          (GET/POST)   - Novo benefício
/case/<int:case_id>/<int:benefit_id>/edit (GET/POST) - Editar benefício
/case/<int:case_id>/<int:benefit_id>/delete (POST)   - Excluir benefício
```

### 8. **documents_bp** - Documentos
```python
# Arquivo: app/blueprints/documents.py
# Prefixo: /cases/<int:case_id>/documents

/                          (GET)        - Lista documentos
/new                       (GET/POST)   - Upload de documento
/<int:document_id>/view    (GET)        - Visualizar documento
/<int:document_id>/delete  (POST)       - Excluir documento
```

### 9. **petitions_bp** - Petições com IA
```python
# Arquivo: app/blueprints/petitions.py
# Prefixo: /cases/<int:case_id>/petitions

/                          (GET)        - Lista petições
/generate                  (GET/POST)   - Gerar petição
/<int:petition_id>         (GET)        - Visualizar petição
/<int:petition_id>/delete  (POST)       - Excluir petição
/<int:petition_id>/download (GET)       - Download DOCX
```

### 10. **assistant_bp** - Assistente Jurídico
```python
# Arquivo: app/blueprints/assistant.py
# Prefixo: /assistente-juridico

/                  (GET)        - Interface do chat
/api               (POST)       - Processar mensagem
```

### 11. **tools_bp** - Ferramentas
```python
# Arquivo: app/blueprints/tools.py
# Prefixo: /tools

/document-summary                    (GET)        - Lista resumos
/document-summary/upload             (GET/POST)   - Upload para resumo
/document-summary/<int:document_id>  (GET)        - Visualizar resumo
/document-summary/<int:document_id>/delete (POST) - Excluir resumo
```

### 12. **settings_bp** - Configurações
```python
# Arquivo: app/blueprints/settings.py
# Prefixo: /settings

/law-firm          (GET)        - Configurações do escritório
/law-firm          (POST)       - Atualizar configurações
```

## 🔄 Como Registrar um Novo Blueprint

### 1. Criar arquivo em `app/blueprints/new_feature.py`

```python
from flask import Blueprint

new_feature_bp = Blueprint('new_feature', __name__, url_prefix='/new-feature')

@new_feature_bp.route('/')
def new_feature_list():
    return render_template('new_feature/list.html')

# Mais rotas...
```

### 2. Adicionar importação em `app/blueprints/__init__.py`

```python
from app.blueprints.new_feature import new_feature_bp

__all__ = [
    # ... outros blueprints
    'new_feature_bp'
]
```

### 3. Registrar em `main.py`

```python
from app.blueprints import new_feature_bp

app.register_blueprint(new_feature_bp)
```

## 🔐 Middleware e Autenticação

Todas as verificações de autenticação estão centralizadas em `app/middlewares.py`:

```python
@app.before_request
def check_session():
    """Verifica autenticação antes de cada requisição"""
    # Lógica de autenticação...

def require_law_firm(f):
    """Decorator para rotas que precisam de escritório"""
    # Lógica de verificação...
```

Use assim em seus blueprints:

```python
from app.middlewares import require_law_firm

@some_bp.route('/protected')
@require_law_firm
def protected_route():
    return render_template('protected.html')
```

## ✨ Vantagens da Estrutura

1. **Modularidade**: Cada feature tem seu próprio arquivo
2. **Manutenibilidade**: Fácil encontrar e editar rotas
3. **Escalabilidade**: Simples adicionar novos blueprints
4. **Reutilização**: Decoradores e helpers compartilhados
5. **Organização**: Estrutura clara e profissional
6. **Sem quebras**: Sistema continua funcionando normalmente

## 📝 Notas Importantes

- O arquivo `app/routes.py` está **depreciado** mas mantido para compatibilidade
- Não adicione novas rotas ao `app/routes.py` - use os blueprints
- Todos os blueprints são registrados automaticamente em `main.py`
- Use o prefixo `url_prefix` nos blueprints para manter consistência
- Nomes de blueprints devem ser únicos (ex: `'cases'`, `'clients'`, etc.)

## 🚀 Proximos Passos

1. Remover o arquivo `app/routes.py` quando tudo estiver funcionando
2. Adicionar testes unitários por blueprint
3. Documentar APIs REST em Swagger/OpenAPI
4. Implementar versionamento de APIs

---

**Estrutura criada em**: 11 de janeiro de 2026
**Sistema**: Intellexia - Gestão Jurídica com IA
