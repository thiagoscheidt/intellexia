# Alertas por palavra-chave no DOU — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** permitir que o escritório configure regras de palavra-chave/órgão/seção que geram alertas do DOU na mesma tela dos alertas de CNPJ.

**Architecture:** motor de casamento próprio, em memória, com fronteira de palavra (`FAP` não casa `FAPESP`), sem modo OU. Uma peneira `LIKE` no banco — usando a maior corrida sem acento do termo — reduz o "testar antes de salvar" de 12 s para 1,9 s sem alterar a resposta. O mesmo `casar()` serve o teste e a colheita diária, então o que foi testado é o que chega.

**Tech Stack:** Flask 3.1, SQLAlchemy, Jinja2/Bootstrap 5, MySQL 8 (prod) / SQLite (dev), `re` + `unicodedata` da stdlib. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-08-14-alertas-palavra-chave-dou-design.md`

## Global Constraints

- **Sem framework de testes.** Testes são scripts executáveis: `uv run python tests/test_dou_regras.py`. Padrão obrigatório: helper `check(nome, condicao, detalhe='')`, lista `_falhas`, `main()` que devolve `0`/`1`. Copiar a moldura de `tests/test_dou_alertas.py`.
- **Sem Alembic.** Migration é script standalone e idempotente em `database/`, dentro de `with app.app_context():`, verificando existência antes de alterar. Modelo: `database/add_dou_alert_resultado_columns.py`.
- **Dependências via `uv`**, nunca `pip`.
- **Multi-tenancy:** `dou_alert_rules` e `dou_alert_rule_hits` **têm** `law_firm_id`. Toda query filtra por ele. (O acervo — `dou_editions`/`dou_articles` — continua sem tenant, é catálogo público.)
- **Datetimes gravados em UTC**; exibição via filtros Jinja `datetime_sp`/`date_sp`.
- **`created_at` de alerta usa `dou_alert_service._utcnow()`**, nunca o default local do modelo.
- **Nunca `git add -A`.** Cada commit encena apenas os caminhos que a tarefa tocou.
- Nomes de função, variável, docstring e commit em **português**, no estilo do módulo.
- Modos válidos, literais: `'frase'` e `'palavras'`. **Não existe modo OU.**

---

### Task 1: Motor de casamento — funções puras

**Files:**
- Create: `app/services/dou_rule_service.py`
- Create: `tests/test_dou_regras.py`

**Interfaces:**
- Consumes: `app.services.dou_search_service.orgao_raiz` (já existe).
- Produces:
  - `MODO_FRASE = 'frase'`, `MODO_PALAVRAS = 'palavras'`, `MODOS = (MODO_FRASE, MODO_PALAVRAS)`
  - `MIN_SONDA = 3`, `DIAS_TESTE = 7`, `CORTE_OK = 5`, `CORTE_ALTO = 20`
  - `normalizar(valor: str | None) -> str`
  - `sonda(termo: str | None) -> str | None`
  - `compilar(termo: str | None, modo: str) -> list[re.Pattern]`
  - `casa_texto(texto_normalizado: str, padroes: list) -> bool`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_dou_regras.py`:

```python
#!/usr/bin/env python3
"""
Testes das regras de palavra-chave do Diário Oficial.

Cada verificação tranca uma descoberta da medição, não uma linha de código.

    uv run python tests/test_dou_regras.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import dou_rule_service as regras

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _casa(texto, termo, modo=regras.MODO_FRASE):
    return regras.casa_texto(regras.normalizar(texto),
                             regras.compilar(termo, modo))


def test_fronteira_de_palavra():
    """O caso que decidiu o motor: o índice acha 92 "FAP", 80 são FAPESP."""
    print('\n1. Fronteira de palavra')

    check('FAP casa "o FAP da empresa"', _casa('o FAP da empresa caiu', 'FAP'))
    check('FAP casa com pontuação', _casa('trata do FAP.', 'FAP'))
    check('FAP NÃO casa FAPESP', not _casa('convênio com a FAPESP', 'FAP'))
    check('FAP NÃO casa FAPED', not _casa('edital FAPED 2026', 'FAP'))
    check('FAP NÃO casa FAPEMIG', not _casa('a FAPEMIG informa', 'FAP'))
    check('FAP NÃO casa UNIFAP', not _casa('a UNIFAP publica', 'FAP'))


def test_acento_e_caixa():
    print('\n2. Acento e caixa são indiferentes')

    check('ACIDENTÁRIO casa acidentario',
          _casa('FATOR ACIDENTÁRIO DE PREVENÇÃO', 'fator acidentario de prevencao'))
    check('acidentario casa ACIDENTÁRIO',
          _casa('fator acidentario de prevencao', 'Fator Acidentário de Prevenção'))


def test_modos():
    """Não existe modo OU — é ele o 748 contra 7."""
    print('\n3. Modos de casamento')

    texto = 'o fator de risco e a prevenção de acidentes'
    check('frase exata NÃO casa palavras espalhadas',
          not _casa(texto, 'Fator Acidentário de Prevenção'))
    check('todas as palavras NÃO casa se faltar uma',
          not _casa(texto, 'fator acidentário prevenção', regras.MODO_PALAVRAS))
    check('todas as palavras casa espalhado',
          _casa('o fator e a prevenção', 'fator prevenção', regras.MODO_PALAVRAS))
    check('frase exata casa a sequência',
          _casa('trata do Fator Acidentário de Prevenção hoje',
                'Fator Acidentário de Prevenção'))
    check('termo vazio não casa nada', regras.compilar('', regras.MODO_FRASE) == [])


def test_sonda():
    """A sonda é o pedaço sem acento que vira LIKE — tem de estar no texto."""
    print('\n4. Sonda da peneira SQL')

    check('licitação → licita', regras.sonda('licitação') == 'licita')
    check('Fator Acidentário de Prevenção → fator acident',
          regras.sonda('Fator Acidentário de Prevenção') == 'fator acident')
    check('FAP → fap', regras.sonda('FAP') == 'fap')
    check('curto demais não vira sonda', regras.sonda('ré') is None)
    check('termo vazio não vira sonda', regras.sonda('') is None)
    check('a sonda está literalmente no termo',
          all(regras.sonda(t) in t.lower()
              for t in ('licitação', 'FAP'.lower(), 'aposentadoria')))


def main():
    print('=' * 60)
    print('TESTES DAS REGRAS DE PALAVRA-CHAVE DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_fronteira_de_palavra()
    test_acento_e_caixa()
    test_modos()
    test_sonda()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_regras.py`
Expected: `ModuleNotFoundError: No module named 'app.services.dou_rule_service'`

- [ ] **Step 3: Escrever o motor**

Criar `app/services/dou_rule_service.py`:

```python
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
    """Padrões que **todos** precisam casar. Lista vazia = a regra não filtra texto.

    Fronteira por ``(?<!\\w)``/``(?!\\w)`` e não por ``\\b``: um termo que
    começa ou termina em pontuação — "art. 22" — faria o ``\\b`` exigir uma
    transição que não existe, e a regra nunca casaria.
    """
    alvo = normalizar(termo).strip()
    if not alvo:
        return []
    pedacos = ([p for p in re.split(r'\s+', alvo) if p]
               if modo == MODO_PALAVRAS else [alvo])
    return [re.compile(r'(?<!\w)' + re.escape(p) + r'(?!\w)') for p in pedacos]


def casa_texto(texto_normalizado: str, padroes: list) -> bool:
    """Todos os padrões presentes. Sem padrão, casa (o recorte é órgão/seção)."""
    if not padroes:
        return True
    return all(p.search(texto_normalizado) for p in padroes)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run python tests/test_dou_regras.py`
Expected: PASS — 4 blocos, todos ✅

- [ ] **Step 5: Commit**

```bash
git add app/services/dou_rule_service.py tests/test_dou_regras.py
git commit -m "feat(dou): motor de casamento das regras de palavra-chave

FAP não casa FAPESP — o índice devolvia 92 matérias e 80 eram FAPED,
FAPEG e FAPESP, fundações de amparo à pesquisa. E não existe modo OU:
sem ele, 'Fator Acidentário de Prevenção' casaria 748 em vez de 7.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Modelo e migrations

**Files:**
- Modify: `app/models.py` (após `DouClientAlertMatch`, e duas colunas em `DouClientAlert`)
- Create: `database/add_dou_alert_rules_tables.py`
- Create: `database/alter_dou_alerts_for_rules.py`

**Interfaces:**
- Consumes: `dou_rule_service.MODO_FRASE`, `MODOS` (Task 1).
- Produces:
  - `DouAlertRule` — `.id .law_firm_id .nome .termo .modo .secoes .orgao_raiz .ativo .created_by_id .last_match_at .created_at .updated_at`; relação `.hits`; propriedades `.lista_secoes -> list[str]`, `.resumo_do_casamento -> str`
  - `DouAlertRuleHit` — `.id .alert_id .rule_id .law_firm_id`; relações `.alert`, `.rule`
  - `DouClientAlert.tem_regra` (Boolean), `DouClientAlert.match_type` agora nullable, relação `DouClientAlert.rule_hits`, propriedade `DouClientAlert.regras_citadas -> list[DouAlertRule]`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_dou_regras.py`, antes de `main()`:

```python
def test_modelo():
    """As colunas que a tela e o filtro dependem, sem abrir a tabela filha."""
    print('\n5. Modelo')

    from app.models import DouAlertRule, DouAlertRuleHit, DouClientAlert

    colunas = {c.name for c in DouAlertRule.__table__.columns}
    check('regra tem law_firm_id (a regra é do escritório)',
          'law_firm_id' in colunas)
    check('regra tem dono registrado', 'created_by_id' in colunas)
    check('regra tem last_match_at', 'last_match_at' in colunas)

    unicas = [tuple(sorted(c.columns.keys()))
              for c in DouAlertRuleHit.__table__.constraints
              if c.__class__.__name__ == 'UniqueConstraint']
    check('hit é único por (alerta, regra)',
          ('alert_id', 'rule_id') in unicas, str(unicas))

    check('alerta tem tem_regra',
          'tem_regra' in {c.name for c in DouClientAlert.__table__.columns})
    check('match_type é nullable (alerta só de regra não tem CNPJ)',
          DouClientAlert.__table__.columns['match_type'].nullable)

    r = DouAlertRule(nome='x', termo='FAP', modo='frase', secoes='DO1,DO3')
    check('lista_secoes separa o CSV', r.lista_secoes == ['DO1', 'DO3'])
    check('sem seções, lista vazia',
          DouAlertRule(nome='x', termo='FAP').lista_secoes == [])
```

