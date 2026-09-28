# Manual — Base de Conhecimento do Painel de Processos

A **Base de Conhecimento** reúne, num só lugar, o material que a IA usa para
montar as peças do escritório:

- **Jurisprudência** — sentenças, acórdãos e embargos de FAP, classificados por
  tese e resultado. Na peça, viram **precedente citado**.
- **Peças-modelo** — impugnações do próprio escritório que servem de molde. Na
  peça, dão a **estrutura e o estilo**.

Fica no menu **Painel de Processos › Base de Conhecimento**, com três abas no
topo: **Visão geral**, **Jurisprudência** e **Peças-modelo**.

> [!INFO] Este item não é o mesmo que o grupo **Base de Conhecimento** do menu
> principal (chat e documentos do escritório). Aqui ficam só as decisões e as
> peças-modelo usadas na geração das peças.

## Visão geral

A primeira aba mostra as duas bases lado a lado e o que precisa de atenção.

- **Busca nas duas bases** — um campo só. O resultado vem em duas colunas: as
  decisões da jurisprudência de um lado e os trechos das peças-modelo do outro,
  com o termo grifado.
- **Cards das bases** — quantas decisões e processos, quanto delas é favorável
  ou parcial, quantas peças-modelo e de quais TRFs.
- **Precisa de atenção** — só aparece o que tem pendência: teses sem ligação com
  o catálogo, PDFs com falha na leitura, decisões aguardando você decidir,
  peças-modelo com falha na indexação. Quando zera, some.
- **Cobertura por tese** — para cada tese do catálogo do escritório, se existe
  peça-modelo para dar a estrutura e decisão favorável para citar.

| Situação | O que significa |
|---|---|
| coberta | Há peça-modelo e decisão favorável ou parcial |
| sem peça-modelo | Há decisões, mas nenhuma peça-modelo da tese |
| sem decisão | Há peça-modelo, mas nenhuma decisão ligada à tese |
| descoberta | Nem peça-modelo, nem decisão favorável |
| maioria contra | A partir de 3 decisões, mais da metade foi desfavorável |

> [!ALERTA] A coluna **Decisões** só conta as teses que já foram ligadas ao
> catálogo na **Correspondência de teses** (veja abaixo). Enquanto houver teses
> pendentes, "sem decisão" pode ser só ligação faltando — a tela avisa.

## Jurisprudência

### Pesquisar

O campo de busca procura em todos os campos da decisão: resumo, motivo do
resultado, ementa, teses, fundamentos, precedentes, partes e relator.

- **Todas as palavras precisam aparecer.** "trajeto prorrogação" traz só as
  decisões que falam das duas coisas.
- **Sinônimos valem**: *trajeto* também acha *percurso*, *in itinere* e
  *casa-trabalho*; *NTEP* acha *nexo técnico epidemiológico*.
- **Aspas juntam uma expressão**: `"erro no custo"`.
- **Número do processo** vale com ou sem pontuação.
- **No inteiro teor**: marque essa opção para procurar no texto completo das
  decisões e ver o trecho da página onde o termo aparece. Só entram as decisões
  que têm o PDF no sistema — a tela mostra quantas são.

### Filtros

Na lateral, cada filtro mostra quantas decisões tem, já considerando os outros
filtros marcados.

- **Tese do catálogo** — a tese padronizada do escritório. É a que a geração da
  peça usa.
- **Tese original** — a tese **como veio escrita na decisão**. Uma decisão pode
  ter várias. Grafias que só diferem em acento ou maiúsculas contam juntas
  ("PRORROGAÇÃO DE BENEFÍCIO" e "PRORROGACAO DE BENEFICIO"); ideias parecidas
  com palavras diferentes continuam separadas. Como a lista é longa, há um campo
  para procurar dentro dela.
- **Resultado** (sempre do ponto de vista da empresa), **Tribunal**,
  **Instância**, **UF de origem**, **Vigência FAP** e **Julgada entre**.

> [!INFO] O filtro de **vigência** pega a decisão cujo período inclui o ano: uma
> decisão sobre "2017 a 2021" aparece quando você escolhe 2019.

### O resultado

- **Como tem decidido** — a barra no topo mostra quantas decisões do recorte
  foram favoráveis, parciais e desfavoráveis. Clicar numa faixa filtra.
- **Um cartão por processo** — sentença, acórdão e embargos do mesmo processo
  aparecem juntos, na ordem. Instância que não está na base aparece como
  lacuna.
- **Virou no acórdão** — selo do processo em que a sentença foi pior para a
  empresa e o acórdão foi melhor. É o precedente mais forte de citar.
- **Copiar citação** — a referência pronta para colar na peça.
- Clicar numa **tese** do cartão filtra por ela.

Prefere uma lista simples, uma linha por decisão? Use :btn-outline-secondary[Por decisão]
no topo da lista.

### A página da decisão

Abas **Resumo** (por que o resultado e a história do caso), **Ementa**,
**Argumentos** (os da empresa que foram acolhidos e os rejeitados),
**Fundamentos** do julgador, **Precedentes** e **PDF**. Ao lado ficam o
resultado, tribunal, relator, data, vigência, as teses originais e as do
catálogo, a **citação pronta** e as **decisões parecidas** — as que discutem o
mesmo ponto, mesmo com outras palavras.

