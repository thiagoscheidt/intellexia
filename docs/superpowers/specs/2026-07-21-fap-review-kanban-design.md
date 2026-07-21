# Visualização Kanban no Revisor de Petições FAP

**Data:** 2026-07-21
**Módulo:** `fap_review` — tela inicial (`/fap-review/`, `templates/fap_review/index.html`)

## Objetivo

Adicionar uma visualização em formato kanban à lista de petições do Revisor FAP, organizada pelas colunas do `workflow_status`, com drag-and-drop para mudar o status. A visão em lista atual permanece; o usuário alterna entre as duas.

## Contexto

- O `workflow_status` da petição (`FapReviewPetition`) já é um pipeline com 6 estágios: `new` → `in_review` → `awaiting_adjustments` → `ready_for_filing` → `filed` → `archived` (rótulos em `PETITION_WORKFLOW_STATUSES`, `app/services/fap_review_service.py`).
- Já existe endpoint de mudança manual de status com auditoria: `POST /fap-review/petitions/<id>/status` (payload `{"workflow_status": "..."}`), em `app/blueprints/fap_review.py` (`petition_update_status`). O kanban **reusa esse endpoint** — nenhuma rota nova.
- A rota `/fap-review/` já envia todas as petições ao template; cada card carrega `data-status`. Não há query nova nem endpoint de leitura novo.

## Abordagem escolhida

Kanban client-side na mesma página (`index.html`), montado a partir dos mesmos dados renderizados, com drag-and-drop HTML5 nativo — **sem biblioteca nova**, conforme convenção do projeto. Alternativas descartadas: SortableJS (dependência nova para ganho pequeno; reordenação intra-coluna não teria persistência — não existe campo de posição no modelo) e rota separada `/fap-review/kanban` (duplicaria busca, filtros e carregamento).

## Design

### Toggle e estrutura

- Par de botões de alternância na barra de busca/filtros: **Lista** (`bi-list-ul`) e **Kanban** (`bi-kanban`). Preferência persistida em `localStorage` (por navegador).
- A visão lista permanece intocada. O kanban é um contêiner irmão (`display:none` quando inativo).
- Busca por texto funciona nas duas visões. As pílulas de filtro por status ficam **ocultas no modo kanban** (as colunas cumprem esse papel).

### Colunas e cards

- 5 colunas do fluxo ativo, na ordem do pipeline: **Nova → Em revisão → Aguardando ajustes → Aprovada pelo revisor → Processo iniciado**. Cada coluna tem cabeçalho com rótulo, contador e cor coerente com as pílulas de filtro atuais.
- **Arquivada** é uma coluna recolhida (só cabeçalho + contador) no fim; clique expande/recolhe. Mesmo recolhida, aceita drop no cabeçalho (soltar = arquivar).
- Card kanban = versão compacta do card da lista: título, identificador, advogado, nº da última revisão/achados, data. Clique no card abre o detalhe da petição; ações "Nova Revisão" e "Última Revisão" viram botões-ícone pequenos no rodapé do card.
- Ordenação dentro da coluna: a mesma da lista (prioridade/data, definida no backend). Sem persistência de ordem manual intra-coluna.
- Cada coluna tem rolagem vertical própria; o quadro tem rolagem horizontal em telas estreitas (mobile).

### Drag-and-drop e tratamento de erros

- HTML5 nativo (`draggable`, `dragover`, `drop`), com realce visual da coluna alvo durante o arraste.
- Soltar em outra coluna → `POST /fap-review/petitions/<id>/status` com o novo status. Atualização **otimista**: o card muda de coluna imediatamente; contadores de coluna (e das pílulas da lista) são atualizados.
- Se a API falhar (rede ou resposta de erro), o card **volta à coluna original** e uma mensagem de erro clara é exibida ao usuário.
- **Todas as transições são permitidas**, em paridade com o editor manual de status existente — nenhuma regra nova de workflow.
- A visão lista compartilha o mesmo DOM de dados (`data-status` atualizado), então alternar de visão após um drag mostra o estado correto sem recarregar.

### Escopo de arquivos

- `templates/fap_review/index.html` — toggle, contêiner kanban, JS (nativo, no padrão da página).
- CSS local da página (bloco de estilo existente no template) — estilos de colunas/cards kanban, sem colidir com estilos globais.
- **Nenhuma mudança** em modelos, migrations, serviços ou rotas.

### Testes

Sem framework de testes no projeto (scripts standalone). Verificação manual: alternância lista/kanban com persistência, busca nas duas visões, drag entre todas as colunas (incluindo Arquivada recolhida), falha de API simulada (card retorna + mensagem), auditoria registrada no log de auditoria existente, responsividade mobile.

## Fora de escopo

- Campo de posição/ordem manual dentro da coluna.
- Regras de restrição de transição de status.
- Kanban em outras telas do módulo.