E registrar em `main()`: `test_modelo()` depois de `test_sonda()`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_regras.py`
Expected: FAIL — `ImportError: cannot import name 'DouAlertRule' from 'app.models'`

- [ ] **Step 3: Acrescentar os modelos**

Em `app/models.py`, logo depois da classe `DouClientAlertMatch`:

```python
class DouAlertRule(db.Model):
    """Tabela dou_alert_rules - o que o escritório quer vigiar no DOU por texto.

    Complementa o alerta por CNPJ, que só dispara para cliente cadastrado e
    citado nominalmente. Fica de fora justamente o que muda o jogo antes de
    virar processo: portaria que altera a metodologia do FAP, pauta de
    julgamento do CRPS, revisão do NTEP. Nada disso escreve CNPJ de ninguém.

    **Tem law_firm_id**, ao contrário do acervo: o DOU é catálogo público, mas
    o que se decide vigiar é do escritório.

    A regra é do escritório e **guarda quem a criou**: sem dono registrado,
    ninguém se sente responsável por desligar a que está fazendo ruído. Editar
    e excluir são do dono ou de admin; criar e ver, de qualquer um do módulo.

    Pelo menos um entre ``termo`` e ``orgao_raiz`` — regra sem nenhum dos dois
    casaria a edição inteira, 3.005 matérias por dia.
    """
    __tablename__ = 'dou_alert_rules'
    __table_args__ = (
        db.Index('ix_dou_alert_rules_firm_ativo', 'law_firm_id', 'ativo'),
    )

    MODO_FRASE = 'frase'
    MODO_PALAVRAS = 'palavras'

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'),
                            nullable=False, index=True)

    # Rótulo humano: é ele que aparece no chip do alerta e na linha do e-mail.
    nome = db.Column(db.String(120), nullable=False)

    # Nulo = regra só de órgão/seção ("tudo que sair do CRPS").
    termo = db.Column(db.String(200))
    modo = db.Column(db.String(10), nullable=False, default=MODO_FRASE)

    # CSV 'DO1,DO3'; nulo = todas as seções.
    secoes = db.Column(db.String(60))
    # Raiz da hierarquia, como no filtro e na faceta da busca; nulo = todos.
    orgao_raiz = db.Column(db.String(255))

    ativo = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Responde "essa regra não pega nada há 40 dias" sem varrer os alertas.
    last_match_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    created_by = db.relationship('User')
    hits = db.relationship('DouAlertRuleHit', back_populates='rule',
                           cascade='all, delete-orphan')

    @property
    def lista_secoes(self):
        """['DO1', 'DO3'] — vazio quer dizer todas, nunca nenhuma."""
        return [s.strip().upper() for s in (self.secoes or '').split(',') if s.strip()]

    @property
    def resumo_do_casamento(self):
        """O que a regra casa, em uma linha, para a lista e o chip."""
        partes = []
        if self.termo:
            rotulo = ('frase exata' if self.modo == self.MODO_FRASE
                      else 'todas as palavras')
            partes.append(f'"{self.termo}" ({rotulo})')
        if self.orgao_raiz:
            partes.append(self.orgao_raiz)
        if self.lista_secoes:
            partes.append(' · '.join(self.lista_secoes))
        return ' — '.join(partes) or 'tudo'

    def __repr__(self):
        return f'<DouAlertRule firm={self.law_firm_id} {self.nome!r}>'


class DouAlertRuleHit(db.Model):
    """Tabela dou_alert_rule_hits - a regra que fez a matéria virar alerta.

    Tabela filha, e não coluna no alerta, porque **a unidade do alerta continua
    sendo a matéria**. Uma portaria pode disparar três regras do escritório; por
    par (regra, matéria) ela viraria três linhas na tela e três no e-mail. É a
    mesma lição que rendeu 41 alertas em vez de 1.333 (32x) no alerta de CNPJ.
    """
    __tablename__ = 'dou_alert_rule_hits'
    __table_args__ = (
        db.UniqueConstraint('alert_id', 'rule_id', name='uq_dou_rule_hits_alert_rule'),
        db.Index('ix_dou_rule_hits_firm_rule', 'law_firm_id', 'rule_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer,
                         db.ForeignKey('dou_client_alerts.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    rule_id = db.Column(db.Integer,
                        db.ForeignKey('dou_alert_rules.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'),
                            nullable=False, index=True)

    alert = db.relationship('DouClientAlert', back_populates='rule_hits')
    rule = db.relationship('DouAlertRule', back_populates='hits')
```

Em `DouClientAlert`, três edições:

1. Depois de `tem_resultado`, acrescentar:

```python
    # A matéria casou alguma regra de palavra-chave do escritório. Denormalizado
    # pelo mesmo motivo que `tem_resultado`: filtro e chip sem abrir a filha.
    tem_regra = db.Column(db.Boolean, nullable=False, default=False, index=True)
```

2. `match_type` passa a aceitar nulo (alerta só de palavra-chave não tem CNPJ
   nenhum). Trocar a linha por:

```python
    # Nulo quando o alerta veio só de regra de palavra-chave — não há CNPJ.
    match_type = db.Column(db.String(10), default=MATCH_EXACT)
```

3. Depois da relação `matches`, acrescentar a relação e a propriedade:

```python
    rule_hits = db.relationship('DouAlertRuleHit', back_populates='alert',
                                cascade='all, delete-orphan', lazy='selectin')

    @property
    def regras_citadas(self):
        """As regras que fizeram esta matéria virar alerta, por nome."""
        return sorted((h.rule for h in self.rule_hits if h.rule),
                      key=lambda r: r.nome or '')
```

Atualizar também o docstring da classe, acrescentando ao fim:

```
    Desde os alertas por palavra-chave a tabela guarda alerta que **não** é de
    cliente (``matches`` vazio, ``match_type`` nulo, ``rule_hits`` preenchido).
    O nome ``dou_client_alerts`` ficou: renomear em produção, com FK apontando
    para ela e a filha ``dou_client_alert_matches`` junto, é risco sem ganho
    visível.
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run python tests/test_dou_regras.py`
Expected: PASS — inclusive o bloco `5. Modelo`

- [ ] **Step 5: Escrever as migrations**

Criar `database/add_dou_alert_rules_tables.py`:

```python
"""
Cria as tabelas das regras de palavra-chave do Diário Oficial:

    dou_alert_rules       o que o escritório quer vigiar
    dou_alert_rule_hits   a regra que fez a matéria virar alerta

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_dou_alert_rules_tables.py

Rode depois: uv run python database/alter_dou_alerts_for_rules.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouAlertRule, DouAlertRuleHit

TABELAS = (DouAlertRule, DouAlertRuleHit)


def add_rule_tables():
    with app.app_context():
        existentes = set(db.inspect(db.engine).get_table_names())
        criadas = []
        for modelo in TABELAS:
            nome = modelo.__tablename__
            if nome in existentes:
                print(f'✓ {nome} já existe — pulando')
                continue
            try:
                modelo.__table__.create(db.engine)
                criadas.append(nome)
                print(f'✓ {nome} criada')
            except Exception as e:
                print(f'✗ Erro ao criar {nome}: {e}')
                raise

        if not criadas:
            print('\nNada a fazer: as tabelas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} tabela(s): {', '.join(criadas)}")
            print('\nAgora rode:')
            print('    uv run python database/alter_dou_alerts_for_rules.py')


if __name__ == '__main__':
    print('Criando as tabelas das regras de palavra-chave do DOU...')
    add_rule_tables()
```

Criar `database/alter_dou_alerts_for_rules.py`:

```python
"""
Prepara dou_client_alerts para os alertas de palavra-chave:

    + tem_regra    BOOLEAN NOT NULL DEFAULT 0
    match_type     passa a aceitar NULL

Um alerta que veio só de regra não tem casamento de CNPJ nenhum, e hoje
match_type é NOT NULL com default 'exato' — deixá-lo assim faria todo alerta de
palavra-chave se declarar casamento exato de cliente, poluindo o filtro e o
contador da tela.

O SQLite não sabe afrouxar NOT NULL com ALTER TABLE. Como no dev o banco é
recriado à vontade, ali o script só avisa; em MySQL ele executa o MODIFY.

Idempotente: o que já está no lugar é reportado e pulado.

    uv run python database/alter_dou_alerts_for_rules.py

Depois de rodar, preencha o que já está no acervo:

    uv run python scripts/gerar_alertas_dou.py --tudo
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

TABELA = 'dou_client_alerts'


def alter_alerts():
    with app.app_context():
        inspector = db.inspect(db.engine)
        if TABELA not in set(inspector.get_table_names()):
            print(f'✗ Tabela {TABELA} não existe.')
            print('  Rode antes: uv run python database/add_dou_client_alert_tables.py')
            return

        colunas = {c['name']: c for c in inspector.get_columns(TABELA)}
        mudou = False

        if 'tem_regra' in colunas:
            print(f'✓ {TABELA}.tem_regra já existe — pulando')
        else:
            with db.engine.begin() as conexao:
                conexao.execute(text(
                    f'ALTER TABLE {TABELA} '
                    'ADD COLUMN tem_regra BOOLEAN NOT NULL DEFAULT 0'))
                conexao.execute(text(
                    'CREATE INDEX ix_dou_client_alerts_tem_regra '
                    f'ON {TABELA} (tem_regra)'))
            mudou = True
            print(f'✓ {TABELA}.tem_regra criada')

        if colunas.get('match_type', {}).get('nullable'):
            print(f'✓ {TABELA}.match_type já aceita NULL — pulando')
        elif db.engine.dialect.name == 'sqlite':
            print(f'⚠ {TABELA}.match_type continua NOT NULL: o SQLite não '
                  'afrouxa a restrição por ALTER TABLE.')
            print('  Em desenvolvimento, recrie o banco se precisar do NULL.')
        else:
            with db.engine.begin() as conexao:
                conexao.execute(text(
                    f'ALTER TABLE {TABELA} MODIFY COLUMN match_type VARCHAR(10) NULL'))
            mudou = True
            print(f'✓ {TABELA}.match_type agora aceita NULL')

        if not mudou:
            print('\nNada a fazer: o esquema já estava pronto.')
        else:
            print('\nPara gerar os alertas do acervo já capturado:')
            print('    uv run python scripts/gerar_alertas_dou.py --tudo')


if __name__ == '__main__':
    print('Ajustando dou_client_alerts para os alertas de palavra-chave...')
    alter_alerts()
```

- [ ] **Step 6: Rodar as migrations no dev**

Run:
```bash
uv run python database/add_dou_alert_rules_tables.py
uv run python database/alter_dou_alerts_for_rules.py
```
Expected: `✓ dou_alert_rules criada`, `✓ dou_alert_rule_hits criada`, `✓ dou_client_alerts.tem_regra criada`

- [ ] **Step 7: Verificar que os alertas atuais continuam de pé**

Run: `uv run python tests/test_dou_alertas.py`
Expected: PASS — nenhuma regressão nos alertas de CNPJ

- [ ] **Step 8: Commit**

```bash
git add app/models.py database/add_dou_alert_rules_tables.py \
        database/alter_dou_alerts_for_rules.py tests/test_dou_regras.py
git commit -m "feat(dou): tabelas das regras de palavra-chave

O hit é tabela filha, não coluna: a unidade do alerta continua sendo a
matéria. Uma portaria pode disparar três regras, e por par ela viraria
três linhas na tela — a mesma lição do 32x do alerta de CNPJ.

match_type vira nullable porque alerta só de palavra-chave não tem CNPJ.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Colheita — casar regras contra as matérias

**Files:**
- Modify: `app/services/dou_rule_service.py` (acrescentar ao fim)
- Modify: `app/services/dou_alert_service.py:196-338` (`gerar_para_edicao`, `gerar_para_datas`, `_gerar_para_materias`)
- Modify: `app/services/dou_ingestion_service.py` (o gancho)
- Modify: `tests/test_dou_regras.py`

**Interfaces:**
- Consumes: `normalizar`, `compilar`, `casa_texto`, `MODO_FRASE` (Task 1); `DouAlertRule`, `DouAlertRuleHit` (Task 2).
- Produces:
  - `dou_rule_service.regras_ativas() -> dict[int, list[DouAlertRule]]`
  - `dou_rule_service.corpus(materia) -> str` (materia = Row com `.identifica .ementa .texto`)
  - `dou_rule_service.casar(regras, materias, cache=None) -> dict[int, list[int]]`
  - `dou_alert_service.gerar_para_edicao(edition, carteiras=None, regras=None) -> int` (assinatura estendida, compatível)
  - `dou_alert_service.gerar_para_datas(datas, carteiras=None, regras=None) -> int`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_dou_regras.py`:

```python
class FakeMateria:
    """Matéria sem banco — o casamento não precisa de ORM."""

    def __init__(self, id, texto='', identifica='', ementa='',
                 pub_name='DO1', orgao_hierarquia=''):
        self.id, self.texto, self.identifica = id, texto, identifica
        self.ementa, self.pub_name = ementa, pub_name
        self.orgao_hierarquia = orgao_hierarquia


class FakeRegra:
    def __init__(self, id, termo=None, modo=regras.MODO_FRASE,
                 secoes=None, orgao=None):
        self.id, self.termo, self.modo = id, termo, modo
        self.lista_secoes = secoes or []
        self.orgao_raiz = orgao


def test_casar():
    print('\n6. Colheita')

    materias = [
        FakeMateria(1, texto='decisão sobre o FAP da empresa', pub_name='DO1',
                    orgao_hierarquia='Ministério da Previdência Social/CRPS'),
        FakeMateria(2, texto='convênio com a FAPESP', pub_name='DO3',
                    orgao_hierarquia='Ministério da Educação'),
        FakeMateria(3, texto='ata da reunião', identifica='PORTARIA CRPS Nº 9',
                    pub_name='DO1',
                    orgao_hierarquia='Ministério da Previdência Social'),
    ]

    achados = regras.casar([FakeRegra(10, termo='FAP')], materias)
    check('casa só a matéria certa', achados == {1: [10]}, str(achados))

    achados = regras.casar([FakeRegra(11, termo='CRPS')], materias)
    check('o corpus inclui identifica', achados == {3: [11]}, str(achados))

    achados = regras.casar([FakeRegra(12, termo='FAP', secoes=['DO3'])], materias)
    check('seção recorta', achados == {}, str(achados))

    achados = regras.casar(
        [FakeRegra(13, orgao='Ministério da Previdência Social')], materias)
    check('regra só de órgão casa pela raiz',
          achados == {1: [13], 3: [13]}, str(achados))

    achados = regras.casar([FakeRegra(14, termo='FAP'),
                            FakeRegra(15, termo='decisão')], materias)
    check('duas regras na mesma matéria dão uma entrada com dois ids',
          achados == {1: [14, 15]}, str(achados))

    check('sem regra, nada casa', regras.casar([], materias) == {})
```

E, no `main()`, chamar `test_casar()`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_regras.py`
Expected: FAIL — `AttributeError: module 'app.services.dou_rule_service' has no attribute 'casar'`

- [ ] **Step 3: Acrescentar a colheita ao motor**

No fim de `app/services/dou_rule_service.py`:

```python
# ------------------------------------------------------------------ colheita

def regras_ativas() -> dict:
    """``{law_firm_id: [DouAlertRule]}`` — só as ligadas, para a colheita."""
    from app.models import DouAlertRule

    por_firma = {}
    for regra in DouAlertRule.query.filter(DouAlertRule.ativo.is_(True)).all():
        por_firma.setdefault(regra.law_firm_id, []).append(regra)
    return por_firma


def corpus(materia) -> str:
    """O texto em que a regra procura: identifica + ementa + texto.

    Não existe a opção "procurar só no título" porque não existe título: medido
    no acervo, ``titulo`` está vazio em **100%** das matérias e ``ementa`` em
    **98%**. O DOU põe o cabeçalho ("PORTARIA Nº 1.234, DE ...") em
    ``identifica`` e todo o resto em ``texto``.
    """
    return ' '.join(filter(None, (getattr(materia, 'identifica', None),
                                  getattr(materia, 'ementa', None),
                                  getattr(materia, 'texto', None))))


def _preparar(regras):
    """[(regra, padroes, secoes, orgao_normalizado)] — compila uma vez só."""
    preparadas = []
    for regra in regras:
        preparadas.append((
            regra,
            compilar(regra.termo, regra.modo),
            set(regra.lista_secoes),
            normalizar(regra.orgao_raiz) if regra.orgao_raiz else None,
        ))
    return preparadas


def casar(regras, materias, cache=None) -> dict:
    """``{article_id: [rule_id]}``. Não toca o banco nem grava nada.

    O corpus normalizado é memorizado por matéria: sem isso, dez regras
    normalizariam os mesmos 34 MB dez vezes. O ``cache`` pode vir de fora para
    dois escritórios com regras diferentes dividirem o mesmo trabalho.

    Recorte barato antes do caro: seção e órgão descartam a matéria antes de
    qualquer normalização de texto.
    """
    if not regras or not materias:
        return {}
    cache = {} if cache is None else cache
    preparadas = _preparar(regras)

    achados = {}
    for materia in materias:
        for regra, padroes, secoes, orgao in preparadas:
            if secoes and (materia.pub_name or '').upper() not in secoes:
                continue
            if orgao and normalizar(orgao_raiz(materia.orgao_hierarquia)) != orgao:
                continue
            if padroes:
                corpo = cache.get(materia.id)
                if corpo is None:
                    corpo = cache[materia.id] = normalizar(corpus(materia))
                if not casa_texto(corpo, padroes):
                    continue
            achados.setdefault(materia.id, []).append(regra.id)
    return achados
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run python tests/test_dou_regras.py`
Expected: PASS — bloco `6. Colheita` verde

- [ ] **Step 5: Gravar os hits junto com os alertas**

Em `app/services/dou_alert_service.py`:

a) No topo, junto aos outros imports de serviço:

```python
from app.services import dou_rule_service as rule_service
```

e acrescentar `DouAlertRuleHit` ao import de `app.models`.

b) Trocar `gerar_para_edicao` e `gerar_para_datas` (linhas 196-220) por:

