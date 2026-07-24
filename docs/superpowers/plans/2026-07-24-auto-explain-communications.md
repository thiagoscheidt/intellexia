# Explicação IA automática de novas comunicações no sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ao sincronizar comunicações (cron), gerar e salvar automaticamente a explicação IA de cada comunicação nova — mesmo efeito do botão "Explicar com IA" da tela.

**Architecture:** Nova função `explain_new_communications(law_firm_id, since, limit)` em `app/services/communication_monitor_service.py` que, **após** o commit do sync, varre as comunicações criadas na rodada (sem `analysis_json`, com `texto`) e chama a já existente `explain_communication` uma a uma (transações curtas). O script `scripts/sync_process_communications.py` a invoca por escritório nos modos incremental e `--caderno` (nunca `--full`/`--dry-run`), com nova flag `--sem-ia` para desligar.

**Tech Stack:** Flask + SQLAlchemy; agente `CommunicationExplainerAgent` (OpenAI, já existente); testes = scripts standalone (`uv run python tests/<arquivo>.py`), sem pytest.

**Spec:** `docs/superpowers/specs/2026-07-24-auto-explain-communications-design.md`

## Global Constraints

- **Nunca** chamada de IA/HTTP dentro da transação de escrita do sync (disciplina rede/escrita de `_ingest_batch` — lock via FK em `users` já congelou produção). A explicação roda só depois do commit do sync, e cada `explain_communication` commita sozinha.
- Falha de explicação **não** derruba o sync nem altera o exit code do script.
- Teto: `AUTO_EXPLAIN_LIMIT = 100` explicações por escritório por execução; truncamento é logado (sem caps silenciosos).
- `since` usa `datetime.now()` — mesmo relógio do default de `created_at` do modelo (TZ global do processo, America/Sao_Paulo definida em `main.py`).
- Multi-tenant: toda query filtra por `law_firm_id`.
- Atribuição de tokens: `user_id=_system_user_id(law_firm_id)` (admin do escritório), como o resto do sync.
- Deps via `uv` (não usar `pip`).

---

### Task 1: Serviço — `explain_new_communications`

**Files:**
- Modify: `app/services/communication_monitor_service.py` (inserir logo após `explain_communication`, ~linha 621, antes de `mark_all_read`; constante `AUTO_EXPLAIN_LIMIT` junto às demais constantes, após `DIGEST_LIMIT` na linha 54)
- Test: `tests/test_explain_new_communications.py` (novo, script standalone)

**Interfaces:**
- Consumes: `explain_communication(law_firm_id, communication_id, user_id=None, force=False)` e `_system_user_id(law_firm_id)` — ambos já existem no mesmo módulo.
- Produces: `explain_new_communications(law_firm_id, since, limit=AUTO_EXPLAIN_LIMIT) -> dict` com chaves `explained` (int), `failed` (int), `pending` (int — elegíveis fora do teto). Task 2 chama exatamente essa assinatura.

- [ ] **Step 1: Escrever o teste (que falha)**

Criar `tests/test_explain_new_communications.py` com o conteúdo completo abaixo. Segue o padrão de `tests/test_communication_monitor.py`: script standalone, `from main import app`, dados criados e removidos no próprio banco de dev, `explain_communication` substituída por fake (sem tocar a OpenAI).

