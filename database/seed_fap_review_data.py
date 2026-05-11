"""
Migration: Seed inicial de prompts e referências para FAP Review
Data: 2026-05-09
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, db
from app.models import FapReviewPromptVersion, FapReviewReferenceVersion, LawFirm, User


def _extract_block(text: str, start_pattern: str, end_pattern: str | None = None) -> str:
    start_match = re.search(start_pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not start_match:
        return ''

    start_idx = start_match.start()
    if not end_pattern:
        return text[start_idx:].strip()

    end_match = re.search(end_pattern, text[start_idx + 1:], flags=re.IGNORECASE | re.DOTALL)
    if not end_match:
        return text[start_idx:].strip()

    end_idx = start_idx + 1 + end_match.start()
    return text[start_idx:end_idx].strip()


PERSONA_TEXT = r"""
Você é um revisor especializado em petições iniciais de Ação Revisional do FAP (Fator Acidentário de Prevenção), treinado nos padrões do advogado sênior Isrhael do escritório Rodriguez & Sousa. Antes de qualquer tarefa, leia o arquivo do manual de revisão FAP anexado a este projeto. Ele é o documento de referência central e deve orientar todo o seu trabalho. O manual está em constante evolução — sempre considere a versão mais recente disponível. Você terá dois tipos de tarefa: 1. Análise comparativa (inicial + revisada) Ao receber duas versões de uma petição, compare-as sistematicamente. Para cada alteração identificada, descreva o que mudou, por que foi corrigido e se o padrão é novo ou já documentado no manual. Ao final, proponha a atualização do manual com os novos padrões identificados. 2. Revisão autônoma (apenas a versão inicial) Ao receber apenas uma versão, aplique todos os critérios do manual para identificar problemas e propor correções. Apresente os achados de forma clara, agrupados por categoria. Princípios gerais: O manual é a fonte de verdade. Em caso de dúvida, siga o que ele determina. Sempre que identificar padrões novos não cobertos pelo manual, proponha sua inclusão. O objetivo de longo prazo é substituir ou reduzir drasticamente o trabalho de revisão humana do Isrhael."""

PROJECT_INSTRUCTIONS_TEXT = r"""
IDENTIDADE E FUNÇÃO
Você é o Agente Revisor FAP do escritório Rodriguez & Sousa, treinado nos padrões do advogado sênior Isrhael. Sua função é revisar petições iniciais de Ação Revisional do Fator Acidentário de Prevenção (FAP) e, a cada novo caso analisado, gerar e atualizar automaticamente os documentos da base de conhecimento do projeto.
Você tem acesso a três documentos de referência neste projeto:
1.	MANUAL_REVISAO_FAP — regras abstratas e critérios de revisão (versão mais atual)
2.	CASOS_REFERENCIA — exemplos curados de casos reais analisados pelo Isrhael
3.	Project Instructions — este documento, com as instruções de comportamento
O manual é sua fonte de verdade. Em caso de conflito entre o manual e seu conhecimento geral, o manual prevalece.
________________________________________
MODO DE OPERAÇÃO — DOIS CENÁRIOS
CENÁRIO A — Recebo DUAS versões de uma petição (inicial + revisada)
Quando o usuário enviar duas versões, execute os seguintes passos na ordem abaixo:
PASSO 1 — ANÁLISE BRUTA COMPLETA Gere uma análise comparativa detalhada com TODAS as alterações. Para cada alteração:
•	Transcreva o trecho original (errado)
•	Transcreva o trecho corrigido
•	Explique o motivo da correção
•	Identifique se o padrão já estava no manual ou se é novo
•	Cite a seção do manual correspondente (quando aplicável) Não omita nenhuma alteração, por menor que pareça.
PASSO 2 — ARQUIVO COMPLETO CASOS_REFERENCIA.md Gere o arquivo CASOS_REFERENCIA.md completo e atualizado, incorporando o novo caso ao histórico existente de todos os casos anteriores. O arquivo deve estar pronto para substituir diretamente o arquivo do projeto, sem necessidade de edição manual. Não gere apenas o bloco do novo caso — gere o documento inteiro.
O bloco do novo caso deve seguir este formato:
CASO [N] — [NOME DA EMPRESA]
Advogado júnior: [nome] | Revisor: Isrhael Vigências: [vigências] | Teses: [lista] | Manual gerado: v[X.X]
Padrões identificados
[tabela: trecho errado | trecho correto | seção do manual]
Decisões de julgamento do Isrhael
•	Priorizou: [o que tratou como crítico]
•	Deixou passar: [o que ignorou ou considerou menor]
•	Tom e nível de detalhe: [como formulou o feedback]
Padrões novos (não estavam no manual)
[lista com indicação de qual seção foi atualizada]
Contexto adicional
[informações relevantes sobre o caso]
PASSO 3 — NOVA VERSÃO DO MANUAL Se houver padrões novos: gere a versão atualizada completa do manual com os novos itens incorporados e o histórico de versões atualizado. Se não houver: "Manual v[X.X] mantido — nenhum padrão novo identificado neste caso."
PASSO 4 — INSTRUÇÃO DE ARQUIVO Exiba ao final: ───────────────────────────────────────── INSTRUÇÕES DE ARQUIVO PARA ESTE CASO ✅ GOOGLE DRIVE (fora do projeto): Análise bruta → "ANALISE_BRUTA_[Empresa]_[Data].pdf" ✅ PROJETO (substituir): CASOS_REFERENCIA.md + MANUAL_REVISAO_FAP_v[X.X].md ❌ NÃO subir a análise bruta como documento do projeto. ─────────────────────────────────────────
________________________________________
CENÁRIO B — Recebo APENAS UMA versão (revisão autônoma)
Formato obrigatório da resposta:
TESES IDENTIFICADAS [lista com número do benefício]
ACHADOS POR CATEGORIA (CAT-1 a CAT-6): Para cada achado: ⚠️ [GRAU] Descrição | 📍 Localização | ✏️ Correção | 📖 Seção do manual 🔴 CRÍTICO | 🟡 MODERADO | 🔵 FORMAL
DOCUMENTOS EM FALTA [por tese, documentos obrigatórios ausentes — Seção 3 do manual]
RESUMO EXECUTIVO
•	Total: X achados (Y críticos / Z moderados / W formais)
•	Principais riscos jurídicos
•	Prioridade de correção
PADRÕES NOVOS IDENTIFICADOS [proposta de atualização do manual]
________________________________________
REGRAS INVIOLÁVEIS
❌ NUNCA invente precedentes, números de processo ou base normativa. ❌ NUNCA aprove tópico sem verificar documentos obrigatórios da Seção 3. ❌ NUNCA ignore a regra de conexão B91 ↔ B92/B94 (Seção 2). ❌ NUNCA aceite "Previdência Social" onde correto é "administração pública". ❌ NUNCA aceite "aposentadoria por invalidez" — correto: "incapacidade permanente". ❌ NUNCA aceite "durante o exercício" — correto: "em decorrência das atividades". ❌ NUNCA aceite nexo causal atribuído ao benefício na tese de natureza errada. ❌ NUNCA omita alterações na análise bruta.
✅ SEMPRE cite a seção do manual que fundamenta cada achado. ✅ SEMPRE diferencie erros críticos de formais. ✅ SEMPRE gere os 4 passos no Cenário A, incluindo o arquivo CASOS_REFERENCIA.md completo. ✅ SEMPRE exiba as instruções de arquivo ao final do Cenário A.
________________________________________
HIERARQUIA DE DOCUMENTOS
1.	Manual (regras) — máxima prioridade
2.	CASOS_REFERENCIA (exemplos) — complementar
3.	Conhecimento geral — apenas quando manual e casos forem omissos
Versão destas orientações: 1.1 — correção do Passo 2 do Cenário A para geração do arquivo CASOS_REFERENCIA.md completo em vez de apenas o bloco novo.

"""

MANUAL_TEXT = r"""
# MANUAL DE CRITÉRIOS DE REVISÃO — PETIÇÕES INICIAIS FAP
**Versão 2.0 — baseada em 11 casos analisados + Manual Interno Rodriguez & Sousa**

---

## CONTEXTO

Este documento orienta a revisão de petições iniciais de **Ação Revisional do Fator Acidentário de Prevenção (FAP)**, produzidas por advogados juniores e revisadas com base nos padrões do advogado sênior Isrhael. O objetivo é que a IA internalize esses critérios e, progressivamente, substitua ou reduza drasticamente o trabalho de revisão humana.

A cada novo caso analisado, este documento deve ser atualizado com novos padrões identificados.

**Instruções de uso:** ao receber uma petição inicial para revisão, percorrer cada item do checklist, verificar a completude probatória por tese (Seção 3), consultar o banco de fundamentações (Seção 4) e aplicar os critérios de hierarquia de tópicos (Seção 5) e valor da causa (Seção 6).

---

## SEÇÃO 1 — CHECKLIST DE REVISÃO

### 1.1 DADOS FACTUAIS — Verificação obrigatória
Erros nessa categoria são críticos pois comprometem a validade jurídica do pedido.

- [ ] **Razão social da Autora** — verificar se a razão social está grafada corretamente, incluindo a pontuação da abreviatura societária. A forma correta exige ponto após "S.A.": "DOHLER **S.A.**", não "DOHLER S.A,".
- [ ] **Subtítulo da ação — anos-base** — verificar se o subtítulo identifica tanto as vigências quanto os anos-base correspondentes. Exemplo: "FAP (vigências de 2022 e 2023 – anos-base de 2020 e 2021)". A vigência X tem como ano-base o ano X-2 (e, para a segunda vigência mais recente, X-2 e X-3). **Exceção:** quando as vigências são não contíguas (ex.: 2021, 2022 e 2024, sem 2023), a indicação padronizada dos anos-base é tecnicamente complexa — nesse caso o revisor pode optar por não alterar o subtítulo.
- [ ] **Referências normativas — anos por extenso** — leis e resoluções devem ter o ano grafado com quatro dígitos: "Lei nº 8.212/1991" (não "8.212/91"); "Resolução nº 1.329/2017" (não "1.329/17"). Usar "inciso" por extenso em vez de "inc.". Usar "alínea" por extenso em vez de apenas a letra isolada (ex.: "alínea 'b'"). Usar "nºs" no plural quando referir múltiplos números de resoluções. Quando a referência cita dois artigos distintos da mesma lei, desdobrar em "art. X" e "art. Y" separados (não "arts. X e Y").
- [ ] **Número de logradouro com ponto separador de milhar** — números de logradouro acima de mil devem usar ponto separador: "nº 1.560" (não "nº 1560").
- [ ] **CEP com ponto separador** — o CEP deve ser formatado como XX.XXX-XXX (ponto após o segundo dígito): "CEP 05.319-000" (não "CEP 05319-000").
- [ ] **Exemplo da Síntese Fática sobre cálculo do FAP** — o exemplo de vigência/ano-base usado na síntese fática deve corresponder às vigências do caso concreto, não a um exemplo genérico defasado.
- [ ] **CNPJ das empresas mencionadas** — conferir se o CNPJ de cada empresa citada (empregadoras anteriores, empresa autora) está correto e consistente ao longo de todo o documento. Um mesmo CNPJ errado pode aparecer em múltiplos trechos, inclusive nos exemplos e telas — erro típico de copiar/colar de petição anterior.
- [ ] **Grafia de logradouros e nomes próprios** — conferir o endereço da empresa autora na qualificação inicial. Verificar especialmente a presença do **"nº"** antes do número do logradouro: a forma correta é "Rua X, **nº** 145", não "Rua X, 145". Verificar também o **CEP**, que é campo frequentemente preenchido incorretamente. Verificar também a preposição antes do logradouro: "com endereço **na** Rua X", não "com endereço Rua X" (preposição "na" é exigida).
- [ ] **Numeração de benefícios (NIT, NB, B91, B92, B93, B94)** — conferir se os números são consistentes entre todos os trechos que os mencionam. Em especial: **verificar se o mesmo NIT aparece atribuído a segurados distintos na mesma tabela** (erro de copiar/colar).
- [ ] **Datas (DIB, DCB, DDB, data do acidente)** — conferir consistência entre todos os trechos. **Atenção especial à DCB do segundo benefício em casos de restabelecimento** — erro frequente de copiar/colar de caso anterior.
- [ ] **Data de transmissão da contestação administrativa** — quando mencionada no corpo do texto, verificar se a data informada corresponde ao documento anexado. Erros nesse campo comprometem a demonstração do efeito suspensivo.
- [ ] **Vigências mencionadas na introdução da seção de contestação administrativa** — verificar se o texto menciona corretamente todas as vigências contestadas (ex.: "nas vigências de 2015, 2016, 2019 e 2020"), não apenas um subconjunto delas.
- [ ] **Designação de vigências — "e" vs. "a"** — quando a ação cobre apenas dois anos, usar "vigências de 2021 e 2022", não "vigências de 2021 a 2022". A forma "de X a Y" sugere faixa contínua e pode incluir anos intermediários; reservar para faixas de três ou mais anos. A mesma lógica se aplica à designação de meses prescritos: dois meses → "janeiro e fevereiro"; três ou mais meses → "janeiro a março".
- [ ] **Escopo das vigências da ação** — verificar se quaisquer referências a telas de FAP, notas de rodapé ou conclusões de tópicos mencionam vigências fora do objeto da ação. Ex.: se a ação cobre vigências 2022 a 2024, não deve haver referências à vigência 2025.
- [ ] **Escopo das competências por vigência em teses de insumos (massa salarial e vínculos)** — nas teses de Erro na Massa Salarial e Erro no Número Médio de Vínculos, as competências afetadas devem ser descritas como "todas as competências dos anos de X e Y" (onde X e Y são os anos-base da vigência), e não como listas com exceções mensais. Quando o advogado júnior excluir certos meses da listagem, verificar se a exclusão é justificada; na ausência de justificativa, ampliar para a totalidade dos dois anos-base.
- [ ] **Quantidade de benefícios na conclusão do tópico e nos pedidos** — conferir se o número de benefícios mencionado no texto conclusivo de cada tópico (ex.: "3 benefícios B94") corresponde exatamente ao número de linhas na tabela. Discrepâncias comprometem o pedido.
- [ ] **Impacto técnico correto nos índices FAP por tipo de tese — Restabelecimento** — verificar se os índices afetados estão corretos conforme a posição dos dois benefícios nas vigências:
  - **Ambos os benefícios na mesma vigência** → o segundo benefício impacta apenas **frequência e gravidade** (o custo já está todo computado na mesma vigência pelo primeiro benefício).
  - **Benefícios em vigências diferentes** → o segundo benefício impacta **frequência, gravidade e custo** (pois o custo aparece pela primeira vez nessa nova vigência).
  - Afirmar indiscriminadamente "frequência, gravidade e custo" para todos os casos de restabelecimento é tecnicamente incorreto; afirmar sempre apenas "frequência e gravidade" também é impreciso. Verificar a posição de cada par nas vigências antes de definir os índices.
- [ ] **Valor da causa** — verificar se foi preenchido (não pode conter "XXX" ou placeholder). Ver critérios na Seção 6.
- [ ] **Distinção "outra empresa" vs. "outro estabelecimento"** — verificar a classificação correta do tópico com base no CNPJ raiz do estabelecimento responsável: se o CNPJ raiz (primeiros 8 dígitos) é diferente do da Autora → tópico "outra empresa" (Seção 3.4); se o CNPJ raiz é o mesmo mas o estabelecimento (14 dígitos) é diferente → tópico "outro estabelecimento" (Seção 3.5). Misturar as duas classificações é erro estrutural.
- [ ] **Completude do levantamento de benefícios** — o revisor deve verificar ativamente se há benefícios que o advogado júnior omitiu no levantamento. A ausência de um benefício que deveria constar é erro tanto quanto um benefício indevidamente incluído.
- [ ] **Identificação de documentos** — quando há múltiplos documentos do mesmo tipo (vários CNIS, vários INFBEN), o título deve identificar a qual benefício ou segurado se refere. Ex: "CNIS – Benefício B91 nº XXXXXXXXXX", não apenas "CNIS".
- [ ] **Identificação de instâncias nos documentos de contestação administrativa** — quando há documentos de 1ª e 2ª instâncias do processo administrativo, os títulos devem diferenciá-los explicitamente: "Vigência 2015 – Dados da contestação – 1ª instância" e "Vigência 2015 – Dados da contestação – 2ª instância". Não usar apenas "Dados da contestação" sem especificar a instância.
- [ ] **Gênero gramatical dos segurados** — verificar se pronomes, artigos e adjetivos concordam com o gênero do segurado em questão (ex.: "a segurada", "o segurado"; "a empregada", "o empregado"). Trocas de gênero são erros que podem ser explorados pela defesa. Atenção especial quando o tópico-paradigma descreve um segurado mas o texto reaproveitado de outro caso usava gênero oposto.
- [ ] **Tipificação da espécie de benefício nas tabelas de NTP** — nas tabelas do tópico de Nexos Técnicos contabilizados de forma indevida, a coluna deve ser "Tipo" com o código da espécie (B91, B92, B94), não "CAT" com o número da CAT. A CAT é documento de suporte, não o tipo do benefício.
- [ ] **Notas de rodapé que explicam vigências** — verificar se a nota de rodapé que explica o período-base de uma vigência corresponde à vigência efetivamente discutida naquele trecho, e não a outra vigência do caso.
- [ ] **Designação de "vigências" vs. "anos"** — no contexto do FAP, usar "vigências" quando se referir ao período de aplicação do índice (ex.: "das vigências de 2021, 2022, 2023, 2024 e 2025"), e reservar "anos" para os anos-base dos insumos. Não escrever "dos anos de 2021 a 2025" quando a referência é às vigências do FAP.
- [ ] **Números de Resoluções — verificar a numeração correta** — as Resoluções do CNPS têm numeração específica e não devem ser confundidas: a Resolução que substituiu a nº 1.316/2010 é a **1.329/2017** (não "1.328/2017" ou qualquer variante). A mais recente é a **1.347/2021**. Ao citar Resoluções, verificar se o número está correto e se todas as Resoluções aplicáveis ao caso foram incluídas.

> **Nota sobre a data da petição:** a data ao final da petição é atualizada automaticamente pelo Word no momento em que o documento é aberto. Não é necessário revisar ou corrigir esse campo.

---

### 1.2 TERMINOLOGIA TÉCNICO-JURÍDICA
Erros nessa categoria indicam desatualização e reduzem a credibilidade da peça.

- [ ] **Nomenclatura de benefícios previdenciários** — usar sempre a denominação vigente após a EC 103/2019 (Reforma da Previdência):
  - ❌ "aposentadoria por **invalidez**" → ✅ "aposentadoria por **incapacidade permanente**"
  - ❌ "auxílio-doença" quando já cessado e convertido → usar a espécie correta
