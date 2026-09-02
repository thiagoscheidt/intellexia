# Remessa R02 — Revisor de Petições Iniciais

**Origem:** briefing de envio R02 (Fred, 14/08/2026) + documento de feedbacks dos
usuários (Gabriel, Isrhael, Rodrigo, Edivan, Guilherme, João, Fred).
**Módulo:** `fap_review` (Revisor de Petições Iniciais).
**Data do design:** 02/09/2026.
**Conferência do retorno:** Fred, em ambiente de teste.

---

## 1. Resumo

Quinze itens (RPI-02 a RPI-25). A análise do código mostrou três grupos com
naturezas bem diferentes, e isso muda o esforço de cada um:

| Grupo | Itens | Natureza |
|---|---|---|
| Bugs com causa raiz localizada | RPI-14, RPI-18, RPI-19 | Correção pontual; duas são de uma linha |
| Já existe no sistema, escopo real é menor | RPI-03, RPI-04, RPI-09, RPI-25 | Completar o que falta, não construir do zero |
| Construção nova | RPI-02, RPI-07, RPI-10, RPI-12, RPI-13, RPI-20, RPI-22, RPI-23 | Camada de saneamento, validação e controle de lotes |

Dez dos quinze itens são atendidos por **três peças de base** descritas na
seção 3. Construí-las primeiro evita resolver o mesmo problema quatro vezes.

---

## 2. Decisões de design tomadas

Registradas aqui porque mudam o resultado e foram escolhas explícitas:

1. **Escopo dos lotes (RPI-02/03/22): o Revisor de Petições.** O cenário
   original do Gabriel ("500 contestações FAP com GPT-mini, reprocessar com
   Claude") é o classificador de contestações — outro módulo. O critério de
   aceite do briefing, porém, diz "abrir o agente de treinamento", que é a tela
   do Revisor. Seguimos o aceite; a remessa fica coesa em um módulo só.
2. **Saneamento de achados: código determinístico + prompt.** O prompt orienta,
   mas quem garante é código testável após a resposta. RPI-12 e RPI-13 são
   exatamente casos em que o modelo já desobedeceu a instrução, e o aceite
   ("não ter mais ocorrências") é absoluto — nenhum prompt garante isso.
3. **Prazo de 60 dias (RPI-10): validador determinístico + manual corrigido.**
   LLM fazendo aritmética de data erra, e o aceite é numérico.
4. **"Ver no documento" (RPI-14): marcação no servidor**, reusando o mecanismo
   já provado no módulo DOU, em vez de endurecer a heurística do navegador.
5. **Comparação de modelos (RPI-22): precisão medida pela triagem humana**
   já coletada, mais a comparação objetiva lado a lado. Sem modelo juiz.
6. **Exclusão (RPI-09): lógica, admin-only**, saindo das listas e estatísticas
   mas preservando registro, arquivos e auditoria.

---

## 3. Espinha dorsal

### 3.1 Persistir o modelo efetivo na execução

**Problema.** `FapReviewExecution` grava versões de prompt e referência
(`prompt_version_id`, `reference_version_id`, `used_versions_json`), tokens e
custo — mas **não grava o modelo**. Sem isso é impossível dizer com que modelo
um lote rodou.

**Mudança.** Nova coluna `FapReviewExecution.model_name` (String(100),
nullable), gravada no momento em que o agente é instanciado. Migration
standalone e idempotente em `database/`, no padrão do projeto (verifica a
existência da coluna antes de criar).

**Por que é a primeira peça.** Destrava RPI-18 (o debug passa a dizer a
verdade), RPI-02 (o lote sabe seu modelo) e RPI-22 (comparar por modelo).

**Cuidado.** Execução antiga fica com `NULL`. A tela mostra "não registrado" —
nunca um valor chutado. Foi justamente um literal chutado que criou o RPI-18.

### 3.2 Saneador de achados

**Módulo novo**, função pura: sem Flask, sem rede, sem LLM — no mesmo espírito
de `dou_xml_parser`. Recebe os achados e o texto do documento; devolve os
achados saneados **e a lista do que foi descartado, com o motivo**.

| Regra | Requisito | O que faz |
|---|---|---|
| R1 | RPI-12 | Se a sugestão de correção, normalizada, é igual ao trecho original, descarta o achado |
| R2 | RPI-13 | Deduplica por fingerprint, reusando `_build_finding_fingerprint` (já existe, hoje só usado para achados descartados) |
| R3 | RPI-07 | Se o `location_excerpt` cai dentro de um span entre aspas do documento, descarta |
| R4 | RPI-10 | Recalcula o intervalo entre datas citadas e corrige o número |
| R5 | RPI-20 | Descarta risco jurídico que não cite âncora (achado ou documento faltante) |
| R6 | — | Mantém a regra atual de falso positivo de razão social (`_should_ignore_finding`) |

**O descarte é registrado e exibido no debug.** Filtro silencioso vira caixa
preta: quando o revisor deixar de apontar algo, ninguém saberá se ele não viu
ou se o saneador comeu. O aceite do Fred é sobre confiança no agente, e isso só
se sustenta se o que foi removido puder ser auditado.

**Por que função pura.** Permite testar os dois exemplos do RPI-10 e os casos de
RPI-12/13 como asserções literais, sem gastar chamada de modelo.

### 3.3 Grifo determinístico no servidor

**Problema.** O destaque de "Ver no documento" é uma busca fuzzy no navegador:
quebra o trecho em palavras de 5+ letras, tenta casar blocos e títulos, e rola
com `behavior:'smooth'`. Quando não casa, fica no topo; quando casa tarde,
"pula" segundos depois. É o comportamento errático do RPI-14.

**Mudança.** O módulo DOU já resolveu exatamente este problema: localizar um
trecho no texto normalizado e marcá-lo no HTML original, com mapa de índices
(o `NFKD` preserva o comprimento em letra acentuada, mas não em ligadura nem em
compatibilidade — sem o mapa o recorte desloca). Extrair
`_normalizar_com_mapa` e `grifar_html` para um util compartilhado; DOU passa a
importar de lá, com comportamento idêntico.

O preview envolve o trecho em `<mark id="alvo">` **no servidor**; o JavaScript
fica reduzido a ancorar. Sem busca no cliente, sem corrida com o layout.

**Atende RPI-14 e RPI-25 pelo mesmo caminho** — o "ver trecho" dos anexos é o
mesmo mecanismo aplicado a outro documento.

---

## 4. Requisito a requisito

### RPI-02 — Controle de lotes de processamento

**Tela:** Treinamento (`/fap-review/training`).

**Pedido.** Saber o prompt e o modelo usados em cada lote processado, para
rastrear erro sistemático. Aceite: ver o histórico de ingestão com detalhes do
lote e modelo, reprocessar o mesmo lote com outro modelo e comparar.

**Hoje.** A tela já lista a atividade recente, mas **corta em 12 registros** e
mostra apenas id, documentos, alvos e data. Modelo, prompt e usuário não
aparecem — e o modelo sequer é gravado.

**Mudança.** (a) Gravar o modelo (peça 3.1). (b) Histórico completo, paginado,
com modelo, versões de prompt e referência, usuário, data e itens do lote.
(c) Ação de reprocessar uma execução concluída com outro modelo, criando uma
execução nova ligada à original — sem sobrescrever a triagem já feita.

---

### RPI-03 — Coerência entre lotes processados por modelos diferentes

**Tela:** Treinamento.

**Pedido.** Definir qual modelo/prompt vale, para que análises sucessivas não
divirjam em classificação de teses e regras de negócio. Aceite: revisar e
aprovar os aprendizados decorrentes de uma ingestão.

**Hoje.** O mecanismo **já existe**: prompts e referências são versionados por
escritório com ativação explícita; `used_versions_json` grava o que cada
execução usou; a aprovação dos aprendizados é a tela de comparação do
treinamento com "Salvar rascunho" / "Salvar e ativar".

**Mudança.** Não é preciso mecanismo novo — é preciso ficar **visível**. O
histórico do lote passa a exibir a combinação usada (modelo + versões) e a
marcar qual está vigente hoje, para que a divergência entre dois lotes seja
legível na tela. Aprovar um aprendizado continua sendo o ato que define o que
vale.

---

### RPI-04 — Filtros na lista de petições

**Tela:** Lista do Revisor (`/fap-review/`).

**Pedido.** Filtrar por advogado e por título, sendo o título incremental.
Feedback do Isrhael acrescenta: busca em dois níveis (advogado primeiro,
depois texto dentro da seleção) e contador por advogado por status.

**Hoje.** A busca incremental **já existe e já cobre título, Id Wrike e nome do
advogado** — o campo `data-search` de cada linha concatena os três e o filtro
roda no evento `input`.

**Mudança.** (a) Seletor de advogado como primeiro nível; a busca textual passa
a filtrar dentro da seleção. (b) Contador por advogado, por status, ao lado do
nome ("Rodrigo — 12, sendo 3 em revisão, 5 aguardando aprovação"), vindo de uma
query agregada na camada de serviço, filtrada por `law_firm_id`.

---

### RPI-07 — Ignorar apontamentos em citação direta

**Tela / funcionalidade:** agente revisor.

**Pedido.** Não auditar trechos entre aspas (citações de doutrina,
jurisprudência ou lei). Transcrições não são corrigidas na peça.

**Hoje.** Não há **nenhum** tratamento de aspas. O caso do Rodrigo mostra o
agente pedindo para uniformizar "nos autos do processo nº" dentro de
transcrição de sentença, e para atualizar terminologia dentro de citação
literal do art. 18 da Lei 8.213/1991.

**Mudança.** Regra R3 do saneador: identificar os spans entre aspas no texto do
documento e descartar o achado cujo `location_excerpt` caia dentro de um deles.
O prompt também passa a instruir a não auditar transcrições — orienta o modelo,
mas quem garante é o código.

---

### RPI-09 — Arquivar ou excluir uma revisão

**Telas:** Lista do Revisor e Detalhe da petição.

**Pedido.** Tirar da lista de revisões em andamento um caso criado para teste ou
um projeto duplicado por erro de Id Wrike. Aceite: a petição sair da lista com
as respectivas mudanças nas estatísticas.

**Hoje.** **Arquivar já existe** — `archived` é status do fluxo, há botão no
detalhe da petição e coluna própria no kanban. O Edivan provavelmente não
encontrou a ação, que hoje só existe no detalhe.

**Mudança.** (a) Trazer arquivar para a lista/kanban, onde o problema aparece.
(b) Exclusão **lógica**, restrita a admin (mesma regra de aprovar e reabrir): a
petição sai das listas e das estatísticas, mas registro, arquivos e auditoria
permanecem. É recuperável — e o caso de uso é justamente engano (teste,
duplicata).

---

### RPI-10 — Regra para o prazo de 60 dias

**Tela / funcionalidade:** agente revisor + referência `manual_fap`.

**Pedido.** Contar o intervalo entre a DCB do benefício anterior e a DIB do
próximo sem considerar o dia da cessação. Aceite: cessação 22/12/2017 com
início 22/01/2018 retorna **30**; cessação 01/01/2020 com início 02/01/2020
retorna **0**.

**Hoje.** A regra não está em código no revisor — vive na referência
`manual_fap`, versionada e editável na tela de configurações. Não há DIB/DCB
estruturado em lugar nenhum: a planilha de benefícios só captura número do
benefício e tese, e o extrator de anexos devolve fatos em texto livre.

**Mudança.** (a) Corrigir a regra no `manual_fap`. (b) Regra R4 do saneador:
quando o achado cita duas datas, o código recalcula o intervalo e corrige o
número (ou descarta o achado, se o intervalo real não sustentar a tese).

> **Ponto para o Fred validar.** O texto do Edivan diz "não contar o primeiro
> dia e contar o último", o que daria **31** no exemplo 1 — contradizendo o
> próprio exemplo dele. Os dois exemplos são consistentes entre si com a
> fórmula `(DIB − DCB) − 1` (31−1=30 e 1−1=0), e o briefing confirma o aceite
> em 30 e 0. Implementaremos pelos exemplos, não pela frase.

---

### RPI-12 — Validação de sugestões

**Tela / funcionalidade:** agente revisor.

**Pedido.** Não apontar erro quando a sugestão de correção for igual ao item
original. Caso relatado: CEP "22.775-005" apontado como errado, com sugestão
"Corrigir para 'CEP 22.775-005'". O mesmo aconteceu com a razão social "SENDAS
DISTRIBUIDORA S.A.".

**Hoje.** Existe só um filtro pequeno e específico, que trata falso positivo de
razão social quando o próprio texto do achado diz que está consistente. Não há
comparação entre sugestão e original.

**Mudança.** Regra R1 do saneador: normalizar sugestão e trecho original
(espaços, caixa, pontuação de formatação) e descartar o achado quando forem
equivalentes.

---

### RPI-13 — Duplicidade de apontamentos

**Tela / funcionalidade:** agente revisor.

**Pedido.** Uma correção aparecer uma vez só na lista. Caso relatado: o
benefício B91 nº 6214157201 apontado nos pontos de atenção 15 e 21, com
descrição e sugestão idênticas.

**Mudança.** Regra R2 do saneador: deduplicar por fingerprint, reusando
`_build_finding_fingerprint` — a mesma função que já identifica achados
descartados entre revisões. Mantém-se a primeira ocorrência; as demais entram
no registro de descarte.

---

### RPI-14 — Função "Ver no documento" não funciona como esperado

**Tela:** Visualizador do documento (modal do resultado da revisão).

**Pedido.** Ao clicar, ser exibido o trecho onde consta o erro daquele item.
Relato: às vezes fica no começo do documento e pula segundos depois, sem
indicação de carregamento; às vezes só mostra o começo. O Edivan relata que
falhou em **todos** os "ver no documento".

**Hoje.** Heurística fuzzy no cliente com rolagem suave — ver 3.3.

**Mudança.** Marcação no servidor com âncora (peça 3.3). O agente já devolve
`location_excerpt` como trecho literal copiado do documento, que é a entrada
exata de que o mecanismo precisa. Quando o trecho não for localizável, a tela
diz isso — em vez de rolar para o topo e parecer quebrada.

---

### RPI-18 — Indicação do modelo de LLM no debug

**Tela:** Resultado da revisão, painel "Debug / Visualização completa".

**Pedido.** Verificar de forma confiável com qual modelo e prompt a revisão foi
gerada. Relato: configurado Sonnet 5, debug mostra `gpt-4o-mini`.

**Causa raiz.** O template lê `execution.model_name`, **coluna que não existe**.
Em Jinja um atributo inexistente é Undefined, que é falsy, então a expressão
`execution.model_name or 'gpt-4o-mini'` cai **sempre** no literal. O runtime usa
corretamente o modelo configurado em `FapReviewSetting.reviewer_model`.

**Conclusão: a configuração está certa; só o debug mente.** Das duas coisas que
o Fred suspeitava, a errada é a exibição.

**Mudança.** Peça 3.1 (gravar o modelo) e remover o literal do template. As
versões de prompt e referência já aparecem e continuam como estão.

> **Observação de arquitetura.** Existe no projeto uma segunda configuração de
> modelo por agente (`ai_model_settings`, com registry próprio). O revisor
> **não** está nesse registry — usa `FapReviewSetting`. Duas fontes para a
> mesma pergunta é confusão latente; não é escopo desta remessa, mas fica
> registrado.

---

### RPI-19 — Aceite da revisão e reprocessamento de erros

**Tela:** Resultado da revisão.

**Pedido.** Permitir aprovar a petição mesmo sem nenhum erro apontado. Relato do
João: petição corrigida até zerar os achados, o botão de enviar para aprovação
sumiu e o caso ficou pendente; só foi possível aprovar depois que uma nova
análise inventou 6 erros e ele os marcou como não pertinentes.

**Causa raiz.** A regra de negócio **já está correta**: a função que decide se a
triagem está completa retorna verdadeiro quando não há achados. O problema é de
template: a barra flutuante com "Versão final — enviar para aprovação" está
**dentro do bloco condicional que só renderiza quando existem achados**. Com
zero achados o bloco inteiro deixa de existir, e com ele o botão.

**Mudança.** Mover a barra de conclusão de triagem para fora desse
condicional. A petição sem achados passa a poder ser aprovada direto.

---

### RPI-20 — Definição de riscos jurídicos

**Tela:** Resultado da revisão, "Resumo executivo".

**Pedido.** Deixar claro como os riscos influenciam a análise de erros e como
são definidos. Aceite: não havendo item errado, não deveria haver risco.

**Análise.** No caso do João havia 0 achados e **6 lacunas documentais**, e os 3
riscos falavam justamente dessas lacunas. Documento faltante é uma lista
separada dos achados, então os riscos não eram invenção — eram outro eixo, sem
rótulo que dissesse isso.

**Mudança.** Todo risco passa a citar sua âncora: um achado específico ou um
documento faltante específico. A tela exibe a âncora ao lado do risco. Risco sem
âncora é descartado (regra R5 do saneador). Com zero achados e zero documentos
faltantes, a seção não aparece. No caso do João os 3 riscos apareceriam
rotulados como lacuna documental, e ele entenderia por que a petição pôde ser
aprovada mesmo assim.

---

### RPI-22 — Comparação entre modelos

**Tela:** Treinamento — comparação A/B (nova).

**Pedido.** Quantificar quanto uma análise é melhor que a outra. Relato do
Edivan: dos 21 pontos críticos apontados pelo GPT, **nenhum estava errado**;
reprocessando com Sonnet melhorou, mas sem medida.

**Hoje.** Reprocessar só é permitido para execução que **falhou** — para não
sobrescrever triagem já feita. Não há comparação.

**Mudança.** (a) Caminho novo e explícito de reprocessar-para-comparar, que
aceita execução concluída e cria uma execução irmã, preservando a original.
(b) Tela de comparação lado a lado: achados em comum, exclusivos de cada
modelo, distribuição por severidade, custo, tokens e tempo. (c) **Precisão pela
triagem humana**: o sistema já registra cada achado como revisado ou não
pertinente. Precisão = aceitos / total. O caso do Edivan vira "21 achados, 21
descartados, precisão 0%" contra o número do Sonnet no mesmo documento — que é
exatamente a quantificação pedida, e vem de verdade de campo, não de um modelo
julgando outro.

---

### RPI-23 — Campo Id Wrike

**Tela:** Nova revisão.

**Pedido.** Aceitar somente números; não permitir avançar com preenchimento
indevido, exibindo mensagem de erro e campo destacado em vermelho.

**Hoje.** O campo é o identificador do documento no escritório, texto de até 96
caracteres, único por escritório. Sem validação de formato.

**Mudança.** Validação no cliente (teclado numérico, padrão, campo em vermelho
com mensagem, botão bloqueado) **e no servidor** — validação só no navegador não
é validação. A unicidade por escritório continua valendo e sua mensagem de erro
segue distinta da de formato.

---

### RPI-25 — Mostrar a fonte dos dados

**Tela:** Resultado da revisão, seção "Documentos auxiliares × benefícios".

**Pedido.** O agente de leitura dos anexos indicar de onde tirou cada
informação, na mesma lógica do "ver no documento" do revisor. Motivo (Fred): o
agente inverte ordem de números e informa datas incoerentes, e não há como
conferir.

**Hoje.** O `source_excerpt` **já é extraído e persistido** para cada fato, e já
é usado no prompt do revisor. Só não é exibido na tela.

**Mudança.** Botão "ver trecho" por fato, abrindo o documento auxiliar com o
trecho grifado — reusando a peça 3.3, o mesmo caminho do RPI-14.

> **Fora de escopo, registrado.** O relato do Edivan sobre a CAT (data do
> acidente correta no anexo, ignorada pela análise) e o do Guilherme sobre
> divergência de NIT são falhas de **leitura** dos anexos, não de exibição.
> Mostrar a fonte torna essas falhas visíveis e diagnosticáveis, que é o
> primeiro passo — mas não as corrige. Merecem item próprio numa remessa
> seguinte.

---

## 5. Itens do documento de feedbacks fora desta remessa

Levantados pelos usuários, sem ID no briefing. Registrados para não se perderem:

| Origem | Item | Situação |
|---|---|---|
| Gabriel 1 | Log de revisões dentro de cada caso, para abrir a tentativa nº 4 | O detalhe da petição já lista as revisões; conferir se atende |
| Gabriel 3 | Usuários da mesma categoria com autorizações diferentes | É o modelo de permissão por módulo, que é por usuário e não por papel — decisão de produto, não defeito |
| Edivan 1 | Baixar anexos das contestações administrativas do FAP Web | Outro módulo (Painel FAP) |
| João 3 | E-mail de recuperação de senha nunca chega | **Defeito de infraestrutura, fora do Revisor.** Sem SMTP configurado o envio degrada em silêncio. Verificar no ambiente antes de tratar como bug de código |
| Fred 3 / Edivan | Erros de leitura de números e datas nos PDFs anexos | Ver nota do RPI-25 |

---

## 6. Ordem de entrega

| Onda | Itens | Por quê |
|---|---|---|
| 1 | RPI-19, RPI-18, RPI-23, RPI-09, RPI-04 | Destrava o aceite com risco baixo. RPI-19 e RPI-18 são correções pontuais que valem mais que o tamanho delas: uma libera o fluxo de aprovação, a outra devolve a confiança no debug |
| 2 | Saneador → RPI-12, RPI-13, RPI-07, RPI-10, RPI-20 | Qualidade dos achados; todos dependem da mesma peça |
| 3 | Grifo → RPI-14, RPI-25 | Ambos saem do mesmo mecanismo |
| 4 | RPI-02, RPI-03, RPI-22 | Bloco mais pesado e o único sem nada pronto; depende da coluna de modelo entregue na onda 1 |

---

## 7. Testes

O projeto não tem framework de testes; o padrão são scripts executáveis em
`tests/`, que importam a aplicação e usam o contexto Flask.

O saneador e o util de grifo são **funções puras**, então os casos críticos
viram asserções literais, sem chamar modelo e sem banco:

- RPI-10: os dois exemplos do briefing (30 e 0), mais as bordas (mesma data;
  DIB anterior à DCB).
- RPI-12: sugestão idêntica ao original, com e sem diferença de espaçamento e
  caixa.
- RPI-13: dois achados de mesmo fingerprint sobrevivem como um.
- RPI-07: achado dentro de aspas descartado; achado fora, preservado; aspas não
  fechadas não engolem o resto do documento.
- RPI-20: risco sem âncora descartado; risco ancorado em documento faltante
  preservado e rotulado.
- Grifo: trecho com acento, com ligadura e atravessando parágrafo.

Para as telas, o roteiro de conferência é o próprio critério de aceite da seção
5 do briefing, executado no ambiente de teste.

---

## 8. Riscos

1. **Extrair os helpers de grifo do DOU pode regredir o DOU.** Mover sem alterar
   comportamento e conferir contra o acervo antes de seguir. Se aparecer
   qualquer divergência, o plano B é implementação própria no Revisor, ao custo
   de duas cópias do mesmo grifo no projeto.
2. **O saneador pode esconder achado legítimo.** Mitigação: todo descarte é
   registrado com motivo e visível no debug. Sem isso não há como distinguir
   "o revisor não viu" de "o saneador comeu".
3. **Reprocessar para comparar custa uma chamada de modelo por execução.** O
   caminho é explícito e admin-only, nunca automático.
4. **Execuções antigas ficam sem modelo registrado.** A tela diz "não
   registrado". Não inferir a partir da configuração atual do escritório: a
   configuração pode ter mudado desde então, e um palpite aqui recria
   exatamente o RPI-18.
