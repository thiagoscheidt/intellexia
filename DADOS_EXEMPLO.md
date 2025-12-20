# Scripts de População de Dados - Sistema Intellexia

Este diretório contém scripts para popular e gerenciar dados de exemplo no sistema de gerenciamento de casos jurídicos Intellexia.

## Scripts Disponíveis

### 1. `populate_sample_data.py`
Script principal para criar dados de exemplo no sistema.

**O que cria:**
- ✅ 4 empresas clientes (construtora, metalúrgica, transportadora, indústria têxtil)
- ✅ 5 varas judiciais (Santa Catarina, São Paulo, Paraná)
- ✅ 4 advogados com diferentes especializações
- ✅ 4 casos jurídicos (revisões FAP, auto de infração)
- ✅ Relacionamentos caso-advogado
- ✅ 6 benefícios previdenciários relacionados aos casos
- ✅ Competências mensais para casos FAP

### 2. `clear_sample_data.py`
Script para limpar dados do sistema.

**Funcionalidades:**
- Limpeza completa de todos os dados
- Limpeza de tabelas específicas
- Visualização de resumo dos dados atuais

## Como Usar

### Executar Population de Dados

```bash
# Executar o script de população
python populate_sample_data.py
```

### Gerenciar Dados Existentes

```bash
# Ver resumo dos dados atuais
python clear_sample_data.py --summary

# Limpar todos os dados (com confirmação)
python clear_sample_data.py

# Limpar todos os dados sem confirmação
python clear_sample_data.py --confirm

# Limpar apenas uma tabela específica
python clear_sample_data.py --table clients
python clear_sample_data.py --table cases
python clear_sample_data.py --table benefits
```

## Dados de Exemplo Criados

### Clientes (Empresas)
1. **Construtora Silva & Filhos Ltda** (SP) - Com filiais
2. **Metalúrgica Aço Forte S.A.** (Blumenau/SC)
3. **Transportadora Rodoviária Express Ltda** (Joinville/SC) - Com filiais
4. **Indústria Têxtil Fios de Ouro S.A.** (Itajaí/SC)

### Varas Judiciais
- 1ª Vara Federal de Blumenau/SC
- 2ª Vara Federal de Joinville/SC
- 1ª Vara Federal de Itajaí/SC
- 3ª Vara Federal de São Paulo/SP
- 1ª Vara Federal de Curitiba/PR

### Advogados
- Dr. João Silva Santos (SP 123456) - Responsável por publicações
- Dra. Maria Fernanda Costa (SC 78901)
- Dr. Carlos Eduardo Oliveira (SC 45123)
- Dra. Ana Paula Rodrigues (SP 67890)

### Casos Jurídicos
1. **Revisão FAP - Acidente de Trabalho 2019-2021**
   - Tipo: fap_trajeto
   - Status: ativo
   - Valor: R$ 250.000,00
   - 2 benefícios relacionados

2. **Revisão FAP - Nexo Causal Contestado 2020-2022**
   - Tipo: fap_nexo
   - Status: ativo
   - Valor: R$ 180.000,00
   - 1 benefício relacionado

3. **Anulação de Auto de Infração - NR12**
   - Tipo: auto_infracao
   - Status: draft
   - Valor: R$ 75.000,00

4. **Revisão FAP - Múltiplos Benefícios 2018-2020**
   - Tipo: fap_multiplos
   - Status: ativo
   - Valor: R$ 420.000,00
   - 3 benefícios relacionados

### Benefícios Previdenciários
Inclui benefícios dos tipos B91, B94 e B31 com:
- Números de benefício únicos
- Dados dos segurados (nome, NIT)
- Datas de acidentes
- Razões de contestação
- Observações detalhadas

## Estrutura do Banco

O sistema utiliza SQLAlchemy com os seguintes modelos:

- **Client**: Empresas autoras dos casos
- **Court**: Varas judiciais
- **Lawyer**: Advogados
- **Case**: Casos jurídicos
- **CaseLawyer**: Relacionamento caso-advogado
- **CaseBenefit**: Benefícios previdenciários
- **CaseCompetence**: Competências mensais (FAP)
- **Document**: Documentos dos casos

## Configuração

Os scripts utilizam:
- Flask + SQLAlchemy
- SQLite para desenvolvimento
- MySQL para produção
- Python 3.14+

## Logs e Feedback

Os scripts fornecem feedback detalhado durante a execução:
- ✅ Itens criados com sucesso
- → Itens que já existiam
- ❌ Erros encontrados
- 📊 Resumos finais

## Segurança

- Scripts verificam dados existentes antes de criar
- Rollback automático em caso de erro
- Confirmação para operações de limpeza
- Respeito às constraints de foreign key