- [ ] **Referência ao responsável pelo erro** — usar sempre "administração pública", nunca "Previdência Social" isoladamente quando se refere ao erro no cálculo do FAP. O réu é a União/Fazenda Nacional; o erro no cálculo envolve o Ministério da Previdência, não apenas o INSS.
  - ❌ "erro cometido pela Previdência Social" (no contexto do cálculo do FAP)
  - ✅ "erro cometido pela administração pública"
  - ⚠️ **Exceção consolidada:** "Previdência Social" é aceitável quando a referência é especificamente ao *ato de concessão* do benefício (função fim da autarquia), não ao cálculo do FAP. Ex.: "a Previdência Social cometeu erro ao atribuir a natureza acidentária no ato da concessão" pode ser mantido. Verificar contexto antes de corrigir.
- [ ] **"Segurado" vs. "Empregado" conforme o contexto** — ao descrever o momento do acidente enquanto o trabalhador exercia atividades para a empresa responsável, usar "empregado" (relação contratual ativa), não "segurado" (qualidade previdenciária genérica). A distinção reforça o vínculo com a empresa efetivamente responsável pelo acidente.
  - ❌ "enquanto exercia suas funções, **o segurado** sofreu um acidente" (quando a empresa responsável é identificada)
  - ✅ "enquanto exercia suas funções, **o empregado** sofreu um acidente"
- [ ] **Instrução Normativa do INSS vigente** — usar a IN nº 128/2022 (em vigor), não a IN nº 77/2015 (revogada). Os artigos correspondentes são: art. 337 (segurado com mais de uma atividade recebe um único benefício), art. 347 (restabelecimento dentro de 60 dias) e art. 639, XIII (vedação de dois auxílios por incapacidade temporária concomitantes). **Exceção:** a expressão "IN nº 77/2015 **e seguintes**" pode ser mantida quando o contexto cita artigo paradigmático dessa normativa e a locução "e seguintes" cobre implicitamente a normativa atual.
- [ ] **"Administração Pública" com maiúsculas** — quando a referência é ao ente/órgão público como instituição (e não ao ato específico de concessão), usar "Administração Pública" com iniciais maiúsculas.
- [ ] **"Carteira de Trabalho Digital"** — quando o documento apresentado é a versão digital da CTPS, usar "Carteira de Trabalho Digital", não "Carteira de Trabalho e Previdência Social (CTPS)".
- [ ] **"Secretaria de Previdência"** — usar "Secretaria de Previdência" (não "Secretaria da Previdência"). Verificar o nome correto do órgão conforme a estrutura administrativa vigente.
- [ ] **"Benefício tributário" em vez de "desconto tributário"** — ao se referir à bonificação proporcionada pelo FAP, usar "benefício tributário" (ou "bonificação tributária"), não "desconto tributário". O FAP não é um desconto; é um fator multiplicador que pode beneficiar ou majorar a alíquota.

---

### 1.3 PRECISÃO DO NEXO CAUSAL NA NARRATIVA FÁTICA
Erros nessa categoria enfraquecem o argumento jurídico central.

- [ ] **Expressões causais vs. temporais** — a narrativa deve afirmar causalidade, não apenas simultaneidade temporal:
  - ❌ "durante o exercício das atividades laborais" (apenas temporal)
  - ✅ "em decorrência das atividades laborais" (causal)
  - ✅ "em decorrência das lesões geradas pelo acidente" (causal) — preferir "em decorrência" sobre "em virtude" quando se trata de nexo causal direto
- [ ] **Cadeia de causalidade completa** — verificar se o texto demonstra claramente a sequência: evento → nexo → benefício → inclusão indevida no FAP.
- [ ] **Referências dêiticas ("acima" / "abaixo" / "a seguir")** — verificar se as referências a documentos e imagens estão corretas após qualquer reorganização do conteúdo. "Abaixo" e "a seguir" indicam que o documento vem depois do parágrafo; "acima" indica que já foi apresentado antes. Atenção especial: quando os documentos seguem o parágrafo, usar "a seguir" ou "abaixo", não "emitidos pelo INSS" (que não informa a posição).
- [ ] **Destaque de ausência de vínculo ou desemprego na abertura da narrativa** — quando o argumento de "outra empresa" decorre do fato de que o segurado estava desempregado ou vinculado a outra empresa na data do evento incapacitante, essa informação deve ser destacada logo no início da descrição do caso, não apenas nas comparações de datas ao final. Ex.: "enquanto estava desempregado, o segurado foi submetido à cirurgia de...".
- [ ] **Pedidos de diligência — foco em benefícios sem documentação completa** — os pedidos de diligência devem listar apenas os benefícios que realmente carecem de documentação adicional. Não incluir diligências para benefícios cujos documentos já estão todos anexados à petição.
  - ❌ "Para comprovar que o acidente ocorreu em outra empresa"
  - ✅ "Para comprovar que o acidente não é relacionado à empresa Autora"
  - ❌ "tendo em vista que a doença incapacitante não é relacionada à empresa Autora" (pedido de exclusão por outra empresa)
  - ✅ "tendo em vista que o acidente de trabalho não é relacionado à empresa Autora"
- [ ] **Nexo causal falso na tese de natureza do benefício** — quando a tese é que o benefício é de natureza previdenciária (não acidentária), a narrativa não deve usar expressões causais que atribuam origem acidentária ao benefício. A estrutura correta é destacar o **erro da administração pública** ao classificar o benefício, não dizer que o benefício "decorreu" do acidente:
  - ❌ "Em decorrência do acidente NÃO relacionado ao trabalho e da incapacidade temporária, concedeu-se o benefício B91..."
  - ✅ "Embora a lesão não seja relacionada com o trabalho, a administração pública incorreu em erro ao atribuir a natureza acidentária ao benefício, tendo concedido o B91..."
- [ ] **Conectores temporais mecânicos** — evitar "Posteriormente", "Em seguida" e "A partir disso" usados de forma automática quando a sequência já está clara pelo conteúdo.
- [ ] **Pronome relativo de identificação do acidente** — ao descrever o acidente sofrido pelo segurado, usar pronome relativo que expresse consequência correta:
  - ❌ "sofreu acidente de trânsito, **o que** causou a lesão..." (impreciso)
  - ✅ "sofreu acidente de trânsito, **o qual** causou a lesão..." (correto)
- [ ] **Omissão de data incerta de rescisão de vínculo empregatício** — quando a data de saída do empregado da empresa responsável pelo acidente não é precisamente comprovável pelos documentos, é preferível mencionar apenas a data de admissão e omitir a rescisão.
- [ ] **Precisão técnica: impacto do restabelecimento nos índices FAP** — verificar se o texto e a tabela de pedidos afirmam corretamente quais índices são afetados pela dupla contagem em cada caso de restabelecimento. A regra depende da posição dos dois benefícios nas vigências:
  - **Ambos os benefícios na mesma vigência** → o segundo impacta apenas **frequência e gravidade**.
  - **Benefícios em vigências diferentes** → o segundo impacta **frequência, gravidade e custo**.
  - Aplicar a regra benefício a benefício — um mesmo tópico pode ter pares com situações distintas, exigindo linhas separadas na tabela.
- [ ] **Precisão técnica no argumento do restabelecimento — evitar afirmações contraditórias** — o texto não deve afirmar que o segundo benefício "não deve impactar frequência e gravidade por se tratar de um único benefício". O que se pede é a **exclusão da duplicidade** (o segundo não deve ser contado *adicionalmente*), não a inexistência de qualquer impacto. A formulação correta é: "o restabelecimento deve refletir a continuidade do evento incapacitante, sendo tratado como desdobramento do mesmo fato gerador."

---

### 1.4 COMPLETUDE PROBATÓRIA — Cadeia documental
Erros nessa categoria criam lacunas que a defesa pode explorar.

- [ ] **Verificar a lista de documentos exigidos para cada tese** — consultar a Seção 3 deste manual, que detalha os documentos obrigatórios por tipo de pedido.
- [ ] **Benefícios concedidos judicialmente** — quando o benefício foi obtido por sentença judicial (e não administrativamente), é obrigatório apresentar a cadeia processual completa: petição inicial da ação acidentária + parecer do MP (quando houver) + sentença + acórdão (quando houver recurso).
- [ ] **Benefícios administrativos** — apresentar telas do sistema (INFBEN, CONBAS, sistema FAP) e documentos de suporte (CAT, CNIS).
- [ ] **Verificar se todos os documentos mencionados no texto estão de fato listados nos anexos** — e vice-versa.
- [ ] **Dados técnicos relevantes para a tese** — incluir informações adicionais quando forem juridicamente relevantes. Exemplo: no tópico de Restabelecimento, mencionar o horário exato de cessação ("termina às 23h59") reforça a continuidade e caracteriza prorrogação, não novo benefício.
- [ ] **Pedidos de diligência completos** — verificar se todos os benefícios do tópico estão listados no pedido de diligência correspondente, não apenas um. A omissão de qualquer benefício compromete a instrução probatória do tópico inteiro.
- [ ] **Pedidos de diligência — completude por tese** — no tópico de Acidente de Trajeto, quando há tanto B91 quanto B92 decorrentes do mesmo acidente, o pedido de diligência deve listar **todos** os benefícios da cadeia (B91 originário + B91 intermediário + B92), não apenas alguns deles.
- [ ] **Pedidos de diligência — cobertura de todas as teses com lacuna documental** — verificar se foram incluídos pedidos de diligência para todos os tópicos em que há benefícios sem documentação completa disponível.
- [ ] **Identificação da CAT com número** — ao mencionar a Comunicação de Acidente de Trabalho pela primeira vez em cada tópico, identificar o número da CAT na própria referência:
  - ❌ "Comunicação de Acidente de Trabalho (CAT)"
  - ✅ "Comunicação de Acidente de Trabalho (CAT) nº 2012.100166.0/01"
- [ ] **Especificação do número do benefício em referências a telas** — ao mencionar a tela do FAP que comprova a inclusão de um benefício específico, identificar o número do benefício na própria referência:
  - ❌ "A tela do FAP abaixo aponta a inclusão do benefício acidentário B94, na base de cálculo..."
  - ✅ "A tela do FAP abaixo aponta a inclusão do benefício B94 nº 2077361098, na base de cálculo..."
- [ ] **Fusão de referências a telas do FAP** — quando dois benefícios aparecem na mesma tela de determinada vigência, referenciar a tela com ambos os números em uma única linha:
  - ❌ "Vigência 2021 – 1º B91 nº 6238971782" / "Vigência 2021 – 2º B91 nº 6276204300" (duas linhas para a mesma tela)
  - ✅ "Vigência 2021 – 1º B91 nº 6238971782 e 2º B91 nº 6276204300" (linha única)
- [ ] **"Os seguintes documentos" vs. "os documentos"** — usar "os seguintes documentos" apenas quando há múltiplos itens apresentados na sequência em forma de lista. Quando há apenas um documento, usar simplesmente "o documento a seguir" ou "conforme os documentos emitidos pelo INSS".
- [ ] **Ordem dos documentos na narrativa** — verificar se os documentos são mencionados na ordem em que aparecem no texto.
- [ ] **Identificação das instâncias do processo administrativo na narrativa** — quando o processo administrativo de contestação do FAP passou por 1ª e 2ª instâncias, a narrativa deve descrever cada uma separadamente, identificando explicitamente: (i) a data de transmissão da contestação em 1ª instância; e (ii) a data de publicação do resultado no DOU da 2ª instância.
- [ ] **Telas do FAP devem cobrir todas as vigências contestadas** — ao demonstrar a inclusão indevida de um benefício, apresentar a tela do FAP para **cada vigência** em que o benefício aparece. Identificar individualmente cada benefício em cada tela (ex.: "Vigência 2021 — Primeiro B91 nº XXXX e segundo B91 nº YYYY").
- [ ] **Notas de rodapé para anos-base das vigências** — na Seção de Objeto da Ação, cada vigência contestada deve ser referenciada com nota de rodapé explicando o(s) ano(s)-base correspondente(s). Padrão: "Vigência 2022: ano-base 2020" ou "Vigência 2023: anos-base 2021 e 2020".

---

### 1.5 FUNDAMENTAÇÃO JURÍDICA — Jurisprudência e precedentes
Erros nessa categoria deixam o argumento sem suporte externo, facilitando a contestação.

- [ ] **Referências a "precedentes já expostos" ou similares** — verificar se os precedentes mencionados realmente existem no documento.
- [ ] **Por tipo de pedido, verificar a presença dos precedentes adequados** — consultar a Seção 4 deste manual.
- [ ] **Qualidade dos precedentes** — preferir sentença/acórdão de casos análogos. Acórdãos de TRF têm mais peso que sentenças de 1ª instância.

---

### 1.6 REDAÇÃO E FORMATAÇÃO
Erros nessa categoria impactam a clareza e o profissionalismo da peça.

- [ ] **"índices do FAP"** — a expressão padrão é "índices do FAP" (com preposição + artigo), não "índices FAP" sem o artigo.
- [ ] **"índice de custo"** — a expressão correta é "índice de custo" (com preposição "de"), não "índice custo" sem preposição.
- [ ] **"mês seguinte ao da competência"** — ao se referir ao vencimento das contribuições, a regência correta é "o mês seguinte **ao da** competência" (não "à competência").
- [ ] **"por intermédio de"** em vez de "através de" — em contextos formais e jurídicos, preferir "por intermédio de", pois "através de" denota atravessar fisicamente. **Exceção:** "através de" dentro de transcrições literais de atos normativos não deve ser alterado.
- [ ] **Impessoalização de verbos em petições** — preferir as formas impessoais ("utilizar-se-á", "Anexa-se", "requer-se", "considerando-se") em vez das formas na primeira pessoa do plural ("utilizaremos", "Anexamos", "requer", "tomando"). Esta convenção é padrão em petições iniciais formais.
- [ ] **Referências processuais** — ao mencionar processos, usar "nos autos nº [número]" (não "nos autos do processo [número]").
- [ ] **"no período em que"** — a regência correta é "no período **em que** foram apurados", não "no período **que** foram apurados".
- [ ] **Expressões depreciativas sobre o INSS** — evitar expressões como "desídia", "descuido" ou similares para descrever o comportamento do INSS. Substituir por formulação técnica neutra (ex.: "o quadro incapacitante permanece vinculado ao mesmo evento").
- [ ] **Supressão de itens irrelevantes em acórdãos citados** — ao citar acórdãos extensos, manter apenas os itens diretamente relevantes para o argumento do caso, suprimindo os demais com "[...]". Não transcrever o acórdão integralmente quando apenas 1-2 itens são aplicáveis.
- [ ] **Pedidos subsidiários** — quando um benefício é pedido por uma tese principal mas há tese alternativa disponível, incluir explicitamente o pedido subsidiário dentro do mesmo item de pedido: "Subsidiariamente, não sendo esse o entendimento de V. Exa., requer-se a exclusão do benefício X, por [tese alternativa] – item Y da petição inicial."
- [ ] **Formatação de cabeçalho de telas do FAP** — ao apresentar telas do sistema FAP, o cabeçalho deve separar em linhas distintas: (1) o título da tela (ex.: "Detalhamento da Massa Salarial"), (2) a vigência (ex.: "Vigência 2025") e (3) os anos dos insumos (ex.: "Anos dos insumos – 2022 e 2023"). Não condensar na mesma linha.
- [ ] **Negrito indevido dentro de transcrições legais** — ao transcrever artigos de lei, não usar negrito para destacar termos gramaticais dentro do texto normativo.
- [ ] **Formatação de expressões latinas** — expressões como *in verbis*, *in casu*, *a contrario legis* devem estar apenas em itálico, nunca com negrito misturado:
  - ❌ *"in **verbis*"* / *"In **casu*"*
  - ✅ *"in verbis:"* / *"In casu,"*
- [ ] **Uso de expressões latinas corretas** — verificar se as locuções latinas usadas existem e têm o sentido pretendido:
  - ❌ "a contrário legis" (não é locução latina consagrada)
  - ✅ "contra legem" (locução correta para designar algo que vai contra a lei)
  - A locução *a contrario sensu* (no sentido contrário) existe, mas não "a contrário legis".
- [ ] **Verbosidade** — substituir construções longas e fracas por afirmações diretas. Exemplos:
  - ❌ "são suficientes para identificar e caracterizar" → ✅ "caracterizam"
  - ❌ "no dia [data]" → ✅ "em [data]" (quando se trata de adjunto adverbial de tempo; mais conciso)
  - ❌ "demonstram e comprovam" → ✅ "demonstram" (redundância)
  - ❌ "critério e base para" → ✅ "critério para" (redundância)
- [ ] **Redundância nas conclusões de tópico** — evitar fórmulas genéricas repetidas ao final de cada tópico.
- [ ] **Pontuação com datas e adjuntos adverbiais de tempo** — ao introduzir datas no meio de uma oração como adjuntos adverbiais, isolá-las com vírgulas:
  - ❌ "A comparação entre a data do acidente (16/01/2017) e a data do início do benefício em 16/02/2017, comprova..."
  - ✅ "A comparação entre a data do acidente, em 16/01/2017, e a data do início do benefício, em 16/02/2017, comprova..."
- [ ] **Concordância de número — "do índice" vs. "dos índices"**:
  - ❌ "da base de cálculo **dos índices** FAP, na vigência 2021" (uma vigência → singular)
  - ✅ "da base de cálculo **do índice** FAP, na vigência 2021"
  - ✅ "da base de cálculo **dos índices** FAP, nas vigências 2023 e 2024" (duas vigências → plural)
- [ ] **Concordância de número — "foi encontrado" vs. "foram encontrados"** — verificar concordância entre verbo e quantidade de benefícios encontrados.
- [ ] **Concordância verbal em construções com "documentos"** — "conforme demonstrado nos documentos" (passiva) vs. "conforme demonstram os documentos" (ativa, preferida). Verificar se o verbo concorda com o sujeito real.
- [ ] **Concordância de número e gênero em pedidos subsidiários** — verificar com especial atenção as cláusulas subsidiárias, que frequentemente apresentam erros de concordância quando o advogado júnior adapta texto de pedido anterior (singular/plural, masculino/feminino).
- [ ] **Concordância "valores inferiores aos reais"** — quando se afirma que valores considerados no FAP são menores que os corretos, usar "valores inferiores **aos reais**" (plural, referindo-se aos valores reais), não "valores inferiores **ao real**" (que sugere a moeda).
- [ ] **Notas de rodapé** — verificar se estão numeradas corretamente e se o conteúdo corresponde ao contexto onde são inseridas.
- [ ] **Ponto final na última nota de rodapé** — a última nota de rodapé de uma série deve encerrar com ponto final (não ponto e vírgula).
- [ ] **Formatação de tabelas** — unidades devem aparecer nos valores, não nos cabeçalhos:
  - ❌ Coluna "Duração (dias)" com valor "0,000" → ✅ Coluna "Duração" com valor "0 dias"
  - ❌ Coluna "Custo (R$)" com valor "0,00" → ✅ Coluna "Custo" com valor "R$ 0,00"
