# Manual do Usuário — Revisor de Petições

> Documentação funcional do módulo **Revisor de Petições**. Explica cada tela, o ciclo de revisão, o significado de cada ponto de atenção e **de onde vêm os dados**, em linguagem de negócio.

---

## O que é o Revisor de Petições

O **Revisor de Petições** usa IA para revisar petições FAP **antes do protocolo**, comparando o documento com o **manual de revisão do escritório** (a "régua" oficial). Ele:

1. **Lê** a petição enviada (PDF, DOCX ou TXT);
2. **Aponta** os pontos de atenção, cada um com gravidade, localização no texto e **sugestão de correção**;
3. **Confere** documentos obrigatórios que faltam e as teses identificadas;
4. **Acompanha** a petição por um ciclo de status até ela ser aprovada para protocolo.

> [!IA] **De onde vêm os apontamentos deste módulo:** de uma **IA revisora** que lê a petição e a confronta com o **manual de revisão do escritório** e os **casos de referência** cadastrados nas Configurações. A IA roda em modo **determinístico** (temperatura zero): a mesma petição tende a gerar a mesma revisão. Em caso de dúvida, **o manual do escritório sempre prevalece** — a IA não inventa critérios fora dele.

Todos os dados são do **seu escritório** — você nunca vê petições de outro.

---

## O ciclo de vida de uma petição (status)

Cada petição tem um **status de acompanhamento**, visível no painel inicial:

| Status | Significado |
|---|---|
| **Nova** | Cadastrada, ainda sem revisão. |
| **Em revisão** | Há uma revisão em andamento. |
| **Aguardando ajustes** | A revisão terminou e apontou itens — a bola está com o advogado. |
| **Aprovada pelo revisor** | Alguém clicou em **"Aprovar petição"**: pronta para protocolo. |
| **Processo iniciado** | A petição já foi protocolada (marcação manual). |
| **Arquivada** | Fora do fluxo (marcação manual). |

Como o status evolui:

- **Automaticamente**: ao enviar uma revisão a petição vira **Em revisão**; quando a revisão conclui (ou falha), vira **Aguardando ajustes**.
- **Manualmente**: sair de "Aguardando ajustes" para **Aprovada pelo revisor** é sempre uma **decisão humana** (botão "Aprovar petição" na tela de resultado, ou troca de status no detalhe da petição). "Processo iniciado" e "Arquivada" também são manuais — e, uma vez nesses dois status, novas revisões **não rebaixam** a petição de volta.

> [!INFO] **O Id Wrike é a chave de tudo.** Cada petição tem um **identificador do documento** (o "Id Wrike", até 96 caracteres). É ele que liga as revisões sucessivas à mesma petição — inclusive as feitas pelo Claude via MCP — e que carrega o histórico de pontos descartados. Use sempre o mesmo identificador para o mesmo documento.

---

## Tela 1 — Início (painel de acompanhamento)

Visão geral das petições do escritório.

### Cartões de estatística

**Total de petições**, **Em revisão** (novas + em revisão — requerem atenção agora), **Aguardando ajustes**, **Aprovadas pelo revisor** e **Revisões executadas**.

### Tabela "Petições em Acompanhamento"

Mostra as 20 petições mais prioritárias (aguardando ajustes primeiro, depois em revisão, depois aprovadas), com busca em tempo real e filtros por status.

| Coluna | O que mostra | De onde vem |
|---|---|---|
| **Petição** | Título da petição. | Sistema |
| **Id Wrike** | Identificador do documento no escritório. | Sistema |
| **Status** | Badge colorido com o status do ciclo (tabela acima). | Sistema |
| **Última Revisão** | Data da última revisão e o usuário responsável. | Sistema |
| **Ações** | Botões "Última Revisão", "Abrir Petição" (histórico completo) e "Nova Revisão". | — |

### Visão kanban

Além da lista, a tela oferece uma **visão kanban**: use o seletor **Lista / Kanban** na barra de filtros. Cada coluna corresponde a um status da petição (Nova, Em revisão, Aguardando ajustes, Aprovada pelo revisor, Processo iniciado), e a coluna **Arquivada** fica recolhida à direita — clique no cabeçalho para expandi-la.

- **Arraste um card** para outra coluna para mudar o status da petição — o efeito é o mesmo da troca manual de status na tela da petição, inclusive no registro de auditoria.
- A **busca** filtra os cards normalmente; a preferência de visão fica salva no navegador.
- Se a mudança de status falhar (por exemplo, sem conexão), o card volta para a coluna original e um aviso é exibido.

---

## Tela 2 — Revisar Petição (envio)

Formulário em três passos:

1. **Selecionar ou criar petição** — escolha uma petição existente **ou** crie uma nova informando **Título** e **Id Wrike**.
2. **Enviar documento principal** — a petição a revisar. Formatos aceitos: **PDF, DOCX e TXT**. Arquivos **.doc não são aceitos** (converta para PDF ou DOCX). Limite de 50 MB por envio.
3. **Complementos (opcionais)**:
   - **Documentos auxiliares** — anexos de apoio (PDF, DOC/DOCX, XLS/XLSX, TXT e imagens).
   - **Planilha de benefícios (.xlsx)** — ativa a conferência "Benefícios da Planilha x Documento" (ver adiante).
   - **Segunda versão do documento** — ativa a **Análise Comparativa** (original × revisado).

Ao enviar, a revisão é processada e você é levado à tela de resultado.

### Revisão focada (a partir da 2ª revisão)

Quando o mesmo documento já foi revisado antes, a IA entra em **modo focado**: em vez de refazer a varredura geral do manual, ela verifica apenas se os **pontos apontados anteriormente foram corrigidos** — mais rápido e mais barato. Uma checagem, porém, roda **sempre**, em qualquer modo:

> [!ALERTA] **Nome da empresa — verificação obrigatória.** Em toda revisão a IA confere se a **razão social da autora** está grafada de forma **idêntica** em todo o documento (qualificação, corpo, tabelas, pedidos), incluindo a forma societária ("S.A." vs "S/A" vs "SA"). Qualquer divergência — mesmo de uma letra, como "WHIRLPOOL" vs "WHIRPOOL" — vira um ponto **CRÍTICO** com a localização exata.

---

## Tela 3 — Resultado da Revisão

Enquanto processa, a tela mostra "A revisão está sendo processada" e se atualiza sozinha. Concluída, ela apresenta:

### Teses Identificadas

As teses jurídicas que a IA reconheceu na petição, com o número do benefício relacionado e o enquadramento.

### Pontos de Atenção Identificados

O coração da revisão. Cada ponto traz:

| Campo | O que significa |
|---|---|
| **Gravidade** | **CRÍTICO** (compromete a petição), **MODERADO** (deve ser corrigido) ou **FORMAL** (padronização/estilo). Os contadores por gravidade aparecem no topo. |
| **Categoria** | Tipo do erro (ex.: "Categoria 3"), conforme o manual do escritório. |
| **Descrição** | O problema encontrado, explicado. |
| **Localização** | Onde está no documento. |
| **Sugestão de Correção** | Como a IA sugere corrigir. |
| **Referência do Manual** | A seção do manual do escritório que fundamenta o apontamento. |
| **Padrão Novo** | Sinaliza quando o caso não está previsto no manual (candidato a Treinamento). |

### Marcar um ponto como "não pertinente"

Discorda de um apontamento? Marque-o como **não pertinente**. O sistema memoriza esse descarte **para aquele documento** (pelo Id Wrike): nas próximas revisões, o mesmo ponto **não será cobrado de novo**. O descarte é reversível (botão de desfazer) e fica registrado na auditoria.

### Documentos Obrigatórios em Falta

Lista os documentos que, segundo o manual, deveriam acompanhar as teses da petição e não foram localizados — com a tese relacionada e a referência do manual.

### Resumo Executivo

Totais por gravidade, **Principais Riscos Jurídicos** e **Prioridade de Correção** (ALTA / MÉDIA / BAIXA).

### Alterações Identificadas (só na Análise Comparativa)

Quando você envia a segunda versão, a IA compara original × revisado e lista cada alteração: trecho original, trecho corrigido, o motivo da correção e se o padrão **já existe no manual** ou é novo.

### Benefícios da Planilha x Documento (só com a planilha .xlsx)

Conferência **automática, sem IA**: o sistema lê as colunas **"Número do Benefício"** e **"TESES"** da planilha e verifica se cada benefício **é citado no texto** da petição (tolerante a pontuação: "123.456.789-0", com espaços etc.). Resultado por linha: **Citado / Não citado**, com totais.

| Detalhe | Origem |
|---|---|
| Pontos de atenção, teses, documentos em falta, resumo executivo | IA |
| Conferência da planilha de benefícios | Cálculo |
| Status, histórico, custo e tokens da revisão | Sistema |

> Só entram na conferência da planilha as linhas com a coluna **TESES** preenchida.

### Ações da tela

**Aprovar petição** (marca "Aprovada pelo revisor"), **Nova Revisão**, **Visualizar Documento** enviado, **Visualizar Manual** de referência e **Copiar JSON** (dados brutos). A tela também mostra o modelo de IA usado, tokens e **custo estimado** da revisão.

---

## Tela 4 — Detalhe da Petição

