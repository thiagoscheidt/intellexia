# Marcadores de imagem no texto extraído das peças

**Data:** 2026-07-29 · **Módulos:** `document_processor_service`, ingestão de peças-modelo

## Problema

As impugnações trazem prints (FAP Web, CNIS, INFBEN, CAT) como prova das teses.
Para PDFs com camada de texto — o caso dessas peças — o pipeline usa o caminho
rápido do `pdfplumber`, que **ignora imagens por completo**: o texto pula da frase
de introdução ("...por decorrer de acidente de trajeto:") direto para o parágrafo
seguinte. O agente nunca sabe que ali havia prova visual, e o trecho indexado
perde justamente o elo entre a tese e o documento que a sustenta.

Medido no acervo local (38 peças já importadas): **1.674 imagens**, **561 únicas**
após deduplicar repetições de cabeçalho — ~15 únicas por peça, ~5.200 projetadas
para as 350 peças.

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
- **Dedup por `xref`** no documento inteiro: o cabeçalho repetido em 20 páginas é
  descrito uma vez e a descrição é reusada (foi o que levou 1.674 → 561).
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
- Caminho Docling (PDF escaneado): hoje o ingestor **descarta** as linhas
  `<!-- image -->`; passam a virar o marcador sem descrição.

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