```python
# As colunas do casamento. `texto` é o único LONGTEXT aqui de propósito:
# `texto_html` e `raw_xml` são três campos gigantes por linha que ninguém usa
# na varredura. `identifica`, `ementa` e `orgao_hierarquia` entraram com as
# regras de palavra-chave — são String, e o corpus da regra depende delas.
_COLUNAS_DA_VARREDURA = (
    DouArticle.id, DouArticle.texto, DouArticle.pub_date, DouArticle.pub_name,
    DouArticle.identifica, DouArticle.ementa, DouArticle.orgao_hierarquia,
)


def gerar_para_edicao(edition, carteiras=None, regras=None) -> int:
    """Gera/atualiza os alertas das matérias de uma edição. Devolve quantos.

    Não comita: quem chama decide. Nunca levanta — o alerta é derivado, e uma
    falha aqui não pode derrubar a captura, mesma regra do índice de busca.
    """
    try:
        materias = (db.session.query(*_COLUNAS_DA_VARREDURA)
                    .filter(DouArticle.edition_id == edition.id).all())
        if not materias:
            return 0
        return _gerar_para_materias(materias, carteiras, regras)
    except Exception:  # noqa: BLE001 — alerta não derruba a captura
        logger.exception('DOU: falha ao gerar alertas da edição %s', edition.id)
        return 0


def gerar_para_datas(datas, carteiras=None, regras=None) -> int:
    """Varredura retroativa: gera alertas das matérias de uma lista de datas."""
    materias = (db.session.query(*_COLUNAS_DA_VARREDURA)
                .filter(DouArticle.pub_date.in_(list(datas))).all())
    return _gerar_para_materias(materias, carteiras, regras)
```

c) Trocar `_gerar_para_materias` inteiro (linha 253 até o fim da função) por:

```python
def _gerar_para_materias(materias, carteiras=None, regras=None) -> int:
    """O laço de casamento. ``materias`` são Rows enxutas, não o modelo inteiro.

    Duas origens desembocam no mesmo alerta: o CNPJ da carteira e as regras de
    palavra-chave. **A matéria que casa as duas continua sendo um alerta só** —
    em registros separados ela apareceria duas vezes na tela e duas no e-mail.

    O laço percorre a união dos escritórios: um escritório pode ter regra sem
    ter carteira válida, e vice-versa.
    """
    if carteiras is None:
        carteiras = carteiras_ativas()
    if regras is None:
        regras = rule_service.regras_ativas()

    firmas = sorted(set(carteiras) | set(regras))
    if not firmas or not materias:
        return 0

    ids = [m.id for m in materias]
    cache_corpus = {}       # normalização compartilhada entre escritórios
    ids_que_casaram = set()  # regras que pegaram algo, para o last_match_at
    gerados = 0

    for law_firm_id in firmas:
        carteira = carteiras.get(law_firm_id)
        hits_por_materia = rule_service.casar(
            regras.get(law_firm_id) or [], materias, cache_corpus)

        # Os alertas já existentes desta leva, para o upsert não duplicar
        existentes = {}
        for pedaco in range(0, len(ids), 500):
            for alerta in (DouClientAlert.query
                           .filter(DouClientAlert.law_firm_id == law_firm_id,
                                   DouClientAlert.article_id.in_(ids[pedaco:pedaco + 500]))
                           .all()):
                existentes[alerta.article_id] = alerta

        for materia in materias:
            casados = carteira.casar(materia.texto) if carteira else []
            rule_ids = hits_por_materia.get(materia.id) or []
            ids_que_casaram.update(rule_ids)
            alerta = existentes.get(materia.id)

            if not casados and not rule_ids:
                # A matéria pode ter sido republicada sem o CNPJ, ou a regra
                # que a trouxe pode ter sido desligada; o alerta deixa de valer.
                if alerta is not None:
                    db.session.delete(alerta)
                continue

            # Um cliente citado por dois estabelecimentos aparece uma vez por
            # CNPJ — é o CNPJ que identifica o estabelecimento no DOU.
            por_cnpj = {cnpj: (cliente, tipo) for cnpj, cliente, tipo in casados}

            if alerta is None:
                # created_at em UTC, não no default local do modelo: é ele que
                # a janela do e-mail compara com last_sent_at.
                alerta = DouClientAlert(law_firm_id=law_firm_id,
                                        article_id=materia.id,
                                        status=DouClientAlert.STATUS_NEW,
                                        created_at=_utcnow())
                db.session.add(alerta)
                gerados += 1

            decisoes = (_decisoes_por_cnpj(materia.id, set(por_cnpj))
                        if por_cnpj else {})

            # Reprocessamento mantém a triagem: quem já leu o alerta não deve
            # vê-lo voltar por causa de uma republicação que não mudou nada.
            alerta.pub_date = materia.pub_date
            alerta.pub_name = materia.pub_name
            alerta.tem_resultado = bool(decisoes)
            alerta.tem_regra = bool(rule_ids)

            # Os campos de cliente só são reescritos quando este escritório
            # tem carteira nesta varredura. Sem a guarda, o backfill de uma
            # regra nova (que passa `carteiras={}` de propósito, para não
            # refazer os CNPJs) zeraria o clients_count de todo alerta de
            # cliente que a regra também casasse.
            if carteira is not None:
                alerta.clients_count = len(por_cnpj)
                if por_cnpj:
                    tem_exato = any(t == DouClientAlert.MATCH_EXACT
                                    for _, t in por_cnpj.values())
                    alerta.match_type = (DouClientAlert.MATCH_EXACT if tem_exato
                                         else DouClientAlert.MATCH_ROOT)
                else:
                    # Alerta só de palavra-chave não tem CNPJ nenhum; declarar
                    # 'exato' aqui poluiria o filtro e o contador da tela.
                    alerta.match_type = None

                # Casa CNPJ a CNPJ em vez de limpar e reinserir. Um `clear()`
                # seguido de append emitia os INSERT antes dos DELETE no mesmo
                # flush e estourava a chave única (alert_id, cnpj) — e ainda
                # reescreveria as 103 linhas de um edital de lista a cada
                # reprocessamento, para nada.
                atuais = {m.cnpj: m for m in alerta.matches}
                for cnpj in list(atuais):
                    if cnpj not in por_cnpj:
                        alerta.matches.remove(atuais.pop(cnpj))
                for cnpj, (cliente, tipo) in sorted(por_cnpj.items()):
                    existente = atuais.get(cnpj)
                    if existente is None:
                        alerta.matches.append(DouClientAlertMatch(
                            law_firm_id=law_firm_id, client_id=cliente.id,
                            cnpj=cnpj, match_type=tipo,
                            resultado=decisoes.get(cnpj)))
                    else:
                        existente.client_id = cliente.id
                        existente.match_type = tipo
                        existente.resultado = decisoes.get(cnpj)

            # Mesmo cuidado nos hits, e pela mesma razão: a unique é
            # (alert_id, rule_id).
            atuais_hits = {h.rule_id: h for h in alerta.rule_hits}
            for rule_id in list(atuais_hits):
                if rule_id not in rule_ids:
                    alerta.rule_hits.remove(atuais_hits.pop(rule_id))
            for rule_id in rule_ids:
                if rule_id not in atuais_hits:
                    alerta.rule_hits.append(DouAlertRuleHit(
                        law_firm_id=law_firm_id, rule_id=rule_id))

    _marcar_ultimo_casamento(regras, materias, ids_que_casaram)
    return gerados


def _marcar_ultimo_casamento(regras, materias, casados_ids) -> None:
    """``last_match_at`` das regras que casaram — responde "essa pega algo?".

    Guarda a data da **matéria**, não o instante da execução: um backfill de
    julho rodado hoje não pode fazer a regra parecer viva. E só as que casaram
    de fato — marcar toda regra ativa esvaziaria o sentido da coluna.
    """
    if not materias or not casados_ids:
        return
    ultima = max((m.pub_date for m in materias if m.pub_date), default=None)
    if not ultima:
        return
    quando = datetime.combine(ultima, time.min)
    for lista in (regras or {}).values():
        for regra in lista:
            if regra.id not in casados_ids:
                continue
            if regra.last_match_at is None or regra.last_match_at < quando:
                regra.last_match_at = quando
```