Histórico completo de uma petição: todas as revisões (número, data, status, documento e responsável) e um resumo (concluídas, em processamento, com falha, comparativas). Aqui você pode **editar o título e o Id Wrike** (o histórico de descartes acompanha a mudança) e **trocar o status** manualmente — inclusive marcar "Processo iniciado" ou "Arquivada".

---

## Tela 5 — Estatísticas dos Advogados (apenas administradores)

Painel de aprendizado da equipe. Para cada advogado: **pontuação (0–100)**, revisões e petições, **retrabalho** (petições que precisaram de mais de uma revisão), achados por gravidade, **reincidência** (o mesmo erro reaparecendo em revisões seguintes), tipos de erro mais frequentes e evolução mensal (últimos 6 meses).

> [!INFO] **Como a pontuação é calculada:** começa em 100 e desconta três sinais — a **média de achados por revisão**, a **taxa de retrabalho** e a **taxa de reincidência**. É uma medida **heurística, para orientar a melhoria da equipe — não para ranquear pessoas**.

---

## Configurações (apenas administradores)

Tudo aqui é **por escritório** e **versionado**: editar cria uma nova versão inativa, que só passa a valer quando você clica em **Ativar** (a versão anterior fica no histórico).

- **Agente Revisor** — modelo de IA e temperatura (padrão 0.0 — determinístico) usados nas revisões; pode ser desativado.
- **Agente de Treinamento** — modelo e temperatura (padrão 0.7) do fluxo de Treinamento.
- **Políticas de Atualização** — se o Treinamento pode atualizar o manual e os casos automaticamente, e se exige aprovação antes de publicar.
- **Prompts** — a "personalidade" do revisor: **Identidade**, **Regras invioláveis** e os textos do Treinamento. O **Formato de saída** é protegido (somente leitura), para as telas não quebrarem.
- **Referências** — o **Manual de revisão do FAP** (a régua das revisões), os **Casos de referência** e as **Instruções do projeto** (somente leitura).

---

## Treinamento (apenas administradores)

É como o revisor **aprende com as correções reais** do escritório, sempre em dois passos com confirmação humana:

1. **Gerar Extrato** — você envia o documento base e o revisado; a IA produz um extrato com as principais alterações e os padrões identificados.
2. **Aplicar** — após sua revisão do extrato, o sistema grava novas versões do manual e/ou dos casos de referência, **respeitando as políticas** das Configurações. Nada é publicado sem confirmação.

---

## Auditoria (apenas administradores)

Trilha completa do módulo: quem criou/alterou petições, iniciou e concluiu revisões, descartou pontos, editou/ativou prompts e referências, mudou configurações e aplicou treinamentos — com data, usuário e descrição, incluindo ações feitas **via MCP**.

---

## :claude: Usando o Revisor pelo Claude (MCP)

Com a IA conectada (veja o manual **"Conectar sua IA"**), o Claude usa **o mesmo agente revisor e o mesmo manual** do escritório:

- **Revisar** uma petição a partir do texto ou **comparar duas versões**;
- **Consultar** petições, revisões anteriores (sem refazer), o histórico de evolução (novos × reincidentes × resolvidos) e o próprio manual de revisão;
- **Registrar** a revisão no módulo: informando o **Id Wrike**, a revisão feita pelo Claude entra no histórico oficial da petição — mesma numeração, mesmo status, mesma auditoria da tela. Sem o identificador, a revisão é apenas informativa e não fica registrada.

As estatísticas dos advogados via MCP seguem a mesma regra da tela: **apenas administradores**.

---

## Quem pode ver o quê

| Área | Quem acessa |
|---|---|
| Início, Revisar Petição, Resultado, Detalhe da Petição | Qualquer usuário com o módulo **Revisor de Petições** liberado |
| Aprovar petição / trocar status / descartar pontos | Qualquer usuário do escritório com o módulo |
| Estatísticas dos Advogados, Configurações, Treinamento, Auditoria | **Somente administradores** |

---

## Glossário rápido

| Termo | Significado |
|---|---|
| **Id Wrike** | Identificador do documento no escritório — a chave que liga as revisões de uma mesma petição. |
| **Ponto de atenção (achado)** | Item apontado pela IA revisora, com gravidade e sugestão de correção. |
| **CRÍTICO / MODERADO / FORMAL** | Gravidades dos achados, da mais séria à de padronização. |
| **Revisão focada** | A partir da 2ª revisão do mesmo documento: verifica só a correção dos pontos anteriores. |
| **Análise Comparativa** | Revisão de duas versões (original × revisada) do mesmo documento. |
| **Reincidência** | O mesmo erro reaparecendo em revisão posterior. |
| **Retrabalho** | Petição que precisou de mais de uma revisão. |
| **Manual de revisão** | Documento de referência do escritório usado como régua pela IA. |
