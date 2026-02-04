# Análise de Sentença Judicial - Implementação

## 📋 Visão Geral

Nova ferramenta para análise automática de sentenças judiciais utilizando Inteligência Artificial. O usuário pode fazer upload de uma sentença judicial e receber uma análise detalhada gerada por IA.

## 🗄️ Estrutura do Banco de Dados

### Tabela: `judicial_sentence_analysis`

```sql
CREATE TABLE judicial_sentence_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    law_firm_id INTEGER NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER,
    file_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    analysis_result TEXT,
    error_message TEXT,
    processed_at DATETIME,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (law_firm_id) REFERENCES law_firms (id)
)
```

**Status possíveis:**
- `pending` - Aguardando processamento
- `processing` - Sendo analisado pela IA
- `completed` - Análise concluída
- `error` - Erro no processamento

## 🎯 Funcionalidades Implementadas

### 1. Upload de Sentença
- **Rota:** `/tools/sentence-analysis/upload`
- **Método:** GET, POST
- **Função:** `judicial_sentence_analysis_upload()`
- **Template:** `templates/tools/sentence_analysis_upload.html`
- **Formatos aceitos:** PDF, DOCX, TXT
- **Tamanho máximo:** 16 MB

### 2. Listagem de Sentenças
- **Rota:** `/tools/sentence-analysis`
- **Método:** GET
- **Função:** `judicial_sentence_analysis_list()`
- **Template:** `templates/tools/sentence_analysis_list.html`
- **Exibe:** Histórico de todas as sentenças analisadas

### 3. Detalhes da Análise
- **Rota:** `/tools/sentence-analysis/<int:sentence_id>`
- **Método:** GET
- **Função:** `judicial_sentence_analysis_detail()`
- **Template:** `templates/tools/sentence_analysis_detail.html`
- **Exibe:** Resultado da análise com informações detalhadas

### 4. Deletar Análise
- **Rota:** `/tools/sentence-analysis/<int:sentence_id>/delete`
- **Método:** POST
- **Função:** `judicial_sentence_analysis_delete()`
- **Remove:** Registro do banco e arquivo físico

### 5. Reprocessar Análise
- **Rota:** `/tools/sentence-analysis/<int:sentence_id>/reprocess`
- **Método:** POST
- **Função:** `judicial_sentence_analysis_reprocess()`
- **Permite:** Reprocessar sentenças com erro

## 📁 Arquivos Criados/Modificados

### Modelos
- ✅ `app/models.py` - Modelo `JudicialSentenceAnalysis` adicionado

### Formulários
- ✅ `app/form.py` - `JudicialSentenceAnalysisForm` criado

### Rotas
- ✅ `app/blueprints/tools.py` - 5 rotas adicionadas para análise de sentenças

### Templates
- ✅ `templates/tools/sentence_analysis_upload.html` - Página de upload
- ✅ `templates/tools/sentence_analysis_list.html` - Listagem
- ✅ `templates/tools/sentence_analysis_detail.html` - Detalhes da análise

### Migração
- ✅ `database/add_judicial_sentence_analysis_table.py` - Script de migração

### Diretórios
- 📂 `uploads/sentence_analysis/` - Armazenamento de arquivos (criado automaticamente)

## 🔄 Fluxo de Funcionamento

```
1. Usuário acessa /tools/sentence-analysis
   ↓
2. Clica em "Enviar Sentença"
   ↓
3. Faz upload do arquivo (PDF, DOCX, TXT)
   ↓
4. Sistema salva o arquivo e cria registro no banco
   ↓
5. Status: "pending" (Aguardando implementação do agente IA)
   ↓
6. [FUTURO] Agente de IA processa o arquivo
   ↓
7. Sistema atualiza status para "completed" e salva resultado
   ↓
8. Usuário visualiza análise detalhada
```

## 🤖 Integração com Agente de IA (Não Implementado)

A estrutura está pronta para integração com agente de IA. Quando implementar, seguir este padrão:

```python
# Na função judicial_sentence_analysis_upload() após salvar o arquivo:

try:
    sentence.status = 'processing'
    db.session.commit()
    
    # TODO: Criar AgentSentenceAnalyzer
    # analyzer = AgentSentenceAnalyzer()
    
    # Para DOCX: extrair texto
    # if is_docx_file(file_path):
    #     text_content = extract_text_from_docx(os.path.abspath(file_path))
    #     analysis = analyzer.analyze_sentence(text_content=text_content)
    # else:
    #     Para PDF: usar file_id
    #     file_agent = FileAgent()
    #     file_id = file_agent.upload_file(os.path.abspath(file_path))
    #     analysis = analyzer.analyze_sentence(file_id=file_id)
    
    # Salvar resultado
    # sentence.analysis_result = analysis
    # sentence.processed_at = datetime.utcnow()
    # sentence.status = 'completed'
    # db.session.commit()
    
except Exception as e:
    sentence.status = 'error'
    sentence.error_message = str(e)
    db.session.commit()
```

## 📊 Análise Esperada do Agente de IA

O agente de IA deve retornar uma análise estruturada contendo:

1. **Dispositivo da Sentença**
   - Decisão (Procedente/Improcedente/Parcialmente Procedente)
   - Condenações

2. **Fundamentos Jurídicos**
   - Legislação aplicada
   - Jurisprudência citada
   - Doutrina mencionada

3. **Análise de Procedência/Improcedência**
   - Pedidos procedentes
   - Pedidos improcedentes
   - Fundamentação de cada decisão

4. **Pontos Relevantes para Recursos**
   - Argumentos fracos
   - Possibilidades de recurso
   - Precedentes aplicáveis

5. **Resumo Executivo**
   - Síntese da decisão
   - Principais pontos de atenção

## 🎨 Interface Visual

Todos os templates seguem o padrão moderno do dashboard:
- Header com gradiente suave
- Ícone circular com sombra
- Cards com outline
- Badges de status coloridos
- Layout responsivo

## 🔐 Segurança

- ✅ Autenticação obrigatória (`@require_law_firm`)
- ✅ Isolamento por escritório (law_firm_id)
- ✅ Verificação de propriedade do documento
- ✅ Sanitização de nomes de arquivo (`secure_filename`)
- ✅ Validação de tipo de arquivo

## 📝 Próximos Passos

1. ⏳ **Implementar Agente de IA**
   - Criar `AgentSentenceAnalyzer` em `app/agents/`
   - Configurar prompts específicos para análise de sentenças
   - Integrar com OpenAI API

2. ⏳ **Melhorias de Interface**
   - Adicionar visualização do PDF inline
   - Exportar análise em DOCX/PDF
   - Adicionar busca e filtros na listagem

3. ⏳ **Notificações**
   - Email quando análise for concluída
   - Alertas em tempo real

4. ⏳ **Analytics**
   - Dashboard de estatísticas
   - Relatórios de análises

## 🧪 Como Testar

1. Acesse: `http://localhost:5000/tools/sentence-analysis`
2. Clique em "Enviar Sentença"
3. Faça upload de um arquivo PDF, DOCX ou TXT
4. Verifique o registro na listagem
5. Clique em "Ver Detalhes" para visualizar
6. Status atual: "Pendente" (aguardando implementação do agente)

## 📚 Referências

Baseado na implementação existente de:
- `tools/document-summary` - Estrutura similar
- Sistema de agentes já implementado no projeto
- Padrão visual do dashboard

---

**Status:** ✅ Estrutura completa - Aguardando implementação do agente de IA
**Data:** 04/02/2026
