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
| **Em revisão** | A IA está processando **ou** o advogado está triando os pontos de atenção. |
| **Aguardando ajustes** | O advogado concluiu a triagem e vai **enviar uma nova versão** corrigida (ou a revisão falhou e precisa de novo envio). |
| **Aguardando aprovação** | O advogado marcou a versão como **final** — a bola está com o **revisor (administrador)**. |
| **Aprovada pelo revisor** | Um **administrador** clicou em :btn-success[Aprovar petição]: pronta para protocolo. A petição fica **travada** para novas revisões. |
| **Processo iniciado** | A petição já foi protocolada (marcação manual). |
| **Arquivada** | Fora do fluxo — some da listagem padrão do painel (fica no filtro **Arquivadas** e na coluna recolhida do kanban). Arquive pelo botão :btn-outline-secondary[Arquivar] no detalhe da petição; :btn-outline-secondary[Desarquivar] a devolve ao fluxo. |

Como o status evolui:

- **Automaticamente**: ao enviar uma revisão a petição vira **Em revisão** e assim permanece enquanto o advogado tria os pontos. Se a revisão **falhar**, vira **Aguardando ajustes** (precisa de novo envio).
- **Pelo advogado**: depois de triar **todos** os pontos de atenção (cada um marcado como revisado ou não pertinente), a tela de resultado oferece dois caminhos: :btn-outline-primary[Revisada — enviar nova versão] (a petição vira **Aguardando ajustes** e você já é levado ao envio da nova versão) ou :btn-primary[Versão final — enviar para aprovação] (vira **Aguardando aprovação**).
- **Pelo administrador**: com a petição **Aguardando aprovação**, o admin decide entre :btn-success[Aprovar petição] (vira **Aprovada pelo revisor**) e :btn-outline-danger[Devolver para ajustes] (volta para **Aguardando ajustes**). "Processo iniciado" e "Arquivada" são marcações manuais.

> [!ALERTA] **Petição em aprovação ou aprovada fica travada.** A partir de **Aguardando aprovação** (e também em "Aprovada pelo revisor", "Processo iniciado" e "Arquivada"), a petição **não aceita novas revisões** — o botão some das telas e o envio é recusado. O destravamento é sempre de **administrador**: em "Aguardando aprovação", com :btn-success[Aprovar petição] ou :btn-outline-danger[Devolver para ajustes]; depois de aprovada, com :btn-outline-secondary[Reabrir petição] (volta para **Aguardando ajustes**).

> [!INFO] **O Id Wrike é a chave de tudo.** Cada petição tem um **identificador do documento** (o "Id Wrike", até 96 caracteres). É ele que liga as revisões sucessivas à mesma petição — inclusive as feitas pelo Claude via MCP — e que carrega o histórico de pontos descartados. Use sempre o mesmo identificador para o mesmo documento.

---

## Tela 1 — Início (painel de acompanhamento)

Visão geral das petições do escritório.

> [!INFO] **Painel de notificações (barra superior).** Em todas as telas, o **painel de notificações** — os chips no lado esquerdo da barra superior, ao lado do nome do escritório — inclui o chip **Revisor**, com as filas ativas das petições: um número **amarelo** para as **Em revisão** (novas + em revisão), um **vermelho** para as **Aguardando ajustes** (ação do advogado) e, para administradores, um **azul** para as **Aguardando aprovação**. Passe o mouse para ver o detalhe; o clique leva a este painel. Detalhes no manual do **Dashboard Principal**.

### Cartões de estatística

**Total de petições**, **Aguardando ajustes**, **Em revisão** (novas + em revisão), **Aguardando aprovação** (a fila do revisor/admin) e **Aprovadas pelo revisor**.

### Tabela "Petições em Acompanhamento"

Mostra **todas** as petições do escritório, priorizadas por status (aguardando ajustes primeiro, depois aguardando aprovação, em revisão e aprovadas), com busca em tempo real e filtros por status.

Sob o título de cada petição aparecem: a **quantidade de revisões** já realizadas, o número de **apontamentos da última revisão** e **há quanto tempo a petição está no status atual** (fica destacado em âmbar quando está aguardando ajustes há 7 dias ou mais).

| Coluna | O que mostra | De onde vem |
|---|---|---|
| **Petição** | Título da petição. | Sistema |
| **Id Wrike** | Identificador do documento no escritório. | Sistema |
| **Status** | Badge colorido com o status do ciclo (tabela acima). | Sistema |
| **Última Revisão** | Data da última revisão e o usuário responsável. | Sistema |
| **Ações** | Botões :btn-outline-primary[Última Revisão], :btn-outline-secondary[Abrir Petição] (histórico completo) e :btn-primary[Nova Revisão]. Em petições **Aguardando aprovação**, o :btn-primary[Nova Revisão] dá lugar ao :btn-success[Aprovar petição] (visível só para administradores — na lista, no kanban e no detalhe da petição); em **aprovadas, protocoladas ou arquivadas**, nenhum dos dois aparece (petição travada). | — |

