# Correção: Erro "Not a valid choice" no Campo FAP

## Problema
Ao tentar salvar o formulário de benefício com o campo "Motivo da Contestação FAP" selecionado, aparecia o erro:
```
Not a valid choice
```

## Causa Raiz
O problema era um **mismatch de tipos de dados** na validação do SelectField:

1. As choices estavam sendo criadas com **strings**: `[(str(r.id), r.display_name) ...]`
2. O campo tinha `coerce=safe_int_coerce` que convertia o valor selecionado para **int**
3. O WTForms comparava um valor int contra uma lista de strings e não encontrava correspondência

## Solução

### 1. Remover o `coerce=safe_int_coerce` (app/form.py)
- **Antes**: `fap_reason_id = SelectField(..., coerce=safe_int_coerce, ...)`
- **Depois**: `fap_reason_id = SelectField(...)`
- Aplicado em ambas as classes: `CaseBenefitForm` e `CaseBenefitContextForm`

### 2. Usar inteiros diretos nas choices (app/blueprints/benefits.py)
- **Antes**: `[(str(r.id), r.display_name) for r in fap_reasons]`
- **Depois**: `[(r.id, r.display_name) for r in fap_reasons]`
- Aplicado em ambas as funções: `case_benefit_new()` e `case_benefit_edit()`

### 3. Remover conversão desnecessária (app/blueprints/benefits.py)
- **Antes**: `fap_reason_id=int(form.fap_reason_id.data) if form.fap_reason_id.data else None`
- **Depois**: `fap_reason_id=form.fap_reason_id.data if form.fap_reason_id.data else None`
- Os dados já são inteiros, não precisa converter

## Arquivos Modificados

1. **app/form.py**
   - Linha 184: Removido `coerce=safe_int_coerce` de `CaseBenefitForm.fap_reason_id`
   - Linha 227: Removido `coerce=safe_int_coerce` de `CaseBenefitContextForm.fap_reason_id`

2. **app/blueprints/benefits.py**
   - Linha 59: Mudado para `[(r.id, r.display_name) ...]` em `case_benefit_new()`
   - Linha 81: Mudado para `fap_reason_id=form.fap_reason_id.data` em `case_benefit_new()`
   - Linha 114: Mudado para `[(r.id, r.display_name) ...]` em `case_benefit_edit()`
   - Linha 134: Mudado para `fap_reason_id=form.fap_reason_id.data` em `case_benefit_edit()`

## Resultado
✅ Campo "Motivo da Contestação FAP" agora salva corretamente
✅ Sem erro de validação "Not a valid choice"
✅ Valor persiste corretamente na edição
