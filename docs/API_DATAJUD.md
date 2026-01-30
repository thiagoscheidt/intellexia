# API DataJud - Documentação

## Índice
- [Visão Geral](#visão-geral)
- [Configuração](#configuração)
- [Autenticação](#autenticação)
- [Tribunais Disponíveis](#tribunais-disponíveis)
- [Métodos Disponíveis](#métodos-disponíveis)
- [Estrutura de Dados](#estrutura-de-dados)
- [Exemplos de Uso](#exemplos-de-uso)
- [Tratamento de Erros](#tratamento-de-erros)

---

## Visão Geral

A API Pública do DataJud é mantida pelo Conselho Nacional de Justiça (CNJ) e fornece acesso aos metadados processuais de todos os tribunais brasileiros. A API utiliza Elasticsearch e segue o padrão Query DSL para buscas.

### Características
- 🔍 Busca em tempo real em todos os tribunais
- 📊 Dados estruturados e padronizados (TPU - Tabelas Processuais Unificadas)
- 🔒 Autenticação via APIKey
- 📄 Suporte a paginação para grandes volumes
- 🎯 Consultas complexas com filtros múltiplos

### Base URL
```
https://api-publica.datajud.cnj.jus.br
```

### Documentação Oficial
https://datajud-wiki.cnj.jus.br/api-publica/

---

## Configuração

### Variáveis de Ambiente

Adicione as seguintes variáveis no arquivo `.env`:

```env
DATA_JUD_API_URL=https://api-publica.datajud.cnj.jus.br
DATA_JUD_API_KEY=sua_chave_publica_aqui
```

### Obter Chave de API

A chave pública está disponível em:
https://datajud-wiki.cnj.jus.br/api-publica/acesso

---

## Autenticação

A API utiliza autenticação via **APIKey** no header das requisições:

```http
Authorization: APIKey cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==
Content-Type: application/json
```

O cliente Python já configura automaticamente os headers necessários.

---

## Tribunais Disponíveis

### Tribunais Superiores
- **STF** - Supremo Tribunal Federal
- **STJ** - Superior Tribunal de Justiça
- **TST** - Tribunal Superior do Trabalho
- **TSE** - Tribunal Superior Eleitoral
- **STM** - Superior Tribunal Militar

### Tribunais Regionais Federais
- **TRF1** - 1ª Região (DF, GO, TO, MT, BA, PI, MA, PA, AM, AC, RR, RO, AP)
- **TRF2** - 2ª Região (RJ, ES)
- **TRF3** - 3ª Região (SP, MS)
- **TRF4** - 4ª Região (RS, SC, PR)
- **TRF5** - 5ª Região (PE, AL, SE, RN, PB, CE)
- **TRF6** - 6ª Região (MG)

### Tribunais de Justiça Estaduais
Todos os 27 TJs estão disponíveis (TJSP, TJRJ, TJMG, TJRS, TJPR, etc.)

---

## Métodos Disponíveis

### 1. `buscar_por_numero_processo()`

Busca processos pelo número único (CNJ).

**Parâmetros:**
- `numero_processo` (str): Número do processo (com ou sem formatação)
- `tribunal` (str): Sigla do tribunal (ex: "TRF1", "TJSP")
- `size` (int, opcional): Quantidade de resultados (padrão: 10)

**Exemplo:**
```python
api = DataJudAPI()
resultado = api.buscar_por_numero_processo(
    numero_processo="0000832-35.2018.4.01.3202",
    tribunal="TRF1"
)
```

**Retorno:**
```json
{
  "took": 6679,
  "hits": {
    "total": {"value": 1},
    "hits": [
      {
        "_source": {
          "numeroProcesso": "00008323520184013202",
          "classe": {"codigo": 436, "nome": "Procedimento do Juizado Especial Cível"},
          "tribunal": "TRF1",
          ...
        }
      }
    ]
  }
}
```

---

### 2. `buscar_por_classe_e_orgao()`

Busca processos por classe processual e órgão julgador.

**Parâmetros:**
- `codigo_classe` (int): Código da classe processual (TPU)
- `codigo_orgao` (int): Código do órgão julgador
- `tribunal` (str): Sigla do tribunal
- `size` (int, opcional): Quantidade de resultados

**Exemplo:**
```python
# Buscar procedimentos do juizado especial (código 436) no órgão 16403
resultado = api.buscar_por_classe_e_orgao(
    codigo_classe=436,
    codigo_orgao=16403,
    tribunal="TRF1",
    size=50
)
```

**Casos de Uso:**
- Estatísticas de processos por vara/comarca
- Análise de carga de trabalho por órgão
- Relatórios por tipo de processo

---

### 3. `buscar_com_paginacao()`

Busca com paginação eficiente usando `search_after` (recomendado para grandes volumes).

**Parâmetros:**
- `query` (dict): Query DSL do Elasticsearch
- `tribunal` (str): Sigla do tribunal
- `size` (int, opcional): Tamanho da página (máx. 100)
- `search_after` (list, opcional): Valores de ordenação da última página

**Exemplo:**
```python
# Primeira página
query = {
    "query": {"match_all": {}},
    "sort": [{"dataAjuizamento": "desc"}]
}

resultado1 = api.buscar_com_paginacao(query, "TRF1", size=100)

# Próxima página
if resultado1['hits']['hits']:
    sort_values = resultado1['hits']['hits'][-1]['sort']
    resultado2 = api.buscar_com_paginacao(
        query, "TRF1", size=100, search_after=sort_values
    )
```

**Vantagens sobre `from/size`:**
- ✅ Performance constante mesmo com milhões de registros
- ✅ Não há limite de páginas
- ✅ Ideal para exportação de dados em massa

---

### 4. `buscar_por_assunto()`

Busca processos por código de assunto (TPU).

**Parâmetros:**
- `codigo_assunto` (int): Código do assunto processual
- `tribunal` (str): Sigla do tribunal
- `size` (int, opcional): Quantidade de resultados

**Exemplo:**
```python
# Buscar processos com assunto "Concessão" (código 6177)
resultado = api.buscar_por_assunto(
    codigo_assunto=6177,
    tribunal="TRF1",
    size=20
)
```

**Assuntos Comuns:**
- 6177 - Concessão de benefícios
- 7716 - Auxílio-doença previdenciário
- 11956 - Aposentadoria por invalidez previdenciária

---

### 5. `buscar_movimentos_por_codigo()`

Busca processos que possuem determinado movimento processual.

**Parâmetros:**
- `codigo_movimento` (int): Código do movimento (TPU)
- `tribunal` (str): Sigla do tribunal
- `data_inicio` (str, opcional): Data inicial (YYYY-MM-DD)
- `data_fim` (str, opcional): Data final (YYYY-MM-DD)
- `size` (int, opcional): Quantidade de resultados

**Exemplo:**
```python
# Buscar processos com sentença publicada (código 123) em 2023
resultado = api.buscar_movimentos_por_codigo(
    codigo_movimento=123,
    tribunal="TRF1",
    data_inicio="2023-01-01",
    data_fim="2023-12-31",
    size=100
)
```

**Movimentos Comuns:**
- 26 - Distribuição
- 123 - Sentença publicada
- 246 - Recurso interposto
- 14732 - Conversão para eletrônico

---

### 6. Métodos Helper

#### `extrair_processos(response)`
Extrai lista limpa de processos da resposta da API.

```python
resultado = api.buscar_por_numero_processo("12345", "TRF1")
processos = api.extrair_processos(resultado)
# Retorna: [processo1_dict, processo2_dict, ...]
```

#### `obter_total_resultados(response)`
Obtém total de resultados encontrados.

```python
total = api.obter_total_resultados(resultado)
print(f"Encontrados: {total} processos")
```

---

## Estrutura de Dados

### Campos Principais do Processo

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | string | Identificador único (Tribunal_Classe_Grau_Orgao_Numero) |
| `numeroProcesso` | string | Número CNJ sem formatação (20 dígitos) |
| `tribunal` | string | Sigla do tribunal (TRF1, TJSP, etc.) |
| `grau` | string | Instância (G1, G2, JE, etc.) |
| `dataAjuizamento` | datetime | Data de ajuizamento |
| `nivelSigilo` | integer | Nível de sigilo (0=público) |

### Classe Processual

```json
{
  "classe": {
    "codigo": 436,
    "nome": "Procedimento do Juizado Especial Cível"
  }
}
```

### Órgão Julgador

```json
{
  "orgaoJulgador": {
    "codigo": 16403,
    "nome": "JEF Adj - Tefé",
    "codigoMunicipioIBGE": 5128
  }
}
```

### Sistema e Formato

```json
{
  "sistema": {
    "codigo": 1,
    "nome": "PJe"
  },
  "formato": {
    "codigo": 1,
    "nome": "Eletrônico"
  }
}
```

### Assuntos (Array)

```json
{
  "assuntos": [
    {
      "codigo": 6177,
      "nome": "Concessão"
    },
    {
      "codigo": 7716,
      "nome": "Auxílio-doença previdenciário"
    }
  ]
}
```

### Movimentos (Array)

```json
{
  "movimentos": [
    {
      "codigo": 26,
      "nome": "Distribuição",
      "dataHora": "2018-10-30T14:06:24.000Z",
      "complementosTabelados": [
        {
          "codigo": 2,
          "valor": 1,
          "nome": "competência exclusiva",
          "descricao": "tipo_de_distribuicao_redistribuicao"
        }
      ],
      "orgaoJulgador": {
        "codigoOrgao": 16403,
        "nomeOrgao": "JEF Adj - Tefé"
      }
    }
  ]
}
```

---

## Exemplos de Uso

### Exemplo 1: Buscar e Exibir Processo

```python
from app.services.data_jud_api import DataJudAPI

api = DataJudAPI()

# Buscar processo
resultado = api.buscar_por_numero_processo("0000832-35.2018.4.01.3202", "TRF1")

# Verificar se houve erro
if resultado.get('error'):
    print(f"Erro: {resultado['message']}")
else:
    # Extrair processos
    processos = api.extrair_processos(resultado)
    
    for processo in processos:
        print(f"Número: {processo['numeroProcesso']}")
        print(f"Classe: {processo['classe']['nome']}")
        print(f"Data: {processo['dataAjuizamento']}")
```

### Exemplo 2: Estatísticas por Classe

```python
# Buscar todos os processos de uma classe
resultado = api.buscar_por_classe_e_orgao(
    codigo_classe=436,  # Procedimento JEC
    codigo_orgao=16403,
    tribunal="TRF1",
    size=100
)

total = api.obter_total_resultados(resultado)
processos = api.extrair_processos(resultado)

print(f"Total de processos JEC neste órgão: {total}")

# Análise de assuntos mais comuns
assuntos_count = {}
for processo in processos:
    for assunto in processo.get('assuntos', []):
        nome = assunto['nome']
        assuntos_count[nome] = assuntos_count.get(nome, 0) + 1

# Top 5 assuntos
top_assuntos = sorted(assuntos_count.items(), key=lambda x: x[1], reverse=True)[:5]
print("\nTop 5 Assuntos:")
for assunto, count in top_assuntos:
    print(f"  {count:3d} - {assunto}")
```

### Exemplo 3: Exportar Processos com Paginação

```python
def exportar_processos(tribunal, classe, arquivo_saida):
    """Exporta todos os processos de uma classe"""
    api = DataJudAPI()
    
    query = {
        "query": {"match": {"classe.codigo": classe}},
        "sort": [{"_id": "asc"}]
    }
    
    todos_processos = []
    search_after = None
    pagina = 1
    
    while True:
        print(f"Buscando página {pagina}...")
        resultado = api.buscar_com_paginacao(
            query, tribunal, size=100, search_after=search_after
        )
        
        if resultado.get('error'):
            print(f"Erro: {resultado['message']}")
            break
        
        processos = api.extrair_processos(resultado)
        if not processos:
            break
        
        todos_processos.extend(processos)
        
        # Próxima página
        search_after = resultado['hits']['hits'][-1]['sort']
        pagina += 1
        
        # Limite de segurança
        if pagina > 100:  # Máx 10.000 processos
            break
    
    # Salvar em JSON
    import json
    with open(arquivo_saida, 'w', encoding='utf-8') as f:
        json.dump(todos_processos, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Exportados {len(todos_processos)} processos para {arquivo_saida}")

# Usar
exportar_processos("TRF1", 436, "processos_jec.json")
```

### Exemplo 4: Monitorar Movimentações Recentes

```python
from datetime import datetime, timedelta

# Buscar processos com sentença nos últimos 7 dias
data_inicio = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
data_fim = datetime.now().strftime('%Y-%m-%d')

resultado = api.buscar_movimentos_por_codigo(
    codigo_movimento=123,  # Sentença
    tribunal="TRF1",
    data_inicio=data_inicio,
    data_fim=data_fim,
    size=50
)

processos = api.extrair_processos(resultado)
print(f"Processos com sentença nos últimos 7 dias: {len(processos)}")

for processo in processos:
    # Encontrar a sentença
    for mov in processo.get('movimentos', []):
        if mov['codigo'] == 123:
            print(f"  • {processo['numeroProcesso']} - {mov['dataHora']}")
            break
```

---

## Tratamento de Erros

### Erros Comuns

#### 1. Tribunal Inválido
```python
try:
    api.buscar_por_numero_processo("12345", "INVALIDO")
except ValueError as e:
    print(f"Erro: {e}")
    # Erro: Tribunal 'INVALIDO' não é válido. Tribunais disponíveis: STF, STJ, ...
```

#### 2. Erro de Autenticação
```json
{
  "error": true,
  "message": "401 Client Error: Unauthorized",
  "status_code": 401
}
```

**Solução:** Verificar se a chave de API está correta.

#### 3. Timeout
```json
{
  "error": true,
  "message": "Connection timeout",
  "status_code": null
}
```

**Solução:** Aumentar o timeout ou simplificar a query.

#### 4. Rate Limit
A API pode ter limites de requisições. Implementar retry com backoff exponencial:

```python
import time
from requests.exceptions import RequestException

def buscar_com_retry(api, numero, tribunal, max_tentativas=3):
    for tentativa in range(max_tentativas):
        resultado = api.buscar_por_numero_processo(numero, tribunal)
        
        if not resultado.get('error'):
            return resultado
        
        if resultado.get('status_code') == 429:  # Rate limit
            wait_time = 2 ** tentativa  # Backoff exponencial
            print(f"Rate limit. Aguardando {wait_time}s...")
            time.sleep(wait_time)
        else:
            break
    
    return resultado
```

### Validação de Resultados

```python
def validar_resultado(resultado):
    """Valida e trata resultado da API"""
    
    # Verificar erro
    if resultado.get('error'):
        return {
            'sucesso': False,
            'erro': resultado.get('message'),
            'processos': []
        }
    
    # Verificar se encontrou resultados
    total = resultado.get('hits', {}).get('total', {}).get('value', 0)
    if total == 0:
        return {
            'sucesso': True,
            'erro': None,
            'processos': [],
            'mensagem': 'Nenhum processo encontrado'
        }
    
    # Extrair processos
    hits = resultado.get('hits', {}).get('hits', [])
    processos = [hit['_source'] for hit in hits]
    
    return {
        'sucesso': True,
        'erro': None,
        'processos': processos,
        'total': total
    }

# Usar
resultado = api.buscar_por_numero_processo("12345", "TRF1")
validado = validar_resultado(resultado)

if validado['sucesso']:
    print(f"Encontrados: {len(validado['processos'])} processos")
else:
    print(f"Erro: {validado['erro']}")
```

---

## Boas Práticas

### 1. Cache de Resultados
```python
import json
import hashlib
from pathlib import Path

def buscar_com_cache(api, numero, tribunal, cache_dir="cache"):
    """Busca com cache em arquivo"""
    Path(cache_dir).mkdir(exist_ok=True)
    
    # Gerar hash para o cache
    cache_key = hashlib.md5(f"{numero}_{tribunal}".encode()).hexdigest()
    cache_file = Path(cache_dir) / f"{cache_key}.json"
    
    # Verificar cache
    if cache_file.exists():
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    # Buscar na API
    resultado = api.buscar_por_numero_processo(numero, tribunal)
    
    # Salvar cache
    if not resultado.get('error'):
        with open(cache_file, 'w') as f:
            json.dump(resultado, f)
    
    return resultado
```

### 2. Logs Estruturados
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def buscar_com_log(api, numero, tribunal):
    logging.info(f"Buscando processo {numero} no {tribunal}")
    
    resultado = api.buscar_por_numero_processo(numero, tribunal)
    
    if resultado.get('error'):
        logging.error(f"Erro na busca: {resultado['message']}")
    else:
        total = api.obter_total_resultados(resultado)
        logging.info(f"Encontrados {total} resultados")
    
    return resultado
```

### 3. Limitar Tamanho de Resposta
```python
# Para queries muito grandes, limitar os campos retornados
query = {
    "query": {"match_all": {}},
    "_source": [
        "numeroProcesso",
        "classe.nome",
        "dataAjuizamento",
        "orgaoJulgador.nome"
    ],
    "size": 100
}
```

---

## Referências

- **Wiki Oficial:** https://datajud-wiki.cnj.jus.br/api-publica/
- **Glossário de Dados:** https://datajud-wiki.cnj.jus.br/api-publica/glossario
- **Elasticsearch Query DSL:** https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html
- **TPU - Tabelas Processuais Unificadas:** https://www.cnj.jus.br/sgt/versoes.php

---

## Suporte

Para questões sobre a API DataJud:
- 📧 Email: suporte@cnj.jus.br
- 📚 Documentação: https://datajud-wiki.cnj.jus.br

Para questões sobre a implementação Python:
- Abra uma issue no repositório do projeto
