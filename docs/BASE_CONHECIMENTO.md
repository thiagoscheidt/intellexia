# 📚 Base de Conhecimento - Documentação Completa

## 📋 Descrição

A **Base de Conhecimento** é um módulo essencial do IntellexIA que permite gerenciar e organizar documentos (PDFs, DOCs, TXTs, etc.) com suporte a categorias, tags e análise por IA. O sistema oferece busca inteligente, resumos automáticos e integração com agentes de IA para pesquisa contextual.

## 🎯 Funcionalidades Principais

### 1. **Gerenciamento de Documentos**
- Upload de múltiplos formatos (PDF, DOCX, TXT, etc.)
- Organização por categorias e tags
- Busca avançada por nome, descrição e conteúdo
- Histórico de uploads com informações do responsável
- Soft-delete (documentos podem ser recuperados)

### 2. **Organização por Categorias**
- Gerenciar categorias customizadas por escritório
- Atribuir cores e ícones às categorias
- Ordenação customizável
- Ativação/desativação de categorias
- Interface CRUD completa

### 3. **Sistema de Tags**
- Tags para marcação flexível de documentos
- 18 tags pré-configuradas (Trabalhista, Previdenciário, STJ, STF, etc.)
- Cores customizáveis para cada tag
- Reutilização em múltiplos documentos
- Gerenciamento CRUD de tags

### 4. **Resumos Automáticos com IA** ✅ IMPLEMENTADO
- **Geração em tempo real** via GPT-4o (OpenAI)
- **Múltiplos formatos**: Resumo curto, resumo longo, pontos-chave
- **Armazenamento JSON** estruturado para persistência
- **Botão interativo** para gerar/regenerar resumos
- **Interface visual** com abas para diferentes resumos
- **Processamento assíncrono** com feedback ao usuário
- **Classe dedicada**: `AgentDocumentSummary` com integração OpenAI
- **Suporte a múltiplos formatos**: PDF, DOCX, TXT, PPTX, etc.

### 5. **Busca Inteligente com IA**
- Pesquisa conversacional na base de conhecimento
- Respostas contextuais com fontes citadas
- Histórico de perguntas e respostas
- Chat integrado para múltiplas perguntas
- Limpeza de histórico

### 6. **Pesquisa Simples**
- Filtro por categoria
- Busca por nome e descrição
- Listagem paginada com DataTables

## 🗄️ Estrutura do Banco de Dados

### Tabela: `knowledge_base`
| Campo              | Tipo         | Descrição                    |
| ------------------ | ------------ | ---------------------------- |
| id                 | Integer      | Chave primária               |
| user_id            | Integer      | FK para usuário que enviou   |
| law_firm_id        | Integer      | FK para escritório           |
| original_filename  | String(255)  | Nome original do arquivo     |
| file_path          | String(500)  | Caminho do arquivo           |
| file_size          | Integer      | Tamanho em bytes             |
| file_type          | String(50)   | Tipo (PDF, DOCX, TXT)        |
| description        | Text         | Descrição do documento       |
| category           | String(100)  | Categoria do documento       |
| tags               | Text         | Tags separadas por vírgula   |
| lawsuit_number     | String(100)  | Número do processo (opcional)|
| is_active          | Boolean      | Soft-delete                  |
| uploaded_at        | DateTime     | Data do upload               |
| updated_at         | DateTime     | Última atualização           |

### Tabela: `knowledge_categories`
| Campo         | Tipo      | Descrição                    |
| ------------- | --------- | ---------------------------- |
| id            | Integer   | Chave primária               |
| law_firm_id   | Integer   | FK para escritório           |
| name          | String    | Nome da categoria            |
| icon          | String    | Emoji ou ícone Bootstrap     |
| description   | Text      | Descrição da categoria       |
| color         | String    | Cor em hexadecimal           |
| display_order | Integer   | Ordem de exibição            |
| is_active     | Boolean   | Status da categoria          |
| created_at    | DateTime  | Data de criação              |
| updated_at    | DateTime  | Última atualização           |

### Tabela: `knowledge_tags`
| Campo         | Tipo      | Descrição                    |
| ------------- | --------- | ---------------------------- |
| id            | Integer   | Chave primária               |
| law_firm_id   | Integer   | FK para escritório           |
| name          | String    | Nome da tag                  |
| icon          | String    | Emoji ou ícone Bootstrap     |
| description   | Text      | Descrição da tag             |
| color         | String    | Cor em hexadecimal           |
| display_order | Integer   | Ordem de exibição            |
| is_active     | Boolean   | Status da tag                |
| created_at    | DateTime  | Data de criação              |
| updated_at    | DateTime  | Última atualização           |

