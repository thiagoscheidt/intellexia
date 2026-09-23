# Base de Jurisprudência (submódulo do Painel de Processos)

Data: 22/09/2026 · Mockup aprovado: `static/mockups/base_jurisprudencia.html`

## Problema

Os advogados mantêm fora do sistema uma base de decisões FAP (sentenças,
acórdãos, embargos) classificadas por IA numa planilha Google — o "Banco Mestre
FAP", 515 decisões de 289 processos. Ela não conversa com o Painel de Processos:
na hora de gerar a impugnação, a jurisprudência citada vem de trechos garimpados
das peças-modelo, e não de decisões classificadas por tese e resultado.

## Escopo

1. **Importar** a planilha estruturada (formato Banco Mestre FAP), com tela de
   conferência antes de gravar.
2. **Enviar PDFs** de decisões: a IA (modelos do OpenRouter que já usamos, nunca
   Gemini direto) lê e grava no mesmo formato.
3. **Pesquisar**: busca com sinônimos, facetas com contagem, barra de "como tem
   decidido", **um card por processo** com a trilha sentença → acórdão →
   embargos.
4. **Correspondência de teses**: tabela curada entre as teses que aparecem nas
   decisões (texto livre) e o catálogo `JudicialLegalThesis` do painel.
5. **Na geração da impugnação**: o passo "Documentos e referências" ganha a
   jurisprudência a citar por tese, escolhida pelo advogado, e a escolha vai ao
   prompt.

Fora do escopo: o sistema Google (não é substituído nem sincronizado), o
recurso de apelação (fluxo separado em Ferramentas), Meilisearch/Qdrant para
esta base.

## Decisões

- **Teses: texto livre + correspondência curada.** A planilha tem 251 grafias
  (219 depois de acento/caixa) e 138 aparecem uma vez só; o catálogo do painel
  é mais fino ("ACIDENTE DE TRAJETO" ↔ Trajeto B91/B92/B93/B94). A decisão
  guarda a tese como veio; `jurisprudence_theses` é por escritório e liga N:N ao
  catálogo. Status: pendente / ligada / sem equivalente. Variantes se **mesclam**
  numa tese canônica (`merged_into_id`), e a grafia mesclada continua resolvendo
  para a canônica nas próximas importações. A IA sugere ligação e mescla; só a
  pessoa confirma. Nome idêntico ao do catálogo liga sozinho na importação.
- **Busca em SQL + Python, sem Meilisearch.** A escala é de centenas a poucos
  milhares de decisões por escritório; um índice seria mais uma coisa para
  reconstruir e sair de sincronia. A semântica é a da ferramenta que os
  advogados já usam: todos os termos (E), cada termo expandido pelos sinônimos,
  em qualquer campo. As facetas são disjuntivas (cada dimensão conta com os
  outros filtros aplicados).
- **Resultado e instância são valores fechados** (`favoravel`/`parcial`/
  `desfavoravel`; `sentenca`/`acordao`/`embargos`/`outra`). A planilha provou
  que pedir no prompt não basta (SENTENÇA e SENTENCA misturados).
- **Tribunal vira sigla + órgão + UF.** 155 textos → 8 siglas. A UF sai do
  número CNJ (TRF4: 70 PR, 71 RS, 72 SC; TRF3: 60 MS, 61 SP), do sufixo "/UF"
  ou, no PDF, da IA.
- **Chave de duplicata:** processo (só dígitos) + instância + data. Reimportar
  não duplica. No PDF, mesmo processo e instância com data diferente vai para
  "revisar" e quem decide é o advogado (manter, substituir, guardar as duas).
- **Correção manual sobrevive.** Campo editado à mão entra em
  `manual_fields_json`, e o reprocessamento não o sobrescreve.
- **Extração do PDF:** saída estruturada (Pydantic), temperatura 0, PDF inteiro
  pela file part do OpenRouter. Se a resposta vier cortada
  (`finish_reason=length`) ou não validar, uma nova tentativa sem raciocínio e
  com a ementa em resumo (o selo muda para "resumo — não é transcrição"). Os
  tokens de toda tentativa são contabilizados.
- **Fila de PDFs persistida** (`jurisprudence_uploads`), processada em thread
  (padrão do módulo), com "tentar de novo" na linha. `processing` parado há
  mais de 20 minutos é tratado como travado.
- **Na geração**, a escolha vai em `confirmed_documents_json.jurisprudence`
  (pares decisão + tese), sem coluna nova. A decisão desfavorável marcada vai
  ao prompt rotulada CONTRÁRIA, para ser rebatida e nunca citada a favor.
- **Tenant:** todas as tabelas têm `law_firm_id`. Permissão = módulo
  `process_panel` (mesmo padrão de `impugnacao_references`). Exclusão e criação
  de tese no catálogo são de admin.

## Dados

- `jurisprudence_decisions`: processo, processo_digits, tribunal, orgao_julgador,
  uf, relator, data_julgamento (Date), tipo_documento, classe_processual,
  resultado, motivo_resultado, parte_autora, vigencia_texto, vigencia_inicio/fim,
  ementa, ementa_modo, resumo_executivo, fundamentos/precedentes/argumentos
  acolhidos/rejeitados/palavras-chave (JSON), teses_brutas_json, search_text,
  source, drive_link, pdf_path, original_filename, extraction_model,
  manual_fields_json, created_by_id, timestamps.
- `jurisprudence_theses` (+ `jurisprudence_decision_theses`,
  `jurisprudence_thesis_catalog_links`).
- `jurisprudence_uploads`: a fila dos PDFs.

## Testes

`tests/test_jurisprudencia.py` (SQLite descartável): normalização, importação
da planilha real, dedup, correspondência e mescla, busca com sinônimos e
facetas, agrupamento por processo, sugestões para a geração, bloco do prompt e
rotas pelo test_client. O agente de extração é testado com LLM falso, e uma vez
de verdade contra PDFs de amostra quando houver.
