# Importador Automático FAP

Documentação do módulo de importação automática de contestações e recursos do portal **FAP/Dataprev**, disponível em **Disputes Center → Importação Automática FAP**.

---

## Visão Geral

O importador permite que o escritório busque e importe diretamente os relatórios de julgamento de contestações FAP do portal `fap-mps.dataprev.gov.br`, sem precisar acessar o portal manualmente para cada empresa/vigência.

O fluxo completo é:

```
Usuário extrai credenciais do browser
  → Salva no IntellexIA (sessão Flask)
  → Sincroniza empresas com procuração
  → Busca contestações por empresa/ano
  → Importa PDFs → FapContestationJudgmentReport + KnowledgeBase
```

---

## Arquitetura

### Camadas

| Camada | Arquivo | Responsabilidade |
|---|---|---|
| Service | `app/services/fap_web_service.py` | Todas as chamadas HTTP ao FAP/Dataprev |
| Blueprint | `app/blueprints/disputes_center.py` | Rotas Flask, validação de entrada, persistência no banco |
| Template | `templates/disputes_center/fap_auto_import.html` | Interface do usuário |

### Separação de responsabilidades

O `FapWebService` **não conhece Flask, banco de dados nem sessão**. Recebe um `FapWebAuthPayload` e devolve um `FapWebResult`. O blueprint faz a ponte: lê a sessão Flask, instancia o service, persiste o resultado.

---

## FapWebService (`app/services/fap_web_service.py`)

### Tipos de dados

#### `FapWebAuthPayload`

Encapsula os dados de autenticação extraídos do browser.

```python
from app.services.fap_web_service import FapWebAuthPayload

# A partir do JSON armazenado na sessão Flask
auth = FapWebAuthPayload.from_json(session['fap_auto_import_auth'])

# A partir de um dicionário (ex: payload de uma request)
auth = FapWebAuthPayload.from_dict({
    'cookies': {'SESSION': '...', 'XSRF-TOKEN': '...'},
    'userAgent': 'Mozilla/5.0 ...',
})

# Serializar de volta para JSON (para salvar em sessão)
json_str = auth.to_json()
```

Propriedades disponíveis:

| Propriedade | Tipo | Descrição |
|---|---|---|
| `cookie_string` | `str` | Cookies no formato `KEY=VALUE; KEY=VALUE` |
| `xsrf_token` | `str` | Valor do cookie `XSRF-TOKEN` |
| `effective_user_agent` | `str` | UA fornecido ou o padrão (Chrome 147) |

#### `FapWebResult`

Retorno padronizado de todos os métodos do service.

```python
result.ok          # bool — True se a chamada foi bem-sucedida
result.data        # Any — payload de retorno (lista, dict, etc.)
result.message     # str — mensagem de erro legível
result.status_code # int | None — código HTTP da resposta
result.expired     # bool — True quando a sessão expirou (HTTP 401/403)
```

### Métodos

#### `check_session() → FapWebResult`

Verifica se a sessão FAP ainda está ativa fazendo um `GET /gateway/oauth2/token`.

```python
svc = FapWebService(auth)
result = svc.check_session()

if result.ok:
    print('Sessão ativa')
elif result.expired:
    print('Sessão expirada')
else:
    print(result.message)
```

#### `fetch_companies() → FapWebResult`

Lista todas as empresas com procuração cadastradas para o usuário autenticado.

```python
result = svc.fetch_companies()
if result.ok:
    companies = result.data  # list[dict]
    # cada item: {'cnpj': '...', 'nome': '...', 'tipoProcuracao': {...}}
```

#### `fetch_contestacoes(cnpj, year) → FapWebResult`

Busca as contestações de primeira e segunda instância de uma empresa em um ano de vigência.

```python
result = svc.fetch_contestacoes(cnpj='12345678', year=2023)
if result.ok:
    items = result.data  # list[dict]
    # cada item contém: id, cnpj, anoVigencia, instancia, situacao,
    #                   protocolo, dataTransmissao, ...
```

- `cnpj` pode ser o CNPJ raiz (8 dígitos) ou completo (14 dígitos).
- Em caso de sessão expirada: `result.expired = True`.

#### `download_contestacao(year, cnpj, contestacao_id) → FapWebResult`

Baixa o PDF de julgamento de uma contestação específica.

```python
result = svc.download_contestacao(year=2023, cnpj='12345678000195', contestacao_id=42)
if result.ok:
    pdf_bytes = result.data['pdf_bytes']  # bytes
    filename  = result.data['filename']   # str, ex: 'relatorio_42.pdf'
```

A API FAP devolve o PDF codificado em Base64 dentro de um JSON; o service já faz o decode e retorna os bytes brutos.

---

## Rotas Flask

