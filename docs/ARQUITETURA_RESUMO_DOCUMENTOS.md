# 🗺️ Arquitetura do Módulo Resumo de Documentos

## 📐 Fluxo de Dados

```
┌─────────────────────────────────────────────────────────────────┐
│                         USUÁRIO                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MENU FERRAMENTAS                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  🧠 Resumo de Documento                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
┌──────────────────┐            ┌──────────────────┐
│   LISTA          │            │   UPLOAD         │
│  (List View)     │◄───────────│   (Form)         │
└────────┬─────────┘            └────────┬─────────┘
         │                               │
         │                               │ Submit
         │                               ▼
         │                      ┌─────────────────────┐
         │                      │   PROCESSAMENTO     │
         │                      │  - Salvar arquivo   │
         │                      │  - Criar registro   │
         │                      │  - Status: pending  │
         │                      └──────────┬──────────┘
         │                                 │
         │                                 ▼
         │                      ┌─────────────────────┐
         └─────────────────────►│   BANCO DE DADOS    │
                                │ ai_document_summaries│
         ┌──────────────────────┤                     │
         │                      └─────────────────────┘
         │                                 │
         ▼                                 │
┌──────────────────┐                      │
│   DETALHES       │◄─────────────────────┘
│  (Detail View)   │
│                  │
│  ┌────────────┐  │
│  │ Info File  │  │
│  └────────────┘  │
│  ┌────────────┐  │
│  │  Summary   │  │ ⏳ Futuro: IA aqui
│  │  (Pending) │  │
│  └────────────┘  │
└──────────────────┘
```

## 🏗️ Estrutura de Arquivos

```
intellexia/
│
├── app/
│   ├── models.py                 ← AiDocumentSummary
│   ├── form.py                   ← AiDocumentSummaryForm
│   └── routes.py                 ← 4 rotas novas
│
├── templates/
│   ├── partials/
│   │   └── sidebar.html          ← Menu Ferramentas
│   │
│   └── tools/                    ← NOVO diretório
│       ├── document_summary_list.html
│       ├── document_summary_upload.html
│       └── document_summary_detail.html
│
├── uploads/
│   └── ai_summaries/             ← NOVO diretório
│       └── [arquivos enviados]
│
├── add_ai_document_summaries_table.py     ← Script migração
├── RESUMO_DOCUMENTOS.md                   ← Documentação
├── INSTALACAO_RESUMO_DOCUMENTOS.md        ← Guia instalação
└── RESUMO_IMPLEMENTACAO.md                ← Este arquivo
```

## 🔄 Ciclo de Vida de um Documento

```
1. UPLOAD
   ├─ Usuário seleciona arquivo
   ├─ Validação de tipo (PDF, DOCX, TXT)
   ├─ Nome único gerado (timestamp)
   ├─ Arquivo salvo em uploads/ai_summaries/
   └─ Registro criado no banco
       └─ status: 'pending'

2. ARMAZENAMENTO
   ├─ Tabela: ai_document_summaries
   ├─ Campos preenchidos:
   │   ├─ user_id
   │   ├─ law_firm_id
   │   ├─ original_filename
   │   ├─ file_path
   │   ├─ file_size
   │   ├─ file_type
   │   ├─ status: 'pending'
   │   └─ uploaded_at
   └─ Campos vazios (para IA):
       ├─ summary_text
       ├─ processed_at
       └─ error_message

3. LISTAGEM
   ├─ Query: ORDER BY uploaded_at DESC
   ├─ Filtro: law_firm_id = atual
   └─ Exibição: Tabela com DataTables

4. VISUALIZAÇÃO
   ├─ Informações do arquivo
   └─ Status:
       ├─ Pendente → Badge amarelo
       ├─ Processando → Badge azul (futuro)
       ├─ Concluído → Badge verde + resumo (futuro)
       └─ Erro → Badge vermelho + mensagem (futuro)

5. EXCLUSÃO
   ├─ Confirmação do usuário
   ├─ Remove arquivo físico
   └─ Remove registro do banco

6. [FUTURO] PROCESSAMENTO IA
   ├─ Worker pega documentos com status='pending'
   ├─ Extrai texto do documento
   ├─ Envia para API de IA
   ├─ Recebe resumo
   ├─ Atualiza banco:
   │   ├─ summary_text = resumo
   │   ├─ status = 'completed'
   │   └─ processed_at = agora
   └─ Usuário vê resumo na interface
```