No topo do arquivo, o import de datas passa a ser
`from datetime import datetime, time, timezone` (hoje traz `datetime` e
`timezone`).

- [ ] **Step 6: Ligar o gancho da ingestão**

Em `app/services/dou_ingestion_service.py`, onde hoje as carteiras são
carregadas uma vez por data, carregar as regras junto:

```python
from app.services import dou_rule_service as rule_service
...
regras = rule_service.regras_ativas()
```

e na chamada depois do commit da edição:

```python
novos = dou_alert_service.gerar_para_edicao(edition, carteiras, regras)
```

O bloco `try/except` com `rollback` em volta permanece exatamente como está:
alerta é derivado da captura, nunca dono dela.

- [ ] **Step 7: Rodar os dois testes**

Run:
```bash
uv run python tests/test_dou_regras.py
uv run python tests/test_dou_alertas.py
```
Expected: PASS nos dois — o segundo prova que os alertas de CNPJ não regrediram

- [ ] **Step 8: Commit**

```bash
git add app/services/dou_rule_service.py app/services/dou_alert_service.py \
        app/services/dou_ingestion_service.py tests/test_dou_regras.py
git commit -m "feat(dou): colheita das regras junto com a dos CNPJs

A matéria que casa CNPJ e palavra-chave continua sendo um alerta só, com
dois motivos — em registros separados ela apareceria duas vezes na tela e
duas no e-mail.

O corpus é identifica + ementa + texto: medido, titulo está vazio em 100%
do acervo e ementa em 98%, então não existe 'procurar só no título'.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Testar a regra antes de salvar

**Files:**
- Modify: `app/services/dou_rule_service.py` (acrescentar ao fim)
- Modify: `tests/test_dou_regras.py`

**Interfaces:**
- Consumes: tudo de Tasks 1 e 3.
- Produces:
  - `dou_rule_service.filtrar_candidatas(termo, secoes, orgao, desde=None) -> Query`
  - `dou_rule_service.testar(termo, modo, secoes, orgao, dias=DIAS_TESTE, exemplos=8) -> dict` com chaves `total`, `por_dia`, `dias`, `nivel`, `vezes_carteira`, `exemplos[]`
  - `dou_rule_service.nivel(por_dia: float) -> str`
  - `dou_rule_service.validar(nome, termo, modo, secoes, orgao) -> list[str]` (mensagens de erro; lista vazia = válido)

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_dou_regras.py`:

```python
def test_peneira_e_superconjunto():
    """A propriedade que autoriza a otimização — sem ela o teste mente.

    O LIKE roda no banco e a regex decide; se a peneira deixar de fora algo que
    a regex casaria, o "testar antes de salvar" mostra menos do que vai chegar.
    O caso perigoso é o termo que só aparece em `identifica`: peneirar apenas
    `texto` perderia a matéria inteira.
    """
    print('\n7. A peneira SQL é superconjunto')

    from main import app
    from app.models import DouArticle, db

    with app.app_context():
        for termo in ('FAP', 'Fator Acidentário de Prevenção', 'aposentadoria'):
            probe = regras.sonda(termo)
            if not probe:
                continue
            peneirados = {r.id for r in
                          regras.filtrar_candidatas(termo, [], None).all()}
            padroes = regras.compilar(termo, regras.MODO_FRASE)
            todos = db.session.query(DouArticle.id, DouArticle.identifica,
                                     DouArticle.ementa, DouArticle.texto).all()
            exatos = {m.id for m in todos
                      if regras.casa_texto(regras.normalizar(regras.corpus(m)),
                                           padroes)}
            check(f'peneira de {termo!r} contém todos os casamentos',
                  exatos <= peneirados,
                  f'{len(exatos - peneirados)} matéria(s) escapariam')


def test_veredito():
    """Os cortes são ancorados na carteira real (~6 alertas/dia), não chutados."""
    print('\n8. Veredito de volume')

    check('zero é vazio', regras.nivel(0) == regras.NIVEL_VAZIO)
    check('1/dia é ok', regras.nivel(1) == regras.NIVEL_OK)
    check('5/dia ainda é ok', regras.nivel(5) == regras.NIVEL_OK)
    check('6/dia é alto', regras.nivel(6) == regras.NIVEL_ALTO)
    check('20/dia ainda é alto', regras.nivel(20) == regras.NIVEL_ALTO)
    check('660/dia é ruidoso (o caso "licitação")',
          regras.nivel(660) == regras.NIVEL_RUIDOSO)


def test_validacao():
    print('\n9. Validação da regra')

    check('sem nome é recusada',
          regras.validar('', 'FAP', regras.MODO_FRASE, [], None))
    check('sem termo e sem órgão é recusada',
          regras.validar('x', '', regras.MODO_FRASE, ['DO1'], None))
    check('só órgão é aceita',
          not regras.validar('x', '', regras.MODO_FRASE, [],
                             'Ministério da Previdência Social'))
    check('só termo é aceita',
          not regras.validar('x', 'FAP', regras.MODO_FRASE, [], None))
    check('modo inválido é recusado',
          regras.validar('x', 'FAP', 'ou', [], None))
    check('termo só de pontuação é recusado',
          regras.validar('x', '...', regras.MODO_FRASE, [], None))
```

E, no `main()`, chamar as três.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_regras.py`
Expected: FAIL — `has no attribute 'filtrar_candidatas'`

- [ ] **Step 3: Implementar o teste da regra**

No fim de `app/services/dou_rule_service.py`:

```python
# --------------------------------------------------------- testar uma regra

def filtrar_candidatas(termo, secoes, orgao, desde=None):
    """A query das matérias que **podem** casar — a peneira, não a resposta.

    Varrer 7 dias em Python custa 9,1 s de carga mais 3,0 s de normalização.
    Inaceitável num botão que a pessoa aperta várias vezes ajustando a regra.
    A peneira derruba isso para 0,5–1,9 s.

    O ``LIKE`` cobre os **três** campos do corpus. Peneirar só ``texto``
    perderia a matéria cujo termo está no cabeçalho ("PORTARIA CRPS Nº 9"), e
    aí o teste mostraria menos do que vai chegar — que é exatamente o defeito
    que este recurso existe para evitar.

    O recorte de órgão vai como prefixo da hierarquia, que é superconjunto da
    raiz: quem decide continua sendo ``orgao_raiz`` em Python, um caminho só.
    """
    from app.models import DouArticle, db

    query = db.session.query(
        DouArticle.id, DouArticle.identifica, DouArticle.ementa,
        DouArticle.texto, DouArticle.pub_date, DouArticle.pub_name,
        DouArticle.pagina_num, DouArticle.orgao_hierarquia)
    if desde is not None:
        query = query.filter(DouArticle.pub_date >= desde)
    if secoes:
        query = query.filter(DouArticle.pub_name.in_(list(secoes)))
    if orgao:
        query = query.filter(DouArticle.orgao_hierarquia.ilike(f'{orgao}%'))
    probe = sonda(termo)
    if probe:
        alvo = f'%{probe}%'
        query = query.filter(db.or_(DouArticle.texto.ilike(alvo),
                                    DouArticle.identifica.ilike(alvo),
                                    DouArticle.ementa.ilike(alvo)))
    return query


def nivel(por_dia: float) -> str:
    """O veredito do volume. Ver CORTE_OK/CORTE_ALTO para a âncora."""
    if por_dia <= 0:
        return NIVEL_VAZIO
    if por_dia <= CORTE_OK:
        return NIVEL_OK
    if por_dia <= CORTE_ALTO:
        return NIVEL_ALTO
    return NIVEL_RUIDOSO


def validar(nome, termo, modo, secoes, orgao) -> list:
    """Mensagens de erro; lista vazia quer dizer regra válida."""
    erros = []
    if not (nome or '').strip():
        erros.append('Dê um nome à regra — é ele que aparece no alerta.')
    if modo not in MODOS:
        erros.append('Modo de casamento inválido.')
    tem_termo = bool(compilar(termo, modo if modo in MODOS else MODO_FRASE))
    if not tem_termo and not (orgao or '').strip():
        erros.append('Informe uma palavra-chave ou um órgão — sem nenhum dos '
                     'dois a regra casaria a edição inteira, 3.005 matérias '
                     'por dia.')
    if (termo or '').strip() and not tem_termo:
        erros.append('A palavra-chave não tem nenhuma letra ou número.')
    return erros


