# Isolamento Multi-Tenant - IntellexIA

## Visão Geral

O sistema foi atualizado para implementar isolamento completo de dados por escritório de advocacia (multi-tenant). Cada registro de Cliente, Advogado, Vara e Caso agora pertence a um escritório específico, garantindo que usuários de diferentes escritórios nunca vejam ou acessem dados uns dos outros.

## Alterações nos Modelos

### Tabelas Atualizadas

Todas as seguintes tabelas receberam o campo `law_firm_id`:

1. **clients** - Clientes do escritório
2. **lawyers** - Advogados do escritório  
3. **courts** - Varas cadastradas pelo escritório
4. **cases** - Casos jurídicos do escritório

### Estrutura Adicionada

```python
law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
law_firm = db.relationship('LawFirm')
```

## Sistema de Isolamento

### Funções Helper

```python
def get_current_law_firm_id():
    """Retorna o law_firm_id do usuário logado"""
    return session.get('law_firm_id')

@require_law_firm
def require_law_firm(f):
    """Decorator para garantir que o usuário tem um escritório associado"""
```

### Proteção Automática

Todas as rotas CRUD agora:

✅ **Listagem** - Filtra automaticamente por `law_firm_id`
```python
clients = Client.query.filter_by(law_firm_id=law_firm_id).all()
```

✅ **Criação** - Adiciona automaticamente o `law_firm_id`
```python
client = Client(
    law_firm_id=get_current_law_firm_id(),
    name=form.name.data,
    ...
)
```

✅ **Edição/Exclusão** - Verifica se o registro pertence ao escritório
```python
client = Client.query.filter_by(
    id=client_id, 
    law_firm_id=law_firm_id
).first_or_404()
```

## Rotas Atualizadas

### Clientes
- `GET /clients` - Lista apenas clientes do escritório
- `POST /clients/new` - Cria cliente vinculado ao escritório
- `GET/POST /clients/<id>/edit` - Edita apenas se pertencer ao escritório
- `POST /clients/<id>/delete` - Exclui apenas se pertencer ao escritório

### Advogados
- `GET /lawyers` - Lista apenas advogados do escritório
- `POST /lawyers/new` - Cria advogado vinculado ao escritório
- `GET/POST /lawyers/<id>/edit` - Edita apenas se pertencer ao escritório
- `POST /lawyers/<id>/delete` - Exclui apenas se pertencer ao escritório

### Varas Judiciais
- `GET /courts` - Lista apenas varas do escritório
- `POST /courts/new` - Cria vara vinculada ao escritório
- `GET/POST /courts/<id>/edit` - Edita apenas se pertencer ao escritório
- `POST /courts/<id>/delete` - Exclui apenas se pertencer ao escritório

### Casos
- `GET /cases` - Lista apenas casos do escritório
- `POST /cases/new` - Cria caso vinculado ao escritório
- `GET/POST /cases/<id>/edit` - Edita apenas se pertencer ao escritório
- `POST /cases/<id>/delete` - Exclui apenas se pertencer ao escritório

### Dashboard
- Estatísticas filtradas por escritório
- Dados isolados automaticamente

## Migração

### Executar Migração

Para adicionar a coluna `law_firm_id` nas tabelas existentes:

```bash
python migrate_add_law_firm_id.py
```

### O que a Migração Faz

1. ✅ Adiciona coluna `law_firm_id` em clients, lawyers, courts, cases
2. ✅ Associa todos os registros existentes ao primeiro escritório
3. ✅ Define a coluna como NOT NULL
4. ✅ Cria índices para melhor performance
5. ✅ Mostra relatório detalhado das mudanças

### Saída Esperada

