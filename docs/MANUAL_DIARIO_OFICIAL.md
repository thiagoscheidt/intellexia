# Manual — Diário Oficial

A tela **Diário Oficial** guarda, dentro do IntellexIA, as edições do Diário
Oficial da União publicadas pela Imprensa Nacional. Todo dia o sistema baixa as
edições, separa cada matéria publicada e deixa tudo pronto para consulta.

> [!DOU] O conteúdo vem do portal de dados abertos da Imprensa Nacional
> (INLABS), em formato XML. Como o próprio portal avisa, esse formato **não
> substitui a versão certificada** — para uso oficial, baixe o PDF assinado da
> edição, disponível na própria tela.

## Acervo

É a tela principal. Você escolhe uma **data** e o sistema mostra as seções
capturadas naquele dia:

- **Seção 1** — atos normativos (portarias, resoluções, decretos).
- **Seção 2** — pessoal do serviço público federal.
- **Seção 3** — contratos, licitações e avisos.
- **Edições Extras** — publicações fora da edição normal do dia.

Abaixo das seções vem a lista de matérias. Clique em qualquer uma para ler o
inteiro teor.

### Filtros

| Filtro | Para que serve |
|---|---|
| Data | O dia da publicação. A lista começa sempre no dia mais recente capturado. |
| Seção | Restringe a uma seção do Diário. |
| Tipo de ato | Portaria, Resolução, Aviso, Extrato — os tipos existentes naquele dia. |
| Órgão | Busca por parte do nome do órgão. Ex.: digitar `Previdência` traz tudo do Ministério da Previdência Social. |

> [!INFO] Nesta versão ainda **não há busca por palavra dentro do texto** das
> matérias. A navegação é por data, seção, órgão e tipo de ato.

### PDF assinado

Quando a edição tem o PDF assinado guardado, aparece o botão vermelho de PDF ao
lado da seção. É o arquivo oficial da Imprensa Nacional, com assinatura digital
— o que você junta em processo.

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