def testar(termo, modo=MODO_FRASE, secoes=None, orgao=None,
           dias: int = DIAS_TESTE, exemplos: int = 8) -> dict:
    """Quanto esta regra teria gerado nos últimos ``dias``, e alguns exemplos.

    Usa o **mesmo** ``casar`` da colheita diária, de propósito: se o teste e a
    colheita tivessem implementações separadas, elas divergiriam e o número
    mostrado antes de salvar viraria mentira — destruindo justamente a peça que
    resolve o problema de volume.
    """
    janela = max(1, int(dias or DIAS_TESTE))
    desde = date.today() - timedelta(days=janela - 1)
    secoes = [s.strip().upper() for s in (secoes or []) if s and s.strip()]
    orgao = (orgao or '').strip() or None

    candidatas = filtrar_candidatas(termo, secoes, orgao, desde).all()

    # Regra ainda não salva: um objeto solto com a mesma superfície que
    # `casar` consome. Assim o teste passa pelo caminho da colheita, não por
    # um paralelo.
    provisoria = SimpleNamespace(id=0, termo=termo, modo=modo,
                                 lista_secoes=secoes, orgao_raiz=orgao)

    achados = casar([provisoria], candidatas)
    casadas = [m for m in candidatas if m.id in achados]
    casadas.sort(key=lambda m: (m.pub_date or desde, m.id), reverse=True)

    total = len(casadas)
    por_dia = round(total / janela, 1)
    return {
        'total': total,
        'dias': janela,
        'por_dia': por_dia,
        'nivel': nivel(por_dia),
        # Quantas vezes o volume da carteira inteira de clientes (~6/dia). É a
        # frase que dói: "essa regra sozinha traria 100x o que já existe".
        'vezes_carteira': int(por_dia / 6) if por_dia > 12 else 0,
        'exemplos': [{
            'id': m.id,
            'pub_date': m.pub_date,
            'pub_name': m.pub_name,
            'pagina': m.pagina_num,
            'identifica': m.identifica or '(sem identificação)',
            'orgao': orgao_raiz(m.orgao_hierarquia) or '',
        } for m in casadas[:exemplos]],
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run python tests/test_dou_regras.py`
Expected: PASS — blocos 7, 8 e 9 verdes

- [ ] **Step 5: Conferir o custo no acervo real**

Run:
```bash
uv run python -c "
import time, sys; sys.path.insert(0,'.')
from main import app
from app.services import dou_rule_service as r
with app.app_context():
    for t in ('FAP','Fator Acidentário de Prevenção','licitação'):
        i=time.perf_counter(); d=r.testar(t, dias=7)
        print(f'{t:<32} {d[\"total\"]:>5} em {time.perf_counter()-i:.2f}s  {d[\"nivel\"]}')
"
```
Expected: cada linha abaixo de ~2,5 s; `licitação` deve sair como `ruidoso`

- [ ] **Step 6: Commit**

```bash
git add app/services/dou_rule_service.py tests/test_dou_regras.py
git commit -m "feat(dou): testar a regra antes de salvar

A peneira LIKE usa a maior corrida sem acento do termo e cobre os três
campos do corpus — peneirar só o texto perderia a matéria cujo termo está
no cabeçalho, e aí o teste mostraria menos do que chegaria.

O teste chama o mesmo casar() da colheita: implementações separadas
divergiriam e o número mostrado viraria mentira.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Tela de regras

**Files:**
- Modify: `app/blueprints/dou.py` (rotas novas depois de `alertas_marcar_todas`)
- Create: `templates/dou/regras.html`
- Create: `templates/dou/regra_form.html`
- Modify: `static/css/dou.css`
- Modify: `tests/test_dou_routes.py`

**Interfaces:**
- Consumes: `dou_rule_service.testar/validar/MODOS/MODO_LABELS/NIVEL_*` (Tasks 1, 4); `DouAlertRule` (Task 2).
- Produces: endpoints `dou.regras`, `dou.regra_nova`, `dou.regra_editar`, `dou.regra_excluir`, `dou.regra_alternar`, `dou.regra_testar`, `dou.regra_backfill`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_dou_routes.py` (no bloco de rotas do DOU, seguindo o
padrão do arquivo — cliente autenticado por sessão forjada):

```python
def test_tela_de_regras():
    print('\nRegras de palavra-chave')

    with app.test_client() as c:
        _entrar(c)                      # helper já existente no arquivo
        r = c.get('/dou/regras')
        check('lista responde 200', r.status_code == 200, str(r.status_code))
        check('tem o botão de nova regra', b'Nova regra' in r.data)

        r = c.get('/dou/regras/nova')
        check('formulário responde 200', r.status_code == 200)
        check('oferece os dois modos',
              b'frase exata' in r.data and b'todas as palavras' in r.data)

        r = c.post('/dou/regras/testar',
                   json={'termo': 'FAP', 'modo': 'frase', 'secoes': [],
                         'orgao': ''})
        check('teste responde JSON', r.is_json, r.content_type)
        dados = r.get_json()
        check('teste traz total e nível',
              'total' in dados and 'nivel' in dados, str(dados)[:120])

        r = c.post('/dou/regras/nova',
                   data={'nome': '', 'termo': '', 'modo': 'frase'},
                   follow_redirects=True)
        check('regra sem nome e sem termo é recusada',
              b'palavra-chave ou um' in r.data or b'nome' in r.data.lower())
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_routes.py`
Expected: FAIL — `/dou/regras` devolve 404

- [ ] **Step 3: Escrever as rotas**

Em `app/blueprints/dou.py`, acrescentar `DouAlertRule` ao import de
`app.models`, `from app.services import dou_rule_service as rule_service`, e
depois de `alertas_marcar_todas`:

```python
# --------------------------------------------------------------- regras

def _regra_do_escritorio(rule_id):
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        abort(403)
    return (DouAlertRule.query
            .filter_by(id=rule_id, law_firm_id=law_firm_id).first_or_404())


def _pode_editar(regra):
    """Editar e excluir são do dono ou de admin — é o que dá sentido ao dono."""
    return (session.get('user_role') == 'admin'
            or regra.created_by_id == session.get('user_id'))


def _campos_do_form():
    """Os campos da regra como vieram do formulário, já normalizados."""
    return {
        'nome': (request.form.get('nome') or '').strip(),
        'termo': (request.form.get('termo') or '').strip(),
        'modo': (request.form.get('modo') or rule_service.MODO_FRASE).strip(),
        'secoes': [s.strip().upper()
                   for s in request.form.getlist('secoes') if s.strip()],
        'orgao': (request.form.get('orgao') or '').strip(),
    }


@dou_bp.route('/regras')
def regras():
    """O que o escritório vigia no DOU por texto, órgão ou seção."""
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        abort(403)

    linhas = (DouAlertRule.query
              .filter_by(law_firm_id=law_firm_id)
              .order_by(DouAlertRule.ativo.desc(), DouAlertRule.nome).all())

    # Quantos alertas cada regra rendeu — um GROUP BY, não N consultas.
    contagem = dict(db.session.query(DouAlertRuleHit.rule_id, func.count())
                    .filter(DouAlertRuleHit.law_firm_id == law_firm_id)
                    .group_by(DouAlertRuleHit.rule_id).all())

    return render_template('dou/regras.html', regras=linhas,
                           contagem=contagem,
                           pode_editar=_pode_editar,
                           MODO_LABELS=rule_service.MODO_LABELS)


@dou_bp.route('/regras/nova', methods=['GET', 'POST'])
def regra_nova():
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        abort(403)

    if request.method == 'POST':
        campos = _campos_do_form()
        erros = rule_service.validar(**campos)
        if erros:
            for erro in erros:
                flash(erro, 'danger')
            return render_template('dou/regra_form.html', regra=None,
                                   campos=campos, orgaos=_orgaos_para_regra(),
                                   MODOS=rule_service.MODOS,
                                   MODO_LABELS=rule_service.MODO_LABELS)
        regra = DouAlertRule(
            law_firm_id=law_firm_id, nome=campos['nome'],
            termo=campos['termo'] or None, modo=campos['modo'],
            secoes=','.join(campos['secoes']) or None,
            orgao_raiz=campos['orgao'] or None, ativo=True,
            created_by_id=session.get('user_id'))
        db.session.add(regra)
        db.session.commit()

        # Gera já os alertas da mesma janela que o teste mostrou: o que foi
        # visto é o que aparece. Vale mesmo se a pessoa salvou sem testar — a
        # janela é do desenho, não do clique.
        quantos = _backfill_da_regra(regra, rule_service.DIAS_TESTE)
        flash(f'Regra criada. {quantos} alerta(s) dos últimos '
              f'{rule_service.DIAS_TESTE} dias.', 'success')
        return redirect(url_for('dou.regras'))

    return render_template('dou/regra_form.html', regra=None,
                           campos=None, orgaos=_orgaos_para_regra(),
                           MODOS=rule_service.MODOS,
                           MODO_LABELS=rule_service.MODO_LABELS)


@dou_bp.route('/regras/<int:rule_id>/editar', methods=['GET', 'POST'])
def regra_editar(rule_id):
    regra = _regra_do_escritorio(rule_id)
    if not _pode_editar(regra):
        abort(403)

    if request.method == 'POST':
        campos = _campos_do_form()
        erros = rule_service.validar(**campos)
        if erros:
            for erro in erros:
                flash(erro, 'danger')
        else:
            regra.nome = campos['nome']
            regra.termo = campos['termo'] or None
            regra.modo = campos['modo']
            regra.secoes = ','.join(campos['secoes']) or None
            regra.orgao_raiz = campos['orgao'] or None
            db.session.commit()
            quantos = _backfill_da_regra(regra, rule_service.DIAS_TESTE)
            flash(f'Regra salva. {quantos} alerta(s) na janela.', 'success')
            return redirect(url_for('dou.regras'))

    return render_template('dou/regra_form.html', regra=regra, campos=None,
                           orgaos=_orgaos_para_regra(),
                           MODOS=rule_service.MODOS,
                           MODO_LABELS=rule_service.MODO_LABELS)


@dou_bp.route('/regras/<int:rule_id>/alternar', methods=['POST'])
def regra_alternar(rule_id):
    regra = _regra_do_escritorio(rule_id)
    if not _pode_editar(regra):
        abort(403)
    regra.ativo = not regra.ativo
    db.session.commit()
    flash(f'Regra {"ligada" if regra.ativo else "desligada"}.', 'success')
    return redirect(url_for('dou.regras'))


@dou_bp.route('/regras/<int:rule_id>/excluir', methods=['POST'])
def regra_excluir(rule_id):
    regra = _regra_do_escritorio(rule_id)
    if not _pode_editar(regra):
        abort(403)
    nome = regra.nome
    # Os hits caem por cascade; o alerta que ficar sem motivo nenhum sai junto.
    orfaos = [h.alert for h in regra.hits
              if h.alert and not h.alert.matches and len(h.alert.rule_hits) == 1]
    db.session.delete(regra)
    for alerta in orfaos:
        db.session.delete(alerta)
    db.session.commit()
    flash(f'Regra "{nome}" excluída.', 'success')
    return redirect(url_for('dou.regras'))


@dou_bp.route('/regras/testar', methods=['POST'])
def regra_testar():
    """O teste antes de salvar. JSON, porque a tela chama por fetch."""
    if not session.get('law_firm_id'):
        abort(403)
    dados = request.get_json(silent=True) or {}
    try:
        return rule_service.testar(
            (dados.get('termo') or '').strip(),
            (dados.get('modo') or rule_service.MODO_FRASE).strip(),
            dados.get('secoes') or [],
            (dados.get('orgao') or '').strip() or None)
    except Exception:  # noqa: BLE001 — a tela mostra o erro, não um 500
        current_app.logger.exception('DOU: falha ao testar regra')
        return {'erro': 'Não foi possível testar a regra agora.'}, 500


@dou_bp.route('/regras/<int:rule_id>/acervo', methods=['POST'])
def regra_backfill(rule_id):
    """Roda a regra no acervo inteiro, não só na janela dos 7 dias."""
    regra = _regra_do_escritorio(rule_id)
    quantos = _backfill_da_regra(regra, dias=None)
    flash(f'{quantos} alerta(s) gerado(s) do acervo.', 'success')
    return redirect(url_for('dou.regras'))


def _backfill_da_regra(regra, dias=None) -> int:
    """Gera os alertas desta regra na janela pedida (None = acervo inteiro)."""
    query = db.session.query(DouEdition.data_publicacao).distinct()
    if dias:
        limite = datetime.now().date() - timedelta(days=dias - 1)
        query = query.filter(DouEdition.data_publicacao >= limite)
    datas = [linha[0] for linha in query.all()]
    if not datas:
        return 0
    quantos = alert_service.gerar_para_datas(
        datas, carteiras={}, regras={regra.law_firm_id: [regra]})
    db.session.commit()
    return quantos


def _orgaos_para_regra():
    """Os órgãos-raiz que existem no acervo, para o select do formulário."""
    linhas = (db.session.query(DouArticle.orgao_hierarquia)
              .filter(DouArticle.orgao_hierarquia.isnot(None))
              .distinct().all())
    raizes = {busca_service.orgao_raiz(linha[0]) for linha in linhas}
    return sorted(r for r in raizes if r)
```

Acrescentar `DouAlertRuleHit` ao import de `app.models` e `timedelta` ao
import de `datetime`.

O `carteiras={}` de `_backfill_da_regra` é deliberado: faz a varredura casar
**só** a regra nova, sem refazer os CNPJs que já viraram alerta. A guarda
`if carteira is not None:` da Task 3 é o que impede esse atalho de zerar o
`clients_count` de um alerta de cliente que a regra também casou.

- [ ] **Step 4: Escrever os templates**

`templates/dou/regras.html` — herda de `layout/base.html` como as demais telas
do módulo, com o `page_hero` do DOU. Corpo:

```jinja
<div class="dou-page">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <div>
      <h5 class="mb-1">Regras de palavra-chave</h5>
      <p class="text-muted small mb-0">
        O que o escritório vigia no Diário Oficial por texto, órgão ou seção.
        Complementa o alerta por CNPJ, que só pega cliente citado nominalmente.
      </p>
    </div>
    <a href="{{ url_for('dou.regra_nova') }}" class="btn btn-success">
      <i class="bi bi-plus-lg"></i> Nova regra</a>
  </div>

  {% if regras %}
  <div class="table-responsive">
    <table class="table align-middle dou-tabela">
      <thead>
        <tr>
          <th>Regra</th><th>O que casa</th><th>Criada por</th>
          <th class="text-end">Alertas</th><th>Último</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% for r in regras %}
        <tr class="{{ '' if r.ativo else 'opacity-50' }}">
          <td>
            <strong>{{ r.nome }}</strong>
            {% if not r.ativo %}<span class="badge bg-secondary ms-1">desligada</span>{% endif %}
          </td>
          <td class="small text-muted">{{ r.resumo_do_casamento }}</td>
          <td class="small">{{ r.created_by.name if r.created_by else '—' }}</td>
          <td class="text-end">
            <a href="{{ url_for('dou.alertas', status='todos', regra=r.id) }}">
              {{ contagem.get(r.id, 0) }}</a>
          </td>
          <td class="small text-muted">
            {{ r.last_match_at | datetime_sp if r.last_match_at else 'nunca' }}
          </td>
          <td class="text-end">
            {% if pode_editar(r) %}
            <a href="{{ url_for('dou.regra_editar', rule_id=r.id) }}"
               class="btn btn-sm btn-outline-secondary">Editar</a>
            <form method="post" class="d-inline"
                  action="{{ url_for('dou.regra_alternar', rule_id=r.id) }}">
              <button class="btn btn-sm btn-outline-secondary">
                {{ 'Desligar' if r.ativo else 'Ligar' }}</button>
            </form>
            <form method="post" class="d-inline"
                  action="{{ url_for('dou.regra_backfill', rule_id=r.id) }}">
              <button class="btn btn-sm btn-outline-primary"
                      title="Rodar esta regra em todo o acervo já capturado">
                Rodar no acervo</button>
            </form>
            <form method="post" class="d-inline"
                  action="{{ url_for('dou.regra_excluir', rule_id=r.id) }}"
                  onsubmit="return confirm('Excluir a regra {{ r.nome }}?');">
              <button class="btn btn-sm btn-outline-danger">Excluir</button>
            </form>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="text-center text-muted py-5">
    <p class="mb-2">Nenhuma regra ainda.</p>
    <p class="small mb-3">Uma regra vigia um tema ("Fator Acidentário de
      Prevenção"), um nome fora da carteira ou um órgão inteiro.</p>
    <a href="{{ url_for('dou.regra_nova') }}" class="btn btn-success">
      Criar a primeira regra</a>
  </div>
  {% endif %}
</div>
```

`templates/dou/regra_form.html` — o formulário com o teste antes de salvar:

```jinja
<div class="dou-page" style="max-width:760px;">
  <h5 class="mb-3">{{ 'Editar regra' if regra else 'Nova regra' }}</h5>
  <form method="post" id="form-regra">
    <div class="mb-3">
      <label class="form-label">Nome</label>
      <input name="nome" id="nome" class="form-control" maxlength="120" required
             value="{{ (campos.nome if campos else regra.nome) or '' }}">
      <div class="form-text">É este nome que aparece no alerta e no e-mail.</div>
    </div>

    <div class="mb-3">
      <label class="form-label">Palavra-chave</label>
      <input name="termo" id="termo" class="form-control" maxlength="200"
             value="{{ (campos.termo if campos else regra.termo) or '' }}">
      <div class="form-text">
        Opcional se você escolher um órgão. Não existe modo "ou" — para vigiar
        dois termos, crie duas regras e veja o volume de cada uma.
      </div>
    </div>

    <div class="mb-3">
      {% set modo_atual = (campos.modo if campos else (regra.modo if regra else 'frase')) %}
      {% for m in MODOS %}
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="radio" name="modo" value="{{ m }}"
               id="modo-{{ m }}" {{ 'checked' if modo_atual == m }}>
        <label class="form-check-label" for="modo-{{ m }}">{{ MODO_LABELS[m] }}</label>
      </div>
      {% endfor %}
    </div>

    <div class="mb-3">
      <label class="form-label">Seções</label><br>
      {% set secoes_atuais = (campos.secoes if campos else (regra.lista_secoes if regra else [])) %}
      {% for s in ['DO1', 'DO2', 'DO3', 'DO1E', 'DO2E', 'DO3E'] %}
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" name="secoes" value="{{ s }}"
               id="secao-{{ s }}" {{ 'checked' if s in secoes_atuais }}>
        <label class="form-check-label" for="secao-{{ s }}">{{ s }}</label>
      </div>
      {% endfor %}
      <div class="form-text">Nenhuma marcada = todas as seções.</div>
    </div>

    <div class="mb-3">
      <label class="form-label">Órgão</label>
      {% set orgao_atual = (campos.orgao if campos else (regra.orgao_raiz if regra else '')) %}
      <select name="orgao" id="orgao" class="form-select select2-cnpj">
        <option value="">Todos os órgãos</option>
        {% for o in orgaos %}
        <option value="{{ o }}" {{ 'selected' if o == orgao_atual }}>{{ o }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="d-flex align-items-center gap-2 mb-3">
      <button type="button" class="btn btn-outline-primary" id="btn-testar">
        Testar regra</button>
      <div id="resultado-teste" class="flex-grow-1"></div>
    </div>

    <div id="confirmar-ruido" class="alert alert-danger d-none py-2">
      <div class="form-check mb-0">
        <input class="form-check-input" type="checkbox" id="ciente" required>
        <label class="form-check-label" for="ciente">
          Entendi o volume e quero salvar assim mesmo.</label>
      </div>
    </div>

    <div class="d-flex gap-2">
      <button class="btn btn-success">Salvar</button>
      <a href="{{ url_for('dou.regras') }}" class="btn btn-outline-secondary">Cancelar</a>
    </div>
  </form>
</div>
```

O JS é nativo, no padrão do projeto:

```html
<script>
(function () {
  const btn = document.getElementById('btn-testar');
  const caixa = document.getElementById('resultado-teste');
  const CORES = {vazio: 'secondary', ok: 'success', alto: 'warning', ruidoso: 'danger'};

  btn.addEventListener('click', async function () {
    btn.disabled = true;
    caixa.innerHTML = '<span class="text-muted">Testando nos últimos 7 dias…</span>';
    try {
      const resposta = await fetch('{{ url_for("dou.regra_testar") }}', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          termo: document.getElementById('termo').value,
          modo: document.querySelector('input[name=modo]:checked').value,
          secoes: Array.from(document.querySelectorAll('input[name=secoes]:checked'))
                       .map(function (e) { return e.value; }),
          orgao: document.getElementById('orgao').value
        })
      });
      const d = await resposta.json();
      if (!resposta.ok || d.erro) {
        caixa.innerHTML = '<span class="text-danger">' +
          (d.erro || 'Não foi possível testar agora.') + '</span>';
        return;
      }
      caixa.innerHTML = montar(d);
      // Regra ruidosa não bloqueia — avisa e pede confirmação explícita.
      document.getElementById('confirmar-ruido').classList
        .toggle('d-none', d.nivel !== 'ruidoso');
    } catch (e) {
      caixa.innerHTML = '<span class="text-danger">Falha de rede ao testar.</span>';
    } finally {
      btn.disabled = false;
    }
  });

  function montar(d) {
    if (!d.total) {
      return '<span class="dou-veredito dou-veredito--secondary">' +
             'Não pegaria nada nos últimos ' + d.dias + ' dias — confira o termo.</span>';
    }
    let html = '<span class="dou-veredito dou-veredito--' + CORES[d.nivel] + '">' +
      d.total + ' matéria(s) em ' + d.dias + ' dias — cerca de ' +
      d.por_dia + ' por dia</span>';
    if (d.nivel === 'alto') {
      html += '<div class="small text-muted mt-1">Volume alto — considere ' +
              'restringir por seção ou órgão.</div>';
    } else if (d.nivel === 'ruidoso') {
      html += '<div class="small text-danger mt-1">Essa regra sozinha traria ' +
              d.vezes_carteira + 'x o que a carteira inteira de clientes traz. ' +
              'Restrinja por seção/órgão ou use frase exata.</div>';
    }
    html += '<ul class="dou-exemplos mt-2">' + d.exemplos.map(function (x) {
      return '<li><span class="text-muted">' + (x.pub_date || '') + ' ' +
             x.pub_name + (x.pagina ? ' p.' + x.pagina : '') + ' · </span>' +
             x.identifica + '</li>';
    }).join('') + '</ul>';
    return html;
  }
})();
</script>
```

- [ ] **Step 5: Verificar o backfill sem estragar o alerta de CNPJ**

Run:
```bash
uv run python -c "
import sys; sys.path.insert(0,'.')
from main import app
from app.models import DouClientAlert
with app.app_context():
    quebrados = DouClientAlert.query.filter(
        DouClientAlert.clients_count == 0,
        DouClientAlert.tem_regra.is_(False)).count()
    print('alertas sem cliente e sem regra (deve ser 0):', quebrados)