## 🗄️ Modelo de Dados

```sql
CREATE TABLE ai_document_summaries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,                 -- FK: users.id
    law_firm_id INTEGER NOT NULL,             -- FK: law_firms.id
    original_filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER,
    file_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',     -- pending|processing|completed|error
    summary_text TEXT,                        -- ← Resumo da IA (futuro)
    error_message TEXT,
    processed_at DATETIME,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## 🛣️ Rotas

```python
# Lista de documentos
GET  /tools/document-summary
→ tools_document_summary_list()
→ templates/tools/document_summary_list.html

# Formulário de upload
GET  /tools/document-summary/upload
→ tools_document_summary_upload()
→ templates/tools/document_summary_upload.html

# Processar upload
POST /tools/document-summary/upload
→ tools_document_summary_upload()
→ Salva arquivo e cria registro
→ Redirect para detail

# Visualizar documento
GET  /tools/document-summary/<id>
→ tools_document_summary_detail(document_id)
→ templates/tools/document_summary_detail.html

# Excluir documento
POST /tools/document-summary/<id>/delete
→ tools_document_summary_delete(document_id)
→ Redirect para list
```

## 🎨 Interface do Usuário

```
┌─────────────────────────────────────────────────────────────┐
│  SIDEBAR                                                     │
├─────────────────────────────────────────────────────────────┤
│  📊 Dashboard                                                │
│  🤖 Assistente Jurídico                                      │
│  🔧 Ferramentas ◄─── NOVO                                    │
│     └─ 🧠 Resumo de Documento ◄─── NOVO                      │
│  📰 Casos                                                    │
│  👥 Clientes                                                 │
│  💼 Advogados                                                │
│  🏛️ Varas Judiciais                                          │
│  💰 Benefícios                                               │
└─────────────────────────────────────────────────────────────┘
```

### Tela: Lista de Documentos

```
┌──────────────────────────────────────────────────────────┐
│  🧠 Documentos para Resumo por IA   [📤 Enviar Documento]│
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ID │ Nome        │ Tipo │ Tamanho │ Data    │ Status  │
│  ───┼─────────────┼──────┼─────────┼─────────┼─────────│
│   3 │ contrato.pdf│ PDF  │ 2.5 MB  │ 07/01   │⏳Pendente│
│   2 │ doc.docx    │ DOCX │ 856 KB  │ 06/01   │⏳Pendente│
│   1 │ relatorio.txt│ TXT │ 45 KB   │ 05/01   │⏳Pendente│
│                                                          │
│  [DataTables: 1-3 de 3 | Buscar: _____ ]                │
└──────────────────────────────────────────────────────────┘
```

### Tela: Upload

```
┌──────────────────────────────────────────────────────────┐
│  📤 Upload para Resumo por IA                            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ℹ️ Como funciona:                                       │
│  • Envie documentos em PDF, DOCX ou TXT                 │
│  • A IA irá processar e gerar um resumo automático      │
│  • Você poderá visualizar o resumo na lista             │
│  • Tamanho máximo: 16 MB por arquivo                    │
│                                                          │
│  Documento: [Escolher arquivo] _____________________    │
│                                                          │
│  ⚠️ Atenção: O resumo será gerado automaticamente       │
│                                                          │
│  [← Voltar]                         [Enviar para Resumo]│
└──────────────────────────────────────────────────────────┘
```

### Tela: Detalhes

```
┌─────────────────────────┬─────────────────────────────────┐
│  📋 Informações        │  🧠 Resumo Gerado pela IA       │
│  ─────────────────────  │  ─────────────────────────────  │
│  ID: 3                 │  ⏳ Aguardando Processamento    │
│  Nome: contrato.pdf    │                                 │
│  Tipo: PDF             │  O documento foi enviado com    │
│  Tamanho: 2.5 MB       │  sucesso e está na fila para    │
│  Upload: 07/01 14:32   │  processamento.                 │
│  Status: ⏳ Pendente    │                                 │
│  Enviado: João Silva   │  O resumo será gerado em breve  │
│                        │  pela IA.                       │
│  ───────────────────   │                                 │
│  [🗑️ Excluir Documento]│                                 │
└─────────────────────────┴─────────────────────────────────┘
```

## 🔐 Segurança

```
┌─────────────────────────────────────────────────────────┐
│  CAMADA DE SEGURANÇA                                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. AUTENTICAÇÃO                                        │
│     └─ @require_law_firm decorator                      │
│        └─ Verifica sessão do usuário                    │
│                                                         │
│  2. AUTORIZAÇÃO                                         │
│     └─ Filtro por law_firm_id                           │
│        └─ Usuário só vê docs do seu escritório          │
│                                                         │
│  3. VALIDAÇÃO DE ARQUIVO                                │
│     └─ FileAllowed(['pdf', 'docx', 'txt', 'doc'])       │
│        └─ Rejeita outros tipos                          │
│                                                         │
│  4. SANITIZAÇÃO                                         │
│     └─ secure_filename(file.filename)                   │
│        └─ Remove caracteres perigosos                   │
│                                                         │
│  5. NOME ÚNICO                                          │
│     └─ timestamp + filename                             │
│        └─ Evita sobrescrita                             │
│                                                         │
│  6. CONFIRMAÇÃO                                         │
│     └─ confirm() antes de excluir                       │
│        └─ Previne exclusão acidental                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 🎯 Estados do Sistema

