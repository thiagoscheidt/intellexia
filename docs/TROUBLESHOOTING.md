# 🔧 Troubleshooting & FAQ - Rotas com Blueprints

## ❓ Perguntas Frequentes

### P: O sistema está quebrado?
**R:** Não! Tudo funciona igual. A mudança foi apenas **organizacional**, não funcional.

### P: Preciso alterar meu frontend?
**R:** Não! Todas as URLs continuam idênticas.

### P: As templates funcionam?
**R:** Sim! Todos os `url_for()` continuam funcionando normalmente.

### P: Meu banco de dados foi afetado?
**R:** Não! Nenhuma mudança no banco. Os dados estão intactos.

### P: Posso remover o arquivo `routes.py`?
**R:** Ainda não! Deixe por compatibilidade. Será removido em versão futura.

---

## 🐛 Problemas Comuns & Soluções

### Erro 1: "ImportError: cannot import name 'xyz_bp' from 'app.blueprints'"

**Causa**: Blueprint não foi importado em `app/blueprints/__init__.py`

**Solução**:
```python
# app/blueprints/__init__.py
from app.blueprints.novo_blueprint import novo_bp  # ← Adicione

__all__ = [
    # ... outros
    'novo_bp'  # ← Adicione aqui
]
```

---

### Erro 2: "AssertionError: "Blueprint 'nome' is already registered with app"

**Causa**: Blueprint foi registrado duas vezes em `main.py`

**Solução**:
```python
# main.py
# Remova linhas duplicadas:
# ❌ app.register_blueprint(cases_bp)
# ❌ app.register_blueprint(cases_bp)  ← Duplicata

# ✅ Deixe apenas uma
app.register_blueprint(cases_bp)
```

---

### Erro 3: "Werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'xyz.abc'"

**Causa**: `url_for()` usando nome de blueprint errado

**Solução**:
```python
# ❌ ERRADO
url_for('cases_detail', case_id=1)  # Sem o blueprint

# ✅ CORRETO
url_for('cases.case_detail', case_id=1)  # Com blueprint
# Padrão: url_for('blueprint_name.function_name', **params)
```

**Blueprint names:**
- `'auth'` - auth.py
- `'dashboard'` - dashboard.py
- `'cases'` - cases.py
- `'clients'` - clients.py
- `'lawyers'` - lawyers.py
- `'courts'` - courts.py
- `'benefits'` - benefits.py
- `'documents'` - documents.py
- `'petitions'` - petitions.py
- `'assistant'` - assistant.py
- `'tools'` - tools.py
- `'settings'` - settings.py

---

### Erro 4: "TypeError: The view function did not return a valid response"

**Causa**: Falta retorno na função da rota

**Solução**:
```python
# ❌ ERRADO
@cases_bp.route('/')
def cases_list():
    cases = Case.query.all()
    # Falta return!

# ✅ CORRETO
@cases_bp.route('/')
def cases_list():
    cases = Case.query.all()
    return render_template('cases/list.html', cases=cases)
```

---

### Erro 5: "Endpoint 'auth.login' not found"

**Causa**: `url_for()` usando endpoint que não existe

**Solução**:
```python
# Verifique o nome da função em auth.py:
@auth_bp.route('/login')
def login():  # ← Nome é 'login'
    ...

# Então use:
url_for('auth.login')  # ✅ Correto
url_for('auth.signin')  # ❌ Errado (função se chama 'login')
```

---

## 📋 Checklist de Novo Blueprint

Seguir estes passos ao criar novo blueprint:

### 1. Criar arquivo
```python
# app/blueprints/novo_feature.py
from flask import Blueprint

novo_feature_bp = Blueprint(
    'novo_feature',          # ← Nome único
    __name__,
    url_prefix='/novo-feature'  # ← Prefixo da URL
)

@novo_feature_bp.route('/')
def index():
    return render_template('novo_feature/index.html')
```

### 2. Adicionar em `__init__.py`
```python
# app/blueprints/__init__.py
from app.blueprints.novo_feature import novo_feature_bp  # ← Importar

__all__ = [
    # ... outros
    'novo_feature_bp'  # ← Exportar
]
```

### 3. Registrar em `main.py`
```python
# main.py
from app.blueprints import (
    # ... outros
    novo_feature_bp  # ← Importar
)

app.register_blueprint(novo_feature_bp)  # ← Registrar
```

### 4. Testar
```bash
# Em template, use:
url_for('novo_feature.index')  # ✅ Deve funcionar

# Em Python:
from flask import url_for
url_for('novo_feature.index')  # ✅ Deve funcionar
```

---

## 🧪 Testando as Rotas

### Teste 1: Verificar se aplicação carrega

```bash
cd /Users/thiagoscheidt/Projects/intellexia
source .venv/bin/activate

python -c "from main import app; print('✓ OK - App carregado')"
```

**Esperado**: Nenhum erro

---

