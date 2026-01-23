# 🧪 Como Testar a Inserção de Imagens

## Pré-requisitos

### 1. Instalar Poppler (Windows)

Escolha uma opção:

**Chocolatey (Recomendado):**
```bash
choco install poppler
```

**Scoop:**
```bash
scoop install poppler
```

**Manual:**
1. Baixe: https://github.com/oschwartz10612/poppler-windows/releases
2. Extraia para `C:\Program Files\poppler`
3. Adicione ao PATH: `C:\Program Files\poppler\Library\bin`
4. Reinicie o terminal

**Verificar instalação:**
```bash
pdftoppm -v
```

### 2. Preparar Arquivos de Teste

Crie uma pasta de teste com documentos de exemplo:
```
test_documents/
├── exemplo_cat.pdf
├── exemplo_fap.pdf
└── exemplo_infben.jpg
```

## 🎯 Teste Passo a Passo

### Teste 1: Upload de Documento CAT

1. **Acessar Sistema**
   - Abra o navegador: http://localhost:5000
   - Faça login

2. **Criar/Abrir Caso**
   - Vá para "Casos"
   - Abra um caso existente ou crie um novo

3. **Anexar Documento CAT**
   - Clique na aba "Documentos"
   - Clique em "Adicionar Documento"
   - Selecione o arquivo `exemplo_cat.pdf`
   - **IMPORTANTE**: No campo "Tipo de Documento", selecione **"CAT"**
   - Clique em "Salvar"

4. **Verificar Upload**
   - Documento deve aparecer na lista
   - Verifique o caminho do arquivo (algo como: `uploads/cases/4/exemplo_cat.pdf`)

### Teste 2: Criar Template com Placeholder

1. **Abrir Template Existente**
   - Navegue até: `templates_docx/modelo_acidente_trajeto.docx`
   - Abra no Microsoft Word

2. **Adicionar Placeholder**
   - Encontre a seção onde quer inserir a imagem CAT
   - Adicione uma nova linha com o texto:
   ```
   {{imagem_cat}}
   ```
   - Salve o arquivo

**Exemplo de conteúdo:**
```
2. DOS DOCUMENTOS COMPROBATÓRIOS

2.1. Comunicação de Acidente de Trabalho

Segue anexa a CAT do acidente:

{{imagem_cat}}

Conforme se observa do documento acima, o acidente ocorreu...
```

3. **Salvar Template**
   - Salve o arquivo Word
   - Feche o Word

### Teste 3: Gerar Petição com Imagem

1. **Voltar ao Caso**
   - No navegador, esteja no caso que tem o documento CAT anexado

2. **Gerar Petição**
   - Vá para aba "Petição"
   - Clique em "Gerar Petição FAP"
   - Aguarde o timer (10-15 segundos)

3. **Baixar Resultado**
   - Clique no botão "Baixar" da petição gerada
   - Salve o arquivo `.docx`

4. **Verificar Resultado**
   - Abra o arquivo no Word
   - Navegue até o local onde estava o placeholder `{{imagem_cat}}`
   - **ESPERADO**: A imagem do documento CAT deve estar inserida
   - **ESPERADO**: A imagem deve estar centralizada
   - **ESPERADO**: A imagem deve ter aproximadamente 6 polegadas de largura

### Teste 4: Múltiplas Imagens

1. **Anexar Mais Documentos**
   - Anexe um documento FAP (tipo: "FAP")
   - Anexe um documento INFBEN (tipo: "INFBEN")

2. **Atualizar Template**
   - Adicione no template:
   ```
   2.1. CAT
   {{imagem_cat}}

   2.2. FAP
   {{imagem_fap}}

   2.3. Informações do Beneficiário
   {{imagem_info_beneficiario}}
   ```

3. **Gerar Nova Petição**
   - Gere nova versão da petição
   - Verifique se **todas as imagens** aparecem corretamente

### Teste 5: PDF vs Imagem Direta

1. **Teste com PDF**
   - Anexe um arquivo `.pdf` como CAT
   - Gere petição
   - Verifique se a **primeira página** do PDF foi convertida para imagem

2. **Teste com Imagem**
   - Anexe um arquivo `.jpg` como CAT
   - Gere petição
   - Verifique se a imagem foi inserida diretamente

## ✅ Checklist de Validação

### Upload de Documento
- [ ] Documento aparece na lista após upload
- [ ] Tipo de documento está correto
- [ ] Arquivo existe fisicamente em `uploads/cases/<case_id>/`