### Tabela: `knowledge_summaries` ✅ IMPLEMENTADA
| Campo              | Tipo      | Descrição                                    |
| ------------------ | --------- | -------------------------------------------- |
| id                 | Integer   | Chave primária                               |
| knowledge_base_id  | Integer   | FK para documento                            |
| payload            | JSON      | JSON estruturado com resumos e metadados:     |
|                    |           | - `summary_short`: Resumo curto (1-2 linhas) |
|                    |           | - `summary_long`: Resumo longo completo      |
|                    |           | - `key_points`: Array com pontos-chave       |
|                    |           | - `language`: Idioma detectado               |
|                    |           | - `word_count`: Contagem de palavras         |
|                    |           | - `processing_time`: Tempo de processamento  |
| created_at         | DateTime  | Data de criação do resumo                    |
| updated_at         | DateTime  | Última atualização do resumo                 |

### Tabela: `knowledge_chat_history`
| Campo         | Tipo      | Descrição                    |
| ------------- | --------- | ---------------------------- |
| id            | Integer   | Chave primária               |
| user_id       | Integer   | FK para usuário              |
| law_firm_id   | Integer   | FK para escritório           |
| question      | Text      | Pergunta do usuário          |
| answer        | Text      | Resposta da IA               |
| sources       | Text      | JSON com fontes utilizadas   |
| response_time_ms | Integer | Tempo de resposta (ms)       |
| tokens_used   | Integer   | Tokens utilizados            |
| user_rating   | Integer   | Avaliação 1-5                |
| user_feedback | Text      | Feedback do usuário          |
| created_at    | DateTime  | Data da pergunta             |

## 📁 Estrutura de Arquivos

```
intellexia/
├── app/
│   ├── blueprints/
│   │   └── knowledge_base.py           # Todas as rotas
│   ├── models.py                       # Modelos de BD
│   └── agents/
│       └── knowledge_ingestor.py       # Processamento e IA
├── templates/
│   └── knowledge_base/
│       ├── list.html                   # Lista de documentos
│       ├── upload.html                 # Upload de arquivo
│       ├── details.html                # Detalhes + resumo
│       ├── categories.html             # Gerenciamento de categorias
│       ├── tags.html                   # Gerenciamento de tags
│       └── search_chat.html            # Chat com IA
├── database/
│   ├── add_knowledge_categories_table.py
│   ├── add_knowledge_tags_table.py
│   ├── add_knowledge_summaries_table.py
│   ├── add_knowledge_chat_history_table.py
│   ├── populate_default_categories.py
│   └── populate_default_tags.py
└── uploads/
    └── knowledge_base/                 # Diretório de uploads
```

## 🚀 Como Usar

### 1. Migração do Banco de Dados

Execute todos os scripts de migração:

```bash
# Criar tabelas
python database/add_knowledge_categories_table.py
python database/add_knowledge_tags_table.py
python database/add_knowledge_summaries_table.py
python database/add_knowledge_chat_history_table.py

# Popular dados padrão
python database/populate_default_categories.py
python database/populate_default_tags.py
```

### 2. Acessar o Sistema

1. Faça login no sistema
2. No menu lateral, clique em **"Base de Conhecimento"**
3. Escolha uma das opções:
   - **Pesquisar com IA** - Chat inteligente
   - **Listar Arquivos** - Visualizar documentos
   - **Adicionar Arquivo** - Upload de novo documento
   - **Categorias** - Gerenciar categorias (admin)
   - **Tags** - Gerenciar tags (admin)

### 3. Upload de Documento

1. Clique em "Adicionar Arquivo"
2. Selecione o arquivo (PDF, DOCX, TXT)
3. Preencha:
   - Descrição (opcional)
   - Categoria (obrigatório)
   - Tags (múltipla seleção com Select2)
   - Número do processo (opcional)
4. Clique em "Enviar"
5. Arquivo será indexado no Qdrant automaticamente

### 4. Gerar Resumo ✅ IMPLEMENTADO

1. Navegue até a página de detalhes do documento
2. Clique no botão **"Gerar Resumo com IA"**
3. **Processamento em tempo real**:
   - Arquivo é convertido para markdown (MarkItDown)
   - Texto é truncado em 24KB (configurável via `SUMMARY_MAX_CHARS`)
   - GPT-4o gera resumos estruturados via prompt especializado
   - Resultado é armazenado em JSON
