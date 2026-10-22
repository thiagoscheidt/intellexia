# Manual do Usuário — Biblioteca de IA

> A Biblioteca de IA guarda num lugar só os prompts, agentes e skills que funcionam: os seus e os do escritório. Cada item pode ser copiado com um clique e já aparece como comando no :claude: Claude, pelo conector do IntellexIA.

---

## O que é

Cada pessoa do escritório tem os prompts que usa todo dia, como o resumo de sentença, o e-mail ao cliente ou o roteiro de revisão da impugnação. Sem a biblioteca, eles ficam espalhados em arquivos e na conta do Claude de cada um. O que funciona para uma pessoa não chega às outras e vai embora quando ela sai do escritório.

Na biblioteca, você:

- **guarda** os seus prompts, só para você ou para todo o escritório;
- **copia** com um clique, ou **preenche e copia** quando o prompt tem campos;
- **usa no Claude** como comando pronto, sem copiar nada;
- **importa** uma skill que já tem no Claude e **baixa** qualquer item como skill.

A biblioteca fica no menu lateral, em **Biblioteca de IA**, e todo usuário tem acesso. O botão **Como usar**, no topo da tela, resume tudo isto.

---

## As abas

| Aba | O que mostra |
|---|---|
| **Meus** | O que você criou, pessoal ou compartilhado |
| **Do escritório** | Tudo o que foi compartilhado com o escritório. Os **Recomendados pelo escritório** vêm primeiro |
| **Do IntellexIA** | Os comandos prontos que vêm com o sistema, como o relatório semanal do FAP e a análise de empresa. Não dá para editar, mas dá para duplicar e adaptar |
| **Favoritos** | Os itens em que você clicou na estrela |

A busca procura no título, no texto, na área e no autor. O filtro lateral separa por **tipo** (prompt, agente, skill), por **área** (FAP, Jurisprudência, Processos...) e por **selo** (recomendados, usa dados do IntellexIA).

---

## Prompt, agente e skill

Os três funcionam do mesmo jeito. A etiqueta serve para quem procura saber o que vai encontrar:

| Tipo | Quando usar | Exemplo |
|---|---|---|
| **Prompt** | Um texto para colar, com ou sem campos | "E-mail ao cliente: contestação deferida" |
| **Agente** | Um roteiro com papel, passos e as ferramentas do IntellexIA que o Claude deve consultar | "Analista de sentença FAP" |
| **Skill** | Instruções com **anexos** (modelo de peça, checklist, exemplos), no formato de skill do Claude | "Revisão de impugnação antes do protocolo" |

Marque **Usa os dados do IntellexIA no Claude** quando o texto manda o Claude consultar benefícios, jurisprudência, processos e outros dados pelo conector. O card ganha o selo de tomada.

---

## Agentes que consultam o IntellexIA

O conector do IntellexIA tem dezenas de **ferramentas**, como listar benefícios do FAP, pesquisar jurisprudência ou ler o Diário Oficial. Para ver todas, clique em **Ferramentas do IntellexIA**, no topo da tela (ou em **Ver ferramentas**, na aba Do IntellexIA): cada uma é um card com a área, um nome curto, o nome técnico e o que ela faz, com busca e filtro por área. As que você não acessa ficam em cinza, no fim.

O Claude escolhe a ferramenta sozinho. Mas um agente que diz **qual ferramenta chamar** dá o mesmo resultado toda vez, e é assim que os comandos prontos do IntellexIA são escritos ("Chame resumo_fap..."). Há dois jeitos de fazer isso sem decorar nomes:

- Em **Ferramentas do IntellexIA**, clique em **Usar num agente** no card. O editor abre um agente novo já com a ferramenta no texto.
- No editor, clique em **Inserir ferramenta do IntellexIA**, procure ("benefícios", "jurisprudência", "CNPJ") ou filtre pela área, e clique no card. Entra no texto, onde está o cursor, uma linha como "Chame a ferramenta `listar_beneficios_fap` do IntellexIA para ..." Complete com o que você quer.

Abaixo do texto, o editor mostra as ferramentas que o roteiro chama e os módulos que elas usam. Citar uma ferramenta já marca "Usa os dados do IntellexIA", e o card mostra quantas o roteiro chama.

> [!ALERTA] Cada ferramenta respeita as permissões de quem usa o item. Um agente do escritório que consulta o Diário Oficial dá "acesso negado" para quem não tem esse módulo. O editor avisa quais módulos o roteiro usa, e as ferramentas que você não acessa aparecem em cinza, com cadeado.

---

## Criar um prompt, agente ou skill

