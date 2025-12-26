# Sistema de Autenticação Multi-Tenant - IntellexIA

## Visão Geral

O sistema foi atualizado para incluir autenticação robusta baseada em escritórios de advocacia (multi-tenant). Cada usuário pertence a um escritório (`law_firm`) e ao se autenticar, tem acesso apenas aos dados do seu escritório.

## Tabelas Criadas

### 1. Tabela `law_firms`
Representa os escritórios de advocacia que usam o sistema.

**Campos principais:**
- `id`: ID único do escritório
- `name`: Razão social
- `trade_name`: Nome fantasia
- `cnpj`: CNPJ único do escritório
- `street`, `number`, `city`, `state`, `zip_code`: Endereço completo
- `phone`, `email`, `website`: Contatos
- `is_active`: Status do escritório (ativo/inativo)
- `subscription_plan`: Plano de assinatura (trial, basic, premium, enterprise)
- `subscription_expires_at`: Data de expiração da assinatura
- `max_users`: Número máximo de usuários permitidos
- `max_cases`: Número máximo de casos permitidos

### 2. Tabela `users`
Representa os usuários do sistema.

**Campos principais:**
- `id`: ID único do usuário
- `law_firm_id`: FK para o escritório do usuário
- `name`: Nome completo
- `email`: Email único (usado para login)
- `password_hash`: Senha criptografada (bcrypt)
- `oab_number`: Número da OAB (opcional)
- `phone`: Telefone
- `role`: Papel do usuário (admin, lawyer, assistant, user)
- `is_active`: Status do usuário (ativo/inativo)
- `is_verified`: Email verificado
- `last_login`: Data do último login
- `last_activity`: Data da última atividade

## Funcionalidades Implementadas

### Autenticação Segura
- Senhas criptografadas com Werkzeug Security (bcrypt)
- Validação de credenciais no banco de dados
- Verificação de status do usuário e escritório
- Sessão com dados do usuário e escritório

### Registro de Novos Usuários
- Criação simultânea de escritório e primeiro usuário
- Validação de CNPJ e email únicos
- Primeiro usuário recebe role 'admin'
- Validação de força de senha (mínimo 6 caracteres)

### Sessão Multi-Tenant
Ao fazer login, a sessão armazena:
```python
session['user_id'] = user.id
session['user_email'] = user.email
session['user_name'] = user.name
session['user_role'] = user.role
session['law_firm_id'] = user.law_firm_id
session['law_firm_name'] = user.law_firm.name
```

### Métodos do Modelo User

```python
# Definir senha
user.set_password('minha_senha')

# Verificar senha
user.check_password('minha_senha')  # Retorna True/False

# Obter dados do usuário como dicionário
user.to_dict()  # Retorna dict com dados do usuário e law_firm
```

## Migração

Execute o script de migração para criar as tabelas e dados de teste:

```bash
python migrate_add_users_lawfirms.py
```

### Dados de Teste Criados

**Escritório Demo:**
- Nome: Escritório de Advocacia Demo
- CNPJ: 00000000000191

**Usuário Administrador:**
- Email: admin@demo.com.br
- Senha: admin123
- Role: admin

**Usuário Regular:**
- Email: usuario@demo.com.br
- Senha: usuario123
- Role: lawyer

## Próximos Passos

### 1. Filtro por Law Firm
Adicione filtros nas queries para mostrar apenas dados do escritório do usuário:

```python
# Exemplo: Listar casos do escritório
cases = Case.query.filter_by(
    law_firm_id=session['law_firm_id']
).all()
```

### 2. Atualizar Models Existentes
Adicione `law_firm_id` nas tabelas que devem ser isoladas por escritório:
- Client
- Case
- Lawyer
- Court (opcional, pode ser compartilhado)

### 3. Middleware de Isolamento
Crie um decorator para garantir isolamento automático:

```python
from functools import wraps

def require_law_firm_context(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'law_firm_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
```

### 4. Permissões por Role
Implemente controle de acesso baseado em roles:

```python
def require_role(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('user_role') != role:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Uso
@app.route('/admin/users')
@require_role('admin')
def admin_users():
    # Apenas admins podem acessar
    pass
```

### 5. Gestão de Usuários
Crie rotas para:
- Listar usuários do escritório
- Adicionar novos usuários
- Editar usuários
- Desativar usuários
- Alterar roles

### 6. Perfil e Configurações
- Página de perfil do usuário
- Alterar senha
- Atualizar dados pessoais
- Configurações do escritório (apenas admin)

### 7. Auditoria
Adicione logs de auditoria:
- Quem criou/editou cada registro
- Histórico de alterações
- Logs de acesso

### 8. Recuperação de Senha
Implementar sistema completo:
- Envio de email com token
- Validação de token
- Página para redefinir senha

## Segurança

### Boas Práticas Implementadas
✅ Senhas criptografadas (nunca armazenadas em texto plano)
✅ Validação de email e senha
✅ Verificação de usuário ativo
✅ Verificação de escritório ativo
✅ Sessões com dados isolados por escritório
✅ Atualização de última atividade

### Melhorias Recomendadas
- [ ] Rate limiting para login (prevenir brute force)
- [ ] Two-factor authentication (2FA)
- [ ] Política de expiração de senha
- [ ] Histórico de senhas (não permitir reutilização)
- [ ] Bloqueio automático após X tentativas falhas
- [ ] Logs de tentativas de login
- [ ] CSRF protection
- [ ] Content Security Policy (CSP)

## Estrutura de Permissões Sugerida

| Role | Permissões |
|------|-----------|
| **admin** | Acesso total ao escritório, gerenciar usuários, configurações |
| **lawyer** | Criar e gerenciar casos, clientes, documentos |
| **assistant** | Visualizar casos, adicionar documentos, não pode criar casos |
| **user** | Apenas visualização, relatórios |

## Exemplo de Uso

```python
from app.models import User, LawFirm

# Criar novo escritório
law_firm = LawFirm(
    name="Meu Escritório",
    cnpj="12345678000190",
    is_active=True
)
db.session.add(law_firm)
db.session.flush()

# Criar usuário
user = User(
    law_firm_id=law_firm.id,
    name="João Silva",
    email="joao@escritorio.com",
    role="admin"
)
user.set_password("senha_segura_123")
db.session.add(user)
db.session.commit()

# Login
user = User.query.filter_by(email="joao@escritorio.com").first()
if user and user.check_password("senha_segura_123"):
    # Login bem-sucedido
    session['user_id'] = user.id
    session['law_firm_id'] = user.law_firm_id
```

## Suporte

Para dúvidas ou problemas, consulte a documentação ou entre em contato com o desenvolvedor.