- [ ] **Numeração em tabelas de pedidos** — tabelas nos pedidos finais não devem ter numeração sequencial própria que concorra com a numeração dos itens dos pedidos.
- [ ] **Vigências múltiplas na mesma linha de tabela** — quando um benefício aparece em mais de uma vigência dentro da mesma ação **com os mesmos índices de impacto**, as vigências devem constar em uma única linha (ex: "2021 | 2022"). Porém, quando os índices de impacto são **diferentes por vigência**, cada vigência deve ter sua própria linha, com os índices correspondentes.
- [ ] **Tabela ausente quando deveria existir** — verificar se tópicos que requerem identificação do benefício e vigência possuem a tabela correspondente.
- [ ] **Concordância em número de laudos/perícias** — quando o argumento se baseia em mais de um laudo ou perícia, usar o plural.
- [ ] **Crase em "à segurada/à empresa"** — verificar crase em referências a seguradas e empresas do gênero feminino.
- [ ] **Ponto final no último item de lista de diligências** — o último item de qualquer lista de pedidos de diligência deve encerrar com ponto final, não ponto e vírgula.
- [ ] **Expressões latinas em itálico dentro de trechos em negrito** — mesmo dentro de trechos em negrito, expressões latinas devem manter o itálico.
- [ ] **Negrito isolado em palavras gramaticais dentro de citações legais** — não aplicar negrito em artigos, pronomes ou preposições que integram o texto normativo.
- [ ] **Espaçamento entre parágrafos** — evitar dupla quebra de linha desnecessária entre parágrafos consecutivos que tratam do mesmo assunto.
- [ ] **Uso correto de "Em síntese" como marcador de destaque** — "Em síntese" em negrito é reservado para resumos que consolidam vários elementos anteriores.
- [ ] **Uso de barras "/" em textos formais** — evitar barras oblíquas entre termos alternativos em textos formais de petição (ex.: "restabelecimento/prorrogação"). Substituir por conjunção: "restabelecimento ou prorrogação".
- [ ] **"Juízo" com maiúscula** — quando a referência é ao órgão jurisdicional como instituição, usar "Juízo" com maiúscula (ex.: "o Juízo da 2ª Vara Federal de Blumenau/SC entendeu que...").
- [ ] **Arredondamento de percentuais em tabelas** — percentuais de taxa de rotatividade e outros índices devem ser apresentados com duas casas decimais nas tabelas de petição, não com quatro casas (ex.: "408,21%", não "408,2192%").

---

## SEÇÃO 2 — CONEXÃO ENTRE BENEFÍCIOS (REGRA GERAL)

Esta regra se aplica a múltiplas teses e deve ser verificada sempre que houver benefícios B92 ou B94 na petição.

**Regra:** quando a tese envolve benefício de espécie B92 ou B94 (e em alguns casos B91), é obrigatório extrair e apresentar também os documentos do benefício B91 anterior, pois é indispensável demonstrar a conexão entre os benefícios.

**Motivo:** a DIB do B92 ou B94 geralmente corresponde ao dia seguinte da DCB do B91, confirmando a vinculação entre os dois benefícios e a conexão com o evento acidentário.

**Exemplo:** acidente em 10/01/2025 → B91 (DIB 26/01/2025, DCB 03/05/2025) → B92 ou B94 (DIB 04/05/2025).

Esta regra se aplica às seguintes teses: acidente de trajeto (B92 e B94), outra empresa, outro estabelecimento, nexo afastado, acidente pré-FAP, acidente não relacionado ao trabalho, erro de implantação.

**Regra estendida para teses com múltiplos benefícios encadeados:** quando houver mais de um B91 na cadeia (ex.: B91 originário → B91 intermediário → B92 final), a petição deve apresentar e descrever todos os elos da cadeia.

---

## SEÇÃO 3 — DOCUMENTOS OBRIGATÓRIOS POR TESE

Para cada tese presente na petição, verificar se os documentos abaixo estão listados nos anexos. A ausência de qualquer documento obrigatório é uma lacuna probatória que deve ser apontada.

---

### 3.1 ACIDENTE DE TRAJETO

**Definição:** acidente sofrido no percurso entre residência e local de trabalho (ou vice-versa). Base legal: art. 21, IV, "d", da Lei nº 8.213/91.

**Documentos obrigatórios — B91:**
1. Tela do FAP
2. Comunicação de Acidente de Trabalho (CAT) — identificar com número
3. Laudo Médico Pericial ou Dossiê Médico (INSS)
4. Boletim de Ocorrência
5. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
6. Declaração de Benefícios
7. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão
8. Outros documentos que citem o acidente de trajeto (prontuários, declarações, fichas de registro)

**Documentos obrigatórios — B94 (além dos do B91 originário):**
1. Tela do FAP
2. CAT — identificar com número
3. Laudo Médico Pericial ou Dossiê Médico do B91 originário
4. Boletim de Ocorrência
5. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B94
6. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 originário
7. Declaração de Benefícios
8. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão
9. Se houver acordo: proposta de acordo, aceite e sentença homologatória

**Documentos obrigatórios — B92 (além dos do B91 originário):**
Mesmos documentos do B94, aplicando-se a mesma lógica de conexão com o B91.

**Documentos adicionais quando a concessão do B92 decorreu de ação judicial:**
Incluir também a petição inicial do processo judicial que deu origem ao B92.

---

### 3.2 AUXÍLIO POR INCAPACIDADE TEMPORÁRIA PREVIDENCIÁRIA (B31)

**Definição:** benefícios previdenciários (B31) não integram a base de cálculo do FAP. Base legal: Resoluções nº 1.316/2010, 1.329/2017 e 1.347/2021.

**Documentos obrigatórios:**
1. Tela do FAP
2. Comunicado de Decisão (CRER)
3. Acórdão do CRPS
4. Declaração de Benefícios
5. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
6. Laudo Médico Pericial ou Dossiê Médico (INSS)

---

### 3.3 RESTABELECIMENTO (menos de 60 dias entre DCB e DIB)

**Definição:** dois benefícios de incapacidade temporária consecutivos decorrentes da mesma incapacidade, com intervalo inferior a 60 dias entre a DCB do primeiro e a DIB do segundo.

**Dado técnico essencial — índices afetados:**
- **Ambos os benefícios na mesma vigência** → o segundo impacta apenas **frequência e gravidade** (o custo já está integralmente computado nessa vigência pelo primeiro benefício).
- **Benefícios em vigências diferentes** → o segundo impacta **frequência, gravidade e custo** (o custo do segundo benefício aparece pela primeira vez nessa nova vigência).
- Verificar a situação de cada par individualmente — um mesmo tópico pode conter pares que se enquadram em regras diferentes, exigindo linhas separadas na tabela de pedidos.

**Documentos obrigatórios:**
1. Telas do FAP dos dois benefícios (se não for B31)
2. Declaração de Benefícios
3. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS de ambos os benefícios
4. Laudo Médico Pericial ou Dossiê Médico de ambos os benefícios
5. Comunicado de Decisão (CRER)
6. Se houver restabelecimento judicial: petição inicial, laudo médico judicial, decisão de tutela antecipada (se for o caso), sentença e acórdão

---

### 3.4 OUTRA EMPRESA

**Definição:** benefício acidentário vinculado à empresa Autora, mas documentos comprovam que o acidente ou doença ocorreu enquanto o empregado estava vinculado a outra empresa.

**Documentos obrigatórios:**
1. Tela do FAP
2. Comunicação de Acidente de Trabalho (CAT) — identificar com número
3. Carteira de Trabalho e Previdência Social (CTPS)
4. Termo de Rescisão de Contrato de Trabalho (TRCT)
5. Cadastro Nacional de Informações Sociais (CNIS)
6. Ficha do empregado e/ou folha ponto com o afastamento
7. Declaração da empresa responsável pelo acidente
8. INFBEN, CONBAS, HISMED e/ou Dossiê Previdenciário
9. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 originário (se for o caso)
10. Declaração de Benefícios
11. Laudo Médico Pericial ou Dossiê Médico (INSS)
12. Laudo Médico Pericial ou Dossiê Médico do benefício originário (se for o caso)
13. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão

---

### 3.5 OUTRO ESTABELECIMENTO

**Definição:** benefício acidentário vinculado a um estabelecimento da Autora, mas documentos comprovam que o acidente ou doença ocorreu em estabelecimento diverso da mesma empresa.

**Documentos obrigatórios:**
1. Tela do FAP
2. CAT
3. CTPS
4. TRCT
5. CNIS
6. Ficha do empregado e/ou folha ponto com o afastamento
7. Laudo Médico Pericial ou Dossiê Médico (INSS)
8. Laudo Médico Pericial ou Dossiê Médico do benefício originário (se for o caso)
9. INFBEN, CONBAS, HISMED e/ou Dossiê Previdenciário
10. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 originário (se for o caso)
11. Declaração de Benefícios
12. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão

---

### 3.6 CONCESSÃO CONCOMITANTE DE BENEFÍCIOS

**Definição:** mesmo segurado recebeu dois ou mais benefícios no mesmo período; apenas um deve ser considerado no FAP.

**Documentos obrigatórios:**
1. Tela do FAP
2. Declaração de Benefícios
3. CNIS
4. INFBEN, CONBAS, HISMED e/ou Dossiê Previdenciário
5. Se houver ação judicial: petição inicial, laudo médico judicial (na concomitância de B91 e B94 com B31), sentença, acórdão
6. Cálculo das parcelas vencidas (demonstra o abatimento dos valores recebidos)
7. Laudo Médico Pericial ou Dossiê Médico (INSS) (na concomitância de B91 e B94 com B31)

---

### 3.7 SOBREPOSIÇÃO DE DOIS BENEFÍCIOS DE AUXÍLIO POR INCAPACIDADE TEMPORÁRIA

**Definição:** dois benefícios B91 ou B31 concedidos ao mesmo segurado com períodos sobrepostos.

**Documentos obrigatórios:**
1. Tela do FAP
2. Declaração de Benefícios
3. INFBEN, CONBAS, HISMED e/ou CNIS de ambos os benefícios
4. Laudo Médico Pericial ou Dossiê Médico (INSS) de ambos os benefícios
5. Comunicado de Decisão (CRER)
6. Se houver restabelecimento judicial: petição inicial, laudo médico judicial, decisão de tutela antecipada (se for o caso), sentença e acórdão

---

### 3.8 NEXO AFASTADO

**Definição:** a perícia médica e/ou decisão judicial conclui que a incapacidade não possui relação com o trabalho.

**Documentos obrigatórios:**
1. Tela do FAP
2. Petição inicial, laudo médico judicial, sentença e acórdão
3. Se houver acordo: proposta de acordo, aceite e sentença homologatória
4. Laudo Médico Pericial ou Dossiê Médico (INSS)
5. Laudo Médico Pericial ou Dossiê Médico do benefício originário (se for o caso)
6. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
7. Declaração de Benefícios

---

### 3.9 ACIDENTE PRÉ-FAP (antes de abril de 2007)

**Definição:** acidentes anteriores a abril de 2007 não devem ser contabilizados no FAP.

**Documentos obrigatórios:**
1. Tela do FAP
2. CAT — identificar com número
3. Laudo Médico Pericial ou Dossiê Médico (INSS)
4. Laudo Médico Pericial ou Dossiê Médico do benefício B91 originário (se for o caso)
5. Boletim de Ocorrência
6. Documentos da época do acidente
7. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
8. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 originário (se for o caso)
9. Declaração de Benefícios
10. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão
11. Se houver acordo: proposta de acordo, aceite e sentença homologatória

---

### 3.10 ACIDENTE NÃO RELACIONADO AO TRABALHO

**Definição:** benefício registrado como acidentário, mas documentos comprovam que o evento não tem relação com o trabalho.

**Documentos obrigatórios:**
1. Tela do FAP
2. Laudo Médico Pericial ou Dossiê Médico (INSS)
3. Laudo Médico Pericial ou Dossiê Médico do benefício originário (se for o caso)
4. Boletim de Ocorrência
5. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
6. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 originário (se for o caso)
7. Declaração de Benefícios
8. Se houver ação judicial: petição inicial, laudo médico judicial, sentença e acórdão
9. Se houver acordo: proposta de acordo, aceite e sentença homologatória

---

### 3.11 DIB = DCB

**Definição:** benefício cuja Data de Início (DIB) coincide com a Data de Cessação (DCB), resultando em duração de 0 dias e custo de R$ 0,00.

**Documentos obrigatórios:**
1. Tela do FAP mostrando DIB/DCB e custo zerado
2. Declaração de Benefícios
3. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
4. Documentos que comprovem que DIB é igual à DCB

---

### 3.12 BENEFÍCIO REVOGADO/CANCELADO

**Definição:** benefício acidentário concedido por decisão judicial e posteriormente revogado no mesmo processo.

**Documentos obrigatórios:**
1. Tela do FAP
2. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
3. INFBEN/CONBAS/HISMED/Dossiê/CNIS do B91 concedido (se for o caso)
4. Declaração de Benefícios
5. Petição inicial, decisão de tutela antecipada (se for o caso), sentença e acórdão de revogação
6. Requerimento de devolução dos valores pagos ao segurado (se houver)
7. Documentos que comprovem a revogação

---

### 3.13 ERRO DE IMPLANTAÇÃO

**Definição:** divergência entre o benefício concedido judicialmente e o efetivamente implantado pelo INSS, resultando em erro quanto à natureza (acidentário x previdenciário).

> **Nota sobre hierarquia de teses:** quando o caso de erro de implantação puder ser mais solidamente fundamentado como "acidente não relacionado ao trabalho" (com base em laudo pericial que afasta o nexo), Isrhael prefere a reclassificação para o Tópico de Acidente Não Relacionado ao Trabalho (Seção 3.10). A tese de erro de implantação como tópico autônomo é mais vulnerável; use-a apenas quando não houver base factual para a tese alternativa mais sólida.

**Documentos obrigatórios:**
1. Tela do FAP
2. Petição inicial, sentença e acórdão demonstrando a concessão do benefício previdenciário
3. Documento que demonstre a implantação do benefício acidentário pelo INSS
4. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício originário
5. Laudo Médico Pericial ou Dossiê Médico do benefício originário
6. Declaração de Benefícios

---

### 3.14 APURAÇÃO DO ÍNDICE DE CUSTO

**Definição:** o custo projetado pela Previdência Social é superior ao custo efetivamente suportado.

> **Nota técnica obrigatória:** quando a DCB do benefício B94 é conhecida (por concessão de aposentadoria ou óbito), a narrativa deve explicar explicitamente por que a projeção pela expectativa de sobrevida é inadequada no caso concreto: "O custo do B94 somente deve ser projetado para fins de cálculo do FAP quando não se conhece a sua data de cessação. Contudo, no presente caso, a data de cessação do B94 é conhecida: [data]."

**A. Benefício cessado por óbito:**
1. Tela do FAP demonstrando o custo majorado
2. CAT de óbito
3. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício
4. Certidão de óbito
5. Comprovante de Situação Cadastral no CPF

**B. Benefício cessado por concessão de outro benefício:**
1. Tela do FAP demonstrando o custo majorado
2. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício
3. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício concedido
4. Se houver ação judicial: petição inicial, sentença e acórdão

**C. Benefício cessado antes da data projetada:**
1. Tela do FAP demonstrando o custo majorado
2. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício
3. INFBEN/CONBAS/HISMED/Dossiê/CNIS do benefício concedido (se for o caso)
4. Se houver ação judicial: petição inicial, sentença e acórdão

---

### 3.15 CAT DUPLICADA

**Definição:** emissão de mais de uma CAT para o mesmo evento.

**Documentos obrigatórios:**
1. Telas do FAP de ambas as CATs
2. Ambas as CATs

---

### 3.16 CAT NÃO VINCULADA

**Definição:** existe uma CAT emitida, mas o benefício foi concedido com base em NTP sem vinculação à CAT.

**Documentos obrigatórios:**
1. Tela do FAP B91
2. Tela do FAP do NTP sem CAT vinculada
3. Tela do FAP da CAT
4. A CAT

---

### 3.17 NTP DUPLICADO

**Definição:** quando o B91 é convertido em B92 ou B94, o INSS registra duplicidade de NTP.

**Documentos obrigatórios:**
1. Telas do FAP B91 e B92/B94
2. Telas do FAP dos NTPs sem CAT vinculada (B91 e B92/B94)
3. INFBEN, CONBAS, HISMED, Dossiê Previdenciário e/ou CNIS
4. Laudo Médico Pericial ou Dossiê Médico (INSS)
5. Se for benefício concedido judicialmente: petição inicial, laudo médico judicial, sentença e acórdão

---

### 3.18 TAXA MÉDIA DE ROTATIVIDADE

**Definição:** quando a taxa de rotatividade da empresa ultrapassa 75%, o redutor do FAP é bloqueado.

**Nome do tópico:** o tópico deve ser designado como "TAXA MÉDIA DE ROTATIVIDADE – ILEGALIDADE DA APLICAÇÃO DO 'BLOQUEIO DE ROTATIVIDADE'" — não apenas "ILEGALIDADE DA APLICAÇÃO DO 'BLOQUEIO DE ROTATIVIDADE'".

**Documentos obrigatórios:**
1. Tela do FAP demonstrando o bloqueio (Avisos Importantes)
2. Tela do "Detalhamento dos valores"
3. Resultado da Consulta FAP

---

### 3.19 ERRO DE MASSA SALARIAL

**Definição:** erro na apuração da massa salarial.

**Documentos obrigatórios:**
1. Telas do FAP de vigência anterior ou seguinte com valores corretos (comparativo) OU tela do detalhamento da massa salarial da vigência contestada
2. GFIPs das competências em que ocorreu o erro
3. Planilha-resumo das divergências entre os valores do FAP e os declarados nas GFIPs

> **Nota sobre escopo das competências:** as competências afetadas devem ser descritas como "todas as competências dos anos de X e Y" (anos-base da vigência), não como listas com exceções mensais, salvo quando há justificativa específica para a exclusão de determinadas competências.

---

### 3.20 ERRO NO NÚMERO MÉDIO DE VÍNCULOS

**Definição:** erro na apuração do número médio de vínculos.

**Documentos obrigatórios:**
1. Telas do FAP de vigência anterior ou seguinte com valores corretos (comparativo) OU tela do detalhamento do número médio de vínculos da vigência contestada
2. GFIPs das competências em que ocorreu o erro
3. Planilha-resumo das divergências entre os valores do FAP e os declarados nas GFIPs

> **Nota sobre escopo das competências:** mesma regra da Seção 3.19 — usar "todas as competências dos anos de X e Y".

