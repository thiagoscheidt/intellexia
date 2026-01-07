# Módulo de Resumo de Documentos por IA

## 📋 Descrição

Este módulo permite que usuários façam upload de documentos (PDF, DOCX, TXT) para que sejam resumidos por IA. O sistema armazena os documentos, gerencia o status de processamento e exibe os resumos gerados.

## 🎯 Funcionalidades Implementadas

### 1. Menu "Ferramentas"
- Novo menu principal adicionado ao sidebar
- Ícone: `bi-tools` (Bootstrap Icons)
- Submenu "Resumo de Documento" com ícone de arquivo

### 2. Página de Lista de Documentos
- **Rota:** `/tools/document-summary`
- **Funcionalidades:**
  - Listagem de todos os documentos enviados
  - Exibição de informações: ID, nome, tipo, tamanho, data de upload, status
  - Badges coloridos para diferentes status
  - Ações: Visualizar e Excluir
  - DataTables para paginação e busca

### 3. Página de Upload
- **Rota:** `/tools/document-summary/upload`
- **Funcionalidades:**
  - Formulário de upload com validação
  - Aceita: PDF, DOCX, DOC, TXT
  - Informações sobre como funciona o sistema
  - Alertas sobre limites e tempo de processamento

### 4. Página de Detalhes
- **Rota:** `/tools/document-summary/<document_id>`
- **Funcionalidades:**
  - Informações completas do documento
  - Exibição do resumo gerado pela IA
  - Status visual do processamento
  - Mensagens de erro (quando aplicável)
  - Opção para excluir o documento

## 🗄️ Estrutura do Banco de Dados

### Tabela: `ai_document_summaries`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| id | Integer | Chave primária |
| user_id | Integer | FK para usuário que enviou |
| law_firm_id | Integer | FK para escritório |
| original_filename | String(255) | Nome original do arquivo |
| file_path | String(500) | Caminho do arquivo no servidor |
| file_size | Integer | Tamanho em bytes |
| file_type | String(50) | Tipo do arquivo (PDF, DOCX, TXT) |
| status | String(20) | Status: pending, processing, completed, error |
| summary_text | Text | Resumo gerado pela IA |
| error_message | Text | Mensagem de erro (se houver) |
| processed_at | DateTime | Data/hora do processamento |
| uploaded_at | DateTime | Data/hora do upload |
| updated_at | DateTime | Data/hora da última atualização |

## 📁 Estrutura de Arquivos

```
intellexia/
├── app/
│   ├── models.py                    # Modelo AiDocumentSummary adicionado
│   ├── form.py                      # Formulário AiDocumentSummaryForm adicionado
│   └── routes.py                    # Rotas adicionadas
├── templates/
│   ├── partials/
│   │   └── sidebar.html            # Menu Ferramentas adicionado
│   └── tools/
│       ├── document_summary_list.html
│       ├── document_summary_upload.html
│       └── document_summary_detail.html
├── uploads/
│   └── ai_summaries/               # Diretório para uploads
└── add_ai_document_summaries_table.py  # Script de migração
```

## 🚀 Como Usar

### 1. Migração do Banco de Dados

Para adicionar a nova tabela ao banco existente:

```bash
python add_ai_document_summaries_table.py
```

Ou para recriar o banco (APAGA TODOS OS DADOS):

```bash
python recreate_database.py
python main.py
```

### 2. Acessar o Sistema

1. Faça login no sistema
2. No menu lateral, clique em "Ferramentas"
3. Selecione "Resumo de Documento"
4. Clique em "Enviar Documento" para fazer upload

### 3. Status dos Documentos

- **Pendente (warning):** Aguardando processamento
- **Processando (info):** IA está analisando
- **Processado (success):** Resumo disponível
- **Erro (danger):** Falha no processamento

## 🔧 Integração com IA (Futuro)

O sistema está preparado para integração com serviços de IA. Para implementar:

1. Criar um serviço/worker que:
   - Monitore documentos com status `pending`
   - Extraia o texto do documento
   - Envie para API de IA (OpenAI, Anthropic, etc.)
   - Atualize o campo `summary_text`
   - Mude o status para `completed`
   - Em caso de erro, defina status como `error` e preencha `error_message`

2. Exemplo de implementação:

```python
from app.models import AiDocumentSummary, db

def process_document(document_id):
    doc = AiDocumentSummary.query.get(document_id)
    
    # Atualizar status
    doc.status = 'processing'
    db.session.commit()
    
    try:
        # Extrair texto do documento
        text = extract_text(doc.file_path)
        
        # Enviar para IA
        summary = ai_service.generate_summary(text)
        
        # Salvar resultado
        doc.summary_text = summary
        doc.status = 'completed'
        doc.processed_at = datetime.utcnow()
        
    except Exception as e:
        doc.status = 'error'
        doc.error_message = str(e)
    
    db.session.commit()
```

## 🔐 Segurança

- Arquivos são isolados por escritório (law_firm_id)
- Validação de tipos de arquivo no upload
- Nomes de arquivo sanitizados (secure_filename)
- Arquivos armazenados com timestamp único
- Autenticação obrigatória (@require_law_firm)

## ⚙️ Configurações

### Tipos de Arquivo Aceitos
Configurado em `app/form.py`:
```python
FileAllowed(['pdf', 'docx', 'txt', 'doc'], 'Mensagem de erro')
```

### Diretório de Upload
Configurado em `app/routes.py`:
```python
upload_dir = os.path.join('uploads', 'ai_summaries')
```

## 📊 Estatísticas

Para obter estatísticas:

```python
from app.models import AiDocumentSummary

# Total de documentos
total = AiDocumentSummary.query.count()

# Por status
pending = AiDocumentSummary.query.filter_by(status='pending').count()
completed = AiDocumentSummary.query.filter_by(status='completed').count()

# Por escritório
docs_by_firm = AiDocumentSummary.query.filter_by(law_firm_id=firm_id).count()
```

## 🐛 Troubleshooting

### Erro ao fazer upload
- Verifique permissões da pasta `uploads/ai_summaries/`
- Confirme que o tipo de arquivo é permitido
- Verifique tamanho máximo do arquivo

### Tabela não existe
- Execute o script de migração: `python add_ai_document_summaries_table.py`

### Menu não aparece
- Limpe cache do navegador
- Verifique se o usuário está autenticado
- Confirme que o sidebar.html foi atualizado

## 📝 Próximos Passos

- [ ] Implementar worker para processamento assíncrono
- [ ] Integrar com API de IA (OpenAI GPT-4, Claude, etc.)
- [ ] Adicionar suporte para mais tipos de arquivo
- [ ] Implementar preview do documento
- [ ] Adicionar opção de download do resumo em PDF
- [ ] Criar dashboard com estatísticas de uso
- [ ] Implementar sistema de notificações quando resumo estiver pronto
- [ ] Adicionar opção de re-processar documento
- [ ] Permitir edição manual do resumo

## 📄 Licença

Este módulo faz parte do sistema IntellexIA.