### Visão kanban

Além da lista, a tela oferece uma **visão kanban**: use o seletor **Lista / Kanban** na barra de filtros. Cada coluna corresponde a um status da petição (Nova, Em revisão, Aguardando ajustes, Aguardando aprovação, Aprovada pelo revisor, Processo iniciado), e a coluna **Arquivada** fica recolhida à direita — clique no cabeçalho para expandi-la.

- **Arraste um card** para outra coluna para mudar o status da petição — o efeito é o mesmo da troca manual de status na tela da petição, inclusive no registro de auditoria. Mudanças reservadas ao administrador (aprovar, ou tirar uma petição de "Aguardando aprovação"/"Aprovada pelo revisor") são recusadas para os demais usuários — o card volta para a coluna original.
- A **busca** filtra os cards normalmente; a preferência de visão fica salva no navegador.
- Se a mudança de status falhar (por exemplo, sem conexão), o card volta para a coluna original e um aviso é exibido.
- Cada card também mostra a quantidade de revisões, os apontamentos da última revisão e há quantos dias a petição está naquele status.

---

## Tela 2 — Revisar Petição (envio)

Formulário em três passos:

1. **Selecionar ou criar petição** — escolha uma petição existente **ou** crie uma nova informando **Título** e **Id Wrike**.
2. **Enviar documento principal** — a petição a revisar. Formatos aceitos: **PDF, DOCX e TXT**. Arquivos **.doc não são aceitos** (converta para PDF ou DOCX). Limite de 50 MB por envio.
3. **Complementos (opcionais)**:
   - **Documentos auxiliares** — anexos de apoio (PDF, DOC/DOCX, XLS/XLSX, TXT e imagens).
   - **Planilha de benefícios (.xlsx)** — ativa a conferência "Benefícios da Planilha x Documento" (ver adiante).
   - **Segunda versão do documento** — ativa a **Análise Comparativa** (original × revisado).

> [!INFO] **Reaproveitar arquivos da revisão anterior.** Ao selecionar uma petição que já tem revisão, aparecem caixas de seleção para **usar os documentos auxiliares** e/ou **a planilha de benefícios do envio anterior** — sem precisar anexar tudo de novo. Os arquivos são copiados para a nova revisão; se você enviar uma planilha nova junto, ela tem prioridade sobre a reutilizada, e auxiliares novos são **somados** aos reaproveitados.

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

### Triagem dos pontos (revisado / não pertinente)

Cada ponto de atenção tem dois botões no canto do card, e **toda marcação é salva no sistema** — o progresso vale em qualquer navegador e fica visível para a equipe:

- **✓ Marcar como revisado** — você conferiu o ponto (e vai corrigi-lo, se for o caso). A barra de **Progresso de revisão** avança.
- **✕ Não pertinente** — você discorda do apontamento. O sistema memoriza esse descarte **para aquele documento** (pelo Id Wrike): nas próximas revisões, o mesmo ponto **não será cobrado de novo**. O descarte é reversível (botão de desfazer) e fica registrado na auditoria.

Ao interagir com esses botões a petição passa a **Em revisão** (se ainda não estava).

### Concluir a triagem

Quando **todos** os pontos estiverem triados (revisados + não pertinentes), surge uma **barra flutuante** no rodapé da tela — "Todos os pontos foram triados. Como deseja concluir esta versão?" — com a decisão sobre esta versão:

- :btn-outline-primary[Revisada — enviar nova versão] — os pontos exigem correções: a petição vira **Aguardando ajustes** e você é levado direto ao formulário de **Nova Revisão**, já com a petição selecionada, para enviar a versão corrigida quando estiver pronta.
- :btn-primary[Versão final — enviar para aprovação] — a versão está boa: a petição vira **Aguardando aprovação** e entra na fila do revisor (administrador).

O sistema **confere no servidor** que a triagem está completa antes de aceitar a conclusão — se faltar algum ponto, ele avisa quantos faltam. Uma revisão **sem pontos de atenção** já nasce com a triagem completa.

### Documentos Obrigatórios em Falta

Lista os documentos que, segundo o manual, deveriam acompanhar as teses da petição e não foram localizados — com a tese relacionada e a referência do manual.

