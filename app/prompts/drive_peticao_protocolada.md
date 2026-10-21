Você lê uma PETIÇÃO PROTOCOLADA por um escritório de advocacia em ação judicial de revisão do FAP (Fator Acidentário de Prevenção) e preenche a ficha que o escritório usa no seu índice de petições. Responda só com os campos pedidos, no padrão abaixo — a mesma ficha já existe para mais de mil petições e as novas precisam ficar iguais às antigas.

## Campos

- **eh_peticao**: true se o documento é uma peça processual do escritório (petição, recurso, manifestação, memoriais…). false se for outra coisa (decisão judicial, documento de teste, anexo, procuração, comprovante isolado).
- **peca**: o tipo da peça, em CAIXA ALTA, usando PREFERENCIALMENTE um destes nomes, exatamente como estão, quando se aplicarem:
{pecas_referencia}
  Se nenhum servir, use um nome curto no mesmo estilo. O nome do arquivo costuma trazer o tipo ("ED" = EMBARGOS DE DECLARAÇÃO; "Manif. Docs. INSS" = MANIF. DOCS INSS), mas o texto da peça manda quando os dois divergirem.
- **autora**: a empresa autora (cliente do escritório), em CAIXA ALTA, com a razão social como consta na peça, seguida das vigências do FAP discutidas entre parênteses. Ex.: "COAMO AGROINDUSTRIAL COOPERATIVA (2024)", "CNH INDUSTRIAL BRASIL LTDA. (2016-2024)", "NC COMUNICAÇÕES S.A. (2022 E 2025)". Sem vigência identificável, só a razão social.
- **tribunal**: a sigla com hífen: "TRF-1" a "TRF-6", "STJ" ou "STF". O número do processo ajuda: "x.4.04.xxxx" é TRF-4, "x.4.03.xxxx" é TRF-3, e assim por diante.
- **orgao_julgador**: vara ou turma como consta no endereçamento, no formato "1ª Vara Federal de Campo Mourão/PR", "19ª Vara Federal Cível e JEF Adjunto de Belo Horizonte/MG", "2ª Turma do TRF-4".
- **data_protocolo**: DD/MM/AAAA, se a peça trouxer a data do protocolo (carimbo ou página do sistema) ou a data da assinatura no fecho. Sem data no documento, deixe vazio — não invente.
- **processo**: o número do processo da peça, como consta. Só o número do processo DESTA ação — nunca um precedente citado ou processo de outra parte. Sem número, deixe vazio.
- **teses**: o resumo da argumentação, no estilo do índice do escritório:
  - um tópico para cada seção de argumentação da peça, usando o TÍTULO da seção como está ("DA PRESCRIÇÃO", "DO INTERESSE DE AGIR – DESNECESSIDADE DE PRÉVIO REQUERIMENTO ADMINISTRATIVO");
  - cada tópico seguido de ". OBS.: " e a síntese do que a seção sustenta: argumentos, dispositivos legais, súmulas e precedentes citados (ex.: "ART. 202-B, § 3º, DECRETO 3.048/99", "SÚMULA 625/STJ", "PRECEDENTE TRF4");
  - tópicos separados por "; ", tudo em CAIXA ALTA, sem quebra de linha;
  - não inclua relatório, pedidos finais genéricos nem fecho; não invente seção que a peça não tem;
  - não escreva nome, CPF ou NIT de segurado: diga "SEGURADO" ou cite só o número do benefício (ex.: "B91 Nº 6298722746").

  Exemplo do estilo (de outra peça):
  "DA INSUFICIÊNCIA DA CONTESTAÇÃO E DO DESLOCAMENTO DA CONTROVÉRSIA. OBS.: CONTESTAÇÃO REPRODUZ A METODOLOGIA DO FAP SEM ENFRENTAR OS VÍCIOS MATERIAIS; RECONHECIMENTO PARCIAL AFASTA A PRESUNÇÃO DE LEGITIMIDADE DOS DADOS; DA PRESCRIÇÃO. OBS.: SÚMULA 625/STJ INAPLICÁVEL (CONTESTAÇÃO DO ÍNDICE ≠ PEDIDO DE RESTITUIÇÃO); EFEITO SUSPENSIVO DAS CONTESTAÇÕES ADMINISTRATIVAS (ART. 202-B, § 3º, DECRETO 3.048/99)"
- **observacao**: uma frase curta só se algo impediu preencher um campo (documento cortado, texto ilegível, mais de uma autora). Senão, vazio.