4. **O resumo exibe**:
   - ✅ Resumo curto (1-2 linhas)
   - ✅ Resumo longo (completo)
   - ✅ Pontos-chave (lista)
   - ✅ Informações técnicas (idioma, contagem de palavras)
5. Use **"Regenerar Resumo"** para atualizar com nova análise

### 5. Pesquisar com IA

1. Acesse **"Pesquisar com IA"**
2. Digite sua pergunta em linguagem natural
3. A IA buscará na base e retornará:
   - Resposta contextual
   - Documentos utilizados como fonte
   - Links para acessar os documentos
4. Histórico é mantido durante a sessão
5. Use **"Limpar histórico"** conforme necessário

### 6. Gerenciar Categorias

1. Acesse **"Categorias"** (requer role admin)
2. Tabela mostra todas as categorias ativas
3. **Criar**: Clique em "Nova Categoria"
4. **Editar**: Clique no ícone de lápis
5. **Desativar**: Clique no ícone de lixeira
6. Customize: Nome, ícone, descrição, cor, ordem

### 7. Gerenciar Tags

1. Acesse **"Tags"** (requer role admin)
2. Tabela mostra todas as tags ativas
3. **Criar**: Clique em "Nova Tag"
4. **Editar**: Clique no ícone de lápis
5. **Desativar**: Clique no ícone de lixeira
6. Customize: Nome, ícone, descrição, cor, ordem

## 🔌 Endpoints da API

### Documentos
```
GET    /knowledge-base/                    # Lista documentos
POST   /knowledge-base/upload               # Upload de arquivo
GET    /knowledge-base/<id>/details         # Detalhes
POST   /knowledge-base/<id>/generate-summary # Gerar resumo
POST   /knowledge-base/<id>/delete          # Deletar
GET    /knowledge-base/<id>/download        # Download
POST   /knowledge-base/api/ask              # Pergunta para IA
GET    /knowledge-base/api/history          # Histórico de chat
POST   /knowledge-base/api/clear-history    # Limpar histórico
```

### Categorias
```
GET    /knowledge-base/categories           # Lista
POST   /knowledge-base/categories/create    # Criar
POST   /knowledge-base/categories/<id>/update # Atualizar
POST   /knowledge-base/categories/<id>/delete # Deletar
```

### Tags
```
GET    /knowledge-base/tags                 # Lista
POST   /knowledge-base/tags/create          # Criar
POST   /knowledge-base/tags/<id>/update     # Atualizar
POST   /knowledge-base/tags/<id>/delete     # Deletar
```

## 🤖 Integração com IA

### KnowledgeIngestor
A classe `KnowledgeIngestor` em `app/agents/knowledge_ingestor.py` é responsável por:

1. **Processamento de Arquivos**
   - Leitura de PDF, DOCX, TXT
   - Conversão para markdown
   - Chunking de conteúdo

2. **Indexação no Qdrant**
   - Embedding com modelos de NLP
   - Armazenamento vetorial
   - Busca semântica

3. **Respostas com LLM**
   - Busca contextual no Qdrant
   - Prompt engineering
   - Respostas com fontes citadas

### Resumos Automáticos com IA ✅ IMPLEMENTADO

**Classe**: `AgentDocumentSummary` em `app/agents/agent_document_summary.py`

**Fluxo de Geração**:
```python
1. Recebe file_path ou text_content
2. Converte arquivo para markdown via MarkItDown
   - Suporta: PDF, DOCX, PPTX, Excel, imagens, etc.
3. Trunca em 24KB (SUMMARY_MAX_CHARS, configurável)
4. Envia para GPT-4o com prompt especializado
5. Retorna JSON com estrutura:
{
    "summary_short": "Resumo de 1-2 linhas",
    "summary_long": "Resumo completo do documento",
    "key_points": ["Ponto 1", "Ponto 2", "..."],
    "language": "pt",
    "word_count": 12345,
    "processing_time_ms": 2500,
    "model": "gpt-4o",
    "timestamp": "2026-01-30T14:30:00Z"
}
```

**Integração com Banco**:
```python
# Em generate_summary() - knowledge_base.py
agent = AgentDocumentSummary()
summary_payload = agent.summarizeDocument(file_path=file.file_path)

# Salva em knowledge_summaries.payload (JSON)
# Permite regeneração sem reprocessar arquivo
```