> [!IA] **Como a checagem funciona.** A IA cruza as teses identificadas com as exigências documentais do manual e verifica se cada documento está **demonstrado no texto da petição** — inclusive **imagens embutidas** (prints de telas do FAP, CATs, extratos), que são detectadas e contam como prova presente no tópico onde aparecem. Nesta checagem a IA **não lê o conteúdo interno das imagens** — ela confere presença, não teor. Já o conteúdo dos **arquivos auxiliares** enviados no formulário é lido em etapa própria (veja **Cruzamento dos documentos auxiliares** abaixo).

### Resumo Executivo

Totais por gravidade, **Principais Riscos Jurídicos** e **Prioridade de Correção** (ALTA / MÉDIA / BAIXA).

### Alterações Identificadas (só na Análise Comparativa)

Quando você envia a segunda versão, a IA compara original × revisado e lista cada alteração: trecho original, trecho corrigido, o motivo da correção e se o padrão **já existe no manual** ou é novo.

### Benefícios da Planilha x Documento (só com a planilha .xlsx)

Conferência **automática, sem IA**: o sistema lê as colunas **"Número do Benefício"** e **"TESES"** de **todas as abas** da planilha (comum ter uma aba por vigência — 2021, 2022, ...; abas sem essas colunas, como anotações, são ignoradas) e verifica se cada benefício **é citado no texto** da petição (tolerante a pontuação: "123.456.789-0", com espaços etc.). Resultado por linha: **Citado / Não citado**, com totais — e, quando a planilha tem várias abas, uma coluna **Aba** indica a origem de cada linha.

| Detalhe | Origem |
|---|---|
| Pontos de atenção, teses, documentos em falta, resumo executivo | IA |
| Conferência da planilha de benefícios | Cálculo |
| Status, histórico, custo e tokens da revisão | Sistema |

> Só entram na conferência da planilha as linhas com a coluna **TESES** preenchida.

### Cruzamento dos documentos auxiliares :claude:

> [!IA] **Leitura e cruzamento automáticos.** Ao enviar documentos auxiliares (CAT, CNIS, INFBEN, prints do FAP Web, laudos), a IA lê cada arquivo, identifica a quais benefícios ele se refere e extrai os dados relevantes às teses da planilha de benefícios. Esses dados são cruzados com a petição: divergências (datas, CNPJ, razão social, espécie do benefício) viram apontamentos na revisão, sempre citando o arquivo de origem.

Como funciona:

| Etapa | Origem |
| --- | --- |
| Identificação dos benefícios e teses | Relatório |
| Leitura e extração dos documentos auxiliares | IA |
| Cruzamento contra a petição | IA |
| Card "Documentos Auxiliares x Benefícios" | Sistema |

- Com a **planilha de benefícios** enviada, a extração é guiada pelas teses de cada benefício (ex.: tese de acidente de trajeto faz a IA buscar data e local do acidente na CAT).
- Sem planilha, os números de benefício são localizados na própria petição.
- Arquivos reenviados em revisões seguintes não são reprocessados (aparecem com o selo "Reaproveitado").
- Documentos que a IA não conseguir vincular a nenhum benefício aparecem como "Sem vínculo identificado" — confira-os manualmente.

### Ações da tela

- **Todos os usuários**: :btn-primary[Nova Revisão], **Visualizar Documento** enviado (em DOCX, o botão :btn-outline-primary[Ver no Documento] de cada ponto abre o conteúdo com o trecho exato do achado destacado), **Visualizar Manual** de referência e **Copiar JSON** (dados brutos). A tela também mostra o modelo de IA usado, tokens e **custo estimado** da revisão.
- **Somente administradores**, quando a petição está **Aguardando aprovação**: :btn-success[Aprovar petição] (marca "Aprovada pelo revisor" e trava a petição) e :btn-outline-danger[Devolver para ajustes] (recusa a versão final — volta para "Aguardando ajustes").
- **Somente administradores**, quando a petição está **Aprovada pelo revisor**: :btn-outline-secondary[Reabrir petição] (destrava e volta para "Aguardando ajustes").

---

## Tela 4 — Detalhe da Petição

Histórico completo de uma petição: todas as revisões (número, data, status, documento e responsável) e um resumo (concluídas, em processamento, com falha, comparativas).

> [!INFO] **Revisões substituídas.** Quando uma nova revisão é enviada, as anteriores passam a exibir o status **Substituída** — elas continuam no histórico para consulta, mas ficam **somente leitura**: a tela da revisão antiga mostra um aviso com atalho para a revisão atual, e a triagem (marcar revisado / não pertinente / concluir) só funciona na revisão mais recente. Aqui você pode **editar o título e o Id Wrike** (o histórico de descartes acompanha a mudança) e **trocar o status** manualmente — inclusive marcar "Processo iniciado" ou "Arquivada".

