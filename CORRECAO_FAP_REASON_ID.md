# Correção: Salvamento do Campo "Motivo da Contestação FAP"

## Problema Identificado
O campo "Motivo da Contestação FAP" (fap_reason_id) não estava sendo salvo no banco de dados durante a criação ou edição de benefícios.

## Causa Raiz
1. **Coluna faltante no banco**: A tabela `case_benefits` tinha a coluna `fap_reason` (VARCHAR) mas não tinha a coluna `fap_reason_id` (INTEGER) que seria uma chave estrangeira para a tabela `fap_reasons`.
2. **Tipo de dados inconsistente**: O modelo SQLAlchemy definiu `fap_reason_id`, mas o banco de dados não tinha essa coluna.
3. **Problema com choices no formulário**: Quando as choices eram populadas após a criação do formulário no modo de edição, o WTForms não conseguia validar o valor existente.

## Solução Implementada

### 1. Adicionar coluna `fap_reason_id` ao modelo (app/models.py)
```python
fap_reason_id = db.Column(db.Integer, db.ForeignKey('fap_reasons.id'), index=True)
fap_reason_obj = db.relationship('FapReason', foreign_keys=[fap_reason_id])
```

### 2. Executar migração do banco de dados
Script criado: `database/add_fap_reason_id_column.py`
- Adiciona a coluna `fap_reason_id` ao banco de dados existente
- Verifica se a coluna já existe para evitar erros

### 3. Corrigir as choices do SelectField (app/blueprints/benefits.py)

**Problema**: As choices precisam ser strings para que o coerce funcione corretamente.

**Solução**:
- Converter IDs para strings nas choices: `[(str(r.id), r.display_name) for r in fap_reasons]`
- Garantir que `fap_reason_id.data` seja convertido para int antes de salvar: `int(form.fap_reason_id.data) if form.fap_reason_id.data else None`

### 4. Corrigir ordem de operações no modo de edição

**Problema**: Quando criávamos o formulário com `form = CaseBenefitContextForm(obj=benefit)`, o WTForms tentava validar o valor de `fap_reason_id` contra as choices, mas as choices ainda não haviam sido populadas.

**Solução**:
1. Popular as choices ANTES de criar o formulário
2. Definir manualmente `form.fap_reason_id.data = str(benefit.fap_reason_id)` após criar o formulário

```python
# Populate choices FIRST
fap_reason_choices = [('', 'Nenhum motivo selecionado')] + [(str(r.id), r.display_name) for r in fap_reasons]

# Create form AFTER choices are ready
form = CaseBenefitContextForm(obj=benefit)

# Set choices on the form
form.fap_reason_id.choices = fap_reason_choices

# Ensure the data is properly set
if benefit.fap_reason_id:
    form.fap_reason_id.data = str(benefit.fap_reason_id)
```

## Arquivos Modificados

1. **app/models.py**
   - Adicionado: coluna `fap_reason_id` com foreign key
   - Adicionado: relacionamento `fap_reason_obj`

2. **app/blueprints/benefits.py**
   - `case_benefit_new()`: Converter IDs para strings nas choices
   - `case_benefit_edit()`: Reordenar lógica para popular choices antes de criar o formulário
   - Ambas as funções: Converter `fap_reason_id` para int ao salvar

3. **database/add_fap_reason_id_column.py** (novo arquivo)
   - Script de migração para adicionar a coluna ao banco de dados

## Validação

✅ Coluna `fap_reason_id` criada no banco de dados
✅ Modelo atualizado com foreign key
✅ Formulário corrigido para lidar com choices dinâmicas
✅ Salvamento funcional em criar e editar

## Próximas Ações

1. Testar criação de um novo benefício com seleção de motivo FAP
2. Testar edição de benefício existente - verificar se o motivo FAP é mantido
3. Verificar se o Related Object (`fap_reason_obj`) está acessível nos templates
4. Considerar exibir o motivo FAP na lista de benefícios