"
```
Expected: `0`

- [ ] **Step 6: Rodar os testes**

Run:
```bash
uv run python tests/test_dou_routes.py
uv run python tests/test_dou_regras.py
uv run python tests/test_dou_alertas.py
```
Expected: PASS nos três

- [ ] **Step 7: Commit**

```bash
git add app/blueprints/dou.py templates/dou/regras.html \
        templates/dou/regra_form.html static/css/dou.css tests/test_dou_routes.py
git commit -m "feat(dou): tela de regras com teste antes de salvar

O teste roda a regra no acervo já capturado e mostra o volume antes do
botão Salvar — 'licitação' avisa que traria 660 por dia contra os ~6 da
carteira inteira. Avisa e deixa salvar: há caso legítimo de volume alto,
e limitar a colheita deixaria um buraco silencioso, pior que ruído.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Alertas na tela — origem, chips e grifo por termo

**Files:**
- Modify: `app/services/dou_alert_service.py` (`listar`, `resumo`, `_termos_de_grifo`, `trechos_do_alerta`, `regras_com_alerta`)
- Modify: `app/blueprints/dou.py` (`alertas`)
- Modify: `templates/dou/alertas.html`
- Modify: `static/css/dou.css`
- Modify: `tests/test_dou_alertas.py`

**Interfaces:**
- Produces:
  - `dou_alert_service.ORIGEM_CLIENTE = 'cliente'`, `ORIGEM_REGRA = 'regra'`
  - `dou_alert_service.listar(..., origem=None, rule_id=None)`
  - `dou_alert_service.regras_com_alerta(law_firm_id) -> list[(rule_id, nome, qtd)]`
  - `trechos_do_alerta` passa a grifar também os termos das regras do alerta

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_dou_alertas.py`. Este bloco fecha os invariantes que
o motor sozinho não prova — os do **registro** de alerta:

```python
def test_origem_e_regra():
    """A matéria que casa CNPJ e regra continua sendo um alerta só."""
    print('\n10. Origem: cliente, regra, ou as duas')

    from app.models import DouAlertRule, DouAlertRuleHit

    with app.app_context():
        firma = 1
        outra = 2
        edicao = DouEdition(data_publicacao=date(2026, 8, 13), secao='DO1',
                            status='ok')
        db.session.add(edicao)
        db.session.flush()

        art_regra = DouArticle(
            edition_id=edicao.id, art_id='a1', id_materia='m1', hash='h1',
            pub_name='DO1', pub_date=edicao.data_publicacao,
            identifica='PORTARIA CRPS Nº 1', texto='trata do CRPS e nada mais')
        art_ambos = DouArticle(
            edition_id=edicao.id, art_id='a2', id_materia='m2', hash='h2',
            pub_name='DO1', pub_date=edicao.data_publicacao,
            identifica='EDITAL', texto='CRPS decide sobre 33.592.510/0001-54')
        db.session.add_all([art_regra, art_ambos])

        regra = DouAlertRule(law_firm_id=firma, nome='CRPS', termo='CRPS',
                             modo='frase', ativo=True)
        regra_outra = DouAlertRule(law_firm_id=outra, nome='CRPS', termo='CRPS',
                                   modo='frase', ativo=True)
        regra_off = DouAlertRule(law_firm_id=firma, nome='desligada',
                                 termo='CRPS', modo='frase', ativo=False)
        db.session.add_all([regra, regra_outra, regra_off])
        db.session.commit()

        alertas.gerar_para_datas([edicao.data_publicacao])
        db.session.commit()

        a_regra = DouClientAlert.query.filter_by(
            law_firm_id=firma, article_id=art_regra.id).one()
        check('alerta só de regra existe', a_regra.tem_regra)
        check('alerta só de regra tem match_type nulo',
              a_regra.match_type is None, str(a_regra.match_type))
        check('alerta só de regra tem clients_count 0',
              a_regra.clients_count == 0, str(a_regra.clients_count))
        check('regra desligada não colhe',
              [h.rule_id for h in a_regra.rule_hits] == [regra.id],
              str([h.rule_id for h in a_regra.rule_hits]))

        a_ambos = DouClientAlert.query.filter_by(
            law_firm_id=firma, article_id=art_ambos.id).one()
        check('cliente + regra é UM alerta com dois motivos',
              a_ambos.clients_count == 1 and a_ambos.tem_regra)
        check('e o match_type de cliente sobrevive',
              a_ambos.match_type is not None)

        # Reprocessar não pode duplicar hit nem apagar a triagem.
        a_regra.status = DouClientAlert.STATUS_READ
        db.session.commit()
        alertas.gerar_para_datas([edicao.data_publicacao])
        db.session.commit()
        db.session.refresh(a_regra)
        check('reprocessar não duplica hit', len(a_regra.rule_hits) == 1,
              str(len(a_regra.rule_hits)))
        check('reprocessar preserva a triagem',
              a_regra.status == DouClientAlert.STATUS_READ)

        # Tenant: a regra do escritório 2 gera alerta do escritório 2, e o
        # filtro de um nunca enxerga o do outro.
        do_outro = DouClientAlert.query.filter_by(
            law_firm_id=outra, article_id=art_regra.id).first()
        check('a regra do outro escritório gerou o alerta dele',
              do_outro is not None)
        pagina = alertas.listar(firma, status=None, rule_id=regra_outra.id)
        check('regra de outro escritório não vaza no filtro',
              pagina.total == 0, str(pagina.total))

        # Origem
        so_regra = alertas.listar(firma, status=None,
                                  origem=alertas.ORIGEM_REGRA)
        check('origem=regra só traz quem tem regra',
              all(a.tem_regra for a in so_regra.items))
        so_cliente = alertas.listar(firma, status=None,
                                    origem=alertas.ORIGEM_CLIENTE)
        check('origem=cliente só traz quem tem CNPJ',
              all(a.clients_count > 0 for a in so_cliente.items))

        # Grifo
        termos = alertas._termos_de_grifo(a_regra)
        check('o grifo inclui o termo da regra', 'CRPS' in termos, str(termos))
