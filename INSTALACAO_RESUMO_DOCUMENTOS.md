# 🚀 Guia de Instalação - Módulo Resumo de Documentos

## Passo a Passo para Ativar o Módulo

### 1. Atualizar o Banco de Dados

O módulo criará automaticamente a tabela `ai_document_summaries` quando você iniciar a aplicação.

**Opção A: Iniciar a aplicação (recomendado)**
```bash
python main.py
```

A tabela será criada automaticamente no primeiro acesso.

**Opção B: Recriar o banco (APAGA TODOS OS DADOS)**
```bash
python recreate_database.py
python main.py
```

### 2. Verificar Estrutura de Pastas

O diretório de upload já foi criado:
```
uploads/
└── ai_summaries/
```

Se não existir, será criado automaticamente no primeiro upload.

### 3. Acessar o Módulo

1. Inicie a aplicação: `python main.py`
2. Acesse: http://localhost:5000
3. Faça login no sistema
4. No menu lateral, procure por **"Ferramentas"**
5. Clique em **"Resumo de Documento"**

### 4. Testar o Upload

1. Clique em "Enviar Documento"
2. Selecione um arquivo PDF, DOCX ou TXT
3. Clique em "Enviar para Resumo"
4. O documento será listado com status "Pendente"

## ✅ Checklist de Verificação

- [ ] Banco de dados atualizado (tabela ai_document_summaries criada)
- [ ] Pasta uploads/ai_summaries/ existe
- [ ] Menu "Ferramentas" aparece no sidebar
- [ ] Consegue acessar /tools/document-summary
- [ ] Consegue fazer upload de arquivo
- [ ] Arquivo aparece na lista com status "Pendente"

## 🔍 Verificando se Funcionou

Execute este código Python para verificar:

```python
from main import app
from app.models import db, AiDocumentSummary

with app.app_context():
    # Verificar se a tabela existe
    try:
        count = AiDocumentSummary.query.count()
        print(f"✅ Tabela existe! Total de documentos: {count}")
    except Exception as e:
        print(f"❌ Erro: {e}")
```

## 🐛 Problemas Comuns

### Erro: "No module named 'openai'"
**Solução:** Instale as dependências
```bash
pip install -r requirements.txt
# ou
uv sync
```

### Menu não aparece
**Solução:** 
- Limpe o cache do navegador (Ctrl+Shift+R)
- Verifique se está logado
- Confira se o arquivo sidebar.html foi atualizado

### Erro ao fazer upload
**Solução:**
- Verifique permissões da pasta uploads/
- Confirme que o tipo de arquivo é permitido (PDF, DOCX, TXT)

## 📋 Status do Módulo

✅ **Implementado:**
- Modelo de dados (AiDocumentSummary)
- Rotas completas (list, upload, detail, delete)
- Formulário de upload com validação
- Templates responsivos com Bootstrap
- Menu lateral integrado
- Sistema de status (pending, processing, completed, error)
- Armazenamento seguro de arquivos

⏳ **Próxima Etapa (não implementada):**
- Integração com API de IA para gerar resumos
- Processamento assíncrono de documentos
- Sistema de notificações

## 🎯 Próximos Passos

Para implementar a IA, você precisará:

1. Criar um worker/serviço para processar documentos
2. Integrar com API de IA (OpenAI, Anthropic, etc.)
3. Atualizar o status e resumo no banco de dados

Exemplo básico:
```python
def process_pending_documents():
    pending = AiDocumentSummary.query.filter_by(status='pending').all()
    for doc in pending:
        # Extrair texto do documento
        text = extract_text(doc.file_path)
        
        # Gerar resumo com IA
        summary = ai_generate_summary(text)
        
        # Atualizar no banco
        doc.status = 'completed'
        doc.summary_text = summary
        doc.processed_at = datetime.utcnow()
        db.session.commit()
```

## 📞 Suporte

Para mais informações, consulte:
- RESUMO_DOCUMENTOS.md - Documentação completa
- app/routes.py - Linhas 1635+ (rotas do módulo)
- app/models.py - Linha 341+ (modelo AiDocumentSummary)