```python
#!/usr/bin/env python3
"""
Teste de explain_new_communications (explicação IA automática pós-sync),
com explain_communication FAKE (sem tocar a OpenAI).

Cobre: só comunicações da rodada (created_at >= since), pula sem teor e já
explicadas, falha em uma não interrompe as demais, teto com contagem de
pendentes e idempotência (segunda chamada não regera nada).

    uv run python tests/test_explain_new_communications.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import db, LawFirm, ProcessCommunication, User
from app.services import communication_monitor_service as monitor

CNPJ_TESTE = '00000000000200'


def _cleanup_firm(firm_id):
    db.session.rollback()
    ProcessCommunication.query.filter_by(law_firm_id=firm_id).delete()
    User.query.filter_by(law_firm_id=firm_id).delete()
    LawFirm.query.filter_by(id=firm_id).delete()
    db.session.commit()


def _comm(firm_id, hash_, texto='PODER JUDICIÁRIO — teste', analysis=None,
          created_at=None):
    comm = ProcessCommunication(
        law_firm_id=firm_id, hash=hash_, texto=texto, analysis_json=analysis,
        sigla_tribunal='TRF4', numero_processo='50011815620234036100',
    )
    if created_at is not None:
        comm.created_at = created_at
    db.session.add(comm)
    db.session.commit()
    return comm.id


def run():
    ok = True
    with app.app_context():
        leftover = LawFirm.query.filter_by(cnpj=CNPJ_TESTE).first()
        if leftover:
            _cleanup_firm(leftover.id)

        firm = LawFirm(name='Teste Auto-Explicação LTDA', cnpj=CNPJ_TESTE)
        db.session.add(firm)
        db.session.flush()
        user = User(law_firm_id=firm.id, name='Admin Teste',
                    email='admin@teste-autoexplain.local', role='admin')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        # Fake: preenche analysis_json como a real; falha para hashes 'boom-*'.
        calls = []
        original_explain = monitor.explain_communication

        def fake_explain(law_firm_id, communication_id, user_id=None, force=False):
            comm = db.session.get(ProcessCommunication, communication_id)
            if comm.hash.startswith('boom'):
                raise ValueError('falha simulada do agente')
            comm.analysis_json = {'generated_at': 'x', 'model': 'fake',
                                  'data': {'resumo': 'fake'}}
            db.session.commit()
            calls.append((communication_id, user_id))

        monitor.explain_communication = fake_explain
        try:
            since = datetime.now() - timedelta(minutes=5)
            antiga = datetime.now() - timedelta(days=3)

            id_nova = _comm(firm.id, 'nova-1')
            id_sem_teor = _comm(firm.id, 'sem-teor', texto=None)
            id_ja_explicada = _comm(firm.id, 'ja-explicada',
                                    analysis={'data': {'resumo': 'antigo'}})
            id_antiga = _comm(firm.id, 'antiga-1', created_at=antiga)
            id_boom = _comm(firm.id, 'boom-1')

            # 1) Explica só a nova com teor; falha não interrompe as demais.
            stats = monitor.explain_new_communications(firm.id, since=since)
            assert stats == {'explained': 1, 'failed': 1, 'pending': 0}, stats
            assert [c[0] for c in calls] == [id_nova], calls
            assert calls[0][1] == user.id, 'user_id deve ser o admin do escritório'
            nova = db.session.get(ProcessCommunication, id_nova)
            assert nova.analysis_json['data']['resumo'] == 'fake'
            assert db.session.get(ProcessCommunication, id_antiga).analysis_json is None
            assert db.session.get(ProcessCommunication, id_ja_explicada) \
                .analysis_json['data']['resumo'] == 'antigo', 'não deve regerar'
            print('✓ explica só a nova da rodada; falha isolada não interrompe')

            # 2) Idempotência: segunda chamada não encontra nada novo
            #    ('boom-1' segue elegível e volta a falhar — fica para o botão).
            calls.clear()
            stats = monitor.explain_new_communications(firm.id, since=since)
            assert stats == {'explained': 0, 'failed': 1, 'pending': 0}, stats
            assert calls == [], calls
            print('✓ idempotente: nada é regerado')

            # 3) Teto: limit=1 explica uma e conta o restante em pending.
            _comm(firm.id, 'nova-2')
            _comm(firm.id, 'nova-3')
            calls.clear()
            stats = monitor.explain_new_communications(firm.id, since=since, limit=1)
            assert stats['explained'] == 1 and stats['pending'] >= 1, stats
            print('✓ teto respeitado com contagem de pendentes')
        except AssertionError as exc:
            ok = False
            print(f'✗ FALHA: {exc}')
        finally:
            monitor.explain_communication = original_explain
            _cleanup_firm(firm.id)

    print('RESULTADO:', 'OK' if ok else 'FALHOU')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `uv run python tests/test_explain_new_communications.py`
Expected: `AttributeError: module 'app.services.communication_monitor_service' has no attribute 'explain_new_communications'` (traceback; exit ≠ 0)

- [ ] **Step 3: Implementar a função no serviço**

Em `app/services/communication_monitor_service.py`, adicionar a constante após `DIGEST_LIMIT = 20` (linha 54):

```python
# Teto de explicações IA automáticas por escritório por execução do sync —
# protege o custo contra rajadas (ex.: primeira rodada após dias parado);
# o excedente fica para o botão "Explicar com IA" da tela.
AUTO_EXPLAIN_LIMIT = 100
```

E a função logo após `explain_communication` (antes de `mark_all_read`):

```python
def explain_new_communications(law_firm_id, since, limit=AUTO_EXPLAIN_LIMIT):
    """Gera e salva a explicação IA das comunicações criadas a partir de ``since``.

    Mesmo efeito do botão "Explicar com IA" da tela, em lote, chamado pelo cron
    DEPOIS do commit do sync — a chamada de IA é rede e nunca entra na transação
    de escrita. Falha em uma comunicação não interrompe as demais (fica para o
    botão manual). Retorna {'explained': n, 'failed': n, 'pending': n} —
    ``pending`` conta as elegíveis que ficaram de fora do teto ``limit``.
    """
    query = (ProcessCommunication.query
             .filter_by(law_firm_id=law_firm_id)
             .filter(ProcessCommunication.analysis_json.is_(None),
                     ProcessCommunication.texto.isnot(None),
                     ProcessCommunication.texto != '',
                     ProcessCommunication.created_at >= since)
             .order_by(ProcessCommunication.data_disponibilizacao.desc(),
                       ProcessCommunication.id.desc()))
    total = query.count()
    comms = query.limit(limit).all() if limit else query.all()
    user_id = _system_user_id(law_firm_id)

    stats = {'explained': 0, 'failed': 0, 'pending': max(0, total - len(comms))}
    for comm in comms:
        try:
            explain_communication(law_firm_id, comm.id, user_id=user_id)
            stats['explained'] += 1
        except Exception as exc:  # IA nunca derruba o sync
            db.session.rollback()
            logger.warning(
                'Explicação IA falhou para comunicação %s (%s): %s', comm.id,
                comm.numero_processo_mascara or comm.numero_processo, exc)
            stats['failed'] += 1
    return stats