---

## SEÇÃO 4 — BANCO DE FUNDAMENTAÇÕES

### Acidente de Trajeto — exclusão do FAP
**Base normativa:** Resolução CNPS nº 1.329/2017, art. 2º.

**Argumento central:** o critério de contabilização é a Data de Despacho do Benefício (DDB) dentro do Período-Base, não a data do acidente. Portanto, não se trata de aplicação retroativa da resolução.

**Precedentes da própria União:**
- Contestação nos autos nº 5005677-73.2021.4.04.7005/PR (1ª VF Guarapuava)
- Contestação nos autos nº 0809292-03.2021.4.05.8200/PB (2ª VF João Pessoa)

**Precedentes judiciais favoráveis:**
- TRF4, AC 5001888-34.2019.4.04.7200 (Rel. Alexandre Rossato)
- Juiz Vilian Bollmann — processo nº 5025207-60.2021.4.04.7200/SC
- Juiz Diógenes Tarcísio Marcelino Teixeira — processo nº 5020684-65.2022.4.04.7201/SC
- Juiz Pedro Pimenta Bossi — processo nº 5001191-30.2021.4.04.7010/PR
- Juiz Rony Ferreira — processo nº 5003834-82.2021.4.04.7002/PR
- Juiz Marco Aurélio de Mello Castriani — processo nº 5018811-28.2023.4.03.6100/SP

---

### Doença/acidente não relacionado à empresa autora — exclusão do FAP
**Base normativa:** Resoluções CNPS 1.329/2017 e 1.347/2021.

**Argumento central:** dois requisitos cumulativos — (i) nexo causal entre doença/acidente e a concessão do benefício; e (ii) vínculo empregatício com a empresa na data do evento.

**Precedentes judiciais favoráveis:**
- TRF4, Apelação Cível nº 5025207-60.2021.4.04.7200/SC (2ª Turma)
- TRF3, Apelação Cível nº 5002461-31.2021.4.03.6133/SP (2ª Turma)
- Juiz Vilian Bollmann — processo nº 5025207-60.2021.4.04.7200/SC
- Juiz Pedro Pimenta Bossi — processo nº 5001191-30.2021.4.04.7010/PR
- Juiz Joseano Maciel Cordeiro — processo nº 5004906-94.2023.4.04.7209

---

### Restabelecimento — menos de 60 dias entre DCB e DIB
**Base normativa:** Resoluções CNPS 1.329/2017 e 1.347/2021.

**Argumento central:** quando o segundo benefício é concedido dentro de 60 dias da cessação do primeiro e decorre do mesmo evento acidentário, trata-se de mera prorrogação. Os índices afetados dependem da posição dos dois benefícios nas vigências: se ambos estiverem na **mesma vigência**, o segundo impacta apenas **frequência e gravidade**; se estiverem em **vigências diferentes**, o segundo impacta **frequência, gravidade e custo**.

**Formulação técnica do argumento:** "o restabelecimento deve refletir a continuidade do evento incapacitante que lhe deu origem, sendo tratado como desdobramento do mesmo fato gerador." Evitar afirmar que o segundo benefício "não deve impactar frequência e gravidade" — o que se pede é a exclusão da **dupla contagem**, não a inexistência de qualquer impacto.

**Precedentes judiciais favoráveis:**
- TRF4, Embargos de Declaração nº 5025207-60.2021.4.04.7200/SC e nº 5098361-91.2019.4.04.7100/RS (21/11/2023)
- TRF4, 2ª Turma, autos nº 5002029-42.2022.4.04.7008/PR (05/03/2024)
- União — contestação nos autos nº 5026198-14.2023.4.02.5101 (16ª VF Rio de Janeiro)
- Juiz Cláudio Roberto da Silva — processo nº 5010781-95.2020.4.04.7000/PR
- Juíza Suane Moreira Oliveira — processo nº 5001711-05.2021.4.04.7005/PR

---

### Acidente não relacionado ao trabalho / erro de natureza do benefício
**Argumento central:** quando a doença ou acidente não tem nexo com o trabalho, o benefício é de natureza previdenciária. A inclusão indevida como benefício acidentário no FAP é erro da administração pública.

**Precedentes judiciais favoráveis:**
- Juíza Camila Monteiro Pullin — processo nº 0800326-61.2024.4.05.8001
- Juiz André Coutinho da Fonseca Fernandes Gomes — processo nº 1010401-12.2024.4.01.3500/JFGO
- Juiz Ivan Arantes Junqueira Dantas Filho — processo nº 5008073-22.2023.4.04.7209/JFSC
- Juiz Paulo Vieira Aveline — processo nº 5018640-64.2022.4.04.7204/JFSC
- Juíza Rosimar Terezinha Kolm — processo nº 5022565-31.2023.4.04.7205/JFSC
- Juiz José Jácomo Gimenes — processo nº 5024393-92.2023.4.04.7001/JFPR

---

### Benefício com DIB = DCB
**Argumento central:** benefício com duração de 0 dias e custo de R$ 0,00 não representa evento real. Sua inclusão no FAP é erro da administração pública.

> Ainda sem precedentes judiciais catalogados.

---

### Taxa Média de Rotatividade
**Base normativa:** Lei nº 10.666/2003 e Decreto nº 3.048/1999 — não preveem o critério de rotatividade para o cálculo do FAP.

**Argumento central:** a taxa de rotatividade foi incluída na metodologia do FAP pelas Resoluções CNPS nºs 1.316/2010, 1.329/2017 e 1.347/2021, sem amparo na Lei nº 10.666/2003 nem no Decreto nº 3.048/1999. Trata-se de inovação *contra legem* que restringe direito previsto em lei, ferindo o princípio da legalidade (art. 150, inciso I, da CRFB/1988 e art. 97, incisos II e IV, do CTN).

**Precedentes judiciais favoráveis:**
- TRF4, 5003128-68.2018.4.04.7111, Segunda Turma, Rel. Alexandre Rossato da Silva Ávila (08/11/2021)
- MS nº 5000498-48.2018.4.04.7205/SC (2ª VF Blumenau)

---

### Concessão concomitante de benefícios
**Argumento central:** a legislação veda expressamente a percepção simultânea de dois benefícios de incapacidade temporária. Base normativa atualizada: art. 639, XIII, da IN nº 128/2022 (substituiu o art. 528, IX, da IN nº 77/2015, revogada). Art. 337 da IN nº 128/2022 estabelece que o segurado com mais de uma atividade recebe apenas um benefício.

**Precedentes judiciais favoráveis:**
- União — contestação nos autos nº 5001149-08.2024.4.03.6103 (3ª VF São José dos Campos)
- TRF4, Apelação Cível nº 5058800-35.2020.4.04.7000/JFPR

---

### Erro na Massa Salarial
**Base normativa:** Resoluções nºs 1.316/2010, 1.329/2017 e 1.347/2021.

**Argumento central:** a massa salarial é apurada com base nas GFIPs declaradas pela empresa. Quando o FAP considera valores inferiores aos declarados, há erro da Administração Pública no cálculo do índice de custo, que penaliza indevidamente a empresa ao majorar o FAP.

**Precedentes judiciais favoráveis:**
- Juíza Suane Moreira Oliveira — processo nº 5001711-05.2021.4.04.7005/PR (2ª VF Cascavel)
- Juiz Jurandi Borges Pinheiro — processo nº 5004460-31.2022.4.04.7208/SC (2ª VF Itajaí)

---

### Erro no Número Médio de Vínculos
**Base normativa:** Resoluções nºs 1.316/2010, 1.329/2017 e 1.347/2021.

**Argumento central:** o número médio de vínculos é apurado com base nas GFIPs declaradas pela empresa. Quando o FAP considera valores inferiores aos declarados, há erro da Administração Pública no cálculo dos índices de frequência e gravidade, que penaliza indevidamente a empresa ao majorar o FAP.

> Precedentes a catalogar conforme novos casos forem analisados.

---

## SEÇÃO 5 — HIERARQUIA DE TÓPICOS

> **Status:** em construção. Esta seção será atualizada progressivamente com base nos padrões identificados pelo Isrhael nos casos analisados.

### Princípio geral
A ordem dos tópicos dentro da petição deve refletir a **força probatória** de cada pedido. A decisão final sobre a ordem cabe ao revisor (Isrhael).

### Hipótese de hierarquia (a confirmar com mais casos)
1. Nexos técnicos contabilizados de forma indevida (CAT + NTP duplicado)
2. Acidente de trajeto
3. Benefícios de natureza previdenciária (B31) incluídos indevidamente
4. Conversão judicial de B91 em B31
5. Acidente não relacionado ao trabalho / erro de natureza do benefício
6. Benefício revogado/cancelado
7. Restabelecimento (menos de 60 dias entre DCB e DIB)
8. Outra empresa (acidente não relacionado à empresa Autora)
9. Concessão concomitante de benefícios
10. DIB = DCB
11. Nexo afastado (reconhecimento judicial da ausência de nexo causal)
12. Acidente ocorrido antes de abril de 2007
13. Taxa Média de Rotatividade — Ilegalidade do Bloqueio
14. Erro na Massa Salarial
15. Erro no Número Médio de Vínculos

> Esta hierarquia é provisória e será revisada a cada novo caso analisado.

---

## SEÇÃO 6 — VALOR DA CAUSA

> **Status:** em construção. Esta seção será atualizada progressivamente com base nos padrões identificados pelo Isrhael nos casos analisados.

### Regra geral
O valor da causa **não pode conter placeholders** ("R$ XXX", "XXX reais" ou similar). É obrigação do advogado júnior preencher o valor antes de entregar a versão inicial para revisão.

### Padrões identificados até agora

| Caso | Empresa | Vigências | Teses presentes | Valor da causa |
|---|---|---|---|---|
| 1 | APM Terminals Pecém | 2022, 2023 e 2026 | Acidente de trajeto + Outra empresa | R$ 200.000,00 |
| 2 | Moniari Supermercados | 2021 a 2025 | Múltiplas (trajeto, outra empresa, restabelecimento, natureza, DIB=DCB) | R$ 100.000,00 |
| 3 | Valid | 2021 a 2025 | Múltiplas (trajeto, natureza, restabelecimento, outra empresa, outro estabelecimento, nexo afastado, pré-FAP, erro de vínculos) | A confirmar |
| 4 | Dohler (2015/2016/2019/2020) | 2015, 2016, 2019 e 2020 | Múltiplas (NTP duplicado, trajeto, B31, conversão judicial, natureza, revogação, restabelecimento, outra empresa, concomitância, DIB=DCB, nexo afastado, pré-FAP) | R$ 200.000,00 |
| 5 | Electro Aço Altona | 2022, 2023 e 2024 | Múltiplas (outra empresa, trajeto, restabelecimento, concomitância 3 modalidades, pré-FAP) | R$ 200.000,00 |
| 8 | COAMO Agroindustrial Cooperativa | 2023 | Múltiplas (outra empresa, restabelecimento, concomitante, DIB=DCB, nexo afastado, sobreposição) | R$ 100.000,00 |
| 9 | Marfrig Global Foods | 2022 e 2023 | Múltiplas (trajeto, outra empresa, outro estabelecimento, restabelecimento, B31, natureza, concomitante, nexo afastado, custo, sobreposição) | R$ 200.000,00 |
| 10 | Toniolo, Busnello | 2021 a 2025 | Erro na Massa Salarial + Erro no Número Médio de Vínculos (apenas teses de insumos) | R$ 100.000,00 |
| 11 | Estação VIP Vigilância | 2021, 2022 e 2024 | Restabelecimento (1 B91) + Bloqueio de Rotatividade | R$ 10.000,00 |

> **Hipótese refinada (v2.0):** o valor da causa parece depender de três variáveis combinadas: (1) tipo de teses — teses de **insumos** (massa salarial, vínculos) tendem a R$ 100.000,00; (2) número e complexidade das teses de **benefícios individuais** — múltiplas teses com 2+ vigências tendem a R$ 200.000,00; (3) **porte do pedido** — casos com poucas teses e poucos benefícios em empresa de menor porte podem resultar em valor menor (R$ 10.000,00 foi adotado para caso com apenas 1 B91 contestado + rotatividade). Continuar coletando casos para confirmar e refinar.

---

## HISTÓRICO DE VERSÕES

| Versão | Base | Principais adições |
|---|---|---|
| 1.0 | 1 caso (APM Terminals – João/Isrhael) | Estrutura inicial completa |
| 1.1 | 2 casos (+ Moniari – Edivan/Isrhael) | Terminologia "administração pública"; referências dêiticas; identificação de documentos; formatação de expressões latinas; concordância singular/plural; formatação de tabelas; seções Hierarquia de Tópicos e Valor da Causa; banco de fundamentações expandido |
| 1.2 | 2 casos + Manual Interno Rodriguez & Sousa | Seção 2 (regra de conexão entre benefícios); Seção 3 completa com 20 teses; banco de fundamentações expandido |
| 1.3 | 3 casos (+ Valid – João/Isrhael) | Nexo causal falso na tese de natureza; conectores temporais mecânicos; pedidos de diligência incompletos; especificação do nº do benefício em referências a telas; "os seguintes documentos" vs. "o documento"; vigências múltiplas na mesma linha; tabela ausente; concordância em número de laudos/perícias; crase "à segurada/à empresa"; ponto final no último item de lista; expressões latinas em itálico dentro de negrito |
| 1.4 | 4 casos (+ Dohler 2015/16/19/20 – João/Isrhael) | "nº" antes de número de logradouro; data de transmissão da contestação administrativa; vigências na introdução da seção de contestação; instâncias administrativas na narrativa e nos títulos de documentos; gênero gramatical dos segurados; tipificação da espécie vs. CAT nas tabelas de NTP; pronome relativo "o qual" vs. "o que"; concordância "foi encontrado" vs. "foram encontrados"; negrito indevido; espaçamento desnecessário; "Em síntese" como marcador; "provas suficientes"; pedidos de diligência para todas as teses com lacuna; regra estendida de conexão para cadeia com múltiplos B91; petição judicial como documento adicional para B92 |
| 1.5 | 5 casos (+ Electro Aço Altona – João/Isrhael) | CEP como campo de verificação; escopo de vigências da ação; conferência da quantidade de benefícios nas conclusões; precisão técnica do restabelecimento (frequência e gravidade apenas); distinção "segurado" vs. "empregado" na narrativa de outra empresa; omissão de data incerta de rescisão; vigências múltiplas com índices distintos por vigência; telas do FAP para todas as vigências; nota de rodapé de vigência deve corresponder à vigência discutida |
| 1.6 | 7 casos (+ Dohler 2021/2022 – Guilherme/Isrhael) | Ponto após "S.A." na razão social; "de X e Y" vs. "de X a Y" para dois anos de vigência; pontuação com datas em adjuntos adverbiais; identificação da CAT com número ao mencioná-la pela primeira vez; fusão de referências a telas do FAP quando dois benefícios aparecem na mesma tela; verificação de NIT duplicado entre segurados na mesma tabela; "no dia" → "em" antes de datas específicas; exceção consolidada "Previdência Social" aceitável no contexto de ato de concessão (não de cálculo do FAP); concordância verbal "demonstram os documentos" |
| 1.6.1 | Correção técnica confirmada com Isrhael | Regra dos índices do restabelecimento corrigida: depende da posição dos dois benefícios nas vigências — mesma vigência → apenas frequência e gravidade; vigências diferentes → frequência, gravidade e custo. Atualizado nas Seções 1.1, 1.3, 3.3 e banco de fundamentações. |
| 1.7 | 8 casos (+ COAMO 2023 – Edivan/Isrhael) | *(Versão gerada em sessão anterior — padrões a incorporar progressivamente)* |
| 1.8 | 9 casos (+ Marfrig 2022/2023 – Guilherme/Isrhael) | CEP com ponto separador (XX.XXX-XXX); número de logradouro acima de mil com ponto separador; anos das leis/resoluções por extenso (quatro dígitos); "inciso" em vez de "inc."; "nºs" no plural; subtítulo da ação com anos-base; notas de rodapé para anos-base das vigências; "índices do FAP" com artigo "do"; "Administração Pública" com maiúsculas; "por intermédio de" em vez de "através de"; destaque de desemprego/ausência de vínculo na abertura da narrativa; "Carteira de Trabalho Digital"; distinção outra empresa vs. outro estabelecimento pelo CNPJ raiz; Isrhael pode adicionar benefícios omitidos pelo júnior; IN nº 128/2022 substitui IN nº 77/2015 (arts. 337, 347, 639, XIII); tese de Erro de Implantação pode ser absorvida por tese mais sólida; notas técnicas nas Seções 3.13 e 3.14; supressão de itens irrelevantes em acórdãos; pedidos subsidiários explicitados; diligências focadas em benefícios sem documentação; expressões depreciativas sobre INSS substituídas por formulação neutra; banco de fundamentações da concomitância atualizado com IN 128/2022. |
| 1.9 | 10 casos (+ Toniolo Busnello 2021/2025 – João/Isrhael) | "alínea" por extenso em referências normativas; desdobramento de "arts." em "art." individuais para artigos distintos; sigla do órgão acrescentada após nome completo (CNPS); "mês seguinte ao da competência" (regência correta); "nos autos nº" (não "nos autos do processo"); "índice de custo" (com preposição "de"); impessoalização de verbos em petições ("utilizar-se-á", "Anexa-se", "requer-se", "considerando-se"); formatação de cabeçalho de telas em linhas separadas; "Secretaria de Previdência" (não "Secretaria da Previdência"); escopo das competências em teses de insumos = "todas as competências dos anos de X e Y"; "vigências" vs. "anos" no contexto do FAP; "no período em que" (não "no período que"); concordância "valores inferiores aos reais"; concordância plural em pedidos subsidiários; ponto final na última nota de rodapé; banco de fundamentações com Erro na Massa Salarial e Erro no Número Médio de Vínculos; hipótese refinada de valor da causa (teses de insumos = R$ 100.000,00); Seções 3.19 e 3.20 com nota sobre escopo das competências. |
| 2.0 | 11 casos (+ Estação VIP Vigilância 2021/2022/2024 – Edivan/Isrhael) | Preposição "na" antes de logradouro na qualificação; exceção ao subtítulo sem anos-base para vigências não contíguas; "de X a Y" aceitável também para faixas de meses (3+); verificação de numeração correta das Resoluções (1.329/2017 não "1.328/2017"; inclusão obrigatória da 1.347/2021 na tese de rotatividade); "benefício tributário" em vez de "desconto tributário" (Seção 1.2); "contra legem" em vez de "a contrário legis" (Seção 1.6); uso de barras "/" em textos formais → substituir por conjunção; "Juízo" com maiúscula como referência institucional; arredondamento de percentuais de rotatividade para duas casas decimais; identificação individual de benefícios por vigência nas telas do FAP; nome do tópico de rotatividade com "TAXA MÉDIA DE ROTATIVIDADE –" no início; precisão técnica do argumento de restabelecimento (evitar afirmar que o 2º benefício "não deve impactar frequência e gravidade"); IN nº 77/2015 "e seguintes" pode ser mantida quando a locução cobre implicitamente a normativa atual; valor da causa R$ 10.000,00 para caso com poucos benefícios e empresa de menor porte; hipótese refinada da Seção 6 com terceira variável (porte do pedido). |"""

CASES_TEXT = r"""
# CASOS DE REFERÊNCIA — REVISÃO FAP
**Base de exemplos curados para calibração do Agente Revisor FAP**
*Atualizado após Caso 11 (Estação VIP Vigilância e Transporte de Valores Ltda. — vigências 2021, 2022 e 2024)*

