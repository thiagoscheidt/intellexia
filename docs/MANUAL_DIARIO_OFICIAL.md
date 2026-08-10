# Manual — Diário Oficial

A tela **Diário Oficial** guarda, dentro do IntellexIA, as edições do Diário
Oficial da União publicadas pela Imprensa Nacional. Todo dia o sistema baixa as
edições, separa cada matéria publicada e deixa tudo pronto para consulta.

> [!DOU] O conteúdo vem do portal de dados abertos da Imprensa Nacional
> (INLABS), em formato XML. Como o próprio portal avisa, esse formato **não
> substitui a versão certificada** — para uso oficial, baixe o PDF assinado da
> edição, disponível na própria tela.

## Como a tela é organizada

A navegação tem três níveis, do geral ao específico. Você desce só até onde
precisa.

### 1. Edições

É a tela de entrada, e é parecida com a listagem do portal da Imprensa Nacional:
**uma linha por dia**, do mais recente para o mais antigo. Em cada linha você vê
quais seções foram publicadas, quantas matérias o dia teve, e os botões para
baixar o PDF assinado de cada seção.

**Se você só quer o Diário do dia em PDF, resolve aqui** — sem precisar entrar
em mais nada.

### 2. A edição do dia

Clicando na data, abre a edição daquele dia com uma **aba por seção**:

- **Seção 1** — atos normativos (portarias, resoluções, decretos).
- **Seção 2** — pessoal do serviço público federal.
- **Seção 3** — contratos, licitações e avisos.
- **Edições Extras** — publicações fora da edição normal do dia.

Cada aba mostra quantas matérias tem e lista essas matérias.

> [!INFO] **Matéria é um ato publicado** — uma portaria, um acórdão, um aviso de
> licitação. Não é um arquivo: o sistema recebe o Diário da Imprensa Nacional e
> separa cada ato individualmente, para você chegar direto no que interessa em
> vez de percorrer um PDF de centenas de páginas.

Como uma seção pode ter milhares de matérias no mesmo dia, use os filtros:

| Filtro | Para que serve |
|---|---|
| Órgão | Busca por parte do nome do órgão. Ex.: digitar `Previdência` traz tudo do Ministério da Previdência Social. |
| Tipo de ato | Portaria, Resolução, Aviso, Extrato — os tipos existentes naquela seção. |

> [!INFO] Nesta versão ainda **não há busca por palavra dentro do texto** das
> matérias. A navegação é por data, seção, órgão e tipo de ato.

### 3. A matéria

Clicando numa matéria, você lê o inteiro teor, com a ementa, o órgão, a página e
o número da edição. Há também um link para a mesma matéria no portal oficial da
Imprensa Nacional.

## Busca

A tela **Busca** procura em todas as matérias já capturadas, de todas as datas
e seções.

### O que dá para digitar

| Você digita | O sistema entende |
|---|---|
| `fator acidentário` | Termo livre — acha variações e tolera pequenos erros de digitação |
| `19.630.496/0001-05` ou `19630496000105` | CNPJ, com ou sem pontuação — dá no mesmo |
| `15414.630210/2026-80` | Número de processo administrativo |

> [!INFO] Para CNPJ e número de processo a busca **não** aceita aproximação: um
> dígito diferente é outra empresa, outro processo. Para termos de texto,
> pequenos erros de digitação são tolerados.

### Buscar por cliente

A lista **"Buscar por cliente"**, ao lado do campo, traz os clientes cadastrados
no escritório. Você pode digitar o nome ou o CNPJ para achar na lista; escolher
um preenche a busca com o CNPJ dele. É o caminho mais rápido para responder
"meu cliente apareceu no Diário?".

### Refinar o resultado

À esquerda, cada filtro mostra **quantas matérias** restam se você marcá-lo.
Assim dá para ver que, dos 704 resultados, 201 são da Seção 1 — e chegar lá num
clique, sem redigitar nada.

Os filtros são: seção, órgão, tipo de ato e período. Marcar duas opções do mesmo
filtro mostra as duas; marcar filtros diferentes soma as condições.

Pode ordenar por **relevância** (padrão) ou por **mais recentes**.

> [!ALERTA] A busca só encontra o que já foi capturado. Se um período não foi
> baixado, ele não aparece — confira a cobertura na aba Captura.

### PDF assinado

Quando a edição tem o PDF assinado guardado, aparece o botão vermelho de PDF —
tanto na lista de edições quanto dentro da aba da seção. É o arquivo oficial da
Imprensa Nacional, com assinatura digital: o que você junta em processo.

> [!ALERTA] Os PDFs são guardados por tempo limitado (24 meses, por padrão), por
> causa do tamanho. O texto das matérias, esse **nunca é apagado**. Se o PDF de
> uma edição antiga não estiver mais disponível, o botão não aparece.

## Captura

Mostra a saúde da coleta. Serve para responder "o Diário de ontem entrou?".

- **Matérias no acervo** — total acumulado.
- **Cobertura por dia** — quantas seções e quantas matérias entraram em cada dia.
- **Execuções recentes** — cada rodada automática, com quantas matérias eram
  novas, quantas foram atualizadas e quantos erros houve.
- **Edições com falha** — o que não entrou, e por quê.

### Reprocessar uma data

Se um dia aparecer incompleto ou com falha, informe a data e clique em
:btn-primary[Reprocessar]. O sistema baixa aquele dia de novo.

> [!INFO] Reprocessar é sempre seguro: matéria que já existe é **atualizada**,
> nunca duplicada. Se a Imprensa Nacional republicou a edição com correções,
> reprocessar é justamente como trazer o texto corrigido.

## Perguntas frequentes

**Com que frequência o sistema busca o Diário?**
Três vezes por dia. A edição normal sai de manhã; as edições extras podem sair a
qualquer hora, por isso as buscas seguintes.

**Por que um dia aparece sem nenhuma matéria?**
Fins de semana e feriados não têm publicação. Nesse caso o dia consta como "não
publicado", o que é normal.

**Por que uma matéria de ontem mudou de texto?**
A Imprensa Nacional às vezes republica uma edição com correções. O sistema
reconfere os últimos dias automaticamente e traz a versão mais recente.

**Consigo ver edições de anos anteriores?**
Só a partir de quando o sistema começou a capturar. O portal da Imprensa
Nacional mantém apenas alguns meses disponíveis para download; edições mais
antigas que isso não podem mais ser resgatadas.
