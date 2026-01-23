# Inserção de Imagens de Documentos em Petições

## Visão Geral

O sistema agora suporta a inserção automática de imagens dos documentos anexados ao caso diretamente nas petições geradas.

## Funcionalidade

Quando você usa placeholders de imagem nos templates Word, o sistema:

1. **Busca** o documento anexado do tipo especificado
2. **Converte** PDFs para imagem (primeira página)
3. **Insere** a imagem no local do placeholder
4. **Centraliza** a imagem automaticamente

## Placeholders Disponíveis

| Placeholder | Tipo de Documento | Descrição |
|------------|------------------|-----------|
| `{{imagem_cat}}` | `cat` | Comunicação de Acidente de Trabalho |
| `{{imagem_fap}}` | `fap` | FAP - Fator Acidentário de Prevenção |
| `{{imagem_info_beneficiario}}` | `infben` | Informações do Beneficiário (INFBEN) |
| `{{imagem_declaracao_beneficio}}` | `declaracao_beneficio` | Declaração de Benefício |
| `{{imagem_inss_beneficiario}}` | `cnis` | CNIS - Cadastro Nacional de Informações Sociais |
| `{{imagem_vigencia_beneficio}}` | `vigencia_beneficio` | Documento de Vigência do Benefício |

## Como Usar

### 1. No Template Word

Adicione o placeholder onde deseja que a imagem apareça:

```
2. DOCUMENTOS COMPROBATÓRIOS

Segue anexa a Comunicação de Acidente de Trabalho:

{{imagem_cat}}

Como se observa do documento acima...
```

### 2. No Sistema

1. Anexe o documento ao caso através da interface de documentos
2. **IMPORTANTE**: Selecione o **Tipo de Documento** correto ao fazer upload:
   - Para CAT, selecione "CAT"
   - Para FAP, selecione "FAP"
   - E assim por diante...

3. Ao gerar a petição, a imagem será automaticamente inserida

## Formatos Suportados

### Imagens Diretas
- PNG
- JPG/JPEG
- BMP
- GIF

### PDFs
- Converte automaticamente a **primeira página** do PDF em imagem
- Resolução: 150 DPI
- Formato resultante: PNG

## Tamanhos

- **Parágrafos normais**: 6 polegadas de largura
- **Células de tabela**: 5 polegadas de largura
- Todas as imagens são **centralizadas** automaticamente

## Instalação do Poppler (Necessário para PDF)

O sistema usa `pdf2image` que requer **Poppler** instalado no sistema operacional.

### Windows

**Opção 1: Usando Chocolatey**
```bash
choco install poppler
```

**Opção 2: Manual**
1. Baixe Poppler para Windows: https://github.com/oschwartz10612/poppler-windows/releases
2. Extraia para `C:\Program Files\poppler`
3. Adicione `C:\Program Files\poppler\Library\bin` ao PATH do sistema

**Opção 3: Scoop**
```bash
scoop install poppler
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get install poppler-utils
```

### macOS
```bash
brew install poppler
```

## Verificar Instalação

Para verificar se o Poppler está instalado corretamente:

```bash
# Windows
pdftoppm -v

# Linux/macOS
pdftoppm --version
```

## Arquitetura Técnica

### Fluxo de Processamento

```
generate_fap_petition()
    ↓
_replace_placeholders_in_document()  (substitui placeholders de texto)
    ↓
_insert_document_images()  (insere imagens)
    ↓ (para cada tipo de documento)
_replace_placeholder_with_image()
    ↓
    ├─→ PDF? → convert_from_path() → BytesIO
    ├─→ Imagem? → open() → BytesIO
    └─→ run.add_picture() → Centraliza
```

### Métodos Principais

#### `_insert_document_images(document, case_id)`
- Itera sobre todos os tipos de placeholders de imagem
- Busca documentos anexados por `document_type`
- Chama `_replace_placeholder_with_image()` para cada documento encontrado

#### `_replace_placeholder_with_image(document, placeholder, file_path)`
- Verifica existência do arquivo
- Detecta formato (PDF vs imagem)
- Converte PDF para imagem se necessário
- Procura placeholder em parágrafos e tabelas
- Substitui texto por imagem
- Centraliza automaticamente

### Tratamento de Erros

O sistema trata graciosamente os seguintes erros:
- ✅ Arquivo não encontrado: Log de erro, continua processamento
- ✅ Formato não suportado: Log de erro, ignora placeholder
- ✅ Erro na conversão PDF: Log de erro, continua
- ✅ Erro ao inserir imagem: Log de erro, continua

Isso garante que **uma imagem problemática não impeça a geração completa da petição**.

## Exemplos de Uso

### Template Simples
```
PROVA DOS ACIDENTES DE TRABALHO

Conforme documentos anexos:

{{imagem_cat}}

Verifica-se pelo documento acima que...
```

### Template em Tabela
```
| Documento | Imagem |
|-----------|--------|
| CAT       | {{imagem_cat}} |
| FAP       | {{imagem_fap}} |
```

### Múltiplas Imagens
```
1. COMUNICAÇÃO DE ACIDENTE
{{imagem_cat}}

2. FATOR ACIDENTÁRIO
{{imagem_fap}}

3. INFORMAÇÕES DO BENEFICIÁRIO
{{imagem_info_beneficiario}}
```

## Troubleshooting

### Imagem não aparece
1. ✅ Verifique se o documento foi anexado ao caso
2. ✅ Verifique se o **tipo de documento** está correto
3. ✅ Verifique se o arquivo existe em `uploads/cases/<case_id>/`
4. ✅ Verifique logs para mensagens de erro

### Erro "Poppler not found"
- ✅ Instale Poppler seguindo as instruções acima
- ✅ Reinicie o terminal/IDE após instalação
- ✅ Verifique PATH do sistema

### PDF não converte
- ✅ Verifique se o PDF não está corrompido
- ✅ Teste abrir o PDF em outro programa
- ✅ Verifique permissões do arquivo

### Imagem muito grande/pequena
- Edite o valor `width=Inches(6)` no código
- Valores típicos: 4-7 polegadas

## Limitações Atuais

- ⚠️ Apenas a **primeira página** de PDFs é convertida
- ⚠️ Um placeholder só pode ser usado **uma vez** por documento
- ⚠️ Imagens são sempre centralizadas (não personalizável via template)

## Próximas Melhorias

- [ ] Suporte para múltiplas páginas de PDF
- [ ] Opção de configurar tamanho da imagem via placeholder: `{{imagem_cat:4}}`
- [ ] Opção de alinhamento: `{{imagem_cat:left}}`
- [ ] Compressão automática de imagens grandes
- [ ] Preview das imagens antes de gerar petição
- [ ] Upload de múltiplos documentos do mesmo tipo
- [ ] Controle de qualidade/DPI por placeholder

## Notas Técnicas

- **Biblioteca de conversão PDF**: `pdf2image` v1.17.0+
- **Biblioteca de imagem**: `Pillow` (PIL)
- **Biblioteca Word**: `python-docx`
- **DPI padrão**: 150 (bom equilíbrio entre qualidade e tamanho)
- **Formato intermediário**: PNG (preserva qualidade)