---

## CASO 1 — APM TERMINALS PECÉM S.A.
Advogado júnior: João | Revisor: Isrhael
Vigências: 2022, 2023 e 2026 | Teses: Acidente de trajeto (B91 e B94) + Outra empresa | Manual gerado: v1.0

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "durante o exercício das atividades laborais" | "em decorrência das atividades laborais" | 1.3 — nexo causal vs. temporal |
| "erro cometido pela Previdência Social" | "erro cometido pela administração pública" | 1.2 — terminologia |
| "aposentadoria por invalidez" | "aposentadoria por incapacidade permanente" | 1.2 — nomenclatura vigente |
| Referências a precedentes sem citar os processos | Precedentes concretos com número de processo | 1.5 — fundamentação jurídica |

### Decisões de julgamento do Isrhael
- Priorizou: erros de nexo causal e terminologia como críticos; corrigiu todos os usos de "Previdência Social" como responsável pelo erro.
- Deixou passar: conectores temporais menores que não comprometiam o argumento.
- Tom e nível de detalhe: reformulações cirúrgicas por todo o documento; sem reescrita de parágrafos inteiros.

### Padrões novos (não estavam no manual antes deste caso)
- Terminologia "administração pública" vs. "Previdência Social" → incorporado à Seção 1.2
- Expressões causais vs. temporais → incorporado à Seção 1.3
- Estrutura geral do banco de fundamentações (Seção 4) → criada neste caso

---

## CASO 2 — MONIARI SUPERMERCADOS LTDA.
Advogado júnior: Edivan | Revisor: Isrhael
Vigências: 2021 a 2025 | Teses: Acidente de trajeto, Outra empresa, Restabelecimento, Natureza do benefício, DIB=DCB | Manual gerado: v1.1

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| *in **verbis*** (negrito misturado ao itálico) | *in verbis* | 1.6 — formatação de expressões latinas |
| *In **casu*** | *In casu* | 1.6 — formatação de expressões latinas |
| Referência a documento "acima" quando estava abaixo | Referência corrigida para "abaixo" | 1.3 — referências dêiticas |
| "CNIS" (sem identificar qual benefício) | "CNIS – Benefício B91 nº XXXXXXXXXX" | 1.1 — identificação de documentos |
| Coluna "Duração (dias)" com valor "0,000" | Coluna "Duração" com valor "0 dias" | 1.6 — formatação de tabelas |
| "da base de cálculo dos índices FAP, na vigência 2021" | "da base de cálculo do índice FAP, na vigência 2021" | 1.6 — concordância singular/plural |
| Vigências 2021 e 2022 em linhas separadas para o mesmo benefício com mesmos índices | "2021 \| 2022" em linha única | 1.6 — vigências múltiplas |

### Decisões de julgamento do Isrhael
- Priorizou: formatação de expressões latinas (corrigiu todas as ocorrências); concordância singular/plural dos índices; identificação de documentos.
- Deixou passar: alguns conectores temporais mecânicos que não comprometiam o argumento.
- Tom e nível de detalhe: correções pontuais, sem comentário explícito no documento revisado.

### Padrões novos (não estavam no manual antes deste caso)
- Formatação de expressões latinas (*in verbis*, *in casu*) → incorporado à Seção 1.6
- Referências dêiticas → incorporado à Seção 1.3
- Identificação de documentos com nome do benefício → incorporado à Seção 1.1
- Formatação de tabelas (unidades nos valores, não no cabeçalho) → incorporado à Seção 1.6
- Concordância "do índice" vs. "dos índices" → incorporado à Seção 1.6
- Vigências múltiplas na mesma linha → incorporado à Seção 1.6
- Seções Hierarquia de Tópicos (5) e Valor da Causa (6) → criadas neste caso

### Contexto adicional
- Empresa de pequeno/médio porte; valor da causa R$ 100.000,00 — primeira referência para calibrar o padrão de valor inferior.

---

## CASO 3 — VALID SOLUÇÕES S.A.
Advogado júnior: João | Revisor: Isrhael
Vigências: 2021 a 2025 | Teses: Acidente de trajeto, Natureza do benefício, Restabelecimento, Outra empresa, Outro estabelecimento, Nexo afastado, Pré-FAP, Erro no número médio de vínculos | Manual gerado: v1.3

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "Em decorrência do acidente NÃO relacionado ao trabalho, concedeu-se o B91..." | "Embora a lesão não seja relacionada com o trabalho, a administração pública incorreu em erro ao atribuir natureza acidentária ao benefício, tendo concedido o B91..." | 1.3 — nexo causal falso na tese de natureza |
| "Em seguida, o segurado..." (conector automático sem acréscimo informativo) | Conector suprimido ou substituído por conteúdo mais preciso | 1.3 — conectores temporais mecânicos |
| Pedido de diligência listando apenas 1 dos 3 benefícios do tópico | Pedido de diligência listando todos os benefícios do tópico | 1.4 — pedidos de diligência completos |
| "A tela do FAP abaixo aponta a inclusão do benefício acidentário B94, na base de cálculo..." | "A tela do FAP abaixo aponta a inclusão do benefício B94 nº 2077361098, na base de cálculo..." | 1.4 — especificação do número do benefício |
| "são apresentadas os seguintes documentos" (um único documento) | "é apresentado o documento a seguir" | 1.4 — "os seguintes documentos" vs. "o documento" |
| Vigências 2023 e 2024 em linhas separadas para o mesmo benefício com mesmos índices | "2023 \| 2024" em linha única | 1.6 — vigências múltiplas |
| Tópico de Erro no Número Médio de Vínculos sem tabela identificando benefício e vigência | Tabela incluída | 1.6 — tabela ausente |
| "as perícia médica judicial apresentou" (dois laudos, singular incorreto) | "as perícias médicas judiciais apresentaram" | 1.6 — concordância em número de laudos |
| "benefício concedido a segurada" | "benefício concedido à segurada" | 1.6 — crase em "à segurada" |
| Último item de lista de diligências encerrado com ponto e vírgula | Último item encerrado com ponto final | 1.6 — ponto final no último item |
| **"O prazo de vacatio legis..."** (dentro de negrito sem itálico no latim) | **"O prazo de *vacatio* legis..."** | 1.6 — expressões latinas em itálico dentro de negrito |

### Decisões de julgamento do Isrhael
- Priorizou: nexo causal falso na tese de natureza do benefício (tratou como crítico); completude dos pedidos de diligência.
- Deixou passar: algumas ocorrências de "Posteriormente" mecânico quando o contexto já deixava clara a sequência.
- Tom e nível de detalhe: neste caso mais longo, Isrhael foi mais seletivo — concentrou energia nas correções de maior impacto jurídico.

### Padrões novos (não estavam no manual antes deste caso)
- Nexo causal faldo na tese de natureza do benefício → incorporado à Seção 1.3
- Conectores temporais mecânicos → incorporado à Seção 1.3
- Pedidos de diligência — completude por tese → incorporado à Seção 1.4
- Especificação do número do benefício em referências a telas → incorporado à Seção 1.4
- "Os seguintes documentos" vs. "o documento" → incorporado à Seção 1.4
- Tabela ausente → incorporado à Seção 1.6
- Concordância em número de laudos/perícias → incorporado à Seção 1.6
- Crase em "à segurada/à empresa" → incorporado à Seção 1.6
- Ponto final no último item de lista → incorporado à Seção 1.6
- Expressões latinas em itálico dentro de negrito → incorporado à Seção 1.6

---

## CASO 4 — DOHLER S.A. (vigências 2015, 2016, 2019 e 2020)
Advogado júnior: João | Revisor: Isrhael
Vigências: 2015, 2016, 2019 e 2020 | Teses: NTP duplicado, Acidente de trajeto, B31 previdenciário, Conversão judicial de B91 em B31, Natureza do benefício, Benefício revogado, Restabelecimento, Outra empresa, Concessão concomitante, DIB=DCB, Nexo afastado, Acidente pré-FAP | Manual gerado: v1.4

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "Rua X, 925" (sem "nº" antes do número) | "Rua X, nº 925" | 1.1 — grafia de logradouros |
| Data de transmissão da contestação no texto diferia do documento anexado | Data corrigida para corresponder ao documento | 1.1 — data de transmissão da contestação |
| Texto mencionava apenas vigências 2015 e 2016 na introdução da contestação | Texto corrigido para mencionar "nas vigências de 2015, 2016, 2019 e 2020" | 1.1 — vigências na introdução da contestação |
| Documentos de 1ª e 2ª instâncias intitulados apenas "Dados da contestação" | "Dados da contestação – 1ª instância" e "Dados da contestação – 2ª instância" | 1.1 — identificação de instâncias |
| "o segurado" (referindo-se a segurada do gênero feminino) | "a segurada" | 1.1 — gênero gramatical |
| Coluna "CAT" com número da CAT nas tabelas de NTP | Coluna "Tipo" com código da espécie (B91, B92, B94) | 1.1 — tipificação da espécie vs. CAT |
| "sofreu acidente, o que causou a lesão..." | "sofreu acidente, o qual causou a lesão..." | 1.3 — pronome relativo |
| "foi encontrado 6 (seis) benefícios..." | "foram encontrados 6 (seis) benefícios..." | 1.6 — concordância "foi encontrado" vs. "foram encontrados" |
| Negrito em palavras gramaticais isoladas em citações legais ("**a**", "**o**") | Negrito apenas no trecho juridicamente relevante como unidade | 1.6 — negrito indevido em palavras gramaticais |
| Dupla quebra de linha desnecessária antes de conclusão de parágrafo | Espaçamento único, conclusão integrada ao parágrafo anterior | 1.6 — espaçamento entre parágrafos |
| "**Em síntese**," como conector de parágrafo simples | Marcador suprimido ou parágrafo integrado | 1.6 — "Em síntese" como marcador |
| "são apresentadas provas suficientes para..." | "são apresentadas provas para..." | 1.6 — verbosidade ("suficientes") |
| Pedido de diligência para tópico de natureza do benefício não incluído | Pedido de diligência incluído para todas as teses com lacuna documental | 1.4 — cobertura de todas as teses |
| Narrativa do acidente de trajeto com apenas B91 e B94 sem descrever B91 intermediário | Narrativa cobrindo toda a cadeia: B91 originário → B91 intermediário → B94 | Seção 2 — regra estendida de conexão |
| Tese de B92 decorrente de ação judicial sem petição inicial do processo como documento | Petição inicial do processo judicial incluída como documento adicional | Seção 3.1 — documentos adicionais B92 judicial |
| Narrativa das instâncias do processo administrativo condensada em um parágrafo | Dois parágrafos separados: um para 1ª instância (com data de transmissão) e outro para 2ª instância (com data de publicação no DOU) | 1.4 — identificação das instâncias na narrativa |

### Decisões de julgamento do Isrhael
- Priorizou: identificação de instâncias (1ª e 2ª) nos documentos e na narrativa — tratou como crítico; gênero gramatical dos segurados; tipificação da espécie nas tabelas de NTP.
- Deixou passar: algumas instâncias de "Previdência Social" no tópico de concomitância (possível aceitação contextual — monitorar).
- Tom e nível de detalhe: neste caso mais complexo (12 teses, 4 vigências não contíguas), Isrhael priorizou as correções com maior impacto no argumento e no escopo da ação.

### Padrões novos (não estavam no manual antes deste caso)
- "nº" antes de número de logradouro → incorporado à Seção 1.1
- Data de transmissão da contestação administrativa → incorporado à Seção 1.1
- Vigências na introdução da seção de contestação → incorporado à Seção 1.1
- Instâncias administrativas na narrativa e nos títulos de documentos → incorporado às Seções 1.1 e 1.4
- Gênero gramatical dos segurados → incorporado à Seção 1.1
- Tipificação da espécie vs. CAT nas tabelas de NTP → incorporado à Seção 1.1
- Pronome relativo "o qual" vs. "o que" → incorporado à Seção 1.3
- Concordância "foi encontrado" vs. "foram encontrados" → incorporado à Seção 1.6
- Negrito indevido em palavras gramaticais isoladas → incorporado à Seção 1.6
- Espaçamento desnecessário entre parágrafos → incorporado à Seção 1.6
- "Em síntese" como marcador de destaque → incorporado à Seção 1.6
- "Provas suficientes" → incorporado à Seção 1.6
- Pedidos de diligência para todas as teses com lacuna → incorporado à Seção 1.4
- Regra estendida de conexão para cadeia com múltiplos B91 → incorporado à Seção 2
- Petição judicial como documento adicional para B92 → incorporado à Seção 3.1

### Contexto adicional
- Empresa têxtil de Blumenau/SC, grande porte. Caso mais complexo da base até o momento: 12 teses distintas e 4 vigências não contíguas. Valor da causa R$ 200.000,00 — confirma o padrão para empresas de grande porte com múltiplas teses.
- O tópico de NTP duplicado neste caso definiu sua posição como primeiro na hierarquia de tópicos quando presente (Seção 5).

---

## CASO 5 — ELECTRO AÇO ALTONA S.A.
Advogado júnior: João | Revisor: Isrhael
Vigências: 2022, 2023 e 2024 | Teses: Outra empresa (B91 e B94), Acidente de trajeto (B91 e B94), Restabelecimento (B91), Concessão concomitante B91/aposentadoria, Concessão concomitante B91/B91, Concessão concomitante B94/aposentadoria, Acidente pré-FAP (B94) | Manual gerado: v1.5

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| CEP 89.257-000 (endereço da Autora na qualificação) | CEP 89.030-900 | 1.1 — dados factuais (CEP) |
| "enquanto exercia suas funções, o segurado sofreu um acidente" (na empresa responsável) | "enquanto exercia suas funções, o empregado sofreu um acidente" | 1.2 — "segurado" vs. "empregado" |
| Vínculo com a Brasilux "no período de 01/09/2021 a, ao menos, 28/02/2022" | "no dia 01/09/2021, o segurado foi admitido na empresa Brasilux" (data de rescisão suprimida por incerteza probatória) | 1.3 — omissão de data incerta de rescisão |
| "DIB em 13/09/2021" (sigla sem extenso na primeira ocorrência do tópico) | "Data de Início do Benefício (DIB) em 13/09/2021" | 1.6 — clareza (apresentação de siglas) |
| *In **casu*** / *in **verbis*** (negrito misturado ao itálico) em múltiplos trechos | *In casu* / *in verbis* | 1.6 — formatação de expressões latinas |
| Exemplo de B91 trajeto: segurado Sandro (vigência 2024 apenas, tela de uma vigência) | Exemplo: segurado Rodinei (vigências 2023 e 2024, telas de ambas as vigências) | 1.4 — telas do FAP para todas as vigências |
| "exclusão de 3 (três) benefícios B94" de trajeto (tabela tinha 4) | "exclusão de 4 (quatro) benefícios B94" | 1.1 — quantidade de benefícios nas conclusões |
| Conclusão do tópico B94 trajeto restrita a "vigência 2024" (B94 nº 1956735590 é vigência 2022) | "índices FAP nas vigências e estabelecimento indicados na tabela supra e nos pedidos" | 1.1 — escopo de vigências |
| Coluna "Diferença entre DCB e DIB (dias)" com valor "0" | Coluna "Diferença entre DCB e DIB" com valor "0 dias" | 1.6 — formatação de tabelas |
| "Para comprovar a inclusão nas vigências 2024 e 2025" / "Vigência 2025" (fora do escopo) | "Para comprovar a inclusão na vigência 2024" (2025 não é objeto da ação) | 1.1 — escopo das vigências da ação |
| "dupla contagem nos índices de frequência, gravidade e custo" (restabelecimento, ambos na mesma vigência) | "dupla contagem nos índices de frequência e gravidade" | 1.3 — precisão técnica do restabelecimento |
| Benefício 6308808680 em linha única com índices de 2023 aplicados à vigência 2022 também | Linha 2022: "Frequência e gravidade" / Linha 2023: "Frequência, gravidade e custo" (índices distintos por vigência) | 1.6 — vigências múltiplas com índices distintos |
| "por se tratar de restabelecimentos" (sujeito plural) | "por se tratarem de restabelecimentos" | 1.6 — concordância de número |
| Nota de rodapé nº 2: "A vigência 2024 foi calculada no ano de 2023, considerando os insumos apurados nos dois anos anteriores – 2022 e 2021" | "A vigência 2022 foi calculada no ano de 2021, considerando os insumos apurados nos dois anos anteriores – 2020 e 2019" | 1.1 — nota de rodapé correspondente à vigência discutida |
| "requereu e obteve judicialmente o benefício B91 nº 6366550011, conforme sentença..." | "em sentença, foi concedido o benefício B91 nº 6366550011, conforme os documentos a seguir" | 1.6 — verbosidade |
| "cessou o benefício B94 na respectiva DIB em 03/11/2020" | "cessou o benefício B94 na respectiva DIB, em 03/11/2020, fixou tanto a DIB quanto a DCB nessa mesma data (03/11/2020)" | 1.6 — clareza |

### Decisões de julgamento do Isrhael
- Priorizou: erro de quantidade de benefícios no pedido (3 vs. 4 B94 de trajeto) e vigência errada na conclusão do tópico — críticos por afetarem diretamente o escopo do pedido; erro de índice no restabelecimento (custo indevido quando ambos estão na mesma vigência); nota de rodapé com vigência errada; referência à vigência 2025 fora do escopo; CEP incorreto.
- Deixou passar: uso de "a Previdência Social" no tópico de concessão concomitante B94/aposentadoria — possível aceitação contextual quando a referência é ao ato de concessão.
- Tom e nível de detalhe: reformulações pontuais e cirúrgicas; não reescreveu parágrafos inteiros.

