# Guia de Visualização de Petições DOCX

## Como Funciona Atualmente

### Para Petições FAP (DOCX):

1. **Geração**: Documento Word é criado com formatação completa
2. **Salvamento**: 
   - Arquivo DOCX salvo em `uploads/petitions/fap/`
   - Texto extraído salvo no banco (para busca/indexação)
3. **Visualização na Web**:
   - Alerta informativo destacado
   - Botão grande para download do DOCX
   - Prévia em texto simples (colapsável)

### Para Petições Normais (Texto):
- Visualização direta no navegador
- Formatação simples preservada

## Melhorias Implementadas

### 1. Interface Clara
```
┌─────────────────────────────────────────┐
│ ℹ️ Petição FAP gerada em formato DOCX  │
│                                         │
│ [Baixar Documento DOCX] ⬅️ DESTAQUE    │
└─────────────────────────────────────────┘
```

### 2. Prévia Opcional
- Escondida por padrão (elemento `<details>`)
- Usuário pode expandir se quiser ver o texto
- Não confunde com o documento principal

### 3. Fluxo de Uso
```
Usuário acessa visualização
        ↓
Vê aviso sobre DOCX
        ↓
Clica no botão para baixar
        ↓
Abre no Word/LibreOffice/Google Docs
        ↓
Visualiza com formatação perfeita
```

## Opções de Visualização Online (Futuro)

### Opção 1: Converter DOCX para HTML
```python
# Usando mammoth
import mammoth

def docx_to_html(docx_path):
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        return result.value
```

### Opção 2: Usar Microsoft Office Online Viewer
```html
<iframe src="https://view.officeapps.live.com/op/embed.aspx?src=URL_DO_DOCUMENTO"></iframe>
```

### Opção 3: Usar Google Docs Viewer
```html
<iframe src="https://docs.google.com/viewer?url=URL_DO_DOCUMENTO&embedded=true"></iframe>
```

### Opção 4: Converter para PDF
```python
# Usando docx2pdf
from docx2pdf import convert

convert("input.docx", "output.pdf")
```

## Recomendação Atual

**Manter o download** é a melhor opção porque:
- ✅ Garante formatação 100% fiel
- ✅ Permite edição posterior
- ✅ Não depende de serviços externos
- ✅ Melhor desempenho (sem conversão)
- ✅ Funciona offline
- ✅ Mais profissional para documentos jurídicos

A prévia em texto é útil para:
- Busca rápida de informações
- Copiar trechos específicos
- Verificação rápida sem abrir Word
