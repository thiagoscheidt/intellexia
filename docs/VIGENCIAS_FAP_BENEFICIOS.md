# Vigências FAP em Benefícios - Guia de Implementação

## 📋 Visão Geral

Foi adicionado um novo campo **multi-select** em benefícios para selecionar as **vigências FAP** (anos). Este campo é preenchido automaticamente com base nos anos inicial e final FAP do caso.

## 🔧 Implementação

### 1. Novo Campo no Modelo

**Arquivo**: `app/models.py` - Classe `CaseBenefit`

```python
fap_vigencia_years = db.Column(db.String(500))  # Anos de vigência FAP (comma-separated)
```

**Tipo de Dados**: String (500 caracteres)
**Exemplo de Valor**: `"2019,2020,2021"`
**Nulo**: SIM (opcional)

### 2. Novo Campo no Formulário

**Arquivo**: `app/form.py` - Classes `CaseBenefitForm` e `CaseBenefitContextForm`

```python
fap_vigencia_years = SelectMultipleField(
    'Vigências FAP (Anos)',
    validators=[Optional()],
    choices=[]  # Populated dynamically based on case dates
)
```

### 3. Lógica de Preenchimento (Backend)

**Arquivo**: `app/blueprints/benefits.py`

#### Na criação de novo benefício:
```python
# Populate fap_vigencia_years choices based on case dates
if case.fap_start_year and case.fap_end_year:
    years = [str(year) for year in range(case.fap_start_year, case.fap_end_year + 1)]
    form.fap_vigencia_years.choices = [(year, year) for year in years]
else:
    form.fap_vigencia_years.choices = []

# Salvar como comma-separated
benefit.fap_vigencia_years = ','.join(form.fap_vigencia_years.data) if form.fap_vigencia_years.data else None
```

#### Na edição de benefício:
```python
# Pre-fill com valores existentes
if benefit.fap_vigencia_years:
    form.fap_vigencia_years.data = benefit.fap_vigencia_years.split(',')
```

## 📊 Fluxo de Dados

```
1. Usuário acessa formulário de novo benefício
   ↓
2. Sistema lê case.fap_start_year e case.fap_end_year
   ↓
3. Gera lista de anos: [2019, 2020, 2021, ...]
   ↓
4. Populaselect múltiplo com essas opções
   ↓
5. Usuário seleciona uma ou mais vigências
   ↓
6. Form valida e junta com vírgula: "2019,2020,2021"
   ↓
7. Salva no banco em case_benefits.fap_vigencia_years
```

## 💾 Migração do Banco de Dados

### Para SQLite:

Execute o script SQL:
```bash
sqlite3 instance/intellexia.db < database/add_fap_vigencia_years.sql
```

Ou via Python:
```bash
python database/add_fap_vigencia_years.py
```

### Script SQL (`add_fap_vigencia_years.sql`):
```sql
ALTER TABLE case_benefits 
ADD COLUMN fap_vigencia_years VARCHAR(500);
```

## 🎯 Casos de Uso

### Exemplo 1: Caso FAP com 3 anos
```
Case:
- fap_start_year = 2019
- fap_end_year = 2021

Benefit 1:
- fap_vigencia_years = "2019,2020,2021"

Benefit 2:
- fap_vigencia_years = "2019,2020"

Benefit 3:
- fap_vigencia_years = "2021"
```

### Exemplo 2: Caso sem FAP
```
Case:
- fap_start_year = NULL
- fap_end_year = NULL

Benefit:
- fap_vigencia_years = NULL
```

## 📝 Campos do Formulário

No template de edição de benefícios, o campo aparece assim:

```html
<div class="form-group">
    <label for="fap_vigencia_years">Vigências FAP (Anos)</label>
    <select id="fap_vigencia_years" name="fap_vigencia_years" multiple>
        <option value="2019">2019</option>
        <option value="2020">2020</option>
        <option value="2021">2021</option>
    </select>
</div>
```

## 🚀 Como Usar

### Criar novo benefício com vigências:

1. Acesse a página do caso
2. Clique em "Novo Benefício"
3. Preencha os campos normais
4. Em "Vigências FAP (Anos)", selecione os anos desejados
5. Clique em "Salvar Benefício"

### Editar vigências de benefício existente:

1. Acesse a página do benefício
2. Clique em "Editar"
3. As vigências selecionadas aparecem marcadas
4. Adicione ou remova anos conforme necessário
5. Clique em "Salvar Benefício"

## 🔍 Verificação

Após a migração, verifique se o campo foi criado:

```sql
-- SQLite
PRAGMA table_info(case_benefits);

-- Deve mostrar:
-- ...
-- | 18 | fap_vigencia_years | text | 0 | NULL | 0 |
-- ...
```

## 📦 Recuperando os dados

Para acessar as vigências em templates ou código:

```python
# No Python
benefit = CaseBenefit.query.get(benefit_id)
vigencias = benefit.fap_vigencia_years.split(',') if benefit.fap_vigencia_years else []
# vigencias = ['2019', '2020', '2021']
```

```jinja2
<!-- Em templates Jinja2 -->
{% if benefit.fap_vigencia_years %}
    <p>Vigências FAP: {{ benefit.fap_vigencia_years.replace(',', ', ') }}</p>
{% endif %}
```

## 🔄 Atualizações Futuras

Possíveis melhorias:
- Adicionar filtro por vigência na lista de benefícios
- Validar se a vigência está dentro do range do caso
- Adicionar coluna "Vigências" na tabela de benefícios
- Criar relatório de benefícios por vigência

## ⚠️ Notas Importantes

1. **Valores automáticos**: O range de anos é gerado automaticamente do caso
2. **Múltipla seleção**: O usuário pode selecionar vários anos ao mesmo tempo
3. **Armazenamento**: Os anos são salvos como string separada por vírgula
4. **Compatibilidade**: Funciona com o sistema existente sem quebrar dados anteriores
5. **Opcional**: O campo é opcional - benefícios sem vigências terão NULL