```
STATUS DO DOCUMENTO
├── pending      → ⏳ Aguardando processamento
├── processing   → 🔄 IA está analisando (futuro)
├── completed    → ✅ Resumo disponível (futuro)
└── error        → ❌ Falha no processamento (futuro)

BADGES DE STATUS
├── pending      → Badge amarelo (warning)
├── processing   → Badge azul (info)
├── completed    → Badge verde (success)
└── error        → Badge vermelho (danger)

ÍCONES BOOTSTRAP
├── Brain        → bi-brain (IA)
├── Tools        → bi-tools (Ferramentas)
├── File         → bi-file-earmark-text
├── Upload       → bi-cloud-upload
├── Eye          → bi-eye (visualizar)
├── Trash        → bi-trash (excluir)
└── Hourglass    → bi-hourglass-split (pendente)
```

## 📊 Relacionamentos

```
┌─────────────┐
│  LawFirm    │
│             │
│  id ◄───────┼────────┐
└─────────────┘        │
                       │
┌─────────────┐        │
│    User     │        │
│             │        │
│  id ◄───────┼───┐    │
│  law_firm_id├───┘    │
└─────────────┘        │
       ▲               │
       │               │
       │               │
┌──────┴────────────┐  │
│ AiDocumentSummary │  │
│                   │  │
│  id               │  │
│  user_id ─────────┘  │
│  law_firm_id ────────┘
│  original_filename
│  file_path
│  status
│  summary_text
│  ...
└───────────────────┘
```

## 🚀 Fluxo Futuro com IA

```
PROCESSAMENTO COM IA (NÃO IMPLEMENTADO)

1. WORKER/CRON JOB
   ↓
2. Query: status = 'pending'
   ↓
3. Para cada documento:
   ├─ Atualizar status → 'processing'
   ├─ Extrair texto do arquivo
   ├─ Enviar para API IA
   │  ├─ OpenAI GPT-4
   │  ├─ Anthropic Claude
   │  └─ Ou outro serviço
   ├─ Receber resumo
   ├─ Salvar no banco:
   │  ├─ summary_text = resumo
   │  ├─ status = 'completed'
   │  └─ processed_at = now()
   └─ Notificar usuário (opcional)
   ↓
4. Usuário acessa e vê resumo
```

---

**Resumo:** Sistema completamente funcional com interface profissional, segurança implementada e base 100% preparada para integração com IA. Apenas aguardando implementação do processamento por IA conforme necessidade futura.
