# 📝 Changelog - Base de Conhecimento

Todas as atualizações e mudanças notáveis neste projeto estão documentadas neste arquivo.

## [2.0.0] - 30 de Janeiro de 2026

### ✨ Adicionado

#### 🤖 Resumos Automáticos com IA (Feature Principal)
- **Integração com OpenAI gpt-5-mini** para geração automática de resumos
- **Classe `AgentDocumentSummary`** em `app/agents/agent_document_summary.py`
  - Suporta conversão de múltiplos formatos (PDF, DOCX, PPTX, Excel, imagens)
  - Truncamento automático de documentos grandes (24KB configurável)
  - Prompt especializado para contexto jurídico
  
#### 📊 Estrutura de Resumos em JSON
- **Resumo curto**: Síntese de 1-2 linhas
- **Resumo longo**: Versão completa e detalhada
- **Pontos-chave**: Lista de destaques principais
- **Metadados**: Idioma, contagem de palavras, tempo de processamento

#### 🗂️ Tabela `knowledge_summaries`
- Armazenamento JSON estruturado de resumos
- Relacionamento direto com documentos (FK)
- Histórico de criação e atualização

#### 🎨 Interface Visual para Resumos
- Card dedicado na página de detalhes
- Abas para visualização de diferentes resumos
- Lista formatada de pontos-chave
- Botão "Gerar Resumo" com feedback visual
- Loading spinner durante processamento

#### 🔌 Endpoint da API
- `POST /knowledge-base/<id>/generate-summary` - Geração de resumos
- Resposta JSON com status e mensagem
- Suporte a regeneração de resumos existentes

### 🔧 Modificado

#### `app/blueprints/knowledge_base.py`
- Importação da classe `AgentDocumentSummary`
- Importação do modelo `KnowledgeSummary`
- Atualização da função `details()` para carregar resumo existente
- Implementação completa da função `generate_summary()`

#### `app/models.py`
- Adição do modelo `KnowledgeSummary`
- Campos: id, knowledge_base_id, payload (JSON), created_at, updated_at

#### `templates/knowledge_base/details.html`
- Novo card de resumo com gradient header verde
- Abas para resumo curto e longo
- Seção de pontos-chave com lista formatada
- Botão interativo "Gerar Resumo com IA"
- Função JavaScript `generateSummary()` para chamada assíncrona

#### `database/add_knowledge_summaries_table.py`
- Script de migração para criar tabela
- Índices para otimização de queries
- Relacionamento com tabela `knowledge_base`

### 📚 Documentação

#### `docs/BASE_CONHECIMENTO.md`
- Criado arquivo de documentação completa
- Seção detalhada sobre implementação de resumos
- Fluxo de processamento com diagrama
- Configuração necessária de variáveis de ambiente
- Exemplos de payload JSON

#### `docs/INDEX.md`
- Adicionada referência a `BASE_CONHECIMENTO.md`
- Link destacado na seção de Funcionalidades

### ⚙️ Configuração

Variáveis de ambiente necessárias (`.env`):
```
OPENAI_API_KEY=sk-xxxxx              # Chave da API OpenAI
SUMMARY_MAX_CHARS=24000              # Limite de caracteres para resumo
```

### 🚀 Melhorias de Performance

- Truncamento automático de documentos em 24KB
- Cache de resumos evita reprocessamento
- Índices no banco para queries rápidas
- Processamento assíncrono com feedback ao usuário

### 🔐 Segurança

- Verificação de autorização (law_firm_id) em todos os endpoints
- Soft-delete respeitado na recuperação
- Isolamento multi-tenant mantido
- Chave da API armazenada em variáveis de ambiente

### 📦 Dependências Novas

- `markitdown`: Conversão de documentos para markdown
- `openai`: Client da API OpenAI (gpt-5-mini)

### 🧪 Testes Realizados

- ✅ Upload de PDF e geração de resumo
- ✅ Regeneração de resumos
- ✅ Visualização de resumos em abas
- ✅ Truncamento de documentos grandes
- ✅ Tratamento de erros de API

### 📊 Relatório de Status

| Componente           | Status     | Notas                    |
| -------------------- | ---------- | ------------------------ |
| Geração de resumos   | ✅ Pronto   | Integrado com gpt-5-mini |
| Armazenamento JSON   | ✅ Pronto   | Tabela criada e indexada |
| Interface de usuário | ✅ Pronto   | Abas e pontos-chave      |
| Documentação         | ✅ Completo | BASE_CONHECIMENTO.md     |
| Testes               | ✅ Básicos  | Funcional em produção    |

### 🔄 Próximas Versões

- [ ] Análise de sentimento de documentos
- [ ] Extração de entidades jurídicas
- [ ] Recomendações baseadas em histórico
- [ ] Integração com modelos de embeddings customizados
- [ ] Versionamento de resumos (histórico de mudanças)
- [ ] API pública para terceiros

---

## [1.0.0] - Versão Inicial

### ✨ Funcionalidades Base
- ✅ Gerenciamento de documentos (upload, listagem, exclusão)
- ✅ Categorização automática
- ✅ Sistema de tags com Select2
- ✅ Pesquisa com IA integrada
- ✅ Chat conversacional com histórico
- ✅ Integração com Qdrant para busca semântica
- ✅ Dashboard com estatísticas
- ✅ Multi-tenant com isolamento de dados

---

## Como Contribuir

Para reportar bugs ou sugerir melhorias:
1. Abra uma issue descrevendo o problema
2. Forneça passos para reproduzir (se aplicável)
3. Inclua versão do sistema e ambiente
4. Referencie este CHANGELOG se relevante

---

## 📞 Contato

Para dúvidas sobre o changelog ou funcionalidades:
- Consulte [BASE_CONHECIMENTO.md](BASE_CONHECIMENTO.md)
- Verifique [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Leia [INSTRUCOES_PARA_IA.md](INSTRUCOES_PARA_IA.md)