**Configuração Necessária** (``.env``):
```
OPENAI_API_KEY=sk-xxxxx
SUMMARY_MAX_CHARS=24000  # Limite de caracteres
```

## 📊 Permissões

| Funcionalidade | Admin | User |
| -------------- | ----- | ---- |
| Listar documentos | ✅ | ✅ |
| Upload | ✅ | ✅ |
| Visualizar detalhes | ✅ | ✅ |
| Gerar resumo | ✅ | ✅ |
| Deletar próprio | ✅ | ✅ |
| Gerenciar categorias | ✅ | ❌ |
| Gerenciar tags | ✅ | ❌ |
| Pesquisar com IA | ✅ | ✅ |

## 🔐 Segurança

- **Isolamento por Escritório**: Cada usuário vê apenas documentos do seu escritório
- **Soft-Delete**: Documentos nunca são permanentemente deletados
- **Auditoria**: Todos as operações registram user_id, data/hora
- **Validação**: Extensões de arquivo validadas
- **Autorização**: Verificação de law_firm_id em cada rota

## 📈 Fluxo de Dados

```
1. Upload → Salva em disk → Cria registro em BD
2. Processamento → KnowledgeIngestor.process_file()
3. Indexação → Qdrant (vetorial)
4. Disponibilidade → Pesquisa e resumo
5. Resumo (NOVO!) → Gera via IA → Armazena em JSON
```

## 🐛 Troubleshooting

### Arquivo não aparece após upload
- Verifique se o diretório `uploads/knowledge_base/<law_firm_id>/` existe
- Confirme se o arquivo foi salvo em `knowledge_base` tabela
- Verifique os logs de `KnowledgeIngestor`

### Resumo não gera
- Função ainda está em desenvolvimento (placeholder)
- Implementar integração com LLM em `generate_summary()`
- Verificar conexão com serviço de IA

### Busca não retorna resultados
- Verifique se o Qdrant está rodando
- Confirme se os documentos foram indexados
- Tente fazer uma pesquisa mais genérica

### Tags não aparecem no upload
- Rode `python database/populate_default_tags.py`
- Verifique se o escritório tem tags ativas
- Confirme que `is_active=True` nas tags

## 📝 Notas de Desenvolvimento

- **Select2**: Usado para seleção múltipla de tags com jQuery
- **DataTables**: Paginação e busca em listas
- **Bootstrap 5**: Tema AdminLTE para UI
- **SQLAlchemy**: ORM para acesso ao banco
- **Soft-Delete**: Usar `is_active=False` ao invés de DELETE
- **MarkItDown**: Conversão de documentos para markdown (PDFs, DOCX, etc)
- **OpenAI GPT-4o**: Geração de resumos estruturados

## 🔄 Versão

**Atual**: v2.0 - Janeiro 2026

### ✅ Funcionalidades Implementadas

- ✅ Gerenciamento completo de documentos (CRUD)
- ✅ Categorias customizáveis por escritório
- ✅ Tags com seletor Select2 múltiplo
- ✅ Dashboard com estatísticas
- ✅ **Resumos automáticos com IA (GPT-4o)** - ⭐ NOVO JANEIRO 2026!
- ✅ Pesquisa inteligente com integração Qdrant
- ✅ Chat conversacional com histórico
- ✅ Multi-tenant com isolamento de dados
- ✅ Suporte a múltiplos formatos de arquivo

### 🚀 Próximas Features

- 🔄 Análise de sentimento de documentos
- 🔄 Extração de entidades jurídicas
- 🔄 Recomendações baseadas em histórico
- 🔄 Integração com modelos de embeddings customizados
- 🔄 Versionamento de resumos (histórico de mudanças)
- 🔄 API pública para terceiros

---
---

## 📚 Ver Também

- [ESTRUTURA_BLUEPRINTS.md](ESTRUTURA_BLUEPRINTS.md) - Todas as rotas do sistema
- [INSTRUCOES_PARA_IA.md](INSTRUCOES_PARA_IA.md) - Integração com IA e agentes
- [MULTI_TENANT.md](MULTI_TENANT.md) - Sistema multi-tenant
- [QUICKSTART_ANALISE_IA.md](QUICKSTART_ANALISE_IA.md) - Guia rápido de análise

---

## 📞 Suporte

Para dúvidas ou problemas:
1. Consulte [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Verifique os logs da aplicação
3. Confirme que `.env` possui `OPENAI_API_KEY` configurada

## 🔄 Versão

- **Última atualização**: Janeiro 2026
- **Status**: Produção
- **Versão do módulo**: v2.0
