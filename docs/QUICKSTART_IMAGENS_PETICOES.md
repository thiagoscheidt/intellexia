# 🖼️ Guia Rápido: Inserção de Imagens em Petições

## ⚡ Como Usar em 3 Passos

### 1️⃣ Anexar Documento ao Caso
1. Acesse o caso
2. Vá para aba "Documentos"
3. Clique em "Adicionar Documento"
4. Faça upload do arquivo (PDF ou imagem)
5. **IMPORTANTE**: Selecione o tipo correto:
   - CAT → Tipo: "CAT"
   - FAP → Tipo: "FAP"
   - INFBEN → Tipo: "INFBEN"
   - etc.

### 2️⃣ Usar Placeholder no Template
No seu template Word (`.docx`), coloque o placeholder onde quer a imagem:

```
2. COMUNICAÇÃO DE ACIDENTE DE TRABALHO

Segue anexa a CAT:

{{imagem_cat}}

Conforme se observa...
```

### 3️⃣ Gerar Petição
- Clique em "Gerar Petição"
- A imagem será inserida automaticamente!

## 🏷️ Placeholders Disponíveis

```
{{imagem_cat}}                    - Comunicação de Acidente
{{imagem_fap}}                    - FAP
{{imagem_info_beneficiario}}      - INFBEN
{{imagem_declaracao_beneficio}}   - Declaração
{{imagem_inss_beneficiario}}      - CNIS
{{imagem_vigencia_beneficio}}     - Vigência
```

## 📋 Formatos Aceitos

✅ **PDFs** (primeira página é convertida)  
✅ **Imagens**: PNG, JPG, JPEG, BMP, GIF

## ⚙️ Instalação Poppler (Apenas Windows)

**Necessário uma vez apenas para converter PDFs:**

### Opção 1: Chocolatey (Recomendado)
```bash
choco install poppler
```

### Opção 2: Scoop
```bash
scoop install poppler
```

### Opção 3: Manual
1. Baixe: https://github.com/oschwartz10612/poppler-windows/releases
2. Extraia para `C:\Program Files\poppler`
3. Adicione ao PATH: `C:\Program Files\poppler\Library\bin`

**Testar instalação:**
```bash
pdftoppm -v
```

## ❓ Problemas Comuns

### Imagem não aparece?
- ✅ Documento foi anexado?
- ✅ Tipo de documento está correto?
- ✅ Placeholder escrito corretamente?

### Erro "Poppler not found"?
- ✅ Instale Poppler (ver acima)
- ✅ Reinicie o terminal/VS Code
- ✅ Teste: `pdftoppm -v`

## 💡 Dicas

- **Qualidade**: PDFs são convertidos em 150 DPI (boa qualidade)
- **Tamanho**: Imagens são inseridas com 6 polegadas de largura
- **Alinhamento**: Sempre centralizado automaticamente
- **Performance**: Primeira página de PDF apenas (rápido)

## 📝 Exemplo Completo

**Template:**
```
EXCELENTÍSSIMO SENHOR DOUTOR JUIZ...

1. DOS FATOS

...texto...

2. DOS DOCUMENTOS COMPROBATÓRIOS

2.1. Comunicação de Acidente de Trabalho

{{imagem_cat}}

Como se observa do documento acima, o acidente...

2.2. Fator Acidentário de Prevenção

{{imagem_fap}}

Verifica-se que o FAP...
```

**Resultado:**  
As imagens dos documentos anexados aparecerão nos locais dos placeholders, centralizadas e com tamanho adequado.

---

📚 **Documentação completa**: [INSERCAO_IMAGENS_DOCUMENTOS.md](INSERCAO_IMAGENS_DOCUMENTOS.md)