### Teste 2: Verificar blueprints registrados

```bash
python << 'EOF'
from main import app

print("\n📋 Blueprints registrados:")
for blueprint in app.blueprints:
    print(f"  ✓ {blueprint}")

print(f"\n📊 Total: {len(app.blueprints)} blueprints")
EOF
```

**Esperado**: 12 blueprints listados

---

### Teste 3: Verificar rotas

```bash
python << 'EOF'
from main import app

print("\n🔗 Rotas registradas:")
for rule in app.url_map.iter_rules():
    if not rule.rule.startswith('/static'):
        print(f"  {rule.rule:40} -> {rule.endpoint}")
EOF
```

**Esperado**: Todas as rotas listadas

---

### Teste 4: Testar rota específica

```bash
# No terminal
curl http://localhost:5000/api/health

# Esperado: {"status": "healthy"}
```

---

## 🔍 Debug Mode

### Ativar debug verbose

```python
# Adicione em main.py, após criar app:
import logging
logging.basicConfig(level=logging.DEBUG)

# Depois rode:
python main.py
```

### Ver stack trace completo

```python
# Em uma rota, adicione:
try:
    # seu código
    pass
except Exception as e:
    import traceback
    print(traceback.format_exc())  # ← Ver erro completo
```

---

## 📝 Logs Úteis

### Log de requisição

```python
# Em um blueprint:
@some_bp.route('/test')
def test():
    from flask import request
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Endpoint: {request.endpoint}")
    print(f"Remote addr: {request.remote_addr}")
    return "OK"
```

### Log de blueprint

```python
# Em __init__.py:
import logging
logger = logging.getLogger(__name__)
logger.info(f"Blueprint cases loaded: {cases_bp}")
```

---

## 🚀 Otimizações

### Carregamento lazy (importação sob demanda)

```python
# Em um blueprint, se precisar de imports pesados:

@some_bp.route('/heavy')
def heavy_route():
    # Importar apenas quando necessário
    from expensive_module import function
    return function()
```

### Cache de templates

```python
# Em main.py:
app.config['TEMPLATES_AUTO_RELOAD'] = False  # Produção
app.config['TEMPLATES_AUTO_RELOAD'] = True   # Desenvolvimento
```

---

## 📊 Monitoramento

### Ver uso de memória

```bash
# Terminal
ps aux | grep python
```

### Profile de performance

```python
# Em main.py:
from werkzeug.middleware.profiler import ProfilerMiddleware

if app.config['DEBUG']:
    app.wsgi_app = ProfilerMiddleware(app.wsgi_app)
```

---

## 🔐 Segurança

### Verificar autenticação em debug

```python
# Em uma rota:
@some_bp.route('/debug')
def debug():
    from flask import session
    print(f"Session: {session}")
    print(f"User ID: {session.get('user_id')}")
    print(f"Law Firm ID: {session.get('law_firm_id')}")
    return "Veja console"
```

### Validar permissões

```python
# Use o decorator:
from app.middlewares import require_law_firm

@some_bp.route('/protegido')
@require_law_firm
def protegido():
    return "Você passou pela autenticação!"
```

---

## 🆘 Como Pedir Ajuda

Se encontrar erro, prepare:

1. **Mensagem de erro exata**
   - Copie o stack trace completo

2. **O que você estava fazendo**
   - Qual URL acessou
   - Qual ação realizou

3. **Código relevante**
   - Sua rota/função
   - Seu template

4. **Contexto**
   - Qual blueprint
   - Qual arquivo

---

## 📚 Recursos Adicionais

### Documentação Interna
- `ESTRUTURA_BLUEPRINTS.md` - Guia completo de rotas
- `MIGRACAO_ROTAS.md` - Como adicionar novas rotas
- `ARQUITETURA_VISUAL.md` - Diagramas visuais

### Documentação Externa
- [Flask Blueprints](https://flask.palletsprojects.com/en/latest/blueprints/)
- [Flask url_for()](https://flask.palletsprojects.com/en/latest/api/#flask.url_for)
- [Werkzeug Routing](https://werkzeug.palletsprojects.com/en/latest/routing/)

---

## ✅ Verificação Final

Execute este checklist:

- [ ] Aplicação carrega sem erros
- [ ] Blueprints aparecem em debug
- [ ] Rotas funcionam em browser
- [ ] Templates renderizam
- [ ] Banco de dados funciona
- [ ] Autenticação funciona
- [ ] `url_for()` funciona em templates
- [ ] Nenhum erro em console

Se tudo passar ✓, seu sistema está pronto!

---

## 🎓 Próximos Passos

1. Revisar `ESTRUTURA_BLUEPRINTS.md`
2. Adicionar nova funcionalidade em blueprint existente
3. Criar novo blueprint de teste
4. Implementar testes unitários

---

**Dúvidas? Consulte a documentação ou revise os blueprints!**

🗓️ Atualizado: 11 de janeiro de 2026
