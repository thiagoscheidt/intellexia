# 🚀 Guia Rápido - Sistema de Comentários

## Como os Advogados Usam

### 1️⃣ Abra um Caso
- Navigate para **Casos** no menu lateral
- Clique em um caso para ver detalhes

### 2️⃣ Localize a Seção de Discussões
- Role para baixo na coluna central
- Procure por **"💬 Discussões Internas"**

### 3️⃣ Adicione um Comentário
```
[Novo Comentário]
├─ Título (opcional): "Revisar documento CAT"
├─ Comentário: "Este documento parece estar incompleto"
├─ Tipo: Apenas Interno
└─ [Enviar Comentário]
```

### 4️⃣ Responda a um Comentário
```
[Comentário de João Silva]
├─ Conteúdo: "..."
└─ [Responder] ← Clique aqui
    ├─ [Modal abre]
    └─ Escreva sua resposta
```

### 5️⃣ Fixe Comentários Importantes
```
[Comentário]
├─ [✎ Editar] [📌 Fixar] [🗑️ Deletar]
└─ Aparece no topo!
```

### 6️⃣ Admin: Marque como Resolvido
```
[Comentário]
└─ [✓ Resolvido] ← Apenas admin pode
```

---

## 📱 Interface Visual

```
┌─────────────────────────────────────────┐
│ 💬 Discussões Internas    [+ Novo]     │
├─────────────────────────────────────────┤
│                                         │
│ 📌 [João Silva]  2h atrás              │
│    Ação Necessária                      │
│    Este documento precisa ser revisado  │
│    💬 2 respostas  [Responder]         │
│    [✎] [📌] [🗑️]                      │
│                                         │
│    ├─ [Maria Costa]  1h atrás          │
│    │  Concordo, vou verificar hoje    │
│    │  [✎] [🗑️]                        │
│    │                                   │
│    └─ [Pedro Oliveira]  45m atrás      │
│       Já fiz a revisão ✓               │
│       [✎] [🗑️]                        │
│                                         │
│ [Carlos Mendes]  30m atrás             │
│  Questão sobre prazos                  │
│  Qual é o prazo para resposta?         │
│  [Responder]                           │
│  [✎] [📌] [🗑️]                        │
│                                         │
└─────────────────────────────────────────┘
```

---

## ⌨️ Atalhos de Teclado

| Atalho              | Ação                                     |
| ------------------- | ---------------------------------------- |
| `Tab`               | Navega entre campos                      |
| `Enter` em textarea | Quebra linha                             |
| `Escape`            | Fecha modal                              |
| `Ctrl+Enter`        | Envia comentário (em alguns navegadores) |

---

## 🎨 Cores e Badges

```
┌──────────────────────┐
│ Fixado        📌 Amarelo
│ Resolvido     ✓ Verde
│ Interno       • Cinza
│ Nota Pessoal  • Azul
└──────────────────────┘
```

---

## ❌ Como Deletar um Comentário

```
1. Clique no botão 🗑️ (lixeira)
2. Confirme: "Deletar comentário?"
3. [OK] → Comentário removido
   └─ Nota: Também deleta respostas!
```

---

## ✏️ Como Editar um Comentário

```
1. Clique no botão ✎ (lápis)
2. Modal abre com seu comentário
3. Edite o conteúdo
4. Clique [Enviar Comentário]
5. ✓ Atualizado!
```

---

## 🔔 Quando Você é Mencionado

```
Alguém escreve: "@João, pode revisar?"
   ↓
João recebe notificação (próx. versão)
   ↓
João vê badge com seu nome
```

---

## ⏰ Timestamps Explicados

```
Agora mesmo   → Enviado há segundos
2m atrás      → Enviado há 2 minutos
1h atrás      → Enviado há 1 hora
2d atrás      → Enviado há 2 dias
18/01 15:30   → Data e hora completa
```

---

## 🔄 Atualização Automática

✨ A cada 30 segundos:
- Novos comentários aparecem
- Respostas são carregadas
- Timestamps se atualizam
- Sem precisar recarregar!

---

## 🎯 Boas Práticas

### ✅ Faça
- ✓ Use títulos descritivos
- ✓ Seja claro e conciso
- ✓ Mencione pessoas relevantes
- ✓ Fixe decisões importantes
- ✓ Marque como resolvido ao concluir

### ❌ Evite
- ✗ Comentários muito longos
- ✗ Usar caps (MAISCULAS)
- ✗ Informações sensíveis sem cuidado
- ✗ Deletar comentários importantes
- ✗ Respostas fora do contexto

---

## 🐛 Solucionar Problemas

### Comentário não aparece
```
1. Aguarde 30s para atualizar
2. Recarregue a página (F5)
3. Verifique se há mensagem de erro
```

### Modal não abre
```
1. Clique novamente em [Novo Comentário]
2. Recarregue a página se persistir
3. Tente em outro navegador
```

### Não consigo responder
```
1. Verifique se clicou em [Responder]
2. Escreva algo na caixa de texto
3. Clique [Responder]
```

---

## 📊 Exemplo de Caso Real

```
CASO: Revisão FAP - 2019-2021

🗨️ João (Responsável do Caso) - 10h atrás
   Título: Ação Necessária
   Conteúdo: Precisamos revisar os documentos CAT.
   [Responder] [Pin] [Delete]

  └─ Maria (Assistente) - 9h atrás
     Já iniciamos. Encontrei inconsistências.
     
  └─ Pedro (Analista) - 8h atrás
     Qual é o prazo para conclusão?

🗨️ Carlos (Admin) - 5h atrás  ✓ RESOLVIDO
   Título: Documentação Completa
   Conteúdo: Todos os documentos foram validados.
   [Responder] [Pin] [Delete]
```

---

## 💬 FAQ

**P: Todos no escritório veem meus comentários?**
A: Sim, comentários "Apenas Interno" são vistos por quem tem acesso ao caso.

**P: Posso deletar comentários de outros?**
A: Não, apenas admin pode. Você só deleta seus próprios.

**P: Os comentários ficam salvos?**
A: Sim, eternamente. Mesmo deletados, ficam em backup.

**P: Posso usar @ mention?**
A: Sim! Digite @ e o nome aparece (próx. versão com notificações).

**P: E se eu digitar algo errado?**
A: Clique no ✎ para editar! Aparece "editado" no histórico.

---

## 📞 Precisa de Ajuda?

- 📖 Documentação: [SISTEMA_COMENTARIOS.md](docs/SISTEMA_COMENTARIOS.md)
- 🐛 Reportar Bug: Fale com seu administrador
- 💡 Sugestão: Envie feedback ao time

---

**Dúvidas? Pergunte a um colega ou ao admin!** 🙋