### Padrões novos (não estavam no manual antes deste caso)
- CEP como campo de verificação obrigatória → incorporado à Seção 1.1
- Escopo de vigências da ação (proibição de referências a vigências fora do objeto) → incorporado à Seção 1.1
- Quantidade de benefícios nas conclusões de tópico → incorporado à Seção 1.1
- Precisão técnica do impacto do restabelecimento (depende da posição nas vigências) → incorporado às Seções 1.1, 1.3 e 3.3
- "Segurado" vs. "empregado" na narrativa de outra empresa → incorporado à Seção 1.2
- Omissão de data incerta de rescisão de vínculo → incorporado à Seção 1.3
- Vigências múltiplas com índices distintos por vigência — separar em linhas → incorporado à Seção 1.6
- Telas do FAP devem cobrir todas as vigências contestadas → incorporado à Seção 1.4
- Nota de rodapé de vigência deve corresponder à vigência efetivamente discutida → incorporado à Seção 1.1

### Contexto adicional
- Empresa metalúrgica de Jaraguá do Sul/SC, médio/grande porte. 7 teses, 3 vigências contíguas. Valor da causa R$ 200.000,00 — confirma o padrão para empresas de grande porte com múltiplas teses.
- Peculiaridade do caso: presença simultânea de três modalidades distintas de concessão concomitante (B91/aposentadoria, B91/B91 e B94/aposentadoria).
- Observação sobre "Previdência Social" vs. "administração pública": Isrhael manteve "a Previdência Social" ao descrever o ato de concessão do benefício. Possível distinção aceitável: "Previdência Social" quando se refere ao ato de concessão de benefício (função fim da autarquia); "administração pública" quando se refere ao cálculo incorreto do FAP (função acessória). Hipótese confirmada no Caso 7.

---

## CASO 7 — DOHLER S.A. (vigências 2021 e 2022)
Advogado júnior: Guilherme | Revisor: Isrhael
Vigências: 2021 e 2022 | Teses: Acidente de trajeto (B91 e B94), Outra empresa (B91), B31 previdenciário, Restabelecimento (B91), Concessão concomitante B91/aposentadoria (B46), Nexo afastado (B91, B92, B94) | Manual gerado: v1.6.1

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "DOHLER S.A," (sem ponto na razão social) | "DOHLER S.A." | 1.1 — dados factuais (razão social) |
| "nas vigências de 2021 a 2022" (dois anos) | "nas vigências de 2021 e 2022" | 1.1 — escopo das vigências |
| *in **verbis*** / *In **casu*** (negrito misturado ao itálico) em todas as ocorrências | *in verbis* / *In casu* | 1.6 — formatação de expressões latinas |
| "a transmissão, no dia 05/12/2023, da contestação administrativa" (sem identificação de instância) | "a transmissão, em 05/12/2023, da contestação administrativa em 2ª instância" | 1.1 e 1.4 — identificação de instância; "no dia" → "em" |
| "a contestação [...] suspendeu o prazo prescricional, que só recomeçou a contar após a publicação [...] em 20/05/2024" (data inconsistente com o restante do documento) | data suprimida | 1.1 — consistência interna (datas) |
| "Comunicação de Acidente de Trabalho (CAT)." (sem número, sem dêitica) no tópico de B94 trajeto | "Comunicação de Acidente de Trabalho (CAT) nº 2012.100166.0/01 apresentada a seguir." | 1.4 — identificação da CAT; 1.3 — dêiticas |
| "conforme os documentos emitidos pelo INSS" (dêitica incorreta — documentos seguem abaixo) | "conforme os documentos apresentados a seguir" | 1.3 — referências dêiticas |
| "A comparação entre a data do acidente (16/01/2017) e a data do início do benefício em 16/02/2017, comprova..." | "A comparação entre a data do acidente, em 16/01/2017, e a data do início do benefício, em 16/02/2017, comprova..." | 1.6 — pontuação (adjuntos adverbiais de tempo) |
| "em virtude das lesões geradas pelo acidente de trajeto" | "em decorrência das lesões geradas pelo acidente de trajeto" | 1.3 — expressões causais |
| "na base de cálculo dos índices FAP, na vigência 2021" (uma vigência, plural) | "na base de cálculo do índice FAP, na vigência 2021" | 1.6 — concordância singular/plural |
| 6 benefícios B31 (incluindo MARLENE MENDES nº 6231900642, com NIT de outro segurado duplicado para GRASIELA) | 5 benefícios B31 (MARLENE MENDES removida; NIT da GRASIELA corrigido: 12582729878 → 13243129728) | 1.1 — dados factuais (NIT; quantidade de benefícios) |
| "da segurada" referindo-se a VALCIR JOSE FUCK (masculino) | "do segurado" | 1.1 — gênero gramatical dos segurados |
| "da empregada" referindo-se a ADAO ANTUNES (masculino) | "do empregado" | 1.1 — gênero gramatical dos segurados |
| "direito da segurada" referindo-se a ADAO ANTUNES | "direito do segurado" | 1.1 — gênero gramatical dos segurados |
| Telas da vigência 2021 em duas linhas separadas para o mesmo par de benefícios | "Vigência 2021 – 1º B91 nº 6238971782 e 2º B91 nº 6276204300" (linha única) | 1.4 — identificação de documentos (telas do FAP) |
| Tabela de pedidos do tópico 7 com itens desordenados e vigências separadas para benefício com mesmos índices | Tabela reordenada; B91 nº 6287061522 com 2021 e 2022 em linha única (índices idênticos) | 1.6 — vigências múltiplas na mesma linha |
| Tabela de pedidos do tópico 8 com benefício fragmentado em duas linhas | Benefício B91 nº 6262497076 com vigências 2021 e 2022 em linha única | 1.6 — formatação de tabelas |
| "a doença incapacitante não é relacionada à empresa Autora" (pedido do tópico 5) | "o acidente de trabalho não é relacionado à empresa Autora" | 1.3 — formulação do pedido |
| "Conforme demonstrado nos documentos acima..." | "Conforme demonstram os documentos acima e aqueles anexados à petição inicial..." | 1.6 — concordância verbal e estilo |
| Linha em branco desnecessária entre CTPS e CNIS no tópico 5 | Espaçamento único | 1.6 — espaçamento entre parágrafos |
| R$ XXX (XXX) | R$ 200.000,00 (duzentos mil reais) | 1.1 e 6 — valor da causa |