> [!ALERTA] Quando a IA não consegue transcrever a ementa, ela guarda um
> **resumo** e a tela mostra o selo "resumo — não é transcrição". Não cite esse
> texto entre aspas como se fosse a ementa.

- **Precedentes** que também estão na base viram link para a decisão.
- :btn-outline-secondary[Corrigir dados] — corrija o que a IA leu errado. O
  campo corrigido fica protegido: se a decisão for lida de novo pela IA, a sua
  correção não é sobrescrita.
- :btn-outline-secondary[Reprocessar com IA] — lê o PDF de novo. Só funciona com
  o PDF no sistema.
- **Anexar PDF** (aba PDF) — para decisões que vieram da planilha sem o arquivo.

### Trazer decisões para a base

Há duas portas, e as duas gravam no mesmo formato.

**Importar planilha** — para a planilha que o escritório já mantinha (formato
Banco Mestre FAP). Você envia o `.xlsx` e, **antes de gravar qualquer coisa**,
vê a conferência: quantas decisões são novas, quantas já existem, o que será
padronizado (grafias de tribunal, instância, resultado e tese) e o que entra com
aviso (sem vigência, sem data). Reimportar a mesma planilha não duplica nada.

**Enviar decisões** — arraste os PDFs das sentenças, acórdãos e embargos. A IA
lê cada um em segundo plano (pode fechar a tela) e classifica processo,
tribunal, resultado, teses, fundamentos e argumentos. A fila mostra a situação
de cada arquivo:

| Situação | O que fazer |
|---|---|
| concluída | Nada — a decisão já está na base |
| revisar | Já existe uma decisão do mesmo processo e instância. Escolha :btn-outline-secondary[manter a da base], :btn-outline-warning[substituir] ou :btn-outline-primary[guardar as duas] |
| falhou | O motivo aparece na linha. Use :btn-outline-primary[tentar de novo] |

> [!INFO] **PDFs das decisões importadas da planilha**: na mesma tela, em
> **Anexar os PDFs das decisões importadas**, envie os PDFs baixados da pasta do
> Drive (até 300 por vez) — cada arquivo é ligado à sua decisão pelo nome que a
> planilha registrou; arquivo sem decisão correspondente é avisado, nunca
> anexado a outra. O botão :btn-outline-secondary[Buscar PDFs no Drive]
> tenta baixar direto, mas só funciona se a pasta estiver compartilhada por link.

### Correspondência de teses

As decisões trazem as teses do jeito que o julgador (ou a IA) escreveu; o
catálogo do escritório é mais detalhado — "ACIDENTE DE TRAJETO" corresponde a
Trajeto B91, B92, B93 e B94. A tela **Teses** (botão no topo da Jurisprudência)
liga uma coisa à outra:

- :btn-success[Aceitar] — aceita a sugestão da IA. Use
  :btn-outline-primary[Sugerir com IA para as pendentes] para a IA analisar as
  pendentes; **nada é ligado sem o seu clique**.
- **Ligar ao catálogo** — escolha uma ou mais teses do catálogo.
- **Mesclar em outra tese** — para grafias diferentes da mesma ideia. A grafia
  mesclada continua levando à mesma tese nas próximas importações, e a mescla
  pode ser desfeita.
- **Sem equivalente** — para temas processuais (honorários, custas) que não são
  tese de FAP.
- **Criar no catálogo** — cria a tese no catálogo do painel (só administradores).

> [!INFO] A correspondência muda a **tese do catálogo** — e com ela a cobertura
> por tese e as sugestões na geração da peça. O filtro de **tese original** não
> muda: ele mostra sempre o que está escrito na decisão.

### Uso na geração da impugnação

Ao gerar uma impugnação no processo, o passo **Documentos** mostra, para cada
tese dos benefícios selecionados, a **Jurisprudência a citar**: primeiro as
favoráveis, do mesmo TRF, de instância mais alta e mais recentes. As três
primeiras vêm marcadas; desmarque ou busque outra na base. Uma decisão
**desfavorável** marcada vai para a IA como **contrária** — para a peça
antecipar e rebater o entendimento, nunca para citar a favor.

Depois de gerada, as notas internas da peça avisam se alguma decisão marcada
não foi citada no texto.

## Peças-modelo

A aba **Peças-modelo** lista as impugnações do escritório usadas como molde,
com TRF, vara, teses, quantidade de trechos e situação da indexação. Por ela
você cadastra uma peça nova, importa várias de uma planilha, busca nos trechos
e arquiva o que não deve mais ser usado.

## Pergunte pelo :claude: Claude (MCP)

Com o IntellexIA conectado ao seu assistente de IA, dá para consultar a
jurisprudência conversando — "qual a chance da tese de trajeto no TRF4?",
"me traz as favoráveis de 2025 com a citação", "exporta tudo do TRF3 em
planilha". As ferramentas estão no manual **Conectar sua IA (MCP)**, seção
Base de Jurisprudência.

## Resetar a base

No fim da tela da Jurisprudência, administradores podem apagar toda a base do
escritório — decisões (com as correções feitas à mão), teses e correspondência,
PDFs, fila de leitura e índice — para recomeçar uma importação. O catálogo de
teses do painel e as peças já geradas não são tocados.

> [!ALERTA] Não dá para desfazer. A confirmação pede que você digite a palavra
> indicada na janela.