```

Observação: chamar `explain_communication` pelo nome global (como acima) é obrigatório — o teste substitui `monitor.explain_communication` e o Python resolve o nome no módulo em tempo de chamada.

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `uv run python tests/test_explain_new_communications.py`
Expected: as três linhas `✓` e `RESULTADO: OK` (exit 0)

- [ ] **Step 5: Regressão do serviço**

Run: `uv run python tests/test_communication_monitor.py`
Expected: mesmo resultado de antes da mudança (sem novas falhas)

- [ ] **Step 6: Commit**

```bash
git add app/services/communication_monitor_service.py tests/test_explain_new_communications.py
git commit -m "Explicação IA automática de comunicações novas (serviço)"
```

---

### Task 2: Script — flag `--sem-ia` e disparo pós-sync

**Files:**
- Modify: `scripts/sync_process_communications.py`

**Interfaces:**
- Consumes: `monitor.explain_new_communications(law_firm_id, since=run_start)` (Task 1); retorna `{'explained', 'failed', 'pending'}`.
- Produces: flag CLI `--sem-ia`; linha de log `🤖 escritório N · X explicada(s), Y falha(s)`.

- [ ] **Step 1: Adicionar helper e flag**

Em `scripts/sync_process_communications.py`, adicionar após a função `_log` (linha 58):

```python
def _explain_new(monitor, firm_id, since) -> None:
    """Explicação IA das comunicações criadas na rodada (pós-commit do sync)."""
    stats = monitor.explain_new_communications(firm_id, since=since)
    if stats['explained'] or stats['failed'] or stats['pending']:
        msg = (f"🤖 escritório {firm_id} · {stats['explained']} explicada(s), "
               f"{stats['failed']} falha(s)")
        if stats['pending']:
            msg += (f" · {stats['pending']} além do teto ficaram para o botão "
                    f"\"Explicar com IA\" da tela")
        _log(msg)
