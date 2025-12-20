# Dashboard do Sistema Intellexia

## 📊 Visão Geral

O Dashboard do Sistema Intellexia fornece uma visão centralizada e em tempo real de todas as métricas importantes do sistema de gerenciamento de casos jurídicos trabalhistas.

## 🎯 Funcionalidades

### Métricas Principais
- **Total de Casos**: Contador geral de todos os casos no sistema
- **Casos Ativos**: Casos em andamento
- **Clientes**: Total de empresas clientes
- **Benefícios**: Total de benefícios previdenciários relacionados aos casos

### Estatísticas Detalhadas
- **Casos por Status**: Distribuição entre ativos, rascunhos, protocolados, etc.
- **Casos por Tipo**: Distribuição entre tipos de caso (FAP Trajeto, FAP Nexo, Auto de Infração, etc.)
- **Valor Total das Causas**: Soma de todos os valores de causa em R$
- **Documentos**: Total de documentos e quantos estão disponíveis para IA

### Casos Recentes
- Lista dos 5 casos mais recentes
- Informações resumidas: título, cliente, status, data de criação
- Link direto para visualização detalhada de cada caso

### Ações Rápidas
- **Novo Caso**: Acesso direto ao formulário de criação de caso
- **Novo Cliente**: Criação rápida de empresa cliente
- **Novo Advogado**: Cadastro de novo advogado
- **Navegação**: Links para todas as listagens principais

## 🚀 Acesso

### URL do Dashboard
```
/dashboard  (rota principal)
/           (redireciona para /dashboard)
```

### Menu de Navegação
O dashboard está disponível no sidebar principal:
- Dashboard → Dashboard Principal

## 📈 Métricas Calculadas

### Casos
- **Total**: `Case.query.count()`
- **Ativos**: `Case.query.filter_by(status='active').count()`
- **Rascunhos**: `Case.query.filter_by(status='draft').count()`
- **Protocolados**: Casos com `filing_date` não nulo

### Clientes e Advogados
- **Total de Clientes**: `Client.query.count()`
- **Clientes com Filiais**: `Client.query.filter_by(has_branches=True).count()`
- **Total de Advogados**: `Lawyer.query.count()`

### Benefícios
- **Total**: `CaseBenefit.query.count()`
- **Tipo B91**: `CaseBenefit.query.filter_by(benefit_type='B91').count()`
- **Tipo B94**: `CaseBenefit.query.filter_by(benefit_type='B94').count()`

### Documentos
- **Total**: `Document.query.count()`
- **Para IA**: `Document.query.filter_by(use_in_ai=True).count()`

### Valores
- **Valor Total**: Soma de `Case.value_cause` de todos os casos

## 🎨 Interface

### Cards de Métricas
- **Azul (Primary)**: Total de casos
- **Verde (Success)**: Casos ativos
- **Amarelo (Warning)**: Clientes
- **Azul claro (Info)**: Benefícios

### Tabela de Casos Recentes
- Título truncado (40 caracteres)
- Cliente truncado (25 caracteres)
- Badge colorido para status
- Data formatada (DD/MM/AAAA)
- Botão de visualização com ícone de olho

### Distribuições
- **Por Tipo**: Lista com badges mostrando quantidade por tipo de caso
- **Por Status**: Lista com badges coloridos por status

## 🔧 Configuração Técnica

### Template
- **Arquivo**: `templates/dashboard.html`
- **Herda de**: `layout/base.html`
- **Ícones**: Bootstrap Icons

### Rota
- **Rota Principal**: `/` (redireciona para `/dashboard`)
- **Rota Dashboard**: `/dashboard`
- **Função**: `dashboard()` em `app/routes.py`
- **Método**: GET
- **Autenticação**: Necessária (via `@app.before_request`)

### Tratamento de Erros
- Try/catch em todas as consultas ao banco
- Flash message em caso de erro
- Renderização do template mesmo com falha nas consultas

## 📱 Responsividade

- **Desktop**: Layout em 3-4 colunas
- **Tablet**: Layout adaptativo
- **Mobile**: Cards empilhados

### Classes Bootstrap Utilizadas
- `col-lg-3 col-6`: Cards principais responsivos
- `col-md-8 col-md-4`: Layout de 2 colunas em telas médias
- `table-responsive`: Tabelas adaptáveis
- `d-grid gap-2`: Botões empilhados

## 📊 Dados de Exemplo

Para testar o dashboard com dados realistas, execute:

```bash
python populate_sample_data.py
```

Isso criará:
- 4 empresas clientes
- 5 varas judiciais
- 4 advogados
- 4 casos completos
- 6 benefícios previdenciários
- Competências mensais para casos FAP

## 🔍 Debugging

Para verificar se o dashboard está funcionando:

```bash
python test_dashboard.py
```

## 🚀 Próximas Melhorias

- [ ] Gráficos interativos (Chart.js)
- [ ] Filtros por período
- [ ] Export de relatórios
- [ ] Dashboard em tempo real (WebSocket)
- [ ] Métricas de performance
- [ ] Alertas e notificações
- [ ] Comparação período anterior