```

Registrar `test_origem_e_regra()` em `main()`. O arquivo já monta banco de
teste próprio — seguir o mesmo `setUp` das demais funções que tocam o banco.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_alertas.py`
Expected: FAIL — `listar() got an unexpected keyword argument 'origem'`

- [ ] **Step 3: Implementar**

Em `dou_alert_service`:

```python
ORIGEM_CLIENTE = 'cliente'
ORIGEM_REGRA = 'regra'
```

Em `listar`, acrescentar os parâmetros e os filtros:

```python
    if origem == ORIGEM_REGRA:
        query = query.filter(DouClientAlert.tem_regra.is_(True))
    elif origem == ORIGEM_CLIENTE:
        query = query.filter(DouClientAlert.clients_count > 0)
    if rule_id:
        query = query.filter(DouClientAlert.id.in_(
            db.session.query(DouAlertRuleHit.alert_id)
            .filter(DouAlertRuleHit.law_firm_id == law_firm_id,
                    DouAlertRuleHit.rule_id == rule_id)))
```

e o `joinedload` ganha `joinedload(DouClientAlert.rule_hits).joinedload(DouAlertRuleHit.rule)`.

Em `resumo`, somar `'por_regra': _base(law_firm_id).filter(DouClientAlert.tem_regra.is_(True)).count()`.

Nova função, no mesmo lugar de `clientes_com_alerta`:

```python
def regras_com_alerta(law_firm_id: int):
    """``[(rule_id, nome, qtd)]`` — só regra que já rendeu alerta.

    Como no filtro de cliente: oferecer opção que não devolve nada é convidar
    para uma tela vazia.
    """
    linhas = (db.session.query(DouAlertRuleHit.rule_id, DouAlertRule.nome,
                               func.count(func.distinct(DouAlertRuleHit.alert_id)))
              .join(DouAlertRule, DouAlertRule.id == DouAlertRuleHit.rule_id)
              .filter(DouAlertRuleHit.law_firm_id == law_firm_id)
              .group_by(DouAlertRuleHit.rule_id, DouAlertRule.nome)
              .order_by(DouAlertRule.nome).all())
    return [(rid, nome, qtd) for rid, nome, qtd in linhas]
```

E `_termos_de_grifo` passa a receber o alerta inteiro:

```python
def _termos_de_grifo(alerta):
    """O que o modal marca: o CNPJ nas duas grafias e o termo de cada regra.

    O CNPJ vai pontuado e cru porque o DOU escreve com pontuação e o banco
    guarda só dígitos. O termo da regra entra como veio — quem escapa é o
    `grifar_html`, sempre antes de marcar.
    """
    termos = []
    for m in alerta.matches:
        termos.append(formatar_cnpj(m.cnpj))
        termos.append(m.cnpj)
    for regra in alerta.regras_citadas:
        if regra.termo:
            termos.append(regra.termo)
    return [t for t in termos if t]
```

Em `trechos_do_alerta`, trocar as duas chamadas `_termos_de_grifo(cnpjs)` por
`_termos_de_grifo(alerta)`, e — quando o alerta não tem CNPJ nenhum — usar os
blocos que contêm o **termo**, não o CNPJ. Acrescentar antes do `return` de
`modo='html'`:

```python
        blocos = _blocos_com_cnpj(sopa, cnpjs) if cnpjs else []
        if not blocos:
            # Alerta só de palavra-chave: o bloco é o que contém o termo.
            blocos = _blocos_com_termos(
                sopa, [r.termo for r in alerta.regras_citadas if r.termo])
```

com a função irmã, ao lado de `_blocos_com_cnpj`:

```python
def _blocos_com_termos(sopa, termos):
    """Blocos cujo texto contém algum dos termos, sem acento e sem caixa."""
    alvos = [rule_service.normalizar(t) for t in termos if t]
    if not alvos:
        return []
    vistos, blocos = set(), []
    for no in sopa.find_all(string=True):
        texto = rule_service.normalizar(str(no))
        if not any(alvo in texto for alvo in alvos):
            continue
        bloco = _bloco_do_no(no)
        if bloco is not None and id(bloco) not in vistos:
            vistos.add(id(bloco))
            blocos.append(bloco)
    return blocos
```

Na rota `alertas` do blueprint, ler `origem` e `regra` de `request.args`,
passar para `listar`, e enviar `regras=alert_service.regras_com_alerta(...)`,
`f_origem`, `f_regra` para o template.

No `templates/dou/alertas.html`: dois selects novos na barra de filtros; e na
linha do alerta, depois dos chips de cliente, os chips de regra:

```jinja
{% for regra in alerta.regras_citadas %}
  <a class="dou-chip dou-chip--regra"
     href="{{ url_for('dou.alertas', status=f_status, regra=regra.id) }}">
    {{ regra.nome }}</a>
{% endfor %}
```