```

E o argumento no parser, após `--tribunais` (linha 114):

```python
    parser.add_argument('--sem-ia', dest='sem_ia', action='store_true',
                        help='não gera a explicação IA das comunicações novas '
                             '(padrão: gera nos modos incremental e --caderno)')
```

- [ ] **Step 2: Disparar no modo incremental (main)**

Em `main()`, capturar o início da rodada logo após entrar no contexto — trocar:

```python
    with app.app_context():
        if args.caderno:
            return _run_caderno(monitor, args)
```

por:

```python
    with app.app_context():
        run_start = datetime.now()
        if args.caderno:
            return _run_caderno(monitor, args, run_start)
```

E, no fim de `main()`, trocar:

```python
        return 1 if failures else 0
```

por (falhas de explicação não alteram o exit code — só as de sincronização):

```python
        if not (args.dry_run or full_from or args.sem_ia):
            for summary in summaries:
                _explain_new(monitor, summary['law_firm_id'], run_start)

        return 1 if failures else 0
```

- [ ] **Step 3: Disparar no modo caderno**

Trocar a assinatura `def _run_caderno(monitor, args) -> int:` por
`def _run_caderno(monitor, args, run_start) -> int:` e, dentro do laço
`for firm_id in firm_ids:`, após o `for r in summary['results']:`
(mesmo nível de indentação do `for r`), adicionar:

```python
        if not (args.dry_run or args.sem_ia):
            _explain_new(monitor, firm_id, run_start)
```

- [ ] **Step 4: Atualizar o docstring do script**

No docstring do módulo, após o parágrafo dos modos de execução (antes de "Execução manual:"), adicionar:

```
Explicação IA: nos modos incremental e --caderno, cada comunicação nova com
teor ganha automaticamente a explicação da IA (a mesma do botão "Explicar com
IA" da tela), até 100 por escritório por execução; use --sem-ia para desligar.
O modo --full nunca explica (carga histórica = custo alto); o backlog fica
para o botão da tela.
```

- [ ] **Step 5: Verificar CLI e caminhos que NÃO explicam**

Run: `uv run python scripts/sync_process_communications.py --help`
Expected: `--sem-ia` listado no help, sem erro de sintaxe.

Run: `uv run python scripts/sync_process_communications.py --dry-run --law-firm-id 1`
Expected: sync roda como antes e **nenhuma** linha `🤖` aparece (dry-run não explica). Se a API do DJEN estiver indisponível no momento, basta o comando iniciar e logar normalmente — o ponto verificado é a ausência de `🤖`.

- [ ] **Step 6: Verificação ponta-a-ponta (opcional, gasta tokens reais)**

Somente se quiser validar com a OpenAI de verdade: escolher um escritório com poucas comunicações novas e rodar `uv run python scripts/sync_process_communications.py --law-firm-id <id>`; conferir a linha `🤖` e, na tela de Monitoramento, que a explicação aparece sem clicar no botão (badge de cache).

- [ ] **Step 7: Commit**

```bash
git add scripts/sync_process_communications.py
git commit -m "Sync de comunicações: explicação IA automática das novas (--sem-ia desliga)"
```