Todas as rotas estão em `disputes_center_bp` (prefixo `/disputes-center`) e requerem autenticação via `@require_law_firm`.

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/fap-auto-import` | Página principal do importador |
| `POST` | `/fap-auto-import/save-auth` | Salva o JSON de autenticação na sessão Flask |
| `GET` | `/fap-auto-import/check-session` | Verifica se a sessão FAP está ativa |
| `POST` | `/fap-auto-import/fetch-companies` | Sincroniza empresas do FAP no banco |
| `POST` | `/fap-auto-import/fetch-reports` | Busca contestações de uma empresa/vigência |
| `POST` | `/fap-auto-import/import-contestacao` | Importa um PDF e registra no banco |
| `GET` | `/fap-auto-import/download-contestacao/<year>/<cnpj>/<id>` | Download direto do PDF |

### `POST /fap-auto-import/save-auth`

```json
{ "auth": "{\"cookies\":{\"SESSION\":\"...\",\"XSRF-TOKEN\":\"...\"},\"userAgent\":\"...\"}" }
```

Salva o valor em `session['fap_auto_import_auth']`. Para apagar a sessão, envie `auth` vazio.

### `GET /fap-auto-import/check-session`

Resposta de sucesso:
```json
{ "ok": true, "status": 200 }
```

Resposta de expiração:
```json
{ "ok": false, "expired": true, "status": 401 }
```

### `POST /fap-auto-import/fetch-companies`

Body:
```json
{
  "cookies": { "SESSION": "...", "XSRF-TOKEN": "..." },
  "userAgent": "Mozilla/5.0 ..."
}
```

Faz upsert das empresas na tabela `fap_companies` (modelo `FapCompany`) e remove as que não foram mais retornadas pela API.

Resposta:
```json
{ "ok": true, "saved_count": 15, "companies": [...] }
```

### `POST /fap-auto-import/fetch-reports`

Body:
```json
{ "cnpj": "12345678", "year": "2023" }
```

Além dos campos originais da API FAP, cada item recebe a anotação `_imported_report_id` (ID do relatório no banco, ou `null` se ainda não foi importado).

### `POST /fap-auto-import/import-contestacao`

Body:
```json
{ "year": "2023", "cnpj": "12345678000195", "contestacao_id": 42 }
```

Fluxo interno:
1. Verifica duplicata em `FapAutoImportedContestacao`
2. Chama `FapWebService.download_contestacao()`
3. Salva o PDF em `uploads/fap_contestation_reports/`
4. Cria registro `FapContestationJudgmentReport` (status `pending` → processado pelo pipeline de IA)
5. Adiciona à `KnowledgeBase` se não houver duplicata por hash SHA-256
6. Registra em `FapAutoImportedContestacao` para evitar reimportações

---

## Modelos de Banco Relacionados

| Modelo | Tabela | Descrição |
|---|---|---|
| `FapCompany` | `fap_companies` | Empresas sincronizadas do portal FAP |
| `FapAutoImportedContestacao` | `fap_auto_imported_contestacoes` | Registro de cada contestação importada (evita duplicatas) |
| `FapContestationJudgmentReport` | `fap_contestation_judgment_reports` | Relatório de julgamento importado (PDF) |
| `KnowledgeBase` | `knowledge_base` | Arquivo indexado para busca RAG |

---

## Interface do Usuário

A página `/fap-auto-import` é dividida em etapas visuais:

**Etapa 1 — Autenticação**
O usuário abre o portal FAP no browser, extrai os cookies e o User-Agent (via extensão ou DevTools) e cola o JSON no campo de autenticação. O sistema salva na sessão Flask e verifica periodicamente se a sessão ainda está ativa (verificação a cada 1–5 minutos, com verificação imediata ao carregar a página).

O alerta de conexão no topo da página muda de cor:
- Cinza + spinner → verificando
- Verde → sessão ativa
- Vermelho → sessão expirada

**Etapa 2 — Sincronização de Empresas**
Busca a lista de empresas com procuração cadastrada no FAP e salva no banco. Necessário apenas uma vez ou quando novas empresas forem adicionadas.

**Etapa 3 — Busca de Relatórios**
Seleciona a empresa (campo com busca via Select2) e o ano de vigência. Após a busca, uma barra de estatísticas exibe quantas contestações já foram importadas e quantas estão pendentes.

**Importação**
Cada contestação pode ser importada individualmente ou em lote pelo botão "Importar Contestações e Recursos". O log em tempo real mostra o progresso.

---

## Como Reutilizar o `FapWebService` em Outros Fluxos

```python
from flask import session
from app.services.fap_web_service import FapWebAuthPayload, FapWebService

def meu_fluxo():
    saved_auth = session.get('fap_auto_import_auth', '')
    auth = FapWebAuthPayload.from_json(saved_auth)
    svc  = FapWebService(auth)

    # Verificar sessão
    if not svc.check_session().ok:
        raise Exception('Sessão FAP expirada')

    # Buscar contestações
    result = svc.fetch_contestacoes(cnpj='12345678', year=2024)
    if result.ok:
        for item in result.data:
            processar(item)

    # Baixar PDF
    dl = svc.download_contestacao(year=2024, cnpj='12345678000195', contestacao_id=99)
    if dl.ok:
        salvar_pdf(dl.data['pdf_bytes'], dl.data['filename'])
```

O service pode ser instanciado fora do contexto de uma request Flask — basta fornecer um `FapWebAuthPayload` válido.

---

## Configuração SSL

O portal FAP/Dataprev usa um certificado SSL que exige configuração especial (SECLEVEL reduzido e `OP_LEGACY_SERVER_CONNECT`). Isso é tratado internamente pelo `FapWebService._build_ssl_ctx()` e não requer nenhuma configuração adicional.