No `static/css/dou.css`, `.dou-chip--regra` com um par de tokens claro/escuro
próprio — **o vermelho continua exclusivo do FAP**, e a regra escopada em
`.dou-page .dou-chip--regra` porque `[data-bs-theme="dark"] a` tem
especificidade (0,1,1) e venceria uma classe só.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run python tests/test_dou_alertas.py`
Expected: PASS

- [ ] **Step 5: Conferir contraste dos chips novos nos dois temas**

Medir a razão de contraste do par cor/fundo do `.dou-chip--regra` em claro e
escuro. Ambos ≥ 4,5:1 (mínimo WCAG para texto pequeno). Ajustar os tokens até
passar — foi o que o badge FAP exigiu (3,82:1 no escuro, corrigido para 5,95).

- [ ] **Step 6: Commit**

```bash
git add app/services/dou_alert_service.py app/blueprints/dou.py \
        templates/dou/alertas.html static/css/dou.css tests/test_dou_alertas.py
git commit -m "feat(dou): alertas de regra na mesma tela, com filtro de origem

Uma portaria que cita o CNPJ do cliente e casa a regra é um alerta só,
com dois motivos. O 'ver trecho' reaproveita tudo — muda só o que se
grifa: antes o CNPJ, agora o termo também.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Bloco de palavras-chave no e-mail

**Files:**
- Modify: `app/services/dou_alert_service.py` (`build_digest`)
- Modify: `app/services/notification_service.py` (`_dou_digest_subject`)
- Modify: `templates/emails/dou_digest.html`
- Modify: `tests/test_dou_alertas.py`

**Interfaces:**
- Produces: `build_digest` passa a devolver também `regras[]` — cada item
  `{rule_id, nome, materias, novos, exemplos[]}` — e `novos_por_regra` (int).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `test_digest_diario()` em `tests/test_dou_alertas.py`:

```python
    # --- bloco de palavras-chave -------------------------------------
    digest = alertas.build_digest(firma)
    check('o digest traz o bloco de regras', 'regras' in digest,
          str(sorted(digest))[:160])
    nomes = [r['nome'] for r in digest['regras']]
    check('só regra que rendeu alerta na janela aparece',
          'CRPS' in nomes and 'nunca casa nada' not in nomes, str(nomes))
    check('cada regra traz contagem e exemplos',
          all('materias' in r and 'exemplos' in r for r in digest['regras']))
    check('exemplo não passa de DIGEST_EXEMPLOS',
          all(len(r['exemplos']) <= alertas.DIGEST_EXEMPLOS
              for r in digest['regras']))

    # A novidade que vem só de regra tem de acordar o e-mail: sem isso, um dia
    # sem citação de cliente e com portaria nova sairia como "nada a relatar".
    so_regra = alertas.build_digest(firma, since=_muito_antigo)
    check('novidade só de regra dispara o e-mail',
          so_regra['has_novidades'] and so_regra['novos_por_regra'] > 0,
          f"novos={so_regra['novos']} regra={so_regra['novos_por_regra']}")
```

onde `_muito_antigo` é um `datetime` anterior a tudo que o teste criou (o
arquivo já usa essa técnica no bloco do digest).

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run python tests/test_dou_alertas.py`
Expected: FAIL — `KeyError: 'regras'`

- [ ] **Step 3: Implementar**

Em `build_digest`, na mesma varredura dos alertas da janela (não uma segunda
consulta), agrupar por regra:

```python
    # Agrupado por regra, como as empresas por nome: é o nome que a pessoa
    # reconhece, não o id. Mesma janela e mesmo selo NOVO do resto do e-mail.
    por_regra = {}
    for alerta in alertas_da_janela:
        for regra in alerta.regras_citadas:
            item = por_regra.setdefault(regra.id, {
                'rule_id': regra.id, 'nome': regra.nome,
                'materias': 0, 'novos': 0, 'exemplos': []})
            item['materias'] += 1
            if since and alerta.created_at and alerta.created_at > since:
                item['novos'] += 1
            if len(item['exemplos']) < DIGEST_EXEMPLOS:
                item['exemplos'].append(_exemplo_do_alerta(alerta))
    regras_ordenadas = sorted(por_regra.values(),
                              key=lambda r: (-r['novos'], -r['materias'], r['nome']))
```

e acrescentar ao dicionário devolvido:

```python
        'regras': regras_ordenadas,
        'novos_por_regra': sum(r['novos'] for r in regras_ordenadas),
```

`has_novidades` passa a ser `novos > 0 or novos_por_regra > 0`.

Em `templates/emails/dou_digest.html`, depois do laço de empresas e antes do
botão, o bloco novo (mesmas restrições: tabela + CSS inline, sem Bootstrap):

```jinja
{% if digest.regras %}
<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:{{ SUAVE }};
            text-transform:uppercase;margin:22px 0 8px 0;">Palavras-chave</div>
{% for r in digest.regras %}
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
       style="margin:0 0 10px 0;border:1px solid {{ BORDA }};border-radius:8px;">
  <tr>
    <td style="padding:11px 16px;">
      <div style="font-size:13.5px;font-weight:700;color:{{ TEXTO }};margin-bottom:2px;">
        {{ r.nome }}
        {% if r.novos %}{{ pilula('NOVO', '#0d6efd', '#ffffff') }}{% endif %}
      </div>
      <div style="font-size:12px;color:{{ SUAVE }};margin-bottom:6px;">
        {{ r.materias }} matéria(s)
      </div>
      {% for x in r.exemplos %}
      <div style="font-size:12.5px;color:{{ TEXTO }};margin:0 0 3px 0;">
        <span style="color:{{ SUAVE }};">{{ x.pub_date.strftime('%d/%m') if x.pub_date }} ·
          {{ x.pub_name }}{% if x.pagina %} p.{{ x.pagina }}{% endif %} ·</span>
        <a href="{{ url_for('dou.materia', article_id=x.article_id, _external=True) }}"
           style="color:#0d6efd;text-decoration:none;">{{ x.identifica }}</a>
      </div>
      {% endfor %}
    </td>
  </tr>
</table>
{% endfor %}
{% endif %}
```

Em `notification_service._dou_digest_subject`, quando não houver desfecho FAP
mas houver regra com novidade, o assunto passa a levar a regra:

```python
    if not digest.get('com_fap') and digest.get('novos_por_regra'):
        principal = digest['regras'][0]
        return (f'Diário Oficial: {principal["nome"]} '
                f'({principal["novos"]} nova(s))')
```

mantendo a regra que já vale: **o assunto leva o desfecho, não a contagem.**

- [ ] **Step 4: Rodar e ver passar**

Run:
```bash
uv run python tests/test_dou_alertas.py
uv run python tests/test_notifications.py
```
Expected: PASS nos dois

- [ ] **Step 5: Enviar um teste real**

Abrir `/settings/notifications`, card "Diário Oficial — clientes citados",
botão "Enviar teste para mim". Conferir no cliente de e-mail que o bloco novo
renderiza e que os links absolutos abrem.

- [ ] **Step 6: Commit**

```bash
git add app/services/dou_alert_service.py app/services/notification_service.py \
        templates/emails/dou_digest.html tests/test_dou_alertas.py
git commit -m "feat(dou): bloco de palavras-chave no e-mail diário

Um e-mail por manhã, não dois: o bloco entra no mesmo dou_digest, com a
mesma janela de 3 edições e o mesmo selo NOVO. Sem desfecho FAP no dia, o
assunto passa a levar a regra com mais novidade.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Backfill, chip do header e documentação

**Files:**
- Modify: `scripts/gerar_alertas_dou.py`
- Modify: `app/blueprints/dou.py` (`inject_dou_health`)
- Modify: `templates/partials/header.html` (se o chip precisar de ajuste)
- Modify: `CLAUDE.md`

**Interfaces:**
- Produces: `scripts/gerar_alertas_dou.py --regras` (só as regras) e o
  comportamento padrão (as duas origens).

- [ ] **Step 1: Estender o script de backfill**

Em `scripts/gerar_alertas_dou.py`, acrescentar as flags e carregar as regras:

```python
parser.add_argument('--regras', action='store_true',
                    help='só as regras de palavra-chave, sem refazer os CNPJs')
parser.add_argument('--clientes', action='store_true',
                    help='só o casamento por CNPJ, sem as regras')
```

e na montagem da chamada:

```python
    from app.services import dou_rule_service as rule_service

    carteiras = None if not args.regras else {}
    regras = None if not args.clientes else {}
    total = alert_service.gerar_para_datas(datas, carteiras, regras)
```

Atualizar o docstring do script com os exemplos.

- [ ] **Step 2: Rodar o backfill no dev**

Run: `uv run python scripts/gerar_alertas_dou.py --tudo`
Expected: termina sem erro e reporta a contagem

- [ ] **Step 3: Conferir o chip do header**

`inject_dou_health` já expõe `dou_alertas_nao_lidos` e o contador soma os
alertas independentemente da origem — nenhuma mudança de código deve ser
necessária. Confirmar visualmente que o número do chip cresceu com os alertas
de regra. **Nada de contagem de volume nova no chip:** badge é pendência,
nunca volume.

- [ ] **Step 4: Documentar no CLAUDE.md**

Na seção "Alertas de cliente no DOU", acrescentar a subseção
**"Alertas por palavra-chave"** com os fatos que custaram medição:

- o motor é próprio e não o Meilisearch — `FAP` devolve 92 pelo índice e 12
  aqui, e as 80 de diferença são FAPED/FAPEG/FAPESP, fundações de amparo à
  pesquisa;
- **não existe modo OU** — `Fator Acidentário de Prevenção` daria 748 contra 7;
- **não existe "procurar só no título"** — `titulo` está vazio em 100% do
  acervo e `ementa` em 98%; o corpus é `identifica + ementa + texto`;
- a peneira `LIKE` usa a maior corrida sem acento do termo, cobre os **três**
  campos do corpus e é superconjunto seguro — 12 s viram 1,9 s no pior caso;
- o teste antes de salvar chama o **mesmo** `casar()` da colheita, de propósito;
- os cortes do veredito são ancorados nos ~6 alertas/dia da carteira inteira;
- a unidade continua sendo a **matéria**: hit é tabela filha, e a matéria que
  casa CNPJ e regra é um alerta só;
- `dou_alert_rules` e `dou_alert_rule_hits` **têm** `law_firm_id`;
- `match_type` nulo identifica alerta só de palavra-chave.

Atualizar também a tabela de serviços com `dou_rule_service` e a linha do
blueprint `dou` mencionando `/dou/regras`.

- [ ] **Step 5: Rodar a suíte inteira do módulo**

Run:
```bash
uv run python tests/test_dou_regras.py
uv run python tests/test_dou_alertas.py
uv run python tests/test_dou_routes.py
uv run python tests/test_notifications.py
```
Expected: PASS nos quatro

- [ ] **Step 6: Commit**

```bash
git add scripts/gerar_alertas_dou.py app/blueprints/dou.py CLAUDE.md
git commit -m "docs(dou): registrar as regras de palavra-chave e o backfill

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Implantação em produção

Na ordem, no servidor de produção (o MySQL desta máquina é cópia desatualizada):

```bash
uv run python database/add_dou_alert_rules_tables.py
uv run python database/alter_dou_alerts_for_rules.py
```

Nenhum backfill é necessário na implantação: não existe regra ainda. Cada regra
criada gera os alertas dos últimos 7 dias sozinha, e o botão "rodar no acervo"
cobre o resto quando o usuário quiser.