### Geração de Petição
- [ ] Petição é gerada sem erros
- [ ] Timer aparece corretamente
- [ ] Arquivo `.docx` é baixado

### Inserção de Imagem
- [ ] Placeholder `{{imagem_cat}}` foi removido
- [ ] Imagem do documento CAT aparece no lugar
- [ ] Imagem está centralizada
- [ ] Imagem tem tamanho adequado (não muito grande/pequena)
- [ ] Qualidade da imagem é boa (150 DPI)

### Conversão PDF
- [ ] PDF é convertido para imagem
- [ ] Apenas primeira página é incluída
- [ ] Conversão mantém legibilidade

### Múltiplas Imagens
- [ ] Todas as imagens aparecem
- [ ] Cada imagem está no local correto
- [ ] Não há duplicação de imagens

## 🐛 Resolução de Problemas

### Erro: "Poppler not found"
```bash
# Instalar Poppler
choco install poppler

# Reiniciar terminal
exit

# Verificar
pdftoppm -v
```

### Imagem não aparece
**Verificar logs:**
```python
# No console/terminal onde Flask está rodando, procure por:
# "Arquivo não encontrado: ..."
# "Erro ao converter PDF: ..."
# "Erro ao inserir imagem: ..."
```

**Verificar arquivo:**
```bash
# Verificar se arquivo existe
dir uploads\cases\<case_id>\

# Verificar se documento está no banco
# Use a interface de documentos do sistema
```

**Verificar tipo de documento:**
- Abra o documento na interface
- Confirme que o "Tipo de Documento" está correto
- Deve ser exatamente: "cat", "fap", "infben", etc. (minúsculas)

### PDF não converte
**Testar conversão manual:**
```bash
# Testar Poppler
pdftoppm -png -f 1 -l 1 uploads/cases/4/exemplo_cat.pdf output

# Se funcionar, o problema está no código Python
# Se não funcionar, o problema é com Poppler ou o PDF
```

**PDF corrompido:**
- Tente abrir o PDF em outro programa
- Tente converter o PDF online primeiro
- Use um PDF diferente para teste

### Imagem muito grande
**Ajustar no código:**

Abra `agent_document_generator.py` e procure por:
```python
run.add_picture(image_stream, width=Inches(6))
```

Altere o valor de `6` para um valor menor (ex: `4` ou `5`).

### Imagem muito pequena
Altere o valor de `6` para um valor maior (ex: `7` ou `8`).

## 📊 Logs de Debug

### Ativar Logs Detalhados

No arquivo `agent_document_generator.py`, os métodos já têm prints de debug:

```python
print(f"Arquivo não encontrado: {file_path}")
print(f"Erro ao converter PDF para imagem: {e}")
print(f"Erro ao ler imagem: {e}")
print(f"Formato de arquivo não suportado: {file_extension}")
print(f"Erro ao inserir imagem: {e}")
```

**Verificar logs:**
- Olhe o terminal onde o Flask está rodando
- Procure por mensagens de erro específicas

## 🎓 Casos de Teste Sugeridos

### Caso 1: CAT Simples
- 1 documento CAT em PDF
- Template com 1 placeholder `{{imagem_cat}}`
- Resultado esperado: Imagem única, centralizada

### Caso 2: Múltiplos Documentos
- CAT (PDF)
- FAP (PDF)
- INFBEN (JPG)
- Template com 3 placeholders
- Resultado esperado: 3 imagens, cada uma no lugar correto

### Caso 3: Sem Documento
- Template com `{{imagem_cat}}` mas sem documento CAT anexado
- Resultado esperado: Placeholder permanece como texto (graceful degradation)

### Caso 4: Formato Misto
- CAT em JPG (imagem direta)
- FAP em PDF (conversão necessária)
- Resultado esperado: Ambas as imagens aparecem corretamente

### Caso 5: PDF Multi-página
- PDF com 5 páginas
- Resultado esperado: Apenas primeira página é convertida e inserida

## 📝 Reportar Problemas

Se encontrar bugs, anote:
1. **Passos para reproduzir**
2. **Mensagem de erro** (do terminal)
3. **Tipo de arquivo** (PDF, JPG, etc.)
4. **Tamanho do arquivo**
5. **Sistema operacional**

## ✨ Próximos Testes

Após validar a funcionalidade básica, teste:
- [ ] Performance com PDFs grandes (10+ páginas)
- [ ] Performance com muitos documentos (10+ imagens)
- [ ] Diferentes resoluções de PDF
- [ ] Imagens PNG transparentes
- [ ] Documentos em tabelas
- [ ] Documentos em cabeçalhos/rodapés
