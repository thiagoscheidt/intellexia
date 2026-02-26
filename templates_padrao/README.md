# Templates de Documentos

## Como funciona

O sistema utiliza o arquivo `modelo_documento.docx` como **base** para gerar os recursos judiciais.

### Processo de Geração:

1. **Copia o template** → Mantém cabeçalhos e rodapés
2. **Limpa o conteúdo antigo** → Remove parágrafos existentes para não herdar formatação
3. **Aplica Segoe UI 11pt** → Define explicitamente a fonte e tamanho em cada parágrafo
4. **Insere os dados da IA** → Adiciona o conteúdo gerado (introdução, fundamentação, pedidos, etc.)
5. **Salva o documento final** → Pronto para download

### Formatação Aplicada:

| Elemento | Fonte | Tamanho | Estilo |
|----------|-------|---------|--------|
| **Título do recurso** | Segoe UI | 16pt | Negrito, Centralizado |
| **Títulos das seções** | Segoe UI | 14pt | Negrito |
| **Texto dos parágrafos** | Segoe UI | 11pt | Normal |

### Vantagens:

✅ Mantém cabeçalhos e rodapés do seu escritório  
✅ **Fonte consistente: Segoe UI 11pt** (padrão profissional)  
✅ Formatação limpa e moderna  
✅ Pronto para envio ao tribunal

### Modificando o Template:

**O que você pode modificar no template:**

1. **Cabeçalho** → Logo do escritório, endereço, telefone
2. **Rodapé** → Informações de contato, página, etc.
3. **Margens e orientação** → Ajustar layout da página

**Formatação do texto:**

A formatação (fonte, tamanho, estilos) é aplicada automaticamente pelo sistema:
- Títulos: Segoe UI 16pt negrito
- Seções: Segoe UI 14pt negrito  
- Parágrafos: Segoe UI 11pt

Para alterar a fonte/tamanho usado, edite o arquivo [process_judicial_appeals.py](../scripts/process_judicial_appeals.py#L40-L75)

---

**Local do template:** `templates_padrao/modelo_documento.docx`
