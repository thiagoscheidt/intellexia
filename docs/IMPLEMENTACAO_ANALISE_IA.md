# 🤖 Implementação da Análise de Documentos por IA

## 📋 Visão Geral

Sistema completo de análise automática de documentos usando **OpenAI GPT-4o** através dos agentes `FileAgent` e `AgentDocumentReader`.

---

## 🏗️ Arquitetura

### Componentes Principais

#### 1. **FileAgent** (`app/agents/file_agent.py`)
- **Função**: Upload de arquivos para a OpenAI
- **Suporte**: URLs (http/https), caminhos locais, file:// URIs
- **Métodos**:
  - `upload_file(file_path)` → Retorna `file_id` da OpenAI

#### 2. **AgentDocumentReader** (`app/agents/agent_document_reader.py`)
- **Função**: Análise jurídica de documentos
- **Modelo**: GPT-4o (ajustável)
- **Métodos**:
  - `analyze_document(file_id)` → Retorna resumo estruturado

#### 3. **DocumentReaderPrompt** (`app/prompts/document_reader_prompt.py`)
- **Função**: Prompt especializado para análise jurídica
- **Foco**: Extração de informações técnico-jurídicas relevantes

---

## 🔄 Fluxo de Processamento

### Para Documentos de Casos (`/cases/<case_id>/documents`)

```
1. Upload do arquivo
   └─→ Salvar no disco (uploads/cases/{case_id}/)
   └─→ Criar registro no banco (status: 'pending')

2. Verificar flag use_in_ai
   ├─→ Se TRUE:
   │   ├─→ Atualizar status: 'processing'
   │   ├─→ Upload para OpenAI (FileAgent)
   │   ├─→ Analisar documento (AgentDocumentReader)
   │   ├─→ Salvar resumo em ai_summary
   │   ├─→ Atualizar status: 'completed'
   │   └─→ Registrar ai_processed_at
   └─→ Se FALSE:
       └─→ Manter status: 'pending'

3. Exibir resultado
   └─→ Template: cases/document_view.html
```

### Para Ferramentas de Resumo (`/tools/document-summary`)

```
1. Upload do arquivo
   └─→ Salvar no disco (uploads/ai_summaries/)
   └─→ Criar registro no banco (status: 'pending')

2. Processamento automático
   ├─→ Atualizar status: 'processing'
   ├─→ Upload para OpenAI (FileAgent)
   ├─→ Analisar documento (AgentDocumentReader)
   ├─→ Salvar resumo em summary_text
   ├─→ Atualizar status: 'completed'
   └─→ Registrar processed_at

3. Exibir resultado
   └─→ Template: tools/document_summary_detail.html
```

---

## 📊 Estrutura de Dados

### Tabela: `documents` (Documentos de Casos)
```sql
id                    INTEGER PRIMARY KEY
case_id               INTEGER FK → cases.id
related_benefit_id    INTEGER FK → case_benefits.id
original_filename     VARCHAR(255)
file_path             VARCHAR(500)
document_type         VARCHAR(50)
description           TEXT
use_in_ai             BOOLEAN DEFAULT TRUE
ai_summary            TEXT          -- Resumo gerado pela IA
ai_processed_at       DATETIME      -- Data do processamento
ai_status             VARCHAR(20)   -- pending, processing, completed, error
ai_error_message      TEXT          -- Mensagem de erro
uploaded_at           DATETIME
```

### Tabela: `ai_document_summaries` (Ferramenta de Resumo)
```sql
id                    INTEGER PRIMARY KEY
user_id               INTEGER FK → users.id
law_firm_id           INTEGER FK → law_firms.id
original_filename     VARCHAR(255)
file_path             VARCHAR(500)
file_size             INTEGER
file_type             VARCHAR(50)
status                VARCHAR(20)   -- pending, processing, completed, error
summary_text          TEXT          -- Resumo gerado pela IA
error_message         TEXT          -- Mensagem de erro
processed_at          DATETIME
uploaded_at           DATETIME
```

---

## 🎯 Funcionalidades Implementadas

### ✅ Blueprint: `documents_bp`