1. Clique em :btn-success[+ Novo] e escolha **Prompt**, **Agente** ou **Skill**. O editor abre com o tipo marcado (dá para trocar lá dentro).
2. Dê um título e, se quiser, diga em uma frase **quando usar**.
3. Confira o **comando no Claude**. Ele sai do título enquanto você digita (`Resumo de sentença FAP` vira `resumo_de_sentenca_fap`), mas pode ser trocado por um nome curto e fácil de lembrar, como `resumo_sentenca`. Na frente do nome vêm, sozinhos, de quem é e o tipo: `/meu_prompt_resumo_sentenca` para um prompt seu, `/escritorio_agente_resumo_sentenca` para um agente do escritório. Mudar o título depois não muda o comando; mudar o tipo ou quem vê muda o começo dele.
4. Cole o texto. O que muda a cada uso vira **campo**, escrito entre chaves duplas: `{{empresa}}`, `{{vigencia}}`, `{{numero_beneficio}}`. A tela mostra os campos que encontrou.
5. Escolha o tipo, a área e **quem vê**: só você ou todo o escritório.
6. Clique em :btn-primary[Salvar na biblioteca].

> [!INFO] Prompt bom para a biblioteca não traz dado do caso: em vez de "a Vale em 2025", escreva "a `{{empresa}}` em `{{vigencia}}`". Assim ele serve para todo mundo.

> [!ALERTA] Ao compartilhar com o escritório, a biblioteca confere se o texto tem **CPF ou CNPJ**. Se tiver, ela avisa e só publica depois de você confirmar.

---

## Usar um prompt

| Botão | O que acontece |
|---|---|
| :btn-primary[Copiar] | Copia o texto, com os anexos, para você colar no Claude |
| :btn-primary[Preencher e copiar] | Aparece quando o prompt tem campos: você preenche, vê como fica e copia o texto pronto |
| :btn-outline-secondary[Abrir no Claude] | Abre uma conversa nova no Claude e copia o texto. Se ele não aparecer escrito na conversa, cole com Ctrl+V |

No :claude: **Claude**, com o conector do IntellexIA, cada item também vira **comando pronto**:

- `meu_<tipo>_<nome>` para os seus itens pessoais (ex.: `meu_prompt_resumo_sentenca`);
- `escritorio_<tipo>_<nome>` para os compartilhados com o escritório (ex.: `escritorio_agente_triagem_publicacoes`).

O tipo no nome ajuda a saber, já na lista do Claude, se o comando é um texto (`prompt`), um roteiro que consulta os dados (`agente`) ou uma skill com anexos (`skill`).

**De qualquer tela, sem sair dela:** o botão **Biblioteca**, no cabeçalho, ao lado do Claude e da API (ou o atalho **Ctrl + K**; no Mac, **Cmd + K**) abre uma janela rápida com os seus favoritos, os recomendados pelo escritório e os mais usados. Digite para buscar em tudo, escolha com as setas e aperte **Enter** para copiar. Se o item tem campos, a janela pede os valores antes, e Enter copia o texto pronto.

O nome do comando aparece em cada card e é o que você escolheu no editor. Os campos viram as perguntas do comando. Se um prompt recém-criado não aparecer na lista, reconecte o conector ou peça ao Claude: "use o prompt de resumo de sentença da minha biblioteca".

Também funciona ao contrário. Quando um pedido der certo numa conversa, diga ao Claude: **"salva isso na minha biblioteca"**. Ele guarda o item só para você, até você pedir para compartilhar.

---

## O menu ⋯ do card

| Ação | Quem pode |
|---|---|
| **Editar** | Quem criou e, nos itens do escritório, os administradores |
| **Duplicar** | Todos. A cópia vai para "Meus", só para você |
| **Ver versões** | Todos. Toda edição do texto guarda a versão anterior, e dá para restaurar |
| **Compartilhar com o escritório** / **Tornar pessoal** | Quem criou |
| **Recomendar ao escritório** | Administradores. O item ganha o selo e vai para o topo da aba "Do escritório" |
| **Baixar como skill do Claude** | Todos |
| **Arquivar** | Quem pode editar. O item sai da biblioteca |

> [!INFO] O item **pessoal** é só seu: nem os administradores o veem. O item do escritório continua na biblioteca mesmo se quem o criou sair do escritório.

---

## Skills do Claude

**Importar.** No Claude, baixe a skill (o arquivo `.zip`) e, na biblioteca, abra :btn-success[+ Novo] → **Importar skill do Claude**. Ela entra em "Meus" como item do tipo skill: as instruções do `SKILL.md` viram o texto, e os outros arquivos de texto viram anexos.

**Baixar.** No menu ⋯ de qualquer item, **Baixar como skill do Claude** gera o `.zip` no formato do Claude, pronto para subir em **Configurações → Capacidades → Skills**.

> [!ALERTA] Só arquivos de texto entram na biblioteca (instruções, modelos, checklists). Scripts ficam de fora, e a tela avisa quais foram ignorados: uma skill compartilhada rodaria o script na máquina dos colegas.
