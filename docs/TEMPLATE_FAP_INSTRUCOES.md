# Instruções para Criar Template DOCX de Petição FAP

## Visão Geral
O `AgentDocumentGenerator` agora suporta geração de petições FAP usando templates DOCX personalizados com preenchimento automático de dados do banco de dados.

## Como Funciona

### 1. Criação do Template DOCX
Crie um arquivo Word (.docx) com o formato da sua petição. Use **placeholders** para indicar onde os dados devem ser inseridos.

### 2. Placeholders Disponíveis

Use a sintaxe `{{variavel}}` para inserir dados automaticamente:

#### Dados do Cliente
- `{{cliente_nome}}` - Nome/Razão Social do cliente
- `{{cliente_cnpj}}` - CNPJ do cliente

#### Dados do Caso
- `{{caso_titulo}}` - Título do caso
- `{{caso_tipo}}` - Tipo do caso (fap, previdenciario, trabalhista, outros)
- `{{fap_motivo}}` - Motivo/Enquadramento FAP (texto legível)
- `{{ano_inicial_fap}}` - Ano inicial do FAP
- `{{ano_final_fap}}` - Ano final do FAP
- `{{total_beneficios}}` - Número total de benefícios no caso
- `{{valor_causa}}` - Valor da causa formatado (R$ X.XXX,XX)
- `{{data_ajuizamento}}` - Data de ajuizamento (dd/mm/aaaa)

#### Dados da Vara
- `{{vara_nome}}` - Nome da vara judicial
- `{{vara_cidade}}` - Cidade da vara
- `{{vara_estado}}` - Estado da vara

### 3. Exemplo de Template

```
EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA {{vara_nome}} - {{vara_cidade}}/{{vara_estado}}

AUTOR: {{cliente_nome}}
CNPJ: {{cliente_cnpj}}

{{cliente_nome}}, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº {{cliente_cnpj}}, 
vem, respeitosamente, à presença de Vossa Excelência, por meio de seus advogados que esta subscrevem, 
propor a presente

AÇÃO DE REVISÃO DE FAP - {{fap_motivo}}

em face do INSTITUTO NACIONAL DO SEGURO SOCIAL - INSS, pelos fatos e fundamentos a seguir expostos:

I - DOS FATOS

O caso refere-se à revisão do Fator Acidentário de Prevenção (FAP) calculado para os anos-base 
{{ano_inicial_fap}} a {{ano_final_fap}}, em razão de {{fap_motivo}}.

Total de benefícios impugnados: {{total_beneficios}}

RELAÇÃO DE BENEFÍCIOS:
[TABELA SERÁ PREENCHIDA AUTOMATICAMENTE]

II - DO DIREITO
...

III - DO PEDIDO

Diante do exposto, requer-se:
a) A procedência do pedido para exclusão dos benefícios listados;
b) Valor da causa: {{valor_causa}}

Termos em que,
Pede deferimento.

{{vara_cidade}}/{{vara_estado}}, {{data_ajuizamento}}
```

### 4. Tabelas de Benefícios

Quando você criar uma **tabela** no documento Word, o sistema automaticamente adicionará uma linha para cada benefício do caso com as seguintes colunas:

| Coluna | Dados |
|--------|-------|
| 0 | ID sequencial (1, 2, 3...) |
| 1 | Número do benefício (NB) |
| 2 | Nome do segurado |
| 3 | NIT do segurado |
| 4 | Data do acidente (dd/mm/aaaa) |
| 5 | Tipo do benefício (B91, B94, etc.) |
| 6 | Motivo do erro (se houver mais colunas) |
| 7 | Empresa do acidente (se houver mais colunas) |

**Exemplo de tabela no Word:**

| Nº | NB | Segurado | NIT | Data Acidente | Tipo |
|----|----|---------|----|---------------|------|
| [Será preenchido automaticamente] | | | | | |

### 5. Localização dos Templates

Salve seus templates DOCX em:
```
c:\Users\thiago\projetos\intellexia\templates_docx\
```

**Templates por motivo FAP (seleção automática):**
- `modelo_acidente_trajeto.docx` - Para "Inclusão indevida de benefício de trajeto"
- `modelo_acidente_trajeto_erro_material.docx` - Para "Erro material no preenchimento da CAT"
- `modelo_acidente_trajeto_extemporanea.docx` - Para "CAT de trajeto transmitida extemporaneamente"

O sistema seleciona automaticamente o template correto baseado no campo `fap_reason` do caso.

### 6. Uso no Sistema

#### Via Código:
```python
from agent_document_generator import AgentDocumentGenerator

agent = AgentDocumentGenerator()

# Seleção automática do template baseada no fap_reason
document = agent.generate_fap_petition(case_id=123)
document.save("peticao_gerada.docx")

# OU especificar template manualmente (override)
document = agent.generate_fap_petition(
    case_id=123,
    template_path="templates_docx/modelo_acidente_trajeto.docx"
)
document.save("peticao_gerada.docx")
```

#### Via Interface Web:
1. Acesse a página do caso
2. Selecione o **Motivo / Enquadramento** no formulário
3. Clique em "Gerar Petição"
4. Para casos FAP, o sistema **automaticamente**:
   - Identifica o motivo selecionado
   - Carrega o template correto
   - Preenche com dados do banco
   - Gera a petição personalizada

### 7. Fluxo de Geração

```
Caso FAP no Sistema
        ↓
Usuário solicita geração de petição
        ↓
Sistema identifica: case_type == 'fap'
        ↓
AgentDocumentGenerator é acionado
        ↓
Template DOCX é carregado
        ↓
Placeholders são substituídos por dados reais
        ↓
Benefícios são adicionados às tabelas
        ↓
Documento DOCX é salvo em uploads/petitions/
        ↓
Conteúdo é extraído e salvo no banco (tabela petitions)
        ↓
Petição disponível para visualização/download
```

## Vantagens desta Abordagem

1. ✅ **Controle Total do Layout**: Você define a formatação no Word
2. ✅ **Dados Sempre Atualizados**: Puxados diretamente do banco de dados
3. ✅ **Tabelas Dinâmicas**: Adicionam automaticamente todos os benefícios
4. ✅ **Fácil Manutenção**: Basta editar o template DOCX
5. ✅ **Específico para FAP**: Agente especializado vs genérico
6. ✅ **Preserva Formatação**: Mantém estilos, fontes, alinhamentos

## Diferenças entre Agentes

### AgentTextGenerator (Padrão)
- Usado para casos não-FAP
- Gera texto via IA
- Mais flexível, menos estruturado
- Formato: Texto puro/Markdown

### AgentDocumentGenerator (FAP)
- Usado para casos FAP (fap)
- Preenche templates DOCX
- Estrutura rígida e profissional
- Formato: Microsoft Word (.docx)

## Próximos Passos

1. Crie seu template DOCX personalizado
2. Salve em `templates_docx/modelo_fap.docx`
3. Adicione os placeholders desejados
4. Teste gerando uma petição via sistema
5. Ajuste o template conforme necessário
