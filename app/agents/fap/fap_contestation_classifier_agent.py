from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_MINI
from app.models import (
    FapContestationClassifierPromptVersion,
    FapContestationClassifierReferenceVersion,
    FapContestationClassifierSetting,
)
from app.services.token_usage_service import TokenUsageService


logger = logging.getLogger(__name__)


class FAPContestationClassifierAgent:
    """Classifica justificativas de contestação FAP em um tópico jurídico padronizado."""

    MIN_CONFIDENCE = 0.80

    SYSTEM_PROMPT = (
        "Voce e um especialista juridico em FAP. "
        "Classifique o texto em ATE 3 topicos e retorne JSON valido. "
        "Ordene por relevancia, com o principal na primeira posicao. "
        "Quando houver cabecalho literal com nome de categoria, trate isso como evidencia forte. "
        "DISCUSSAO MEDICA / OUTROS ARGUMENTOS so pode ser usada quando nenhum outro topico especifico se aplicar. "
        "Prefira sempre topicos juridicos especificos quando houver evidencia textual suficiente. "
        "Evite falso positivo: nunca retorne PRE-FAP, B31 ou NEXO PENDENTE sem evidencia textual explicita. "
        "Quando houver evidencia de evento anterior a abril de 2007/pre-FAP, PRE-FAP deve ser o topico principal. "
        "Nao use categorias de OUTRA EMPRESA ou ERRO DE ESTABELECIMENTO sem indicios textuais explicitos de outro CNPJ/estabelecimento/vinculo empregaticio diverso. "
        "Quando houver indicio de acidente vinculado a outro CNPJ/estabelecimento, priorize categorias de OUTRA EMPRESA e/ou ERRO DE ESTABELECIMENTO. "
        "Informe tambem a confianca individual de cada topico retornado. "
        "So retorne topicos especificos quando a confianca global for maior ou igual a 0.80. "
        "Se a confianca global for menor que 0.80, seja conservador e nao retorne topicos especificos. "
        "Priorize interpretacao juridica. "
        "Nunca invente categorias."
    )

    USER_PROMPT_MARKDOWN_DEFAULT = """## Regras

- Retorne de 1 a 3 slugs validos, sem duplicidade.
- O primeiro slug deve ser o tema principal.
- So use discussao_medica quando NAO houver enquadramento claro em nenhum outro topico especifico.
- So use outros_argumentos quando NAO houver enquadramento claro em nenhum outro topico especifico.
- Se houver ao menos um topico especifico aplicavel, NAO inclua discussao_medica nem outros_argumentos.
- Nao retorne pre_fap, b31_previdenciario ou nexo_pendente sem mencao textual clara e direta.
- Se o texto mencionar numero de CAT (ex: 'CAT no XXXX', 'CAT 2018...'), use acidente_trajeto, NUNCA acidente_trajeto_sem_cat.
- acidente_trajeto_sem_cat SOMENTE quando o texto diz explicitamente que NAO ha CAT emitida.
- Quando houver mencao a evento/DID anterior a abril de 2007, pre_fap deve ser o primeiro slug.
- Se o texto indicar outro CNPJ, outro estabelecimento, ou ausencia de nexo com este estabelecimento, priorize uma das categorias abaixo:
    - outra_empresa_cat
    - outra_empresa_nunca_empregado
    - outra_empresa_pos_rescisao
    - outra_empresa_did_anterior
    - erro_estabelecimento
- Nao use categorias de outra_empresa_* nem erro_estabelecimento sem expressao textual explicita de outro CNPJ/estabelecimento/empresa.
- Informe reason apenas quando confidence >= 0.80; caso contrario, reason deve ser string vazia.
- Se nao houver encaixe:
    - Se houver termos medicos -> discussao_medica
    - Caso contrario -> outros_argumentos

## Exemplos de sinal forte para OUTRA EMPRESA/ERRO DE ESTABELECIMENTO

- nao relacionado a este estabelecimento
- acidente vinculado a outro CNPJ
- requer exclusao da base de calculo FAP deste estabelecimento por vinculo a outro estabelecimento

## Exemplos de sinal forte para PRE-FAP

- evento acidentario anterior a 1o de abril de 2007
- DID 2002
- acidente/doenca antes da vigencia do FAP

## Sinais juridicos fortes por categoria

- nexo_pendente: mencao a NTP/nexo tecnico com contestacao pendente de julgamento e pedido de efeito suspensivo
- acidente_trajeto: mencao expressa de acidente de trajeto com CAT comprovando o evento
- acidente_trajeto_sem_cat: acidente de trajeto comprovado por acao judicial, sem CAT
- restabelecimento_b91_60: mencao a restabelecimento em menos de 60 dias (DCB->novo beneficio)
- b31_previdenciario: mencao expressa de especie previdenciaria/B31 e exclusao por nao ser acidentario
- erro_estabelecimento: beneficio imputado ao estabelecimento/CNPJ errado
- pre_fap: evento anterior a abril/2007, art. 202-A, decreto 6.957/2009, irretroatividade
- outra_empresa_cat: CAT vincula acidente a outra empresa
- outra_empresa_nunca_empregado: ausencia de vinculo empregaticio historico com a empresa
- outra_empresa_pos_rescisao: DIB/evento posterior a rescisao contratual
- outra_empresa_did_anterior: DID anterior a admissao na empresa
- nexo_afastado: pericia/sentenca afasta nexo causal ou concausalidade laboral
- beneficio_justica_federal: concessao judicial na Justica Federal indicando natureza previdenciaria
- concomitante_b91_aposentadoria: B91 concedido com aposentadoria ativa
- concomitante_dois_b91: concessao concomitante de dois auxilios-doenca
- concomitante_b94_aposentadoria: B94 acumulado com aposentadoria
- b94_duplicado: dois B94 para mesmo fato gerador
- b94_sem_custo: DIB=DCB/beneficio sem custo juridico efetivo
- discussao_medica: debate clinico/pericial sem enquadramento juridico FAP especifico

## Regra de estruturacao

- Se o texto trouxer mais de um bloco justificativo com fundamentos distintos, retorne multiplos slugs (ate 3), sem inventar.
"""

    REFERENCE_MARKDOWN_DEFAULT = """# NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO

A caracterização do benefício como acidentário pode ser realizada por meio da emissão da Comunicação de Acidente de Trabalho (CAT) ou pela atribuição de um Nexo Técnico Previdenciário (NTP) pela INSS. O NTP possui presunção relativa, permitindo a apresentação de provas em contrário. Nesse contexto, a empresa é notificada sobre a concessão do benefício acidentário e pode contestar o NTP, o que pode resultar na conversão do benefício de acidentário para previdenciário.

No presente caso, apesar da atribuição de um NTP que resultou na concessão do benefício acidentário, este não se origina de um acidente de trabalho ou doença ocupacional. Dessa forma, a empresa apresentou contestação ao INSS, solicitando a conversão do benefício para a natureza previdenciária. Essa contestação encontra-se pendente de julgamento.

Diante dessa situação, a contestação deve suspender os efeitos tributários do benefício, impedindo sua inclusão no índice FAP, uma vez que a natureza acidentária ainda não foi definida. O Código Tributário Nacional (CTN), em seu art. 116, II, estabelece que "considera-se ocorrido o fato gerador e existentes os seus efeitos: [...] II - tratando-se de situação jurídica, desde o momento em que esteja DEFINITIVAMENTE constituída, nos termos de direito aplicável".

Assim, requer-se a concessão do efeito suspensivo deste benefício no cálculo do FAP, com a exclusão até o julgamento da contestação de NTP pelo INSS, e, posteriormente, a exclusão definitiva.

# ACIDENTE DE TRAJETO

A Resolução nº 1.347/2021 do CNPS dispõe que os benefícios decorrentes de acidentes de trajeto não devem compor a base de cálculo do Fator Acidentário de Prevenção, assim identificados por meio da CAT ou por outro instrumento que venha a substitui-la. No presente caso, a CAT nº 2019.123.456-9/01 comprova a vinculação entre o benefício e o acidente registrado.

Assim, sendo um benefício decorrente de acidente de trajeto, este não deve integrar a base de cálculo do FAP da empresa. Diante do exposto, requer-se a exclusão do referido benefício do cálculo do índice FAP.

## ACIDENTE DE TRAJETO SEM CAT - AÇÃO JUDICIAL

A Resolução nº 1.347/2021 do CNPS dispõe que os benefícios decorrentes de acidentes de trajeto não devem compor a base de cálculo do Fator Acidentário de Prevenção.

O acidente de trajeto é definido como aquele ocorrido entre a residência do trabalhador e o local de trabalho, e vice-versa, independentemente do meio de locomoção utilizado, incluindo veículo de propriedade do segurado (art. 21, IV, ''d'', da Lei no 8.213).

Nesse contexto, a classificação do evento como sendo de trajeto está vinculada ao local, às circunstâncias e ao horário em que ocorreu, sendo as condições específicas do incidente os elementos que determinam essa classificação.

Nesse passo, a ação judicial nº 5015126-19.2021.8.24.0036/SC confirma que o benefício é oriundo de um acidente de trajeto.

Assim, sendo um benefício decorrente de acidente de trajeto, este não deve integrar a base de cálculo do FAP da empresa. Diante do exposto, requer-se a exclusão do referido benefício do cálculo do índice FAP.

# RESTABELECIMENTO DE BENEFÍCIO - B91 60 DIAS

O § 3º do artigo 75 do Decreto nº 3.048/1999 estabelece que, se um novo benefício é concedido em menos de 60 (sessenta) dias após o término do anterior, isso deve ser considerado um restabelecimento, não uma nova concessão. Isso ocorre porque se trata da mesma condição de saúde e não de uma nova situação ou agravamento.

De acordo com os Regulamentos da Previdência Social, caso o segurado não se recupere completamente dentro do período de 60 dias após a cessação do benefício anterior e necessite de um novo afastamento, a medida correta é o restabelecimento do benefício originalmente concedido, e não a concessão de um novo.

Nesse contexto, o benefício em questão decorre da mesma causa que originou a incapacidade que justificou a concessão do benefício nº xxxxxx, cuja data de cessação (DCB) ocorreu há menos de sessenta dias. Entretanto, em vez de restabelecer o primeiro benefício, o INSS concedeu equivocadamente um segundo benefício ao segurado. Cumpre destacar que o primeiro benefício já foi considerado no cálculo do FAP em outras vigências.

Dessa forma, comprovado o erro no cálculo do índice FAP devido à inclusão de um novo benefício que, na verdade, refere-se ao restabelecimento do benefício anterior, requer-se a exclusão desse benefício para evitar a caracterização de bis in idem.

# AUXÍLIO-DOENÇA PREVIDENCIÁRIO - B31

A Resolução nº 1.347/2021 do CNPS, que estabelece a metodologia de cálculo do Fator Acidentário de Prevenção, determina que a base de cálculo do índice deve ser composta exclusivamente por benefícios de natureza acidentária. Portanto, benefícios de natureza previdenciária não devem ser incluídos nessa base.

No entanto, de acordo com o sistema de benefícios por incapacidade do INSS, verifica-se que o benefício em questão foi concedido sob a espécie previdenciária. Dessa forma, a inclusão desse benefício contraria a legislação vigente, uma vez que penaliza a empresa ao elevar o FAP e, consequentemente, a alíquota de contribuição ao Seguro de Acidente de Trabalho (SAT), além de não atender ao propósito para o qual o FAP foi criado.

Diante do exposto, considerando que se trata de um benefício de natureza previdenciária, requer-se a exclusão desse benefício da base de cálculo do índice FAP.

# ERRO DE ESTABELECIMENTO

A Resolução nº 1.347/2021 do CNPS estabelece a metodologia de cálculo do Fator Acidentário de Prevenção (FAP), estipulando parâmetros e critérios para a determinação do percentual a ser atribuído a cada estabelecimento, de forma individualizada, com base em seu Cadastro Nacional de Pessoas Jurídicas (CNPJ).

Essa apuração está relacionada à forma de cálculo da alíquota de contribuição para o Seguro de Acidente de Trabalho (SAT), conforme dispõe a Súmula nº 351 do STJ, a qual determina que o cálculo deve ocorrer por estabelecimento.

Dessa forma, os estabelecimentos com maior incidência e gravidade de acidentes apresentam um índice FAP mais elevado em comparação àqueles com menor frequência de ocorrências.

Contudo, para que um benefício acidentário seja considerado na base de cálculo do FAP de um estabelecimento, é indispensável que exista nexo entre: (i) o empregado; (ii) o acidente ou a doença que deu origem ao benefício; e (iii) o estabelecimento identificado pelo CNPJ ao qual o empregado estava vinculado na data do acidente de trabalho.

No caso, o acidente que originou o benefício não se relaciona a este estabelecimento, mas ao CNPJ [CNPJ_CORRETO], conforme demonstra a Comunicação de Acidente de Trabalho (CAT) nº [XXXX.XXXXXX.X/XX], que vincula o evento ao referido CNPJ.

Dessa forma, não é possível imputar a este estabelecimento o aumento do índice FAP decorrente de benefício cuja origem está vinculada a outro estabelecimento (CNPJ).

Portanto, para a correta aplicação da legislação e considerando que este estabelecimento não é o responsável pelo acidente ou doença, requer-se a exclusão desse benefício da base de cálculo do índice FAP.

# PRÉ-FAP

O art. 202-A, § 9º, do Decreto nº 3.048/1999, na redação dada pelo Decreto nº 6.957, de 2009, estabelece que: "Excepcionalmente, no primeiro processamento do FAP serão utilizados os dados de abril de 2007 a dezembro de 2008." Assim, somente acidentes ou doenças ocorridos a partir de 1º abril de 2007 podem compor a base de cálculo do FAP.

Essa delimitação decorre do princípio da legalidade no Sistema Tributário Brasileiro, que restringe o poder de tributar e assegura ao contribuinte a certeza jurídica quanto ao momento em que as obrigações tributárias podem ser exigidas. Além disso, aplica-se o princípio da irretroatividade, que estabelece que, em geral, a legislação tributária não retroage para abranger eventos geradores anteriores à sua vigência.

No presente caso, o evento acidentário que originou o benefício ocorreu antes da implementação e vigência do FAP, ou seja, antes de 1º de abril de 2007.

Por tais razões, e considerando que o benefício decorre de um acidente ou doença adquirida antes de abril de 2007, requer-se a exclusão desse benefício da base de cálculo do índice FAP.

# OUTRA EMPRESA - CAT VINCULADA

A Resolução nº 1.347/2021 do CNPS estabelece a metodologia de cálculo do Fator Acidentário de Prevenção (FAP), definindo parâmetros e critérios para a determinação do percentual a ser atribuído a cada estabelecimento, de forma individualizada, com base em seu Cadastro Nacional de Pessoas Jurídicas (CNPJ).

Nesse contexto, para que um benefício acidentário seja considerado na base de cálculo do Fator Acidentário de Prevenção (FAP) de um estabelecimento, é fundamental que exista um nexo entre: (i) o empregado; (ii) o acidente ou doença que gerou o benefício; e (iii) o estabelecimento identificado pelo seu Cadastro Nacional de Pessoas Jurídicas (CNPJ), ao qual o empregado estava vinculado na data do acidente ou doença.

Contudo, conforme a Comunicação de Acidente de Trabalho (CAT) nº 2019.123.456-9/01 vinculada ao benefício, verifica-se que o empregado sofreu um acidente de trabalho em outra empresa. Dessa forma, a empresa não pode ser responsabilizada por benefício que teve origem em um acidente ou doença ocorridos em outra empresa.

Diante disso, requer-se a exclusão do benefício da base de cálculo do índice FAP.

## OUTRA EMPRESA - NUNCA FOI EMPREGADO

A Resolução nº 1.347/2021 do CNPS estabelece a metodologia de cálculo do Fator Acidentário de Prevenção (FAP), definindo parâmetros e critérios para a determinação do percentual a ser atribuído a cada estabelecimento, de forma individualizada, com base em seu Cadastro Nacional de Pessoas Jurídicas (CNPJ).

Nesse contexto, para que um benefício acidentário seja considerado na base de cálculo do Fator Acidentário de Prevenção (FAP) de um estabelecimento, é fundamental que exista um nexo entre: (i) o empregado; (ii) o acidente ou doença que gerou o benefício; e (iii) o estabelecimento identificado pelo seu Cadastro Nacional de Pessoas Jurídicas (CNPJ), ao qual o empregado estava vinculado na data do acidente ou doença.

No caso, o segurado nunca manteve vínculo empregatício com a empresa, conforme evidenciado pela ausência de registros internos e pelas informações prestadas na Guia de Recolhimento do Fundo de Garantia do Tempo de Serviço e Informações à Previdência Social (GFIP) e no e-Social.

Diante da inexistência de vínculo empregatício com a empresa, requer-se a exclusão do benefício da base de cálculo do índice FAP.

## OUTRA EMPRESA - APÓS A RESCISÃO CONTRATUAL

A Resolução nº 1.347/2021 do CNPS estabelece a metodologia de cálculo do Fator Acidentário de Prevenção (FAP), definindo parâmetros e critérios para a determinação do percentual a ser atribuído a cada estabelecimento, de forma individualizada, com base em seu Cadastro Nacional de Pessoas Jurídicas (CNPJ).

Nesse contexto, para que um benefício acidentário seja considerado na base de cálculo do Fator Acidentário de Prevenção (FAP) de um estabelecimento, é fundamental que exista um nexo entre: (i) o empregado; (ii) o acidente ou doença que gerou o benefício; e (iii) o estabelecimento identificado pelo seu Cadastro Nacional de Pessoas Jurídicas (CNPJ), ao qual o empregado estava vinculado na data do acidente ou doença.

No caso, a rescisão contratual do empregado ocorreu em [data]. Assim, verifica-se que a data de início do benefício (DIB) é posterior à rescisão do contrato de trabalho. Portanto, a empresa não pode ser responsabilizada pelo acidente de trabalho.

Para reforçar a argumentação, o período de graça tem como objetivo garantir a qualidade de segurado, e não vincular um benefício a uma empresa com a qual o segurado não possui mais vínculo. Essa distinção é fundamental, pois responsabilizar uma empresa por um acidente de trabalho envolvendo um ex-empregado contraria os princípios que regem a legislação trabalhista e a metodologia do Fator Acidentário de Prevenção (FAP).

Ademais, o cálculo do índice FAP visa incentivar a melhoria das condições laborais e de saúde dos empregados, estimulando os estabelecimentos a implementarem medidas coletivas e individuais de prevenção aos riscos de acidentes ou doenças do trabalho. Assim, atribuir responsabilidade a uma empresa por um acidente de trabalho envolvendo um segurado sem vínculo empregatício não apenas contraria a metodologia e os objetivos do FAP, mas também ignora a impossibilidade de a empresa evitar o referido acidente.

Portanto, diante da inexistência de vínculo empregatício com a empresa na data do evento acidentário, requer-se a exclusão do benefício da base de cálculo do índice FAP.

## OUTRA EMPRESA - DID ANTERIOR À ADMISSÃO NA EMPRESA

A Resolução nº 1.347/2021 do CNPS estabelece a metodologia de cálculo do Fator Acidentário de Prevenção (FAP), definindo parâmetros e critérios para a determinação do percentual a ser atribuído a cada estabelecimento, de forma individualizada, com base em seu Cadastro Nacional de Pessoas Jurídicas (CNPJ).

Nesse contexto, para que um benefício acidentário seja considerado na base de cálculo do Fator Acidentário de Prevenção (FAP) de um estabelecimento, é fundamental que exista um nexo entre: (i) o empregado; (ii) o acidente ou doença que gerou o benefício; e (iii) o estabelecimento identificado pelo seu Cadastro Nacional de Pessoas Jurídicas (CNPJ), ao qual o empregado estava vinculado na data do acidente ou doença.

No presente caso, conforme indicado no laudo médico pericial de concessão do benefício, a data de início da doença (DID) é anterior à admissão do empregado. Portanto, o benefício decorre de um acidente de trabalho ou de uma doença ocupacional sofrida em outra empresa, o que significa que a responsabilidade pela inclusão desse benefício deve recair sobre o índice FAP da empresa onde ocorreu o evento.

Diante dessas considerações, e tendo em vista que a DID precede a admissão do empregado, requer-se a exclusão do benefício da base de cálculo do índice FAP desta empresa.

# NEXO AFASTADO

Para que o benefício de incapacidade seja classificado como acidentário, é necessário estabelecer a relação de causa e efeito entre o trabalho e o acidente, ou seja, a confirmação do nexo causal ou da concausalidade, conforme disposto no art. 19, caput, e no art. 21, I, da Lei nº 8.213/1991.

A caracterização do benefício como acidentário ocorre por meio da emissão da Comunicação de Acidente de Trabalho (CAT) ou por uma das modalidades de Nexo Técnico Previdenciário (NTP), este último possuindo presunção relativa, admitindo prova em contrário.

No caso em questão, a perícia médica judicial realizada nos autos nº 1029867-26.2023.4.01.3500, que tramitou na Justiça Federal ou do Trabalho, apresentou fundamentos técnicos que afastaram o nexo de causalidade e concausalidade entre os problemas de saúde do empregado e suas atividades laborais, evidenciando que as condições apresentadas são degenerativas e inerentes à idade do empregado.

Diante disso, a sentença judicial declarou a inexistência de acidente de trabalho, concluindo que a doença do empregado não está relacionada com o exercício de suas funções. Assim, conforme reconhecido pela decisão judicial, fica evidenciado que as lesões do segurado não decorrem do trabalho, caracterizando-se, portanto, como um benefício de natureza previdenciária.

Por essas razões, requer-se a exclusão do benefício da base de cálculo do índice FAP.

# BENEFÍCIO CONCEDIDO NA JUSTIÇA FEDERAL

Consoante a Súmula nº 235 do Supremo Tribunal Federal (STF), compete à Justiça Comum Estadual julgar as ações acidentárias que, propostas pelo segurado contra o Instituto Nacional do Seguro Social (INSS), visem à prestação de benefícios relativos a acidentes de trabalho. Em contraposição, o art. 109, I e § 3º, da Constituição da República Federativa do Brasil (CRFB) de 1988 confere à Justiça Federal a competência para processar e julgar causas de natureza previdenciária, deixando claro que está não tem jurisdição sobre casos que envolvem acidentes de trabalho.

Dessa forma, fica evidente que a Justiça Estadual é responsável pela concessão de benefícios acidentários, enquanto a Justiça Federal atua em matérias previdenciárias.

No caso, o benefício foi concedido por meio de ação judicial que tramitou na JUSTIÇA FEDERAL, reafirmando sua natureza previdenciária. Contudo, o INSS implantou o benefício de forma equivocada, considerando-o acidentário.

Portanto, tendo em vista que o benefício possui natureza previdenciária, requer-se a exclusão desse benefício do índice FAP da empresa.

# CONCOMITANTE - AUXÍLIO-DOENÇA (B91) COM APOSENTADORIA

Conforme dispõe o artigo 7º, inciso XXIV, da Constituição da República Federativa do Brasil de 1988, é assegurado aos empregados urbanos e rurais o direito à aposentadoria, desde que atendidos os requisitos legais. Esse benefício constitui uma prestação previdenciária mensal conferida pela Previdência Social.

Importa ressaltar, ademais, a vedação de sua acumulação com o auxílio-doença, conforme preceituam o artigo 167, inciso I, do Decreto nº 3.048/1999, o artigo 124, inciso I, da Lei nº 8.213/1991 e o artigo 639, inciso I, da Instrução Normativa nº 128/2022 do INSS.

Não obstante a proibição legal de acumulação entre aposentadoria e auxílio-doença, foi concedido o benefício de auxílio-doença em questão ao segurado, apesar de este já estar em gozo do benefício de aposentadoria (NB xxxxx), com data de início (DIB) fixada em [data]. Tal acumulação indevida configura violação a legislação vigente.

Portanto, a inclusão desse benefício não atende aos critérios e metodologia estabelecidos no Fator Acidentário de Prevenção (FAP), considerando que o segurado já é beneficiário de aposentadoria.

Diante do exposto, requer-se a exclusão desse benefício da base de cálculo do índice FAP.

## CONCESSÃO CONCOMITANTE DE DOIS AUXÍLIO-DOENÇA (DOIS B91)

O segurado que exerce mais de uma atividade abrangida pela Previdência Social e fica incapacitado para uma ou mais atividades, seja na espécie previdenciária ou acidentária, terá direito a um único benefício, conforme estipulado no art. 337, caput, da Instrução Normativa (IN) nº 128/2022 do INSS.

Logo, é vedado ao segurado receber simultaneamente dois ou mais benefícios de incapacidade temporária, como previsto no art. 639, XII, da mesma Instrução Normativa.

Todavia, apesar da proibição legal da cumulação de dois benefícios B91, foi concedido concomitantemente o benefício em tela, enquanto o empregado já estava usufruindo do auxílio-doença por acidente de trabalho, espécie B91, nº XXXXXX, com DIB em [data] e DCB em [data].

Diante da vedação legal à concessão simultânea de mais de um auxílio-doença por acidente de trabalho, é evidente que o benefício em discussão, não deve ser incluído na base de cálculo do FAP.

Diante do exposto, requer-se a exclusão deste benefício da base de cálculo do índice FAP.

## CONCESSÃO - AUXÍLIO-ACIDENTE (B94) COM APOSENTADORIA

Conforme dispõe o artigo 7º, inciso XXIV, da Constituição da República Federativa do Brasil de 1988, é assegurado aos empregados urbanos e rurais o direito à aposentadoria, desde que atendidos os requisitos legais. Esse benefício constitui uma prestação previdenciária mensal conferida pela Previdência Social.

Importa ressaltar, ademais, a vedação de sua acumulação com o auxílio-acidente, conforme preceituam o artigo 167, inciso IX, do Decreto nº 3.048/1999, o artigo 86, parágrafo 2º, da Lei nº 8.213/1991 e o artigo 639, inciso VI, da Instrução Normativa nº 128/2022 do INSS.

Não obstante a proibição legal de acumulação entre aposentadoria e auxílio-acidente, foi concedido o benefício de auxílio-acidente em questão ao segurado, apesar de este já estar em gozo do benefício de aposentadoria (NB xxxxx), com data de início (DIB) fixada em [data]. Tal acumulação indevida configura violação a legislação vigente.

Portanto, a inclusão desse benefício não atende aos critérios e metodologia estabelecidos no Fator Acidentário de Prevenção (FAP), considerando que o segurado já é beneficiário de aposentadoria.

Diante do exposto, requer-se a exclusão desse benefício da base de cálculo do índice FAP.

# AUXÍLIO-ACIDENTE (B94) DUPLICADO

A Resolução nº 1.347/2021 do CNPS estabelece os parâmetros e critérios para a apuração do índice Fator Acidentário de Prevenção (FAP). Entre as diretrizes, destaca-se a regra disposta no item 2.5, que determina que o cálculo anual do FAP considera os eventos de acidentalidade ocorridos nos dois anos anteriores ao ano de cálculo.

Além disso, para a composição do índice, apenas um único benefício de cada espécie (B91, B92, B93 e B94) pode ser considerado para cada evento acidentário. Dessa forma, a inclusão de dois benefícios da mesma espécie, oriundos do mesmo fato gerador, mesmo que em vigências distintas, contraria a metodologia estabelecida pela norma, resultando em contagem duplicada e registro do mesmo acidente ou doença do trabalho e, consequentemente, distorcendo o cálculo do FAP.

Neste contexto, verificou-se a concessão de dois benefícios de auxílio-acidente decorrentes do mesmo evento acidentário, sendo que o benefício nº xxxxx já foi incluído no índice FAP. Portanto, a inclusão de dois benefícios da mesma espécie (B94) relacionados ao mesmo fato gerador contraria a metodologia de cálculo do FAP e resulta em duplicidade na contagem dos eventos.

Diante do exposto, requer-se a exclusão deste benefício da base de cálculo do índice FAP.

# AUXÍLIO-DOENÇA (B94) SEM CUSTO

O erro constata-se pela inclusão na base de cálculo do FAP do benefício nº xxxxx com a mesma data de início (DIB) e de cessação (DCB).

Isso porque, não existe a possibilidade de concessão de benefício acidentário sem prazo de duração (DIB = DCB) e sem custo associado, ou seja, esse benefício nunca existiu no mundo jurídico. E, se não existiu não pode ser incluído na base de cálculo do FAP da Autora.

Assim, o equívoco da Previdência Social ao incluir no sistema o benefício de auxílio-acidente com datas de início (DIB) e cessação (DCB) coincidentes, resultou em erro no cálculo de frequência, gravidade e custo, aumentando indevidamente o índice FAP e causando maior tributação à Autora.

Diante do exposto, requer-se a exclusão deste benefício da base de cálculo do índice FAP.

# DISCUSSÃO MÉDICA / OUTROS

É muito comum perceber empresas que fazem discussões médicas no corpo das contestações administrativas de FAP.

Esse tipo de discussão não é cabível no momento das contestações anuais de FAP, mas apenas nas contestações de nexo técnico.

As contestações de fap e de nexo técnico são completamente diferentes e acontecem em momentos diferentes.

Orientação para interpretação de contexto: todas as vezes em que você identificar uma contestação que não se adeque aos padrões dos tópicos indicados acima, é necessário avançar para a próxima etapa: interpretação livre do texto.

Nessa etapa de interpretação livre, é muito comum percebermos casos em que houve DISCUSSÃO MÉDICA.

O que precisamos é: sempre que você entrar na etapa de interpretação livre, verifique se a contestação de FAP está trazendo uma DISCUSSÃO MÉDICA. Em caso positivo, classifique o benefício sob a categoria DISCUSSÃO MÉDICA.

Para qualquer outro tipo de discussão, que não seja médica, classifique o benefício como "OUTROS ARGUMENTOS".
"""

    FIXED_PROMPT_PREFIX = """# Tarefa

Classifique o texto e retorne uma lista de SLUGS de 1 a 3 itens.

## Slugs válidos

{{SLUGS_MARKDOWN}}
"""

    FIXED_PROMPT_SUFFIX = """## Formato de resposta

- Retorne slugs em `topics` somente quando `confidence` for maior ou igual a 0.80.
- Retorne `topic_confidences` como um array de numeros na mesma ordem de `topics`.
- Se `confidence` for menor que 0.80, retorne `topics` vazio (`[]`).

```json
{"topics":["slug1","slug2"],"topic_confidences":[0.91,0.83],"confidence":0.0,"reason":"explicacao curta ou vazio"}
```

## Texto para classificar

{{TEXT}}
"""

    ALLOWED_TOPICS: tuple[str, ...] = (
        "NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO",
        "ACIDENTE DE TRAJETO",
        "ACIDENTE DE TRAJETO SEM CAT – AÇÃO JUDICIAL",
        "RESTABELECIMENTO DE BENEFÍCIO – B91 60 DIAS",
        "AUXÍLIO-DOENÇA PREVIDENCIÁRIO – B31",
        "ERRO DE ESTABELECIMENTO",
        "PRÉ-FAP",
        "OUTRA EMPRESA – CAT VINCULADA",
        "OUTRA EMPRESA – NUNCA FOI EMPREGADO",
        "OUTRA EMPRESA – APÓS A RESCISÃO CONTRATUAL",
        "OUTRA EMPRESA – DID ANTERIOR À ADMISSÃO NA EMPRESA",
        "NEXO AFASTADO",
        "BENEFÍCIO CONCEDIDO NA JUSTIÇA FEDERAL",
        "CONCOMITANTE – AUXÍLIO-DOENÇA (B91) COM APOSENTADORIA",
        "CONCESSÃO CONCOMITANTE DE DOIS AUXÍLIO-DOENÇA",
        "CONCESSÃO - AUXÍLIO-ACIDENTE (B94) COM APOSENTADORIA",
        "AUXÍLIO-ACIDENTE (B94) DUPLICADO",
        "AUXÍLIO-DOENÇA (B94) SEM CUSTO",
        "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS",
        "OUTROS ARGUMENTOS",
    )

    SLUG_TO_TOPIC: dict[str, str] = {
        "nexo_pendente": "NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO",
        "acidente_trajeto": "ACIDENTE DE TRAJETO",
        "acidente_trajeto_sem_cat": "ACIDENTE DE TRAJETO SEM CAT – AÇÃO JUDICIAL",
        "restabelecimento_b91_60": "RESTABELECIMENTO DE BENEFÍCIO – B91 60 DIAS",
        "b31_previdenciario": "AUXÍLIO-DOENÇA PREVIDENCIÁRIO – B31",
        "erro_estabelecimento": "ERRO DE ESTABELECIMENTO",
        "pre_fap": "PRÉ-FAP",
        "outra_empresa_cat": "OUTRA EMPRESA – CAT VINCULADA",
        "outra_empresa_nunca_empregado": "OUTRA EMPRESA – NUNCA FOI EMPREGADO",
        "outra_empresa_pos_rescisao": "OUTRA EMPRESA – APÓS A RESCISÃO CONTRATUAL",
        "outra_empresa_did_anterior": "OUTRA EMPRESA – DID ANTERIOR À ADMISSÃO NA EMPRESA",
        "nexo_afastado": "NEXO AFASTADO",
        "beneficio_justica_federal": "BENEFÍCIO CONCEDIDO NA JUSTIÇA FEDERAL",
        "concomitante_b91_aposentadoria": "CONCOMITANTE – AUXÍLIO-DOENÇA (B91) COM APOSENTADORIA",
        "concomitante_dois_b91": "CONCESSÃO CONCOMITANTE DE DOIS AUXÍLIO-DOENÇA",
        "concomitante_b94_aposentadoria": "CONCESSÃO - AUXÍLIO-ACIDENTE (B94) COM APOSENTADORIA",
        "b94_duplicado": "AUXÍLIO-ACIDENTE (B94) DUPLICADO",
        "b94_sem_custo": "AUXÍLIO-DOENÇA (B94) SEM CUSTO",
        "discussao_medica": "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS",
        "outros_argumentos": "OUTROS ARGUMENTOS",
    }
    VALID_SLUGS: set[str] = set(SLUG_TO_TOPIC.keys())

    MEDICAL_TERMS: tuple[str, ...] = (
        "laudo",
        "pericia",
        "diagnostico",
        "cid",
        "atestado",
        "prognostico",
        "parecer medico",
        "prontuario",
        "incapacidade",
    )

    PRE_FAP_TERMS: tuple[str, ...] = (
        "pre fap",
        "pre-fap",
        "art. 202-a",
        "art 202-a",
        "decreto 6.957",
        "decreto nº 6.957",
        "decreto n 6.957",
        "abril de 2007",
        "1º de abril de 2007",
        "1 de abril de 2007",
        "antes de abril de 2007",
        "anterior a abril de 2007",
        "antes de 2007",
        "did 200",
        "did 19",
    )

    OTHER_COMPANY_TERMS: tuple[str, ...] = (
        "outro cnpj",
        "outro estabelecimento",
        "outra empresa",
        "nao relacionado a este estabelecimento",
        "nao esta relacionado a este estabelecimento",
        "não relacionado a este estabelecimento",
        "não está relacionado a este estabelecimento",
        "nunca foi empregado",
        "apos a rescisao",
        "após a rescisão",
        "did anterior a admissao",
        "did anterior à admissão",
        "cat vinculada",
    )

    def __init__(self, model_name: str | None = None, temperature: float = 0.1):
        self.model_name = model_name or self.get_default_model_name()
        self.temperature = temperature
        self.token_usage_service = TokenUsageService()

    @staticmethod
    def get_default_model_name() -> str:
        return os.environ.get("FAP_CLASSIFIER_MODEL") or DEFAULT_MODEL_MINI

    @classmethod
    def _load_selected_model_name(cls, law_firm_id: int | None) -> str | None:
        if not law_firm_id:
            return None

        setting = FapContestationClassifierSetting.query.filter_by(law_firm_id=law_firm_id).first()
        if setting and (setting.selected_model or "").strip():
            return setting.selected_model.strip()
        return None

    @classmethod
    def _normalize_topic(cls, value: str | None) -> str:
        if not value:
            return ""

        normalized = str(value).strip().upper()
        replacements = {
            "TÉ": "TE",
            "É": "E",
            "Ê": "E",
            "Ã": "A",
            "Á": "A",
            "Â": "A",
            "À": "A",
            "Í": "I",
            "Ó": "O",
            "Ô": "O",
            "Õ": "O",
            "Ú": "U",
            "Ç": "C",
            "–": "-",
            "—": "-",
            "‑": "-",
        }

        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def _build_topic_lookup(cls) -> dict[str, str]:
        return {cls._normalize_topic(topic): topic for topic in cls.ALLOWED_TOPICS}

    @classmethod
    def _get_canonical_topic(cls, topic: str | None) -> str | None:
        normalized = cls._normalize_topic(topic)
        if not normalized:
            return None

        topic_lookup = cls._build_topic_lookup()
        return topic_lookup.get(normalized)

    @classmethod
    def _normalize_text_for_match(cls, value: str) -> str:
        normalized = cls._normalize_topic(value)
        normalized = normalized.replace("-", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _strip_markdown_json_fence(raw_content: str) -> str:
        content = (raw_content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        return content

    def _safe_parse_json(self, raw_content: str) -> dict[str, Any] | None:
        if not raw_content:
            return None

        content = self._strip_markdown_json_fence(raw_content)

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception:
            # Fallback para respostas com texto adicional fora do JSON.
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                return None

            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

    @classmethod
    def _build_slugs_markdown(cls) -> str:
        lines = []
        for slug, topic in cls.SLUG_TO_TOPIC.items():
            lines.append(f"- {topic} -> {slug}")
        return "\n".join(lines)

    @classmethod
    def get_default_user_prompt_markdown(cls) -> str:
        return cls.USER_PROMPT_MARKDOWN_DEFAULT.strip()

    @classmethod
    def get_default_reference_markdown(cls) -> str:
        return cls.REFERENCE_MARKDOWN_DEFAULT.strip()

    @staticmethod
    def compute_prompt_hash(prompt_markdown: str) -> str:
        return hashlib.sha256((prompt_markdown or "").encode("utf-8")).hexdigest()

    @classmethod
    def _remove_non_editable_sections(cls, prompt_markdown: str) -> str:
        prompt = (prompt_markdown or "").strip()
        if not prompt:
            return ""

        prompt = re.sub(
            r"(?is)^\s*#\s*Tarefa\s*.*?(?=\n##\s|\Z)",
            "\n",
            prompt,
        )
        prompt = re.sub(
            r"(?is)\n*##\s*Slugs\s+v[aá]lidos\s*.*?(?=\n##\s|\Z)",
            "\n",
            prompt,
        )

        prompt = re.sub(
            r"(?is)\n*##\s*Formato\s+de\s+resposta.*?(?=\n##\s|\Z)",
            "\n",
            prompt,
        )
        prompt = re.sub(
            r"(?is)\n*##\s*Texto\s+para\s+classificar.*?(?=\n##\s|\Z)",
            "\n",
            prompt,
        )
        prompt = prompt.replace("{{SLUGS_MARKDOWN}}", "")
        prompt = prompt.replace("{{TEXT}}", "")
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
        return prompt.strip()

    @classmethod
    def _render_user_prompt(
        cls,
        prompt_markdown: str,
        cleaned_text: str,
        reference_markdown: str,
    ) -> str:
        prompt_body = cls._remove_non_editable_sections(
            prompt_markdown or cls.get_default_user_prompt_markdown()
        )
        reference_body = (reference_markdown or cls.get_default_reference_markdown()).strip()
        fixed_prefix = cls.FIXED_PROMPT_PREFIX.strip().replace("{{SLUGS_MARKDOWN}}", cls._build_slugs_markdown())
        fixed_suffix = cls.FIXED_PROMPT_SUFFIX.strip().replace("{{TEXT}}", cleaned_text)
        reference_section = ""
        if reference_body:
            reference_section = (
                "## Referencia tecnico-juridica para interpretacao\n\n"
                f"{reference_body.strip()}"
            )

        if prompt_body:
            if reference_section:
                return f"{fixed_prefix}\n\n{prompt_body}\n\n{reference_section}\n\n{fixed_suffix}".strip()
            return f"{fixed_prefix}\n\n{prompt_body}\n\n{fixed_suffix}".strip()

        if reference_section:
            return f"{fixed_prefix}\n\n{reference_section}\n\n{fixed_suffix}".strip()
        return f"{fixed_prefix}\n\n{fixed_suffix}".strip()

    @classmethod
    def _load_user_prompt_markdown(cls, law_firm_id: int | None) -> str:
        if not law_firm_id:
            return cls.get_default_user_prompt_markdown()

        prompt_version = (
            FapContestationClassifierPromptVersion.query.filter_by(
                law_firm_id=law_firm_id,
                is_active=True,
            )
            .order_by(
                FapContestationClassifierPromptVersion.version.desc(),
                FapContestationClassifierPromptVersion.id.desc(),
            )
            .first()
        )
        if prompt_version and (prompt_version.prompt_markdown or "").strip():
            return prompt_version.prompt_markdown

        return cls.get_default_user_prompt_markdown()

    @classmethod
    def _load_reference_markdown(cls, law_firm_id: int | None) -> str:
        if not law_firm_id:
            return cls.get_default_reference_markdown()

        reference_version = (
            FapContestationClassifierReferenceVersion.query.filter_by(
                law_firm_id=law_firm_id,
                is_active=True,
            )
            .order_by(
                FapContestationClassifierReferenceVersion.version.desc(),
                FapContestationClassifierReferenceVersion.id.desc(),
            )
            .first()
        )
        if reference_version and (reference_version.reference_markdown or "").strip():
            return reference_version.reference_markdown

        return cls.get_default_reference_markdown()

    def _fallback_topic(self, text: str) -> str:
        normalized_text = self._normalize_text_for_match(text)
        if any(term.upper() in normalized_text for term in self.MEDICAL_TERMS):
            return "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS"
        return "OUTROS ARGUMENTOS"

    def _fallback_slug(self, text: str) -> str:
        normalized_text = self._normalize_text_for_match(text)
        if any(term.upper() in normalized_text for term in self.MEDICAL_TERMS):
            return "discussao_medica"
        return "outros_argumentos"

    @classmethod
    def _build_topics_response(
        cls,
        topics: list[str],
        *,
        topic_confidences: list[float | None] | None = None,
    ) -> dict[str, Any]:
        return {
            "topics": topics,
            "topic_confidences": topic_confidences or [],
        }

    @classmethod
    def _parse_confidence(cls, value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            confidence = float(value)
        except (TypeError, ValueError):
            return None

        if confidence < 0:
            return 0.0
        if confidence > 1:
            return 1.0
        return confidence

    def _build_topic_confidences(
        self,
        parsed: dict[str, Any],
        topics_slugs: list[str],
        *,
        fallback_confidence: float | None = None,
    ) -> list[float | None]:
        details_by_slug: dict[str, float | None] = {}
        raw_details = parsed.get("topic_confidences")

        if isinstance(raw_details, list):
            if all(not isinstance(item, dict) for item in raw_details):
                ordered_confidences: list[float | None] = []
                for index, slug in enumerate(topics_slugs):
                    raw_confidence = raw_details[index] if index < len(raw_details) else fallback_confidence
                    ordered_confidences.append(self._parse_confidence(raw_confidence))
                return [fallback_confidence if item is None else item for item in ordered_confidences]

        if isinstance(raw_details, dict):
            for raw_slug, raw_confidence in raw_details.items():
                slug = str(raw_slug or "").strip().lower()
                if slug not in self.VALID_SLUGS or slug not in topics_slugs or slug in details_by_slug:
                    continue
                details_by_slug[slug] = self._parse_confidence(raw_confidence)

        if isinstance(raw_details, list):
            for item in raw_details:
                if not isinstance(item, dict):
                    continue

                slug = str(item.get("slug") or item.get("topic") or "").strip().lower()
                if slug not in self.VALID_SLUGS or slug not in topics_slugs or slug in details_by_slug:
                    continue

                details_by_slug[slug] = self._parse_confidence(item.get("confidence"))

        ordered_details: list[float | None] = []
        for slug in topics_slugs:
            detail = details_by_slug.get(slug)
            confidence = fallback_confidence if detail is None else detail
            if confidence is None:
                confidence = fallback_confidence
            ordered_details.append(confidence)

        return ordered_details

    def _has_pre_fap_evidence(self, normalized_text: str) -> bool:
        if any(term.upper() in normalized_text for term in self.PRE_FAP_TERMS):
            return True

        year_matches = re.findall(r"\b(19\d{2}|20\d{2})\b", normalized_text)
        if year_matches and any(int(year) < 2007 for year in year_matches):
            if "DID" in normalized_text or "ACIDENT" in normalized_text:
                return True

        return False

    def _has_other_company_evidence(self, normalized_text: str) -> bool:
        if any(term.upper() in normalized_text for term in self.OTHER_COMPANY_TERMS):
            return True

        # Cobrir variacoes frasais comuns em justificativas de erro de estabelecimento.
        if re.search(
            r"NAO\s+(?:ESTA\s+)?RELACIONAD[OA]\s+A\s+ESTE\s+ESTABELECIMENTO",
            normalized_text,
        ):
            return True

        # Quando ha mencao de CNPJ diferente em contexto de estabelecimento, tambem e forte indicio.
        if "CNPJ" in normalized_text and "ESTABELECIMENTO" in normalized_text and "NAO" in normalized_text:
            return True

        return False

    def _has_positive_cat_evidence(self, normalized_text: str) -> bool:
        has_negative_cat_signal = bool(
            re.search(r"SEM\s+CAT|AUSENCIA\s+DE\s+CAT|INEXISTENCIA\s+DE\s+CAT|NAO\s+HA\s+CAT", normalized_text)
        )
        if has_negative_cat_signal:
            return False

        return bool(
            re.search(
                r"\bCAT\b|EMISSAO\s+DE\s+CAT|EMITIU\s+CAT|EMISSAO\s+DA\s+CAT|RESPONSAVEL\s+PELA\s+EMISSAO\s+DE\s+CAT|CAT\s+VINCULADA",
                normalized_text,
            )
        )

    def _has_other_company_cat_evidence(self, normalized_text: str) -> bool:
        if not self._has_positive_cat_evidence(normalized_text):
            return False

        if self._has_other_company_evidence(normalized_text):
            return True

        return bool(
            re.search(
                r"OUTRA\s+EMPRESA|EMPRESA\s+DIVERSA|OUTRO\s+CNPJ|OUTRO\s+ESTABELECIMENTO|VINCULO\s+A\s+OUTR[OA]\s+EMPRESA",
                normalized_text,
            )
        )

    def _has_pos_rescisao_evidence(self, normalized_text: str) -> bool:
        return bool(
            re.search(
                r"APOS\s+A\s+RESCISAO|APOS\s+RESCISAO|POS\s+RESCISAO|DESLIGAD[OA]|RESCISAO\s+CONTRATUAL|DIB\s+(?:E\s+)?POSTERIOR",
                normalized_text,
            )
        )

    def _has_b94_duplicado_evidence(self, normalized_text: str) -> bool:
        return bool(
            re.search(
                r"B94\s+DUPLICAD|DOIS\s+B94|2\s*B94|MESMO\s+FATO\s+GERADOR.*B94|B94.*MESMO\s+FATO\s+GERADOR|JA\s+FOI\s+INCLUID[OA].*B94|B94.*DUAS\s+VEZES",
                normalized_text,
            )
        )

    def _has_aposentadoria_concomitante_evidence(self, normalized_text: str) -> bool:
        has_aposentadoria = bool(re.search(r"\bAPOSENTADORIA\b|\bAPOSENTAD[OA]\b", normalized_text))
        has_accumulation_signal = bool(
            re.search(r"ACUMULA|ACUMULACAO|CUMULA|CONCOMITANT|VEDACAO\s+DE\s+ACUMUL|PROIBICAO\s+DE\s+ACUMUL", normalized_text)
        )
        return has_aposentadoria and has_accumulation_signal

    def _detect_critical_regex_slugs(self, normalized_text: str) -> list[str]:
        detected: list[str] = []

        has_ntp = bool(re.search(r"\bNTP\b|NEXO TECNICO PREVIDENCIARIO", normalized_text))
        has_pending_signal = bool(
            re.search(
                r"PENDENT[EA]|PENDENTE DE JULGAMENTO|AGUARDANDO JULGAMENTO|EFEITO SUSPENSIVO",
                normalized_text,
            )
        )
        has_contestation = bool(re.search(r"CONTESTACAO|CONTESTAR", normalized_text))
        if has_ntp and (has_pending_signal or has_contestation):
            detected.append("nexo_pendente")

        has_trajeto = bool(re.search(r"ACIDENTE DE TRAJETO", normalized_text))
        has_judicial_signal = bool(
            re.search(r"ACAO JUDICIAL|PROCESSO|AUTOS|SENTENCA|DECISAO JUDICIAL", normalized_text)
        )
        has_sem_cat_signal = bool(re.search(r"SEM CAT|AUSENCIA DE CAT|INEXISTENCIA DE CAT", normalized_text))
        has_positive_cat_evidence = self._has_positive_cat_evidence(normalized_text)
        if has_trajeto and not has_positive_cat_evidence and (has_sem_cat_signal or has_judicial_signal):
            detected.append("acidente_trajeto_sem_cat")

        has_justica_federal = bool(re.search(r"\bJUSTICA\s+FEDERAL\b", normalized_text))
        has_legal_basis = bool(re.search(r"SUMULA\s*235|ART\.?\s*109", normalized_text))
        has_previdenciario_basis = bool(re.search(r"NATUREZA\s+PREVIDENCIARIA|BENEFICIO\s+PREVIDENCIARIO", normalized_text))
        if has_justica_federal and (has_legal_basis or has_previdenciario_basis):
            detected.append("beneficio_justica_federal")

        return detected

    def _has_justica_federal_evidence(self, normalized_text: str) -> bool:
        has_justica_federal = bool(re.search(r"\bJUSTICA\s+FEDERAL\b", normalized_text))
        has_legal_basis = bool(re.search(r"SUMULA\s*235|ART\.?\s*109", normalized_text))
        has_previdenciario_basis = bool(re.search(r"NATUREZA\s+PREVIDENCIARIA|BENEFICIO\s+PREVIDENCIARIO", normalized_text))
        return has_justica_federal and (has_legal_basis or has_previdenciario_basis)

    def _apply_rule_based_guards(self, text: str, topics_slugs: list[str]) -> list[str]:
        normalized_text = self._normalize_text_for_match(text)
        guarded_topics = topics_slugs.copy()
        critical_slugs = self._detect_critical_regex_slugs(normalized_text)

        other_company_slugs = {
            "erro_estabelecimento",
            "outra_empresa_cat",
            "outra_empresa_nunca_empregado",
            "outra_empresa_pos_rescisao",
            "outra_empresa_did_anterior",
        }

        has_pre_fap = self._has_pre_fap_evidence(normalized_text)
        has_other_company = self._has_other_company_evidence(normalized_text)
        has_other_company_cat = self._has_other_company_cat_evidence(normalized_text)
        has_pos_rescisao = self._has_pos_rescisao_evidence(normalized_text)
        has_b94_duplicado = self._has_b94_duplicado_evidence(normalized_text)
        has_aposentadoria_concomitante = self._has_aposentadoria_concomitante_evidence(normalized_text)
        has_justica_federal = self._has_justica_federal_evidence(normalized_text)

        for slug in reversed(critical_slugs):
            guarded_topics = [item for item in guarded_topics if item != slug]
            guarded_topics.insert(0, slug)

        if "acidente_trajeto_sem_cat" in guarded_topics:
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto"]

        # Se há CAT numerada explícita no texto, é ACIDENTE DE TRAJETO (com CAT), não sem_cat.
        has_trajeto_text = bool(re.search(r"ACIDENTE DE TRAJETO", normalized_text))
        has_positive_cat_evidence = self._has_positive_cat_evidence(normalized_text)
        if has_trajeto_text and has_positive_cat_evidence:
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto_sem_cat"]
            if "acidente_trajeto" not in guarded_topics:
                guarded_topics.insert(0, "acidente_trajeto")

        if has_other_company_cat:
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto_sem_cat"]
            guarded_topics = [slug for slug in guarded_topics if slug != "outra_empresa_cat"]
            guarded_topics.insert(0, "outra_empresa_cat")

        if has_other_company and has_pos_rescisao:
            guarded_topics = [slug for slug in guarded_topics if slug != "outra_empresa_pos_rescisao"]
            insert_index = 1 if guarded_topics and guarded_topics[0] == "outra_empresa_cat" else 0
            guarded_topics.insert(insert_index, "outra_empresa_pos_rescisao")

            # Em cenário de outra empresa + pós-rescisão, acidente de trajeto tende a ser contexto,
            # não a tese principal da exclusão para este CNPJ.
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto"]

        if not has_justica_federal:
            guarded_topics = [slug for slug in guarded_topics if slug != "beneficio_justica_federal"]

        if has_pre_fap:
            guarded_topics = [slug for slug in guarded_topics if slug != "pre_fap"]
            guarded_topics.insert(0, "pre_fap")

        if not has_b94_duplicado:
            guarded_topics = [slug for slug in guarded_topics if slug != "b94_duplicado"]

        if not has_aposentadoria_concomitante:
            guarded_topics = [
                slug
                for slug in guarded_topics
                if slug not in {"concomitante_b91_aposentadoria", "concomitante_b94_aposentadoria"}
            ]

        if has_other_company:
            has_other_company_topic = any(slug in other_company_slugs for slug in guarded_topics)
            if not has_other_company_topic:
                guarded_topics.insert(0, "erro_estabelecimento")
            guarded_topics = [slug for slug in guarded_topics if slug != "discussao_medica"]
        else:
            guarded_topics = [slug for slug in guarded_topics if slug not in other_company_slugs]

        if critical_slugs:
            guarded_topics = [slug for slug in guarded_topics if slug != "discussao_medica"]

        # Remove outros_argumentos e discussao_medica quando há tópico específico
        GENERIC_SLUGS = {"outros_argumentos", "discussao_medica"}
        specific_topics = [s for s in guarded_topics if s not in GENERIC_SLUGS]
        if specific_topics:
            guarded_topics = specific_topics

        deduped: list[str] = []
        for slug in guarded_topics:
            if slug in self.VALID_SLUGS and slug not in deduped:
                deduped.append(slug)
            if len(deduped) >= 3:
                break

        if not deduped:
            deduped = [self._fallback_slug(text)]

        return deduped

    @staticmethod
    def _extract_last_message_content(response_payload: dict[str, Any] | None) -> str:
        if not isinstance(response_payload, dict):
            return ""

        messages = response_payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return ""

        last_message = messages[-1]

        if hasattr(last_message, "content"):
            return str(last_message.content or "").strip()

        if isinstance(last_message, dict):
            return str(last_message.get("content", "") or "").strip()

        return str(last_message or "").strip()

    def classify(
        self,
        text: str,
        *,
        law_firm_id: int | None = None,
        prompt_markdown_override: str | None = None,
        reference_markdown_override: str | None = None,
        model_name_override: str | None = None,
    ) -> dict[str, Any]:
        """
        Classifica um texto de justificativa FAP em tópico padronizado.

        Returns:
            Dict no formato:
            {
              "topics": ["TOPICO 1", "TOPICO 2", ...],
                            "topic_confidences": [0.91, 0.84]
            }
        """
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            return self._build_topics_response(
                ["OUTROS ARGUMENTOS"],
                                topic_confidences=[None],
            )

        user_prompt_markdown = (
            self._remove_non_editable_sections(prompt_markdown_override)
            if prompt_markdown_override is not None
            else self._load_user_prompt_markdown(law_firm_id)
        )
        reference_markdown = (
            str(reference_markdown_override or "").strip()
            if reference_markdown_override is not None
            else self._load_reference_markdown(law_firm_id)
        )
        user_prompt = self._render_user_prompt(user_prompt_markdown, cleaned_text, reference_markdown)
        effective_model_name = (
            str(model_name_override or "").strip()
            or self._load_selected_model_name(law_firm_id)
            or self.model_name
        )

        try:
            llm = ChatOpenAI(model=effective_model_name, temperature=self.temperature)
            agent = create_agent(model=llm, system_prompt=self.SYSTEM_PROMPT)

            call_started_at = time.time()
            response_payload = agent.invoke(
                {"messages": [{"role": "user", "content": user_prompt}]}
            )
            latency_ms = int((time.time() - call_started_at) * 1000)

            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="FAPContestationClassifierAgent",
                action_name="classify",
                print_prefix="[FAPContestationClassifierAgent][tokens]",
                model_name=effective_model_name,
                model_provider="openai",
                user_id=None,
                law_firm_id=law_firm_id,
                chat_session_id=None,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "input_chars": len(cleaned_text),
                    "temperature": self.temperature,
                },
            )

            raw_content = self._extract_last_message_content(response_payload)
            parsed = self._safe_parse_json(raw_content)

            if not parsed:
                return self._build_topics_response(
                    ["OUTROS ARGUMENTOS"],
                    topic_confidences=[None],
                )

            confidence = self._parse_confidence(parsed.get("confidence"))

            raw_topics = parsed.get("topics")
            topics_slugs: list[str] = []

            if isinstance(raw_topics, list):
                for item in raw_topics:
                    slug = str(item or "").strip().lower()
                    if slug in self.VALID_SLUGS and slug not in topics_slugs:
                        topics_slugs.append(slug)
                    if len(topics_slugs) >= 3:
                        break

            # Compatibilidade com formato antigo: {"topic":"slug"}
            if not topics_slugs:
                topic_slug = str(parsed.get("topic") or "").strip().lower()
                if topic_slug in self.VALID_SLUGS:
                    topics_slugs = [topic_slug]

            if confidence is None or confidence < self.MIN_CONFIDENCE:
                fallback_slug = self._fallback_slug(cleaned_text)
                return self._build_topics_response(
                    [self.SLUG_TO_TOPIC[fallback_slug]],
                    topic_confidences=[confidence],
                )

            if not topics_slugs:
                fallback_slug = self._fallback_slug(cleaned_text)
                return self._build_topics_response(
                    [self.SLUG_TO_TOPIC[fallback_slug]],
                    topic_confidences=[confidence],
                )

            topics_slugs = self._apply_rule_based_guards(cleaned_text, topics_slugs)

            topics = [self.SLUG_TO_TOPIC[slug] for slug in topics_slugs]
            topic_confidences = self._build_topic_confidences(
                parsed,
                topics_slugs,
                fallback_confidence=confidence,
            )

            return self._build_topics_response(topics, topic_confidences=topic_confidences)

        except Exception as exc:
            logger.exception("Erro ao classificar justificativa FAP: %s", exc)
            return self._build_topics_response(
                ["OUTROS ARGUMENTOS"],
                topic_confidences=[None],
            )