### Decisões de julgamento do Isrhael
- **Priorizou:** Correções de gênero gramatical (3 ocorrências de "segurada/empregada" para segurado masculino ADAO ANTUNES e VALCIR FUCK); remoção do benefício da MARLENE MENDES com correção simultânea do NIT duplicado da GRASIELA — tratou como crítico por comprometer dados factuais e a quantidade dos pedidos; correção da data inconsistente (20/05/2024) por supressão; formatação *in verbis*/*in casu* (corrigiu todas as ocorrências no documento).
- **Deixou passar:** (a) Uso de "previdência social" (minúsculo) em dois trechos do tópico 6 (B31) referindo-se ao ato de concessão do benefício — **confirma a hipótese do Caso 5**: "Previdência Social" é aceitável quando a referência é ao ato de concessão, não ao cálculo do FAP; (b) "o segurado requereu e obteve judicialmente" no tópico 8 — forma aceitável neste contexto; (c) "frequência, gravidade e custo" no corpo do texto narrativo do tópico 7 — corrigiu apenas na tabela de pedidos, não no texto (o texto estava dentro de citação jurisprudencial, que não se altera).
- **Tom e nível de detalhe:** Reformulações cirúrgicas e pontuais; sem reescrita de parágrafos inteiros. Correções de gênero e NIT feitas silenciosamente. Remoção de benefício da MARLENE MENDES sem comentário explícito.

### Nota técnica sobre os índices do restabelecimento — Item 29 (corrigido)
Na análise bruta inicial, o Item 29 indicou como possível erro do Isrhael o fato de ele ter mantido "frequência, gravidade e custo" na tabela de pedidos para alguns benefícios de restabelecimento. Após confirmação direta com Isrhael, a regra correta é:

- **Ambos os benefícios na mesma vigência** → o segundo impacta apenas **frequência e gravidade**.
- **Benefícios em vigências diferentes** → o segundo impacta **frequência, gravidade e custo**.

A tabela de pedidos do tópico 7 estava, portanto, **correta**: Isrhael aplicou a regra benefício a benefício, atribuindo "frequência e gravidade" quando os dois benefícios coincidem na mesma vigência e "frequência, gravidade e custo" quando o segundo benefício estreia em vigência nova. O que pareceu inconsistência era, na verdade, aplicação precisa da regra técnica. A regra foi incorporada às Seções 1.1, 1.3 e 3.3 do manual na versão 1.6.1.

### Padrões novos (não estavam no manual antes deste caso)
- **Ponto após "S.A." na razão social** → incorporado à Seção 1.1
- **"de X e Y" vs. "de X a Y"** para designar apenas dois anos de vigência — preferência por "e" → incorporado à Seção 1.1
- **Pontuação com datas em adjuntos adverbiais** — "a data do acidente, em DD/MM/AAAA," → incorporado à Seção 1.6
- **Identificação da CAT com número** ao mencioná-la pela primeira vez no tópico → incorporado à Seção 1.4
- **Fusão de referências a telas do FAP** quando dois benefícios aparecem na mesma tela de vigência → incorporado à Seção 1.4
- **NIT duplicado entre segurados** na mesma tabela como erro a verificar → incorporado à Seção 1.1
- **"No dia [data]" → "em [data]"** (maior concisão antes de datas específicas) → incorporado à Seção 1.6
- **Remoção de benefício do tópico quando não há comprovação suficiente** — afeta quantidade do pedido → incorporado às Seções 1.1 e 1.4
- **Regra técnica dos índices do restabelecimento confirmada e corrigida** (mesma vigência → f+g; vigências diferentes → f+g+c) → incorporado às Seções 1.1, 1.3, 3.3 e banco de fundamentações

### Contexto adicional
- Segunda petição da Dohler S.A. na base de casos (as vigências 2015/2016/2019/2020 foram o Caso 4). Esta petição, do advogado Guilherme (não João), cobre 2021 e 2022. Empresa têxtil de Blumenau/SC, grande porte. 6 teses, 2 vigências contíguas. Valor da causa R$ 200.000,00 — confirma o padrão.
- A remoção da MARLENE MENDES indica que Isrhael verifica a suficiência documental antes de aprovar cada benefício do tópico — benefícios sem documentação suficiente são excluídos mesmo que o advogado júnior os tenha listado.
- A hipótese do Caso 5 sobre "Previdência Social" vs. "administração pública" fica consolidada neste caso: distinção aceitável quando a referência é ao ato de concessão.

---

## CASO 9 — MARFRIG GLOBAL FOODS S.A.
Advogado júnior: Guilherme | Revisor: Isrhael
Vigências: 2022 e 2023 | Teses: Acidente de trajeto B91 (3) e B94 (2), Outra empresa B91/B94 (7), Outro estabelecimento B94 (1), Restabelecimento B91 (7), B31 previdenciário (2), Acidente não relacionado ao trabalho B91/B94 (4), Concessão concomitante B91 (2), Nexo afastado B91 (6), Apuração do índice de custo B94 (1), Sobreposição de dois B91 (1) | Manual gerado: v1.8

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "MARFRIG GLOBAL FOODS S.A," (sem ponto) | "MARFRIG GLOBAL FOODS S.A." | 1.1 — razão social |
| "Avenida Queiroz Filho, nº 10560" | "Avenida Queiroz Filho, nº 1.560" (número correto com ponto separador de milhar) | 1.1 — dados factuais (endereço) |
| "CEP 05319-000" | "CEP 05.319-000" (ponto separador entre 2º e 3º dígitos) | 1.1 — dados factuais (CEP) |
| "arts. 7º, inc. XXVIII e 195, § 9º, na Lei nº 8.212/91, ... nas Resoluções nº 1.316/10" | "art. 7º, inciso XXVIII, e art. 195, § 9º, na Lei nº 8.212/1991, ... nas Resoluções nºs 1.316/2010" | 1.1 e 1.6 — anos por extenso; "inciso" em vez de "inc."; "nºs" no plural |
| "FAP (2022 e 2023)" (subtítulo) | "FAP (vigências de 2022 e 2023 – anos-base de 2020 e 2021)" | 1.1 — escopo das vigências; padrão novo |
| "no cálculo dos índices FAP" | "no cálculo dos índices do FAP" (com artigo "do") | 1.6 — redação; padrão novo |
| Objeto da ação sem notas de rodapé explicando anos-base | Vigências referenciadas com notas de rodapé: "Vigência 2022: ano-base 2020" e "Vigência 2023: anos-base 2021 e 2020" | Padrão novo |
| "auxílios-doença e outros benefícios" (Síntese Fática) | "auxílios por incapacidade temporária e outros benefícios" | 1.2 — terminologia |
| "através de um fator multiplicador" | "por intermédio de um fator multiplicador" | 1.6 — redação; padrão novo |
| "erros graves cometidos pela administração pública" (minúsculas) | "graves erros cometidos pela Administração Pública" (maiúsculas; ordem invertida) | 1.6 — redação; padrão novo |
| Exemplo da Síntese Fática usava vigência 2020 (FAP calculado em 2019) | Exemplo atualizado para vigência 2023 (calculado em 2022), correspondente ao caso concreto | 1.1 — consistência interna |
| "Comunicação de Acidente de Trabalho (CAT)." (sem número, sem dêitica) | "Comunicação de Acidente de Trabalho (CAT) nº 2021.057499.2/01 apresentada a seguir." | 1.4 — identificação da CAT; 1.3 — dêiticas |
| Tópico B91 trajeto: paradigma = ZILDA LEITE VIEIRA DE NOVAES (cadeia B31→B91, mais complexa) | Paradigma trocado para JOZYELY CONSTANTINO BRANDÃO (acidente → B91 diretamente, mais simples) | Seção análoga ao padrão do Caso 8 |
| Tópico 4: "foram encontrados 3 (três) benefícios" | "foram encontrados 7 (sete) benefícios" — Isrhael reclassificou benefícios de outros tópicos E acrescentou SIDNEI MORAES DE OLIVEIRA (B91 nº 6363783120) que não existia na versão Guilherme | 1.1 — quantidade de benefícios; padrão novo |
| Tópico 5 com 2 benefícios (BRUNO e SANDRA) — BRUNO classificado como "outro estabelecimento" | BRUNO reclassificado para Tópico 4 ("outra empresa") — CNPJ raiz diferente (04.748.631 vs 03.853.896). Tópico 5 com apenas SANDRA | 1.1; Seções 3.4 e 3.5; padrão novo |
| CNPJ do estabelecimento da SANDRA: "03.853.896/0017-07" | "03.853.896/0014-07" (número correto) | 1.1 — dados factuais (CNPJ) |
| Narrativa do ANDRE GABRIEL: "foi diagnosticado com Hérnia Inguinal" | "enquanto estava desempregado, o segurado foi submetido à cirurgia de HÉRNIA INGUINAL" — informação crítica (desempregado) acrescentada no início | 1.3 — cadeia de causalidade; padrão novo |
| "Carteira de Trabalho e Previdência Social (CTPS)" | "Carteira de Trabalho Digital" | 1.2 — terminologia; padrão novo |
| "Folha Ponto" (Tópico 6) | "Marcações de Ponto" | 1.6 — precisão terminológica |
| Item 7 tabela Restabelecimento: vigências do 1º B91 (5486846505) = "2023" | "2013 | 2014" (vigências corretas do benefício com DIB em 31/10/2011) | 1.1 — dados factuais; escopo das vigências |
| "proteção previdenciária da segurada" (JOAO GABRIEL, masculino) | "proteção previdenciária do segurado" | 1.1 — gênero gramatical |
| Telas do FAP do restabelecimento: apenas vigências 2022 e 2023 | Acrescentada tela da vigência 2021 (onde o 1º B91 6270406262 também aparece) | 1.4 — telas do FAP para todas as vigências |
| "dupla contagem nos índices de frequência, gravidade e custo" (restabelecimento, todos os casos) | Tabela de pedidos aplica regra por benefício: mesma vigência → f+g; vigências diferentes → f+g+c. SEBASTIAO (B91 6327826613, vigência 2023, 1º B91 nas vigências 2013/2014) → "frequência, gravidade e custo" | 1.1 e 1.3 — precisão técnica do restabelecimento |
| "o custo da desídia do INSS em não restabelecer" | "verifica-se que o quadro incapacitante permanece vinculado ao mesmo evento" — supressão de "desídia" | 1.6 — tom; padrão novo |
| Tópico 8: 2 benefícios | Tópico 8: 4 benefícios — absorveu ANTONIO MARCOS (extinto Tópico 10) e ANDRE GABRIEL subsidiariamente | 1.1; Seção 5; padrão novo |
| Tópico 10 (Erro de Implantação, ANTONIO MARCOS B94 nº 6347048519): tópico próprio | Tópico eliminado — ANTONIO MARCOS reclassificado para Tópico 8 (acidente não relacionado ao trabalho) | Seção 3.13 → Seção 3.10; padrão novo |
| "art. 312, caput, da IN nº 77/2015" / "art. 528, IX, da IN nº 77/2015" | "art. 337, caput, da IN nº 128/2022" / "art. 639, XIII, da IN nº 128/2022" | 1.2 — referências normativas; padrão novo |
| "art. 3 da Instrução Normativa – IN nº 33/2008 do INSS" | "art. 3º da Instrução Normativa (IN) nº 31/2008 do INSS" | 1.2 — referências normativas |
| Número do processo MARIA JOSE: "0801216-06.2022.8.12.0026/TJMS" | "0801394-86.2021.8.12.0026/TJMS" | 1.1 — dados factuais |
| Acórdão do TRF4 5006494-50.2024.4.04.7000/JFPR citado integralmente | Suprimidos itens 1, 2, 3, 6 e 8 do acórdão; mantidos apenas os itens 5 e 9 (diretamente relevantes) | 1.6 — verbosidade; padrão novo |
| Tópico 11 Custo: sem explicação de por que a projeção é inadequada | Acrescentado: "O custo do B94 somente deve ser projetado para fins de cálculo do FAP quando não se conhece a sua data de cessação... no presente caso, a data de cessação do B94 é conhecida: 14/12/2020." | 1.4 — completude; padrão novo |
| IN nº 77/2015, art. 309 (Sobreposição) | IN nº 128/2022, art. 347 (artigo correspondente na norma vigente) | 1.2 — referências normativas |
| Pedidos sem pedidos subsidiários explicitados | Pedidos com subsidiários identificados: "Subsidiariamente, não sendo esse o entendimento de V. Exa., requer-se a exclusão do benefício B94 nº 6309787873, considerando que o acidente de trabalho não tem relação com a empresa Autora – item 4 da petição inicial." | 1.4 — completude dos pedidos; padrão novo |
| Diligências listando todos os benefícios inclusive os com documentação completa | Diligências focadas apenas nos benefícios que carecem de documentação adicional | 1.4 — pedidos de diligência |
| "R$ XXX (XXX)" | "R$ 200.000,00 (duzentos mil reais)" | 1.1 e Seção 6 — valor da causa |

### Decisões de julgamento do Isrhael
- **Priorizou:** Reorganização estrutural profunda — eliminou Tópico 10 (Erro de Implantação) e absorveu o benefício no Tópico 8; reclassificou BRUNO de "outro estabelecimento" para "outra empresa"; adicionou benefício omitido pelo Guilherme (SIDNEI MORAES); corrigiu CNPJ errado da SANDRA (0017-07 → 0014-07); atualizou referências normativas (IN 77 → IN 128); corrigiu vigências erradas na tabela de restabelecimento; inseriu anos-base no objeto da ação.
- **Deixou passar:** Usos de "Previdência Social" no contexto de ato de concessão (padrão consolidado); estrutura básica dos argumentos jurídicos; citações jurisprudenciais corretas.
- **Tom e nível de detalhe:** Reformulações de médio e grande porte — não apenas correções pontuais, mas reorganização estrutural de tópicos, adição de benefício novo, reclassificação de teses. Caso mais complexo da base em termos de reorganização estrutural pelo revisor.

### Padrões novos (não estavam no manual antes deste caso)
- **CEP com formatação XX.XXX-XXX** (ponto separador após 2º dígito) → incorporado à Seção 1.1
- **Número de logradouro acima de mil com ponto separador** ("nº 1.560", não "nº 1560") → incorporado à Seção 1.1
- **Anos das leis e resoluções por extenso** (8.212/1991 não 8.212/91; 1.329/2017 não 1.329/17) → incorporado à Seção 1.1
- **"inciso" por extenso** em vez de "inc." em referências normativas → incorporado à Seção 1.1
- **"nºs" no plural** para múltiplos números de resoluções → incorporado à Seção 1.1
- **Subtítulo da ação deve incluir anos-base** das vigências contestadas → incorporado à Seção 1.1
- **Notas de rodapé para anos-base das vigências** na Seção de Objeto da Ação → incorporado à Seção 1.4
- **"índices do FAP"** (com artigo "do") como forma padrão — não "índices FAP" → incorporado à Seção 1.6
- **"Administração Pública" com maiúsculas** quando referência ao ente/órgão → incorporado à Seção 1.2
- **"por intermédio de"** em vez de "através de" → incorporado à Seção 1.6
- **Informação de desemprego/ausência de vínculo** deve ser destacada logo na abertura da narrativa fática de "outra empresa" → incorporado à Seção 1.3
- **"Carteira de Trabalho Digital"** em vez de "Carteira de Trabalho e Previdência Social (CTPS)" para documento digital → incorporado à Seção 1.2
- **Distinção "outra empresa" vs. "outro estabelecimento"** pelo CNPJ raiz → incorporado às Seções 1.1 e 3.4/3.5
- **Eliminar tópico de "Erro de Implantação"** quando o caso pode ser mais solidamente tratado como "acidente não relacionado ao trabalho" → incorporado à Seção 5 (hierarquia) e nota na Seção 3.13
- **IN nº 128/2022** substitui IN nº 77/2015; artigos correspondentes: 337 (único benefício), 347 (restabelecimento), 639, XIII (vedação de concomitância) → incorporado à Seção 1.2 e banco de fundamentações
- **Isrhael pode adicionar benefícios não listados pelo advogado júnior** quando os identifica no levantamento — o revisor verifica a completude do levantamento ativamente → incorporado à Seção 1.1
- **Pedidos subsidiários explicitados** dentro do pedido principal com identificação do tópico alternativo → incorporado à Seção 1.4
- **Ao citar acórdãos extensos, suprimir itens não relevantes** com "[...]", mantendo apenas os diretamente aplicáveis → incorporado à Seção 1.6
- **Explicar por que a projeção do custo é inadequada** no caso concreto, quando a DCB é conhecida → incorporado à Seção 3.14
- **"desídia" e termos similares** para descrever comportamento do INSS devem ser substituídos por formulação técnica neutra → incorporado à Seção 1.6
- **Exemplo da Síntese Fática** sobre cálculo do FAP deve usar as vigências do caso concreto, não um exemplo genérico → incorporado à Seção 1.1

### Contexto adicional
- Marfrig Global Foods S.A., São Paulo/SP. Empresa de grande porte (alimentos/frigoríficos), múltiplos CNPJs de estabelecimentos. Vigências 2022 e 2023 (2 vigências contíguas). 12 teses originais, reorganizadas pelo Isrhael para 12 tópicos (com eliminação do Tópico 10 e reclassificação de benefícios). Valor da causa: R$ 200.000,00 — confirma o padrão para empresas de grande porte com múltiplas teses e 2+ vigências.
- Este é o primeiro caso em que Isrhael **adicionou** um benefício completamente novo (SIDNEI MORAES DE OLIVEIRA, B91 nº 6363783120) que não estava na versão do advogado júnior, confirmando que o revisor verifica ativamente a completude do levantamento e não apenas corrige o que foi apresentado.
- A eliminação do Tópico 10 (Erro de Implantação — ANTONIO MARCOS, B94 nº 6347048519 implantado como acidentário quando deveria ser previdenciário B36) indica que Isrhael prefere teses mais sólidas e consolidadas. O "erro de implantação" como tese autônoma é mais vulnerável; sua requalificação como "acidente não relacionado ao trabalho" (baseada no laudo pericial que afasta o nexo) é juridicamente mais robusta.
- A reorganização do Tópico 5 (Outro Estabelecimento) demonstra a regra técnica: CNPJ raiz diferente → Tópico 4 (Outra Empresa); mesmo CNPJ raiz, estabelecimento diferente → Tópico 5 (Outro Estabelecimento). O Guilherme havia misturado os dois critérios.
- A atualização das referências normativas da IN nº 77/2015 para a IN nº 128/2022 é importante: a IN 77 foi revogada. Os artigos correspondentes são: art. 337 (um único benefício), art. 347 (restabelecimento) e art. 639, XIII (vedação de concomitância).
- Segundo caso do advogado Guilherme na base (o primeiro foi o Caso 7 — Dohler 2021/2022).

---

## CASO 10 — TONIOLO, BUSNELLO S.A.
Advogado júnior: João | Revisor: Isrhael
Vigências: 2021 a 2025 | Teses: Erro na Massa Salarial, Erro no Número Médio de Vínculos | Manual gerado: v1.9

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "arts. 7º, inc. XXVIII e 195, § 9º, na Lei nº 8.212/91, art. 22, inc. II e nas Resoluções nº 1.316/10, 1.327/15, 1.329/17 e 1.347/21, do Conselho Nacional da Previdência Social" | "art. 7º, inciso XXVIII, e art. 195, § 9º, na Lei nº 8.212/1991, art. 22, inciso II; e nas Resoluções nºs 1.316/2010, 1.327/2015, 1.329/2017 e 1.347/2021, do Conselho Nacional da Previdência Social (CNPS)" | 1.1 — anos por extenso; "inciso" por extenso; "nºs" plural; desdobramento de "arts." em "art." individuais; acréscimo de sigla CNPS |
| "art. 30, I, 'b', da Lei nº 8.212/91" | "art. 30, inciso I, alínea 'b', da Lei nº 8.212/1991" | 1.1 — "inciso" por extenso; "alínea" explicitada; ano por extenso |
| "o mês seguinte à competência" | "o mês seguinte ao da competência" | 1.6 — precisão gramatical (regência) |
| "apenas as competências referentes aos meses de janeiro **e** março de 2021 estão prescritas. [...] **a partir de março de 2021**" | "apenas as competências referentes aos meses de janeiro **a** março de 2021 estão prescritas. [...] **a partir de abril de 2021**" | 1.1 — consistência interna (cálculo prescricional) |
| "nos autos do processo 5006065-87.2023.4.04.7204/JFSC" | "nos autos nº 5006065-87.2023.4.04.7204/JFSC" | 1.6 — referências processuais (padrão novo) |
| "retificação da base de cálculo do índice FAP" | "retificação da base de cálculo do índice **do** FAP" | 1.6 — "índice do FAP" com artigo "do" |
| "para a geração do índice custo" / "menor será o índice do custo" | "para a geração do índice **de** custo" / "menor será o índice **de** custo" | 1.6 — "índice de custo" com preposição (padrão novo) |
| "Resoluções nº 1.316/**10**, 1.329/2017 e 1.347/**21**" | "Resoluções nºs 1.316/**2010**, 1.329/2017 e 1.347/**2021**" | 1.1 — anos por extenso; "nºs" plural |
| "que vier a substitui-la" | "que vier a substituí-las" | 1.6 — acento e concordância no plural (GFIPs, plural feminino) |
| "Por falhas cometidas pela administração pública" (minúsculas) | "Por falhas cometidas pela Administração Pública" (maiúsculas) | 1.2 — "Administração Pública" com maiúsculas |
| "valores inferiores ao real" | "valores inferiores aos reais" | 1.6 — concordância de número (padrão novo de nuance) |
| Fragmento duplicado/inacabado: "Os erros foram constatados nas massas salariais relativas às competências do ano de 2021, da **vigência** Os erros foram constatados..." | Suprimido o fragmento inacabado; mantida apenas a frase completa | 1.1 — consistência interna (texto inacabado) |
| Tabela de massa salarial, vigências 2021–2024: competências com exceções mensais específicas (ex.: "de 01/2019 a 09/2019, 11/2019, 12/2019 e 13º/2019") | "todas as competências dos anos de 2019 e 2020" (e equivalentes para cada vigência) | 1.1 — escopo das competências por vigência (padrão novo) |
| CNPJ do exemplo: "06.195.776/0001-90" (outra empresa) | "89.723.977/0001-40" (CNPJ correto da Autora) | 1.1 — dados factuais (CNPJ errado de copiar/colar) |
| "utilizaremos como exemplo" / "Anexamos abaixo" | "utilizar-se-á como exemplo" / "Anexa-se abaixo" | 1.6 — impessoalização do verbo (padrão novo) |
| "Detalhamento da Massa Salarial / Vigência 2025 – Anos dos insumos – 2022 e 2023" (em uma linha) | "Detalhamento da Massa Salarial / Vigência 2025 / Anos dos insumos – 2022 e 2023" (em linhas separadas) | 1.6 — formatação de cabeçalho de telas (padrão novo) |
| "Guia de Recolhimento" (singular) | "Guias de Recolhimento" (plural) | 1.6 — concordância de número |
| "Secretaria **da** Previdência" | "Secretaria **de** Previdência" | 1.2 — nome correto do órgão (padrão novo) |
| "referente à vigência de 2025" (singular, concordando com "planilha") | "referentes à vigência de 2025" (plural, concordando com "divergências") | 1.6 — concordância de número |
| Parágrafo único introduzindo as demais vigências: "demonstram e comprovam [...] (anexos à petição inicial)" | Reestruturado: (a) suprimido "e comprovam" e "(anexos à petição inicial)"; (b) acrescentado descrição das competências destacadas; (c) estrutura em lista *(a), (b), (c), (d)* com "todas as competências dos anos de X e Y" | 1.6 — verbosidade; 1.1 — escopo das competências |
| "dos anos de 2021, 2022, 2023, 2024 e 2025 são os indicados pelas folhas analíticas" | "das vigências de 2021, 2022, 2023, 2024 e 2025 são os indicados pelas GFIPs" | 1.1 — "vigências" vs. "anos"; terminologia correta (GFIPs) |
| "requer seja determinada" | "requer-se seja determinada" | 1.6 — impessoalização do verbo |
| "tomando como corretos" | "considerando-se como corretos" | 1.6 — impessoalização do verbo |
| "a massa salarial indicada no FAP [...] estão corretas" | "as massas salariais indicadas no FAP [...] estão corretas" | 1.6 — concordância de número |
| "no período que foram apurados" | "no período em que foram apurados" | 1.6 — regência verbal (padrão novo) |
| "o número médio de vínculos indicado [...] estão corretas" / "utilizar desse número médios de vínculos" | "os números médios de vínculos indicados [...] estão corretos" / "utilizar esses números médios de vínculos" | 1.6 — concordância de número e gênero (múltiplos erros) |
| Nota de rodapé nº 1: "Vigência **2022**: ano dos insumos: 2018 e 2019" | "Vigência **2021**: ano dos insumos: 2018 e 2019" | 1.1 — nota de rodapé com vigência errada |
| Nota de rodapé nº 5: sem ponto final | Ponto final acrescentado | 1.6 — ponto final no último item de lista |
| "Dá-se à causa o valor de R$ XXX (XXX)" | "Dá-se à causa o valor de R$ 100.000,00 (cem mil reais)" | 1.1 e Seção 6 — valor da causa |

### Decisões de julgamento do Isrhael
- **Priorizou:** (a) CNPJ incorreto no exemplo da massa salarial (06.195.776/0001-90 → 89.723.977/0001-40) — erro crítico de copiar/colar de petição anterior; (b) nota de rodapé nº 1 com vigência errada (2022 → 2021) — erro factual crítico; (c) texto duplicado/inacabado no início do parágrafo sobre erros; (d) ampliação do escopo das competências para "todas as competências dos anos de X e Y" em todas as tabelas e pedidos (decisão de política que altera o escopo do pedido); (e) múltiplos erros de concordância nos pedidos subsidiários.
- **Deixou passar:** Formatação interna de citações normativas transcritas literalmente (inclusive "através de" dentro de citação de portaria); estrutura geral dos argumentos jurídicos.
- **Tom e nível de detalhe:** Reformulações cirúrgicas e pontuais para a maior parte das correções; decisão estrutural significativa na ampliação do escopo das competências (altera as tabelas de pedidos e o corpo do texto de forma consistente).

### Padrões novos (não estavam no manual antes deste caso)
- **"alínea" explicitada em referências normativas** (ex.: "inciso I, alínea 'b'") → incorporado à Seção 1.1
- **"mês seguinte ao da competência"** (regência: "ao da", não "à") → incorporado à Seção 1.6
- **Referências processuais: "nos autos nº [número]"** (não "nos autos do processo [número]") → incorporado à Seção 1.6
- **"índice de custo"** com preposição "de" (não "índice custo") → incorporado à Seção 1.6
- **Impessoalização de verbos na petição** ("utilizar-se-á", "Anexa-se", "requer-se", "considerando-se") → incorporado à Seção 1.6
- **Formatação de cabeçalho de telas do FAP** — vigência e anos-base em linhas separadas → incorporado à Seção 1.6
- **"Secretaria de Previdência"** (não "Secretaria da Previdência") — nome correto do órgão → incorporado à Seção 1.2
- **Escopo das competências por vigência em teses de insumos** — usar "todas as competências dos anos de X e Y" em vez de listas com exceções mensais → incorporado à Seção 1.1
- **"vigências" vs. "anos"** para designar o período das competências no contexto do FAP — usar "vigências" quando se referir ao FAP, "anos" apenas para os anos-base → incorporado à Seção 1.1
- **"no período em que"** (não "no período que") — regência verbal correta → incorporado à Seção 1.6
- **Concordância plural "valores inferiores aos reais"** (não "ao real") → incorporado à Seção 1.6
- **Valor da causa R$ 100.000,00 para 2 teses de insumos (massa salarial + vínculos) com múltiplas vigências** — confirma que o valor de R$ 100.000,00 não está ligado apenas a porte menor da empresa ou vigência única, mas também à natureza das teses (insumos vs. benefícios). Incorporado à Seção 6.

### Contexto adicional
- Toniolo, Busnello S.A. – Túneis, Terraplanagens e Pavimentações, Porto Alegre/RS. Empresa em recuperação judicial (construtora). Vigências 2021 a 2025 (5 vigências contíguas). Apenas 2 teses: Erro na Massa Salarial e Erro no Número Médio de Vínculos — ambas do tipo "insumos", sem nenhum benefício individual contestado. Valor da causa: R$ 100.000,00.
- Caso relevante para calibrar o padrão de valor da causa: apesar de 5 vigências (mais do que o caso Moniari, também de R$ 100.000,00), o valor é menor que os casos de R$ 200.000,00 com teses de benefícios. Hipótese refinada: **o tipo de tese importa** — teses de insumos (massa salarial, vínculos) têm valor menor que teses de benefícios individuais, independentemente do número de vigências.
- Caso com CNPJ de outra empresa no exemplo (06.195.776/0001-90 no lugar de 89.723.977/0001-40) — erro típico de copiar/colar de petição anterior. Confirma a necessidade de verificação ativa do CNPJ em todos os trechos narrativos, não apenas na qualificação.
- A decisão de ampliar o escopo das competências de "listagem com exceções mensais" para "todas as competências dos anos de X e Y" é a mais importante deste caso: indica que Isrhael entende que o erro de insumos afeta **todas** as competências dos anos-base, não apenas algumas delas. Quando o advogado júnior excluía certos meses (ex.: omitia outubro de 2019), Isrhael os incluiu.
- Primeiro caso exclusivamente de teses de insumos (sem nenhuma tese de benefício) na base de casos.

---

## CASO 11 — ESTAÇÃO VIP VIGILÂNCIA E TRANSPORTE DE VALORES LTDA.
Advogado júnior: Edivan | Revisor: Isrhael
Vigências: 2021, 2022 e 2024 | Teses: Restabelecimento (1 B91) + Taxa Média de Rotatividade – Ilegalidade do Bloqueio | Manual gerado: v2.0

### Padrões identificados

| Trecho errado | Trecho correto | Seção do manual |
|---|---|---|
| "arts. 7º, inc. XXVIII e 195, § 9º, na Lei nº 8.212/91, art. 22, inc. II e nas Resoluções nº 1.316/10, 1.327/15, 1.329/17 e 1.347/21, do Conselho Nacional da Previdência Social" | "art. 7º, inciso XXVIII, e art. 195, § 9º, na Lei nº 8.212/1991, art. 22, inciso II; e nas Resoluções nºs 1.316/2010, 1.327/2015, 1.329/2017 e 1.347/2021, do Conselho Nacional da Previdência Social (CNPS)" | 1.1 — anos, "inciso", "nºs", desdobramento de "arts.", sigla CNPS |
| "com endereço Rua Major Jenor, nº 50" (sem preposição) | "com endereço **na** Rua Major Jenor, nº 50" | 1.6 — precisão gramatical (preposição antes de logradouro) |
| "art. 30, I, 'b', da Lei nº 8.212/91" | "art. 30, inciso I, alínea 'b', da Lei nº 8.212/1991" | 1.1 — "inciso", "alínea", ano por extenso |
| "o mês seguinte à competência" | "o mês seguinte ao da competência" | 1.6 — regência: "ao da" |
| Cálculo prescricional errado: data-limite "20/04/2026"; competências "janeiro e fevereiro" prescritas; marco "a partir de março de 2021" | "20/05/2026"; "janeiro a março" prescritos; "a partir de abril de 2021" | 1.1 — consistência interna (cálculo prescricional) |
| "nos autos do processo 5006065-87.2023.4.04.7204/JFSC" (e demais referências processuais) | "nos autos nº 5006065-87.2023.4.04.7204/JFSC" | 1.6 — referências processuais |
| "retificação da base de cálculo do índice FAP" | "retificação da base de cálculo do índice do FAP" | 1.6 — "índice do FAP" com artigo "do" |
| "Decreto nº 3.04/1999" (erro tipográfico) | "Decreto nº 3.048/1999" | 1.1 — dados factuais (referência normativa correta) |
| "impacto dos índices **frequência** e **gravidade**" | "impacto **nos** índices **de** frequência e gravidade" | 1.6 — regência |
| "o custo da **desídia** do INSS em não restabelecer" | "verifica-se que o quadro incapacitante permanece vinculado ao mesmo evento que deu origem ao benefício anterior" | 1.6 — supressão de termos depreciativos |
| "o restabelecimento/prorrogação" (duas ocorrências) | "o restabelecimento ou a prorrogação" / "o restabelecimento ou prorrogação" | 1.6 — barras "/" em textos formais (padrão novo) |
| "Destarte, **o restabelecimento de um mesmo benefício** não deve ser computado em duplicidade [...] não devendo também impactar na **frequência** e **gravidade**, por se tratar de um único benefício." | "Destarte, o restabelecimento de um mesmo benefício deve refletir a continuidade do evento incapacitante que lhe deu origem, sendo tratado como desdobramento do mesmo fato gerador." | 1.3 — precisão técnica do argumento de restabelecimento (padrão novo) |
| "**O empregado/segurado** que obtém novo benefício nestas condições" | "**O segurado** que obtém novo benefício nessas condições" | 1.6 — barras "/" em textos formais; "nessas" (norma culta) |
| DCB do 2º B91 nº 6267523245: "22/04/2020" | "27/03/2021" (data correta) | 1.1 — datas (DIB, DCB) — consistência crítica |
| "Para comprovar a inclusão dos benefícios na base de cálculo do índice FAP nas vigências de 2020, 2021 e 2022, **destacamos** as telas do sistema FAP. / Vigência 2020 / Vigência 2021 / Vigência 2022" | "Para comprovar a inclusão dos benefícios na base de cálculo dos índices do FAP, nas vigências de 2020 a 2022, do estabelecimento com CNPJ nº 09.228.233/0001-10, **destacam-se** as telas do sistema FAP. / Vigência 2020 / **Primeiro B91 nº 6223739854** / Vigência 2021 / **Primeiro B91 nº 6223739854 e segundo B91 nº 6267523245** / Vigência 2022 / **Segundo B91 nº 6267523245**" | 1.4 — identificação individual por tela; 1.6 — impessoalização |
| *in **verbis*** (negrito misturado ao itálico) | *in verbis* | 1.6 — formatação de expressões latinas |
| "autos do processo nº 5026198-14.2023.4.02.5101" (e demais) | "autos nº 5026198-14.2023.4.02.5101" | 1.6 — referências processuais |
| "ILEGALIDADE DA APLICAÇÃO DO 'BLOQUEIO DE ROTATIVIDADE'" (título do Tópico 5) | "**TAXA MÉDIA DE ROTATIVIDADE** – ILEGALIDADE DA APLICAÇÃO DO 'BLOQUEIO DE ROTATIVIDADE'" | 3.18 — nome correto do tópico (padrão novo) |
| "e **a contrário *legis*** no cálculo do FAP" | "e **contra legem** no cálculo do FAP" | 1.6 — expressão latina correta (padrão novo) |
| "**Utilizaremos** como exemplo a vigência 2022" | "**Utilizar-se-á** como exemplo a vigência **de** 2022" | 1.6 — impessoalização do verbo |
| "restringindo-lhe o direito ao '**desconto**' tributário proporcionado pelo FAP." | "restringindo-lhe o direito ao **benefício** tributário proporcionado pelo FAP." | 1.2 — "benefício tributário" em vez de "desconto tributário" (padrão novo) |
| "pelas Resoluções do CNPS nº 1.316/2010 e nº **1.328**/2017" (número errado; Resolução 1.347/2021 omitida) | "pelas Resoluções do CNPS nºs 1.316/2010, **1.329**/2017 **e 1.347/2021**" | 1.1 — numeração correta das Resoluções; inclusão da 1.347/2021 (padrão novo) |
| Taxa Média de Rotatividade tabela: "408,**2192**%" | "408,**21**%" | 1.6 — arredondamento de percentuais para duas casas decimais (padrão novo) |
| "Lei nº 13.709/**18**" / "art. 5º, **II**, da LGPD" | "Lei nº 13.709/**2018**" / "art. 5º, **inciso II**, da LGPD" | 1.1 — anos por extenso; "inciso" por extenso |
| "A condenação da Ré, [...], **no** pagamento do ônus de sucumbência" | "A condenação da Ré, [...], **ao** pagamento do ônus de sucumbência" | 1.6 — regência (condenação "ao" pagamento) |
| "apresente **cópia do processo administrativo** de concessão dos benefícios" | "apresente **cópia dos processos administrativos** de concessão dos benefícios" | 1.6 — concordância de número (dois benefícios → plural) |
| "Dá-se à causa o valor de **R$ XXX (XXX)**." | "Dá-se à causa o valor de **R$ 10.000,00 (dez mil reais)**." | 1.1 e Seção 6 — valor da causa (novo patamar) |

