# 🤖 Assistente Jurídico IntellexIA

## 📋 Visão Geral

O **Assistente Jurídico** é uma ferramenta de IA conversacional especializada em direito trabalhista, integrada ao sistema IntellexIA. Ele oferece acesso inteligente a todas as informações dos processos, casos, clientes e benefícios através de uma interface de chat moderna.

## 🎯 Funcionalidades Principais

### 💬 Interface de Chat
- **Design moderno** estilo ChatGPT
- **Conversação em tempo real** com indicador de digitação
- **Histórico de mensagens** na sessão
- **Sugestões de perguntas** para facilitar o uso
- **Interface responsiva** para desktop e mobile

### 🧠 Inteligência Artificial
- **Especialização em direito trabalhista**
- **Acesso aos dados do sistema** em tempo real
- **Respostas contextualizadas** baseadas nos casos reais
- **Análise de estatísticas** e relatórios
- **Suporte a consultas complexas**

### 📊 Tipos de Consulta Suportadas

#### Estatísticas Gerais
- Total de casos, casos ativos, rascunhos
- Número de clientes e advogados
- Quantidade de benefícios por tipo
- Valor total das causas

#### Casos FAP
- Informações sobre diferentes tipos de FAP
- Casos de trajeto, nexo causal, múltiplos benefícios
- Estatísticas específicas por tipo

#### Dados de Clientes
- Total de clientes cadastrados
- Clientes com filiais
- Informações específicas por empresa

#### Benefícios Previdenciários
- Análise por tipo (B91, B94, B31)
- Estatísticas e distribuições
- Informações contextualizadas

#### Casos Recentes
- Lista dos casos mais novos
- Detalhes por status e tipo
- Links diretos para visualização

## 🚀 Como Usar

### Acesso
1. **Menu lateral**: Clique em "Assistente Jurídico" 🤖
2. **Dashboard**: Use o botão verde "Assistente Jurídico"
3. **URL direta**: `/assistente-juridico`

### Exemplos de Perguntas
```
📊 "Quantos casos ativos temos?"
👥 "Informações sobre clientes"
⚖️ "Casos FAP no sistema"
💰 "Estatísticas de benefícios"
📋 "Quais são os casos recentes?"
📂 "Tipos de casos cadastrados"
❓ "Ajuda" - ver todas as funcionalidades
```

### Comandos Especiais
- **"ajuda"** - Lista todas as funcionalidades
- **"Nova Conversa"** - Limpa o histórico do chat
- **Enter** - Enviar mensagem
- **Shift+Enter** - Nova linha

## 🔧 Arquitetura Técnica

### Backend (Flask)
```python
# Rotas principais
@app.route('/assistente-juridico')          # Interface do chat
@app.route('/api/assistente-juridico')      # API para processar mensagens
```

### Funções Core
- `get_system_context()` - Coleta dados do sistema
- `process_legal_assistant_message()` - Processa mensagens da IA
- Integração com todos os modelos (Case, Client, Lawyer, etc.)

### Frontend
- **Template**: `templates/assistant/chat.html`
- **JavaScript**: Interação em tempo real
- **CSS**: Estilização moderna com animações
- **Bootstrap Icons**: Ícones profissionais

### API Endpoints
```javascript
POST /api/assistente-juridico
Content-Type: application/json
{
  "message": "Quantos casos ativos temos?"
}

Response:
{
  "response": "🔢 **Casos Ativos:** 15 casos...",
  "timestamp": "2025-12-20T10:30:00"
}
```

## 🎨 Interface do Usuário

### Header do Chat
- **Avatar do assistente** com ícone de robô
- **Status online** e especialização
- **Botão "Nova Conversa"** para limpar histórico

### Área de Mensagens
- **Mensagens do usuário**: Azul, alinhadas à direita
- **Mensagens do assistente**: Cinza claro, alinhadas à esquerda
- **Timestamp** em cada mensagem
- **Scroll suave** automático
- **Indicador de digitação** animado

### Área de Input
- **Textarea expansível** (auto-resize)
- **Suporte a texto multilinhas**
- **Botão de envio** com ícone
- **Placeholders informativos**

### Sugestões Rápidas
- **Botões clicáveis** com perguntas comuns
- **Animações hover** para feedback visual
- **Categorização** por tipo de consulta

## 🤖 Lógica da IA

### Processamento de Mensagens
```python
def process_legal_assistant_message(message, context):
    # Análise de palavras-chave
    # Consulta ao contexto do sistema
    # Formatação de resposta com markdown
    # Emojis e formatação profissional
```

### Contexto do Sistema
```python
context = {
    'total_cases': Case.query.count(),
    'active_cases': Case.query.filter_by(status='active').count(),
    'recent_cases': Case.query.order_by(Case.created_at.desc()).limit(3).all(),
    'case_types': db.session.query(Case.case_type, db.func.count()).group_by().all(),
    'clients_list': Client.query.all(),
    'lawyers_list': Lawyer.query.all()
}
```

### Tipos de Resposta
- **Estatísticas numéricas** com formatação visual
- **Listas organizadas** com bullets e emojis
- **Informações contextuais** baseadas nos dados reais
- **Sugestões de próximas ações**
- **Links e referências** quando aplicável

## 📱 Responsividade

### Desktop
- **Chat em tela cheia** (80vh)
- **Layout em 2 colunas** quando necessário
- **Sugestões horizontais** em linha

### Mobile/Tablet
- **Interface adaptável** com stacking
- **Textarea otimizada** para toque
- **Botões maiores** para facilitar interação

## 🔐 Segurança

### Autenticação
- **Sessão obrigatória** via `@app.before_request`
- **Validação de entrada** para prevenir XSS
- **Escape de HTML** em mensagens do usuário

### Validação de Dados
- **Sanitização** de inputs
- **Limite de caracteres** nas mensagens
- **Rate limiting** (pode ser implementado)

## 🚀 Expansões Futuras

### IA Avançada
- [ ] Integração com OpenAI GPT
- [ ] Processamento de linguagem natural
- [ ] Análise de documentos PDF
- [ ] Geração de relatórios automáticos

### Funcionalidades
- [ ] Histórico persistente de conversas
- [ ] Exportação de conversas
- [ ] Notificações push
- [ ] Integração com e-mail
- [ ] Agendamento de tarefas

### Analytics
- [ ] Métricas de uso do assistente
- [ ] Perguntas mais frequentes
- [ ] Satisfação do usuário
- [ ] Relatórios de eficiência

## 📈 Métricas de Sucesso

- **Taxa de uso** do assistente pelos usuários
- **Tempo de resposta** das consultas
- **Precisão das respostas** baseadas no feedback
- **Redução de tempo** em consultas manuais
- **Satisfação do usuário** com as respostas

## 🎯 Casos de Uso Principais

1. **Consulta rápida de estatísticas** durante reuniões
2. **Verificação de status de casos** sem navegar pelo sistema
3. **Análise de distribuição** de tipos de processo
4. **Consulta de informações de clientes** específicos
5. **Relatórios ad-hoc** para tomada de decisão
6. **Onboarding de novos usuários** com guidance

O Assistente Jurídico representa um **salto tecnológico** no sistema IntellexIA, oferecendo uma interface natural e intuitiva para acesso às informações jurídicas complexas.