#### 1. Upload e Análise Automática
- **Rota**: `POST /cases/<case_id>/documents/new`
- **Arquivo**: `app/blueprints/documents.py`
- **Função**: `case_document_new()`
- **Ação**: 
  - Upload do arquivo
  - Análise automática se `use_in_ai=True`
  - Salvamento do resumo no banco

#### 2. Visualização do Resumo
- **Rota**: `GET /cases/<case_id>/documents/<document_id>/view`
- **Template**: `templates/cases/document_view.html`
- **Exibe**:
  - Informações do documento
  - Status do processamento
  - Resumo gerado pela IA
  - Botão de reprocessar (se erro)

#### 3. Reprocessamento
- **Rota**: `POST /cases/<case_id>/documents/<document_id>/reprocess`
- **Função**: `case_document_reprocess()`
- **Ação**: Reanalisa documentos com erro

### ✅ Blueprint: `tools_bp`

#### 1. Upload e Análise Automática
- **Rota**: `POST /tools/document-summary/upload`
- **Arquivo**: `app/blueprints/tools.py`
- **Função**: `tools_document_summary_upload()`
- **Ação**: 
  - Upload do arquivo
  - Análise automática imediata
  - Salvamento do resumo no banco

#### 2. Visualização do Resumo
- **Rota**: `GET /tools/document-summary/<document_id>`
- **Template**: `templates/tools/document_summary_detail.html`
- **Exibe**:
  - Informações do arquivo
  - Status do processamento
  - Resumo gerado pela IA
  - Botão de reprocessar (se erro)

#### 3. Reprocessamento
- **Rota**: `POST /tools/document-summary/<document_id>/reprocess`
- **Função**: `tools_document_summary_reprocess()`
- **Ação**: Reanalisa documentos com erro

---

## 🎨 Interface do Usuário

### Estados de Processamento

#### 🟡 Pending (Pendente)
```html
<span class="badge bg-warning">
  <i class="bi bi-hourglass-split"></i> Pendente
</span>
```
- Documento aguardando processamento
- Não foi enviado para a IA ainda

#### 🔵 Processing (Processando)
```html
<span class="badge bg-info">
  <i class="bi bi-arrow-repeat"></i> Processando
</span>
```
- Upload para OpenAI em andamento
- Análise sendo realizada pela IA
- Botão "Atualizar Página" disponível

#### 🟢 Completed (Concluído)
```html
<span class="badge bg-success">
  <i class="bi bi-check-circle"></i> Processado
</span>
```
- Análise concluída com sucesso
- Resumo disponível para visualização
- Data/hora do processamento exibida

#### 🔴 Error (Erro)
```html
<span class="badge bg-danger">
  <i class="bi bi-exclamation-triangle"></i> Erro
</span>
```
- Falha no processamento
- Mensagem de erro detalhada
- Botão "Reprocessar Documento" disponível

---

## 🔧 Tratamento de Erros

### Erros Comuns

#### 1. Arquivo Corrompido
```python
Exception: "Unable to read file content"
```
**Solução**: Reenviar arquivo ou verificar integridade

#### 2. Timeout da OpenAI
```python
Exception: "Request timeout"
```
**Solução**: Reprocessar documento

#### 3. Limite de API Excedido
```python
Exception: "Rate limit exceeded"
```
**Solução**: Aguardar e reprocessar

#### 4. Arquivo Muito Grande
```python
Exception: "File size exceeds maximum"
```
**Solução**: Reduzir tamanho ou dividir arquivo

### Sistema de Recuperação

```python
try:
    # Processar documento
    ai_summary = doc_reader.analyze_document(file_id)
    document.ai_status = 'completed'
except Exception as e:
    # Registrar erro
    document.ai_status = 'error'
    document.ai_error_message = str(e)
    # Permitir reprocessamento
```

---

## 📝 Exemplos de Uso

### Exemplo 1: Upload de CAT
```python
# 1. Usuário envia CAT em PDF
file = "cat_joao_silva.pdf"

# 2. Sistema processa
file_id = file_agent.upload_file(file_path)
ai_summary = doc_reader.analyze_document(file_id)

# 3. IA retorna resumo
"""
**COMUNICAÇÃO DE ACIDENTE DE TRABALHO (CAT)**

**Segurado**: João da Silva
**NIT**: 123.456.789-10
**Data do Acidente**: 15/03/2024
**Empresa**: Empresa XYZ Ltda
**CNPJ**: 12.345.678/0001-00
**Tipo de Acidente**: Trajeto
**CID-10**: S82.0 - Fratura da patela

**Resumo dos Fatos**:
Segurado sofreu acidente de trânsito ao retornar do trabalho...
"""
```