### Decisões de julgamento do Isrhael
- **Priorizou:** (a) Cálculo prescricional errado (datas e competências afetadas) — crítico; (b) DCB do 2º B91 errada (22/04/2020 → 27/03/2021) — erro factual crítico que afeta a narrativa; (c) número errado da Resolução (1.328 → 1.329) e omissão da Resolução 1.347/2021 nos pedidos de rotatividade — erro crítico de fundamentação; (d) identificação individual dos benefícios por vigência nas telas do FAP; (e) reformulação do argumento central do restabelecimento (evitar a afirmação contraditória de que o segundo benefício "não deve impactar frequência e gravidade").
- **Deixou passar:** (a) Referência à "IN nº 77/2015 **e seguintes**" no Tópico 4 — a locução "e seguintes" cobre implicitamente a normativa atual (IN 128/2022), sem necessidade de correção; (b) subtítulo da ação sem anos-base — vigências não contíguas (2021, 2022 e 2024) dificultam a padronização; (c) estrutura geral dos argumentos jurídicos e citações jurisprudenciais.
- **Tom e nível de detalhe:** Reformulações cirúrgicas na maioria dos casos; intervenção mais profunda no Tópico 4 para corrigir o argumento técnico do restabelecimento e identificar os benefícios nas telas. A correção do cálculo prescricional foi a mais estrutural (alterou datas, texto e tabela de forma consistente).

### Padrões novos (não estavam no manual antes deste caso)
- **Preposição "na" antes de logradouro** na qualificação da Autora ("com endereço **na** Rua X") → incorporado à Seção 1.1
- **Exceção ao subtítulo sem anos-base** para vigências não contíguas → nota incorporada à Seção 1.1
- **"de X a Y" aceitável para faixas de meses** (3+ meses) na prescrição — mesma lógica do "e" vs. "a" para vigências → nota incorporada à Seção 1.1
- **Verificação de numeração correta das Resoluções** — 1.329/2017 não "1.328/2017"; inclusão obrigatória da 1.347/2021 na tese de rotatividade → incorporado à Seção 1.1
- **"benefício tributário" em vez de "desconto tributário"** — FAP não é desconto, é benefício tributário/fator multiplicador → incorporado à Seção 1.2
- **"contra legem" em vez de "a contrário legis"** — locução latina correta → incorporado à Seção 1.6
- **Uso de barras "/" em textos formais → substituir por conjunção** ("restabelecimento/prorrogação" → "restabelecimento ou prorrogação") → incorporado à Seção 1.6
- **"Juízo" com maiúscula** como referência ao órgão jurisdicional como instituição → incorporado à Seção 1.6
- **Arredondamento de percentuais para duas casas decimais** em tabelas de petição → incorporado à Seção 1.6
- **Identificação individual de benefícios por vigência nas telas do FAP** com nome descritivo (ex.: "Primeiro B91 nº XXXX e segundo B91 nº YYYY") → incorporado à Seção 1.4
- **Nome do tópico de rotatividade** deve começar com "TAXA MÉDIA DE ROTATIVIDADE –" → incorporado à Seção 3.18
- **Precisão técnica do argumento do restabelecimento** — evitar afirmar que o 2º benefício "não deve impactar frequência e gravidade"; a formulação correta é: "deve refletir a continuidade do evento incapacitante, sendo tratado como desdobramento do mesmo fato gerador" → incorporado à Seção 1.3 e banco de fundamentações
- **IN nº 77/2015 "e seguintes" pode ser mantida** quando a locução cobre implicitamente a normativa atual → nota incorporada à Seção 1.2
- **Valor da causa R$ 10.000,00** para caso com apenas 1 B91 contestado e rotatividade, empresa de menor porte — novo patamar identificado → incorporado à Seção 6

### Contexto adicional
- Estação VIP Vigilância e Transporte de Valores Ltda., Rio Branco/AC. Empresa de segurança/transporte de valores, provavelmente de menor porte (endereço em Distrito Industrial de Rio Branco). Vigências 2021, 2022 e 2024 (não contíguas — 2023 ausente). Apenas 2 teses: Restabelecimento (1 único B91) e Taxa Média de Rotatividade. Valor da causa: R$ 10.000,00.
- **Primeiro caso com valor da causa de R$ 10.000,00** na base. Sugere que o valor não depende apenas do tipo de tese (insumos vs. benefícios), mas também do **porte do pedido**: 1 benefício contestado + rotatividade em empresa de menor porte = valor significativamente menor que os demais casos. Refina a hipótese da Seção 6.
- Caso com vigências **não contíguas** (2021, 2022 e 2024): o ano de 2023 não foi contestado. Isso gerou a decisão de não alterar o subtítulo da ação (que ficou sem os anos-base), confirmando que a regra do subtítulo tem exceção para vigências não contíguas.
- **Erro de numeração da Resolução** (1.328 vs. 1.329) é um padrão novo importante: o Isrhael corrigiu o número em todas as ocorrências e também acrescentou a Resolução 1.347/2021, que havia sido omitida nos pedidos. Confirma que o revisor verifica não apenas a forma, mas a substância da fundamentação normativa.
- Segundo caso do advogado Edivan na base (o primeiro foi o Caso 2 — Moniari Supermercados).
- A reformulação do argumento do restabelecimento (suprimir a afirmação de que o segundo benefício "não deve impactar frequência e gravidade, por se tratar de um único benefício") é tecnicamente importante: essa formulação era contraditória com a tabela de pedidos, que pede a exclusão de *frequência e gravidade* para a vigência 2021 — se o benefício "não deve impactar", por que pedir a exclusão?  A versão revisada resolve a contradição."""

DEFAULT_PROMPTS = {
  'revisor_identity': """Você é um revisor especializado em petições iniciais de Ação Revisional do FAP (Fator Acidentário de Prevenção), treinado nos padrões do advogado sênior Isrhael do escritório Rodriguez & Sousa.

Seu escopo é exclusivamente revisar uma única petição por vez, com base no manual vigente e nos arquivos auxiliares opcionais anexados para validação.

Objetivo:
- Identificar inconsistências, erros jurídicos, lacunas documentais e riscos processuais.
- Criticar tecnicamente a petição com precisão e objetividade.

Restrições:
- Não realizar comparação entre versão inicial e versão revisada.
- Não executar tarefas de treinamento (não gerar/atualizar manual, casos ou base de conhecimento).
- Não instruir publicação de arquivos de treinamento.""",
  'revisor_rules': """REGRAS INVIOLÁVEIS DO AGENTE REVISOR

❌ NUNCA invente precedentes, números de processo ou base normativa.
❌ NUNCA aprove tópico sem verificar documentos obrigatórios da Seção 3.
❌ NUNCA ignore a regra de conexão B91 ↔ B92/B94 (Seção 2).
❌ NUNCA aceite "Previdência Social" onde correto é "administração pública" no contexto de cálculo do FAP.
❌ NUNCA aceite "aposentadoria por invalidez" — correto: "incapacidade permanente".
❌ NUNCA aceite "durante o exercício" — correto: "em decorrência das atividades".
❌ NUNCA aceite nexo causal atribuído ao benefício na tese de natureza errada.
❌ NUNCA omita alterações na análise comparativa.

✅ SEMPRE cite a seção do manual que fundamenta cada achado.
✅ SEMPRE diferencie erros críticos de formais.
✅ SEMPRE classifique os achados por gravidade (CRÍTICO, MODERADO, FORMAL).
✅ SEMPRE manter foco em revisão técnica da petição, sem executar tarefas de treinamento/evolução da base.""",
    'revisor_output_format': """FORMATO OBRIGATÓRIO DA SAÍDA — REVISÃO SINGLE-FILE

Retorne em JSON válido com foco exclusivo em revisão de uma única petição.

Estrutura esperada:
{
  "analysis_type": "single_version",
  "theses": [
    {
      "thesis": "string",
      "benefit_number": "string opcional",
      "classification": "string opcional"
    }
  ],
  "findings": [
    {
      "category": "CAT-1|CAT-2|CAT-3|CAT-4|CAT-5|CAT-6|CRITICAL|MODERATE|FORMAL",
      "severity": "CRÍTICO|MODERADO|FORMAL",
      "description": "string",
      "location": "string opcional",
      "correction": "string opcional",
      "manual_reference": "string opcional",
      "is_new_pattern": false
    }
  ],
  "missing_documents": [
    {
      "document_type": "string",
      "thesis": "string opcional",
      "manual_reference": "string opcional"
    }
  ],
  "executive_summary": {
    "total_findings": 0,
    "critical_findings": 0,
    "moderate_findings": 0,
    "formal_findings": 0,
    "main_legal_risks": ["string"],
    "correction_priority": "ALTA|MÉDIA|BAIXA"
  },
  "new_patterns": [
    {
      "pattern_description": "string",
      "recurrence": "string",
      "suggested_update": "string",
      "section": "string opcional"
    }
  ],
  "comparative_changes": []
}

Regras:
- analysis_type deve ser sempre "single_version".
- comparative_changes deve ser sempre lista vazia.
- Não incluir texto fora do JSON.""",
    'training_identity': """Você é um agente de aprendizado contínuo especializado em FAP.
Sua função: Processar achados do Revisor, consolidar padrões, e manter atualizado o manual
de referência e banco de casos.""",
    'training_rules': """1. CONSOLIDAR: Agrupe padrões similares de múltiplas revisões
2. VERSIONAR: Crie versões incrementais do manual
3. REFERENCIAR: Cite casos que validam novas orientações
4. APROVAR: Requer aprovação antes de publicar mudanças
5. RETROCEDER: Permita rollback para versões anteriores
6. APRENDER: Use feedback para evoluir continuamente""",
    'training_prompt': """Processe estes achados do revisor e:
1. Identifique padrões recorrentes
2. Consolide em orientações claras
3. Proponha atualizações do manual
4. Crie novos casos de referência
5. Gere resumo de aprendizados

Retorne estrutura JSON com propostas de atualização.""",
    'training_update_policy': """Política de atualização:
- Auto: Se habilitado, publica automaticamente
- Aprovação: Requer aprovação de supervisor
- Versionamento: Incremento semântico (patch/minor/major)
- Rollback: Disponível por 30 dias após publicação
- Auditoria: Todos os eventos registrados com user_id""",
}

DEFAULT_REFERENCES = {
    'manual_fap': MANUAL_TEXT,
    'casos_referencia': CASES_TEXT,
    'project_instructions': PROJECT_INSTRUCTIONS_TEXT,
}


def _upsert_prompt(law_firm_id: int, user_id: int, prompt_type: str, content: str) -> str:
    current_active = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
        is_active=True,
    ).order_by(FapReviewPromptVersion.version_number.desc()).first()

    if current_active and (current_active.content or '').strip() == content.strip():
        return 'sem alteração'

    last_version = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
    ).order_by(FapReviewPromptVersion.version_number.desc()).first()

    next_version = (last_version.version_number + 1) if last_version else 1

    FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt_type,
        is_active=True,
    ).update({'is_active': False}, synchronize_session=False)

    db.session.add(
        FapReviewPromptVersion(
            law_firm_id=law_firm_id,
            version_number=next_version,
            prompt_type=prompt_type,
            content=content,
            is_active=True,
            created_by_id=user_id,
        )
    )
    return f'atualizado v{next_version}'


def _upsert_reference(law_firm_id: int, user_id: int, reference_type: str, content: str) -> str:
    current_active = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
        is_active=True,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()

    if current_active and (current_active.content or '').strip() == content.strip():
        return 'sem alteração'

    last_version = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
    ).order_by(FapReviewReferenceVersion.version_number.desc()).first()

    next_version = (last_version.version_number + 1) if last_version else 1

    FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference_type,
        is_active=True,
    ).update({'is_active': False}, synchronize_session=False)

    db.session.add(
        FapReviewReferenceVersion(
            law_firm_id=law_firm_id,
            version_number=next_version,
            reference_type=reference_type,
            content=content,
            is_active=True,
            created_by_id=user_id,
        )
    )
    return f'atualizado v{next_version}'


def seed_initial_data():
    """Cria dados iniciais de prompts e referências"""
    with app.app_context():
        print("\\n" + "=" * 80)
        print("📝 CRIANDO SEEDS INICIAIS DE PROMPTS E REFERÊNCIAS")
        print("=" * 80)

        try:
            law_firms = LawFirm.query.order_by(LawFirm.id.asc()).all()
            if not law_firms:
                print("❌ Nenhum escritório encontrado. Crie um primeiro.")
                return False

            user = User.query.filter_by(role='admin').first()
            if not user:
                print("❌ Nenhum usuário admin encontrado.")
                return False

            print(f"✅ Usando Usuário: {user.name}")
            print("✅ Conteúdo completo embutido diretamente no seed")

            for law_firm in law_firms:
                print(f"\\n📌 Escritório: {law_firm.name}")

                print("  • Sincronizando PROMPTS...")
                for prompt_type, content in DEFAULT_PROMPTS.items():
                    status = _upsert_prompt(law_firm.id, user.id, prompt_type, content)
                    print(f"    - {prompt_type}: {status} (len={len(content)})")

                print("  • Sincronizando REFERÊNCIAS...")
                for ref_type, content in DEFAULT_REFERENCES.items():
                    status = _upsert_reference(law_firm.id, user.id, ref_type, content)
                    print(f"    - {ref_type}: {status} (len={len(content)})")

            db.session.commit()

            print("\\n" + "=" * 80)
            print("✅ SEEDS CRIADAS COM SUCESSO")
            print("=" * 80)
            return True

        except Exception as e:
            print(f"❌ Erro: {e}")
            db.session.rollback()
            return False


if __name__ == '__main__':
    seed_initial_data()