As mudanças de status reservadas ao administrador valem aqui também: para quem não é admin, o seletor de status **não oferece** "Aprovada pelo revisor" e fica **bloqueado** quando a petição está "Aguardando aprovação" ou aprovada. Em petição **aprovada**, o botão :btn-primary[Nova Revisão] some e o administrador vê :btn-outline-secondary[Reabrir petição] no lugar.

O painel **Última Revisão** traz também o **Panorama da revisão**: os totais do Resumo Executivo (apontamentos totais, críticos, moderados e formais) e a prioridade de correção — sem precisar abrir o resultado completo.

A seção **Histórico de Alterações** mostra a linha do tempo da petição: cada mudança de status (inclusive as feitas arrastando o card no kanban), revisões executadas e edições cadastrais, com usuário e data de cada evento.

---

## Tela 5 — Estatísticas dos Advogados (apenas administradores)

Painel de aprendizado da equipe. Para cada advogado: **pontuação (0–100)**, revisões e petições, **retrabalho** (petições que precisaram de mais de uma revisão), achados por gravidade, **reincidência** (o mesmo erro reaparecendo em revisões seguintes), tipos de erro mais frequentes e evolução mensal (últimos 6 meses).

> [!INFO] **Como a pontuação é calculada:** começa em 100 e desconta três sinais — a **média de achados por revisão**, a **taxa de retrabalho** e a **taxa de reincidência**. É uma medida **heurística, para orientar a melhoria da equipe — não para ranquear pessoas**.

---

## Configurações (apenas administradores)

Tudo aqui é **por escritório** e **versionado**. No editor você escolhe entre **Salvar Rascunho** (cria a versão sem ativá-la) e **Salvar e Ativar** (a nova versão já passa a valer). Ao abrir uma versão antiga, um aviso deixa claro que ela está inativa.

- **Agente Revisor** — modelo de IA e temperatura (padrão 0.0 — determinístico) usados nas revisões; pode ser desativado.
- **Agente de Treinamento** — modelo e temperatura (padrão 0.7) do fluxo de Treinamento.
- **Políticas de Atualização** — se o Treinamento pode atualizar o manual e os casos automaticamente, e se exige aprovação antes de publicar.
- **Prompts** — a "personalidade" do revisor: **Identidade**, **Regras invioláveis** e os textos do Treinamento. O **Formato de saída** é definido pelo próprio sistema (contrato técnico embutido no agente) — o campo nas Configurações é apenas informativo e não influencia a revisão.
- **Referências** — o **Manual de revisão do FAP** (a régua das revisões), os **Casos de referência** e as **Instruções do projeto** (somente leitura). O botão **Importar de arquivo** carrega o conteúdo de um `.md`, `.txt` ou `.docx` para o editor — você revisa e salva como nova versão.

Recursos do histórico de versões:

- **O que mudou nesta versão?** — anote um resumo ao salvar; ele aparece no histórico e na auditoria.
- **Comparar versões** — o botão de diff mostra, linha a linha, o que mudou entre a versão aberta e qualquer versão anterior (adições em verde, remoções em vermelho).
- **Rastreabilidade** — cada revisão registra com quais versões de prompt e referência ela rodou (visível na aba de detalhes técnicos do resultado).

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
| Triar pontos (revisado / não pertinente) e concluir a triagem | Qualquer usuário do escritório com o módulo |
| :btn-success[Aprovar petição], :btn-outline-danger[Devolver para ajustes] e :btn-outline-secondary[Reabrir petição] | **Somente administradores** |
| Estatísticas dos Advogados, Configurações, Treinamento, Auditoria | **Somente administradores** |

---

## Glossário rápido

| Termo | Significado |
|---|---|
| **Id Wrike** | Identificador do documento no escritório — a chave que liga as revisões de uma mesma petição. |
| **Ponto de atenção (achado)** | Item apontado pela IA revisora, com gravidade e sugestão de correção. |
| **Triagem** | Conferência humana dos pontos de atenção: cada um é marcado como **revisado** ou **não pertinente**; concluída, define o próximo passo da petição. |
| **CRÍTICO / MODERADO / FORMAL** | Gravidades dos achados, da mais séria à de padronização. |
| **Revisão focada** | A partir da 2ª revisão do mesmo documento: verifica só a correção dos pontos anteriores. |
| **Análise Comparativa** | Revisão de duas versões (original × revisada) do mesmo documento. |
| **Reincidência** | O mesmo erro reaparecendo em revisão posterior. |
| **Retrabalho** | Petição que precisou de mais de uma revisão. |
| **Manual de revisão** | Documento de referência do escritório usado como régua pela IA. |