```
============================================================
MIGRAÇÃO: Adicionar law_firm_id para isolamento multi-tenant
============================================================

📌 Usando escritório padrão: Escritório de Advocacia Demo (ID: 1)

1. Migrando tabela 'clients'...
   ✓ Coluna adicionada e populada com law_firm_id=1

2. Migrando tabela 'lawyers'...
   ✓ Coluna adicionada e populada com law_firm_id=1

3. Migrando tabela 'courts'...
   ✓ Coluna adicionada e populada com law_firm_id=1

4. Migrando tabela 'cases'...
   ✓ Coluna adicionada e populada com law_firm_id=1

============================================================
✅ MIGRAÇÃO CONCLUÍDA COM SUCESSO!
============================================================
```

## Segurança

### Proteções Implementadas

1. **Isolamento de Dados**
   - Escritórios nunca veem dados de outros
   - Queries automáticas com filtro por `law_firm_id`

2. **Validação de Acesso**
   - Decorator `@require_law_firm` em todas as rotas
   - Verificação automática de propriedade nos registros

3. **404 em Tentativas de Acesso**
   - Retorna 404 se tentar acessar registro de outro escritório
   - Nunca revela existência de dados de outros

4. **Proteção no Nível do Banco**
   - Foreign keys garantem integridade referencial
   - Índices garantem performance nas queries filtradas

## Exemplo de Uso

### Antes (Sem Isolamento)
```python
# ❌ Todos viam todos os clientes
clients = Client.query.all()
```

### Depois (Com Isolamento)
```python
# ✅ Cada escritório vê apenas seus clientes
@require_law_firm
def clients_list():
    law_firm_id = get_current_law_firm_id()
    clients = Client.query.filter_by(law_firm_id=law_firm_id).all()
```

## Verificação

### Testar Isolamento

1. **Criar dois escritórios diferentes**
2. **Criar usuários em cada escritório**
3. **Login com usuário do Escritório A**
   - Criar alguns clientes, casos, etc.
4. **Logout e login com usuário do Escritório B**
   - Verificar que não vê dados do Escritório A
   - Criar seus próprios dados
5. **Confirmar isolamento total**

### Query Manual para Verificar

```python
# Ver todos os clientes e seus escritórios
SELECT c.id, c.name, lf.name as law_firm_name 
FROM clients c 
JOIN law_firms lf ON c.law_firm_id = lf.id;
```

## Impacto nas Funcionalidades

### ✅ Funcionando Automaticamente
- Listagens (filtradas por escritório)
- Criação (com law_firm_id automático)
- Edição (com verificação de propriedade)
- Exclusão (com verificação de propriedade)
- Dashboard (estatísticas isoladas)
- Relacionamentos (Client → Cases, etc.)

### ⚠️ Requer Atenção
- APIs externas que criam dados (precisam receber law_firm_id)
- Importações em massa (devem incluir law_firm_id)
- Relatórios consolidados (se necessário acesso multi-tenant)

## Próximos Passos Recomendados

### 1. Auditoria Adicional
```python
# Adicionar campos de auditoria
created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
updated_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
```

### 2. Logs de Acesso
```python
# Log de todas as operações CRUD
@app.after_request
def log_access(response):
    if request.endpoint not in ['static']:
        # Log: user, action, resource, timestamp
    return response
```

### 3. Backup por Escritório
```python
# Script para backup de dados de um escritório específico
def backup_law_firm_data(law_firm_id):
    # Export all data for specific law firm
    pass
```

### 4. Relatórios Multi-Tenant (Admin Global)
```python
# Para administradores do sistema (não do escritório)
@require_system_admin
def global_stats():
    # Estatísticas de todos os escritórios
    pass
```

## Troubleshooting

### Erro: "law_firm_id não pode ser NULL"
**Causa**: Tentando criar registro sem law_firm_id  
**Solução**: Certifique-se de usar `get_current_law_firm_id()` na criação

### Erro: "404 Not Found" ao editar registro
**Causa**: Registro pertence a outro escritório  
**Solução**: Verificar se usuário está logado no escritório correto

### Registros "perdidos" após migração
**Causa**: Registros antigos sem law_firm_id  
**Solução**: Executar script de migração novamente

## Contato

Para dúvidas sobre o sistema multi-tenant, consulte a documentação ou entre em contato com o desenvolvedor.
