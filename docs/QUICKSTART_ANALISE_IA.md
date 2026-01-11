# 🚀 Quick Start - Análise de Documentos por IA

## ⚡ Uso Rápido

### 📄 Upload em Casos
```bash
1. Acesse um caso: /cases/{id}
2. Clique em "Documentos"
3. "Novo Documento"
4. Selecione arquivo
5. ☑ Marque "Usar na IA"
6. Enviar
```

### 🔍 Upload na Ferramenta
```bash
1. Menu: Ferramentas > Resumo de Documentos
2. "Upload Documento"
3. Selecione arquivo
4. Enviar (análise automática)
```

---

## 🎯 Requisitos

```bash
# .env
OPENAI_API_KEY=sk-...
```

---

## 📊 Estados do Documento

| Badge         | Status     | Ação             |
| ------------- | ---------- | ---------------- |
| 🟡 Pendente    | Aguardando | Aguarde          |
| 🔵 Processando | Analisando | Atualizar página |
| 🟢 Concluído   | Pronto     | Ver resumo       |
| 🔴 Erro        | Falhou     | Reprocessar      |

---

## 🔄 Reprocessar Documento

Se um documento falhar:
1. Abra a visualização do documento
2. Veja a mensagem de erro
3. Clique em "Reprocessar Documento"
4. Aguarde nova análise

---

## 🧪 Teste Rápido

```bash
# Inicie o servidor
uv run main.py

# Acesse
http://localhost:5000/tools/document-summary/upload

# Upload de um PDF
# Aguarde processamento
# Veja o resumo
```

---

## 📂 Tipos de Arquivo Suportados

- ✅ PDF
- ✅ DOCX
- ✅ DOC
- ✅ TXT

---

## 🤖 O Que a IA Analisa?

### Documentos Jurídicos
- Partes envolvidas
- Objeto do documento
- Datas importantes
- Fundamentos legais
- Pedidos e valores
- Prazos e obrigações
- Riscos identificados

---

## 🆘 Erros Comuns

### "Invalid API Key"
```bash
# Verifique o .env
OPENAI_API_KEY=sk-...
```

### "File too large"
```bash
# Reduza o tamanho do arquivo
# Máximo: ~20MB
```

### "Timeout"
```bash
# Arquivo muito grande ou servidor lento
# Clique em "Reprocessar"
```

---

## 📈 Monitorar Processamento

### Via Banco de Dados
```sql
-- Ver status de todos os documentos
SELECT id, original_filename, ai_status, ai_processed_at
FROM documents
WHERE use_in_ai = 1
ORDER BY uploaded_at DESC;

-- Ver erros
SELECT id, original_filename, ai_error_message
FROM documents
WHERE ai_status = 'error';
```

### Via Interface
```bash
# Lista de documentos
/cases/{id}/documents

# Detalhes com resumo
/cases/{id}/documents/{doc_id}/view
```

---

## 🎓 Exemplo de Resumo

### Input
```
CAT - Comunicação de Acidente de Trabalho
João da Silva
NIT: 123.456.789-10
Data: 15/03/2024
...
```

### Output da IA
```
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

**Observações Jurídicas**:
- Caracterizado como acidente de trajeto
- Requer análise de nexo causal
- Prazo para contestação: 15 dias
```

---

## 🔗 Links Rápidos

| Função              | URL                                   |
| ------------------- | ------------------------------------- |
| Upload (Casos)      | `/cases/{id}/documents/new`           |
| Upload (Ferramenta) | `/tools/document-summary/upload`      |
| Lista (Ferramenta)  | `/tools/document-summary`             |
| Visualizar          | `/cases/{id}/documents/{doc_id}/view` |

---

## ✅ Checklist Antes de Usar

- [ ] OpenAI API Key configurada
- [ ] Servidor rodando
- [ ] Banco de dados atualizado
- [ ] Documento em formato suportado
- [ ] Tamanho do arquivo < 20MB

---

## 💡 Dicas

1. **Marque "Usar na IA"** para análise automática
2. **Aguarde** durante processamento (pode levar 1-2 min)
3. **Atualize a página** se status não mudar
4. **Reprocesse** se houver erro
5. **Verifique o formato** do arquivo antes

---

## 📞 Suporte

- 📖 Doc completa: `docs/IMPLEMENTACAO_ANALISE_IA.md`
- 📊 Fluxos: `docs/FLUXO_ANALISE_IA_VISUAL.md`
- 📝 Resumo: `docs/RESUMO_IMPLEMENTACAO_IA.md`

---

**Pronto para usar!** 🎉