### Exemplo 2: Upload de Extrato INSS
```python
# 1. Usuário envia extrato
file = "extrato_beneficio_b91.pdf"

# 2. Sistema processa
ai_summary = doc_reader.analyze_document(file_id)

# 3. IA retorna resumo estruturado
"""
**EXTRATO DE BENEFÍCIO B91**

**Número do Benefício**: 123.456.789-0
**Tipo**: B91 - Auxílio-Doença Acidentário
**DIB**: 20/03/2024
**Status**: Ativo

**Competências**:
- 03/2024: R$ 1.500,00
- 04/2024: R$ 1.500,00
- 05/2024: R$ 1.500,00

**Observações**:
Benefício concedido por acidente de trabalho...
"""
```

---

## 🚀 Como Testar

### 1. Teste de Upload (Casos)
```bash
# Acessar caso
http://localhost:5000/cases/1

# Ir para "Documentos"
http://localhost:5000/cases/1/documents

# Clicar em "Novo Documento"
# Upload de arquivo PDF
# Marcar "Usar na IA" = TRUE
# Enviar

# Verificar processamento
http://localhost:5000/cases/1/documents/{id}/view
```

### 2. Teste de Upload (Ferramentas)
```bash
# Acessar ferramentas
http://localhost:5000/tools/document-summary

# Clicar em "Upload Documento"
http://localhost:5000/tools/document-summary/upload

# Upload de arquivo
# Enviar (processamento automático)

# Verificar resultado
http://localhost:5000/tools/document-summary/{id}
```

### 3. Teste de Reprocessamento
```bash
# Simular erro (remover chave API temporariamente)
# Upload de documento
# Verificar status "error"
# Restaurar chave API
# Clicar em "Reprocessar Documento"
# Verificar status "completed"
```

---

## 🔐 Configuração

### Variáveis de Ambiente (.env)
```bash
# OpenAI API Key
OPENAI_API_KEY=sk-...

# Modelo (opcional, padrão: gpt-4o)
OPENAI_MODEL=gpt-4o
```

### Ajustar Modelo
```python
# Em app/agents/agent_document_reader.py
def __init__(self, model_name="gpt-4o-mini"):  # Modelo mais barato
    self.model = ChatOpenAI(model=model_name)
```

---

## 📈 Monitoramento

### Logs de Processamento
```python
# Adicionar logs para debug
import logging

logger = logging.getLogger(__name__)

def case_document_new():
    logger.info(f"Upload iniciado: {filename}")
    logger.info(f"File ID OpenAI: {file_id}")
    logger.info(f"Análise concluída: {len(ai_summary)} caracteres")
```

### Métricas
- Total de documentos processados
- Taxa de sucesso/erro
- Tempo médio de processamento
- Tamanho médio dos resumos

---

## ✅ Checklist de Implementação

- [x] FileAgent implementado
- [x] AgentDocumentReader implementado
- [x] Modelo ajustado para GPT-4o
- [x] Integração com documents_bp
- [x] Integração com tools_bp
- [x] Templates atualizados
- [x] Sistema de reprocessamento
- [x] Tratamento de erros
- [x] Badges de status
- [x] Documentação completa

---

## 🎯 Próximas Melhorias

1. **Processamento Assíncrono** (Celery)
   - Evitar bloqueio durante análise
   - Processar múltiplos documentos em paralelo

2. **Cache de Resumos**
   - Evitar reprocessamento de arquivos idênticos
   - Hash MD5 dos arquivos

3. **Análise Comparativa**
   - Comparar múltiplos documentos
   - Identificar inconsistências

4. **Exportação de Resumos**
   - PDF estruturado
   - DOCX formatado
   - JSON para integração

5. **Dashboard de Análises**
   - Gráficos de processamento
   - Estatísticas por tipo de documento
   - Histórico de análises

---

**Status**: ✅ IMPLEMENTADO
**Versão**: 1.0.0
**Data**: 11/01/2026
