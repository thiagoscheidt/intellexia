# Marcadores de imagem no texto extraído das peças

**Data:** 2026-07-29 · **Módulos:** `document_processor_service`, ingestão de peças-modelo

## Problema

As impugnações trazem prints (FAP Web, CNIS, INFBEN, CAT) como prova das teses.
Para PDFs com camada de texto — o caso dessas peças — o pipeline usa o caminho
rápido do `pdfplumber`, que **ignora imagens por completo**: o texto pula da frase
de introdução ("...por decorrer de acidente de trajeto:") direto para o parágrafo
seguinte. O agente nunca sabe que ali havia prova visual, e o trecho indexado
perde justamente o elo entre a tese e o documento que a sustenta.

Medido no acervo local (38 peças já importadas): **1.673 ocorrências** de imagem,
das quais **1.180 descartadas como cromo do documento** (cabeçalho/rodapé/timbrado
repetido na mesma posição — ver filtro de estabilidade posicional) e **491 imagens
únicas reais** — mediana de 11 por peça, ~4.500 projetadas para as 350 peças.

## Decisões (aprovadas pelo usuário)

1. Implementar os dois níveis de uma vez (marcador + descrição por visão), porque
   reprocessar 350 peças duas vezes custa muito mais que a visão.
2. **Visão ligada por padrão**: `IMPUGNACAO_IMAGE_VISION_ENABLED` ausente = ligada.
   `false` desliga e mantém só o marcador.
3. Comportamento **desligado por padrão no processador compartilhado**: documentos
   de caso, base de conhecimento e petições não mudam. Só a ingestão de
   peças-modelo liga.

## Formato do marcador

Inserido inline, na posição do fluxo de texto onde a imagem aparece:

- com descrição: `[IMAGEM: print do extrato CNIS — vínculo de LEANDRO LOPES, DIB 12/2019, DCB 03/2020]`
- sem descrição (visão desligada/falhou): `[IMAGEM — print citado no parágrafo acima]`

O marcador é texto comum: flui para os chunks, para o embedding no Qdrant e para
o prompt do gerador, sem schema novo.

## Serviço novo: `app/services/pdf_image_annotator.py`

```python
annotate_pages_with_images(pdf_path, page_texts, *, describe=None,
                           law_firm_id=None) -> list[tuple[int, str]]
```

- `describe=None` → lê `IMPUGNACAO_IMAGE_VISION_ENABLED` (default **true**).
- Via PyMuPDF (já é dependência): posição de cada imagem e dos blocos de texto.
- **Filtro de ruído**: ignora imagens com área < `IMAGE_MIN_AREA` (15.000 pt²) —
  descarta logo, assinatura e linhas decorativas.
- **Dedup por `xref`** no documento inteiro: o cabeçalho repetido em várias páginas
  é descrito uma vez e a descrição é reusada.
- **Filtro de cromo com estabilidade posicional**: um xref repetido em páginas
  distintas só é descartado como cromo se também aparecer aproximadamente na MESMA
  posição em todas elas (tolerância ~12pt em x0/y0) — cabeçalho/rodapé repete no
  mesmo lugar; a mesma prova (ex.: print do CNIS) colada sob teses diferentes no
  meio do texto varia de posição e não é descartada, mesmo repetindo em várias
  páginas. Foi esse filtro que levou 1.673 ocorrências → 1.180 cromo → 491 imagens
  únicas reais.
- **Ancoragem**: o marcador entra logo após o bloco de texto imediatamente acima
  da imagem — casando o fim desse bloco (normalizado) dentro do texto da página.
  Sem casamento, o marcador vai para o fim da página. Nunca some, nunca entra em
  posição errada em silêncio.
- **Teto por documento**: `IMAGE_MAX_DESCRIBED_PER_DOC` (default 40) — acima
  disso as imagens ainda recebem marcador, mas sem descrição.
- **Visão**: renderiza o recorte em PNG (~150 DPI), envia em lotes
  (`IMAGE_VISION_BATCH_SIZE`, default 5) ao modelo barato de visão
  (`IMPUGNACAO_IMAGE_VISION_MODEL`, default `gpt-4o-mini`), pedindo **uma linha
  por imagem** em português: que tela/documento é e quais dados aparecem. Uso
  registrado no `TokenUsageService`, como todo agente do projeto.
- **Degradação graciosa**: qualquer falha (PyMuPDF, render, visão) → mantém o
  marcador sem descrição e a ingestão segue. Nunca levanta para o chamador.

## Integração

- `DocumentProcessorService.process_document(file_path, *, annotate_images=False)`
  — parâmetro novo, **default False** (nada muda para os outros módulos). Quando
  True e o caminho rápido do pdfplumber for usado, anota `page_texts` **antes** de
  `_build_pages_with_sections`, para os marcadores fluírem para `chunks_with_pages`
  e `full_text`.
- `ImpugnacaoReferenceIngestor._process_document` passa `annotate_images=True`.
- Caminho Docling (PDF escaneado): a conversão de `<!-- image -->` para o marcador
  sem descrição só vale no **fallback** `_split_by_headings` (usado quando não há
  `chunks_with_pages` nenhum). O caminho Docling **por página**
  (`DocumentProcessorService.process_document`, via `doc.iterate_items()`) descarta
  itens sem `.text` — que é o caso dos itens de imagem — antes de montar
  `page_texts`/`chunks_with_pages`; por isso um PDF escaneado processado pelo
  caminho normal (com segmentação por página) segue **sem** marcador de imagem nos
  chunks por página, mesmo com este recurso.

## Fora de escopo

Salvar as imagens; descrever imagens em documentos de caso/KB; o gerador emitir
marcadores de prova no documento produzido (`[INSERIR PRINT DE ...]`) — passo
natural seguinte, destravado por este.

## Testes

- Ancoragem: dado texto de página e uma âncora conhecida, o marcador entra logo
  após ela; âncora ausente → marcador no fim da página.
- Filtro de área e dedup por `xref` (sem PDF real, com estruturas simuladas).
- Leitura do env: ausente → ligada; `false`/`0`/`no` → desligada.
- Verificação manual sobre uma peça real do acervo, comparando o texto extraído
  antes e depois.
