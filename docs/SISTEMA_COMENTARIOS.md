# 💬 Sistema de Comentários e Discussões Internas

## Visão Geral

Foi implementado um sistema completo de comentários e discussões internas para permitir que os advogados se comuniquem dentro dos casos sem sair da plataforma.

## 🎯 Recursos Implementados

### 1. **Comentários Principais**
- Adicionar comentários com título (opcional) e conteúdo
- Visualizar todos os comentários em ordem cronológica
- Fixar comentários importantes (aparecem no topo)
- Marcar comentários como resolvidos
- Editar/deletar próprios comentários
- Respostas em thread (repostas aos comentários)

### 2. **Sistema de Threads**
- Responder diretamente a um comentário
- Visualizar todas as respostas de um comentário
- Thread expandível/recolhível
- Até 3 níveis de profundidade

### 3. **Notificações e Mentions**
- Mencionar outros advogados usando @
- Notificações para usuários mencionados
- JSON array armazenando IDs dos mencionados

### 4. **Timeline de Atividades**
- Registro automático de todas as ações:
  - Novos comentários
  - Respostas a comentários
  - Alterações de status
  - Documentos adicionados
  - Advogados vinculados

### 5. **Controle de Acesso**
- Apenas usuários do mesmo escritório podem acessar
- Apenas o autor ou admin podem editar/deletar
- Admin pode marcar como resolvido
- Validação em cada operação

## 📊 Estrutura de Dados

### Tabela: `case_activities`
```
- id: Integer (PK)
- case_id: Integer (FK)
- user_id: Integer (FK)
- activity_type: String (comment, status_change, etc)
- title: String
- description: Text
- related_id: Integer (ID do recurso relacionado)
- created_at: DateTime
- updated_at: DateTime
```

### Tabela: `case_comments`
```
- id: Integer (PK)
- case_id: Integer (FK)
- user_id: Integer (FK)
- comment_type: String (internal, external, note)
- title: String (opcional)
- content: Text
- parent_comment_id: Integer (FK para resposta em thread)
- is_pinned: Boolean
- is_resolved: Boolean
- resolved_by_id: Integer (FK)
- resolved_at: DateTime
- mentions: JSON (array de user_ids)
- created_at: DateTime
- updated_at: DateTime
```

## 🔌 Endpoints da API

### Comentários
```
GET    /cases/<case_id>/comments/              - Lista comentários principais
POST   /cases/<case_id>/comments/              - Adiciona novo comentário
GET    /cases/<case_id>/comments/<id>/replies  - Obtém respostas
POST   /cases/<case_id>/comments/<id>/reply    - Adiciona resposta
PUT    /cases/<case_id>/comments/<id>          - Atualiza comentário
DELETE /cases/<case_id>/comments/<id>          - Deleta comentário
POST   /cases/<case_id>/comments/<id>/pin      - Fixar/desafixar
POST   /cases/<case_id>/comments/<id>/resolve  - Marcar resolvido
```

### Timeline
```
GET    /cases/<case_id>/comments/timeline      - Lista atividades do caso
```

## 💻 Como Usar

### No Frontend (HTML)
```html
<!-- Incluir a seção de comentários -->
{% include 'cases/comments_section.html' %}
```

### JavaScript
Os comentários são carregados automaticamente e atualizam a cada 30 segundos.

**Funções Disponíveis:**
- `loadComments()` - Recarrega comentários
- `saveComment()` - Salva novo comentário
- `saveReply()` - Responde a comentário
- `togglePin(commentId)` - Fixa/desafixa
- `deleteComment(commentId)` - Deleta
- `showReplyForm(commentId)` - Abre modal de resposta
- `loadReplies(commentId)` - Carrega respostas em thread

## 🎨 Interface

### Modal de Novo Comentário
- Título (opcional)
- Conteúdo (required)
- Tipo (Internal/Note)
- Botões: Cancelar, Enviar

### Card de Comentário
- Avatar e nome do autor
- Timestamp com formato relativo (2h atrás, etc)
- Badge de fixado (⚠️ amarelo)
- Badge de resolvido (✓ verde)
- Botões de ação (Editar, Fixar, Deletar)
- Contador de respostas
- Botão para responder

### Respostas em Thread
- Cards menores com fundo secundário
- Editar/deletar inline
- Sempre alinhadas ao comentário pai

## 🔄 Fluxo de Uso

1. **Usuário abre página de detalhes do caso**
   - Seção de comentários aparece na coluna principal
   - Comentários são carregados automaticamente

2. **Clica "Novo Comentário"**
   - Modal abre
   - Preenche título (opcional) e comentário
   - Clica "Enviar Comentário"

3. **Comentário é salvo**
   - Atividade registrada em `case_activities`
   - Comentário aparece na lista
   - Se houver mentions, usuários são notificados

4. **Outro usuário vê comentário**
   - Pode responder diretamente
   - Pode fixar se for importante
   - Admin pode marcar como resolvido

5. **Busca automática**
   - A cada 30s os comentários são recarregados
   - Novas respostas aparecem em tempo real

## 📱 Responsividade

- Layout adaptativo para desktop/tablet/mobile
- Scrollbar customizada com estilo
- Modais responsivas
- Botões acessíveis com ícones Bootstrap

## 🔐 Segurança

✅ Validação de acesso ao caso (law_firm_id)
✅ Validação de propriedade do comentário (user_id)
✅ Permissões específicas por role (admin)
✅ Sanitização de entrada (escapa HTML)
✅ CSRF protection via Flask

## 📈 Próximas Melhorias

- [ ] Upload de anexos nos comentários
- [ ] Notificações via email
- [ ] Lembretes automáticos
- [ ] Labels/tags customizadas
- [ ] Busca de comentários
- [ ] Reações com emojis
- [ ] Histórico de edições
- [ ] Integração com Slack/Teams

## 🛠️ Desenvolvimento

### Adicionar novo tipo de atividade:
```python
# Em case_comments.py
activity = CaseActivity(
    case_id=case_id,
    user_id=session.get('user_id'),
    activity_type='novo_tipo',  # Adicionar aqui
    title='Descrição',
    related_id=resource_id
)
db.session.add(activity)
```

### Customizar ícones de atividade:
```python
# Em case_comments.py, função get_activity_icon()
icons = {
    'novo_tipo': 'bi-novo-icone',  # Adicionar aqui
    # ...
}
```

## 📞 Suporte

Para dúvidas ou problemas, consulte:
- Endpoints: [case_comments.py](../app/blueprints/case_comments.py)
- Template: [comments_section.html](../templates/cases/comments_section.html)
- Modelos: [models.py](../app/models.py)
