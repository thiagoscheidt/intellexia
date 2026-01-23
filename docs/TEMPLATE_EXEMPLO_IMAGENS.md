# Template de Exemplo: Inserção de Imagens

Este é um exemplo de como usar os placeholders de imagem nos templates Word.

## Estrutura do Template

```
EXCELENTÍSSIMO SENHOR DOUTOR JUIZ FEDERAL DA [VARA]

[Introdução do caso...]

I - DOS FATOS

[Narrativa dos fatos...]

II - DOS DOCUMENTOS COMPROBATÓRIOS

2.1. Comunicação de Acidente de Trabalho (CAT)

Conforme Comunicação de Acidente de Trabalho anexa:

{{imagem_cat}}

Como se observa do documento acima, o acidente de trabalho foi devidamente comunicado ao INSS...

2.2. Fator Acidentário de Prevenção (FAP)

Segue o demonstrativo do FAP da empresa:

{{imagem_fap}}

Verifica-se que o FAP aplicado à empresa no período de {{vigencia_fap}} foi de...

2.3. Informações do Beneficiário (INFBEN)

Conforme extrato do INFBEN:

{{imagem_info_beneficiario}}

Observa-se que o beneficiário possui registro de...

2.4. Cadastro Nacional de Informações Sociais (CNIS)

Extrato do CNIS do segurado:

{{imagem_inss_beneficiario}}

Conforme se verifica do CNIS, o segurado possui vínculos...

2.5. Declaração de Benefício

Declaração emitida pelo INSS:

{{imagem_declaracao_beneficio}}

A declaração confirma que...

2.6. Vigência do Benefício

Documento comprobatório da vigência:

{{imagem_vigencia_beneficio}}

Constata-se que o benefício está vigente desde...

III - DO DIREITO

[Fundamentação jurídica...]

IV - DOS PEDIDOS

Diante do exposto, requer-se:

a) A citação do INSS...
b) A condenação do réu...

Termos em que pede deferimento.

[Cidade], [Data]

[Advogado]
OAB/UF [Número]
```

## Placeholders Disponíveis

| Placeholder | Tipo de Documento | Quando Usar |
|------------|------------------|-------------|
| `{{imagem_cat}}` | CAT | Comunicação de Acidente de Trabalho |
| `{{imagem_fap}}` | FAP | Demonstrativo do Fator Acidentário |
| `{{imagem_info_beneficiario}}` | INFBEN | Extrato de informações do beneficiário |
| `{{imagem_inss_beneficiario}}` | CNIS | Cadastro Nacional de Informações Sociais |
| `{{imagem_declaracao_beneficio}}` | Declaração | Declarações diversas do INSS |
| `{{imagem_vigencia_beneficio}}` | Vigência | Comprovante de vigência do benefício |

## Dicas de Formatação

### Antes do Placeholder
- Adicione um título ou subtítulo
- Explique brevemente o que é o documento
- Use numeração clara (2.1, 2.2, etc.)

### Depois do Placeholder
- Faça referência ao documento: "Como se observa do documento acima..."
- Extraia informações relevantes
- Conecte com a argumentação jurídica

### Espaçamento
- Deixe uma linha em branco antes do placeholder
- Deixe uma linha em branco depois do placeholder
- Isso garante que a imagem terá espaço adequado

## Exemplo de Seção Completa

```
2.1. COMUNICAÇÃO DE ACIDENTE DE TRABALHO

Conforme Comunicação de Acidente de Trabalho - CAT nº {{numero_cat}}, 
emitida em {{data_acidente}}, segue documento comprobatório:

{{imagem_cat}}

Do documento acima, verifica-se que:

a) O acidente ocorreu em {{data_acidente}};
b) O tipo de acidente foi: {{tipo_acidente}};
c) A natureza da lesão: {{natureza_lesao}};
d) A parte do corpo atingida: {{parte_corpo}}.

Dessa forma, resta comprovado que o acidente é de natureza ocupacional...
```

## Exemplo com Tabela

```
| Documento | Número/Referência | Imagem |
|-----------|-------------------|--------|
| CAT | {{numero_cat}} | {{imagem_cat}} |
| Benefício | {{numero_beneficio}} | {{imagem_declaracao_beneficio}} |
```

**Nota**: Imagens em tabelas são redimensionadas para 5 polegadas (vs 6 polegadas em parágrafos normais).

## Exemplo com Múltiplos Beneficiários

```
2.3. BENEFÍCIOS CONCEDIDOS

Seguem os comprovantes dos benefícios concedidos aos segurados:

2.3.1. Primeiro Segurado

Nome: {{nome_segurado_1}}
NB: {{numero_beneficio_1}}

{{imagem_declaracao_beneficio}}

2.3.2. Segundo Segurado

Nome: {{nome_segurado_2}}
NB: {{numero_beneficio_2}}

{{imagem_vigencia_beneficio}}
```

## Tratamento de Erros

### Se o documento não foi anexado:
- O placeholder permanecerá como texto
- Não causará erro na geração
- Você verá: `{{imagem_cat}}` no documento final

### Se o documento está corrompido:
- O placeholder permanecerá como texto
- Uma mensagem de erro aparecerá no log do servidor
- A geração da petição continuará normalmente

## Boas Práticas

### ✅ Fazer
- Use títulos claros antes de cada imagem
- Faça referência específica ao documento após a imagem
- Mantenha espaçamento adequado
- Numere as seções claramente

### ❌ Evitar
- Não use múltiplos placeholders do mesmo tipo no mesmo documento
- Não coloque placeholders em cabeçalhos/rodapés
- Não confie apenas na imagem - sempre adicione texto explicativo
- Não use imagens como única prova - contextualize com dados textuais

## Formatação Automática

O sistema automaticamente:
- ✅ Centraliza todas as imagens
- ✅ Ajusta largura para 6 polegadas (parágrafos) ou 5 polegadas (tabelas)
- ✅ Converte PDF para PNG com 150 DPI
- ✅ Remove o placeholder após inserir a imagem
- ✅ Mantém formatação do restante do parágrafo

## Integração com Outros Placeholders

Você pode combinar placeholders de imagem com placeholders de texto:

```
SEGURADO: {{nome_segurado}}
CPF: {{cpf_segurado}}
NB: {{numero_beneficio}}
CAT: {{numero_cat}}

COMPROVANTE:

{{imagem_cat}}

Conforme documento acima, o acidente ocorreu em {{data_acidente}}...
```

## Testando seu Template

1. Crie o template com os placeholders
2. Salve como `.docx`
3. Coloque em `templates_docx/`
4. Anexe documentos ao caso (com tipos corretos!)
5. Gere a petição
6. Verifique o resultado

## Solução de Problemas

### Imagem não aparece?
- Verifique se o documento foi anexado
- Verifique se o **tipo de documento** está correto
- Verifique os logs do servidor

### Imagem muito grande?
- Considere reduzir o tamanho do arquivo original
- O sistema já limita a 6 polegadas de largura

### Imagem de baixa qualidade?
- Use arquivos de maior resolução
- Para PDFs, garanta que foram criados com qualidade adequada
- Evite scans de baixa resolução

---

📚 **Documentação Completa**: [INSERCAO_IMAGENS_DOCUMENTOS.md](INSERCAO_IMAGENS_DOCUMENTOS.md)
🧪 **Guia de Testes**: [TESTE_INSERCAO_IMAGENS.md](TESTE_INSERCAO_IMAGENS.md)
⚡ **Quickstart**: [QUICKSTART_IMAGENS_PETICOES.md](QUICKSTART_IMAGENS_PETICOES.md)
