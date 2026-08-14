"""
Regras de palavra-chave do Diário Oficial — o motor de casamento.

Este módulo **não sabe o que é alerta**: recebe regras e matérias e devolve
``{article_id: [rule_id]}``. Quem grava alerta é o ``dou_alert_service``, que
continua sendo o dono único desse registro.

Por que motor próprio e não o Meilisearch, que já indexa o acervo: o índice
busca com tolerância a erro e trata o termo como prefixo. Medido em 7 dias de
acervo, ``FAP`` devolve **92** matérias pelo índice e **12** aqui — as 80 de
diferença são FAPED (82x), FAPEG (34x), FAPESP, FAPEMIG, FAPERJ, fundações de
amparo à pesquisa. Para uma caixa de busca isso é recall; para um alerta são 80
falsos positivos que fazem a pessoa desligar a regra e nunca mais voltar.

E ``Fator Acidentário de Prevenção`` devolve **748** pelo índice contra **7**
aqui, porque o modo OU casa "Fator" e "Prevenção" sozinhos — 107x as mesmas
palavras. **Por isso não existe modo OU aqui.** Quem quiser OU cria duas
regras, e aí vê o volume de cada uma separado.

De quebra o alerta deixa de depender do índice, o que já era invariante do
módulo: o índice serve à tela de busca; o alerta não pode depender dele.
"""

import logging
import re
import unicodedata
from datetime import date, timedelta
from types import SimpleNamespace

from app.services.dou_search_service import orgao_raiz

logger = logging.getLogger(__name__)

# Modos de casamento. Não existe OU — ver docstring do módulo.
MODO_FRASE = 'frase'        # a sequência inteira, na ordem
MODO_PALAVRAS = 'palavras'  # todas as palavras, em qualquer posição
MODOS = (MODO_FRASE, MODO_PALAVRAS)

MODO_LABELS = {
    MODO_FRASE: 'frase exata',
    MODO_PALAVRAS: 'todas as palavras',
}

# Sonda menor que isto não peneira nada — vale mais varrer tudo.
MIN_SONDA = 3

# Janela do teste e do backfill ao salvar: o que foi visto é o que chega.
DIAS_TESTE = 7

# Cortes do veredito, ancorados no volume real: a carteira inteira de clientes
# gera ~6 alertas/dia (41 em 7 dias). Uma regra que passa disso já merece
# atenção; acima de 20/dia ela sozinha supera tudo o que existe hoje.
ALERTAS_DIA_CARTEIRA = 6
CORTE_OK = 5
CORTE_ALTO = 20

NIVEL_VAZIO = 'vazio'
NIVEL_OK = 'ok'
NIVEL_ALTO = 'alto'
NIVEL_RUIDOSO = 'ruidoso'


def normalizar(valor: str | None) -> str:
    """Minúsculo e sem acento — a forma em que texto e termo se comparam."""
    texto = unicodedata.normalize('NFKD', valor or '')
    return ''.join(c for c in texto if not unicodedata.combining(c)).lower()


def sonda(termo: str | None) -> str | None:
    """A maior corrida de caracteres sem acento do termo, ou None.

    É a peneira do banco: ``licitação`` vira ``licita``, ``Fator Acidentário de
    Prevenção`` vira ``fator acident``. Esse pedaço está **literalmente** no
    texto publicado, então ``LIKE '%sonda%'`` é superconjunto seguro do
    casamento por fronteira de palavra — nunca muda a resposta, só evita
    carregar 34 MB de LONGTEXT para a memória.

    Sem acento de propósito: o MySQL ignoraria acento pela collation, o SQLite
    do ambiente de desenvolvimento não. A sonda remove a diferença em vez de
    depender de uma das duas.
    """
    baixo = (termo or '').lower()
    corridas, atual = [], ''
    for ch in baixo:
        if normalizar(ch) == ch:
            atual += ch
        else:
            corridas.append(atual)
            atual = ''
    corridas.append(atual)
    melhor = max(corridas, key=len, default='')
    return melhor if len(melhor.strip()) >= MIN_SONDA else None


def compilar(termo: str | None, modo: str = MODO_FRASE) -> list:
    r"""Padrões que **todos** precisam casar. Lista vazia = não filtra texto.

    Fronteira por ``(?<!\w)``/``(?!\w)`` e não por ``\b``: um termo que começa
    ou termina em pontuação — "art. 22" — faria o ``\b`` exigir uma transição
    que não existe, e a regra nunca casaria.
    """
    alvo = normalizar(termo).strip()
    if not alvo:
        return []
    pedacos = ([p for p in re.split(r'\s+', alvo) if p]
               if modo == MODO_PALAVRAS else [alvo])
    padroes = []
    for pedaco in pedacos:
        # Pedaço sem letra nem dígito (só pontuação) não delimita nada.
        if not re.search(r'\w', pedaco):
            continue
        padroes.append(re.compile(r'(?<!\w)' + re.escape(pedaco) + r'(?!\w)'))
    return padroes


def casa_texto(texto_normalizado: str, padroes: list) -> bool:
    """Todos os padrões presentes. Sem padrão, casa (o recorte é órgão/seção)."""
    if not padroes:
        return True
    return all(p.search(texto_normalizado) for p in padroes)
