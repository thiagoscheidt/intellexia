# FAP Reviewer - Temperature Determinism Fix
**Data**: 2026-05-12  
**Status**: ✅ Implementado

---

## Problema Identificado

Execuções consecutivas do revisor FAP sobre o **mesmo documento** produziam **achados completamente diferentes**:

```
Execução 14: benefício inconsistência (página 14) ✅ ENCONTRADO
Execução 15: benefício inconsistência (página 14) ❌ NÃO ENCONTRADO
Execução 16: benefício inconsistência (página 14) ❌ NÃO ENCONTRADO
```

### Causa Raiz
Você estava usando `google/gemini-2.5-pro` via OpenRouter, que **não oferece determinismo** mesmo com `temperature=0.0`.

---

## Solução Implementada

### 1. **Temperature Padrão: 0.0**
- Mudado de `0.2` → `0.0` em todos os defaults
- `temperature=0.0` fornece o **máximo determinismo possível** para o modelo escolhido
- Migração executada: 1 registro `FapReviewSetting` atualizado ✅

**Files alterados:**
- `app/agents/fap_review/reviewer_agent.py`: temperatura padrão = 0.0
- `app/models.py`: `FapReviewSetting.reviewer_temperature` default = 0.0
- `app/blueprints/fap_review.py`: inicialização com 0.0
- `database/update_reviewer_temperature_to_deterministic.py`: migração criada

### 2. **Flexibilidade de Modelo Mantida**
O usuário pode escolher modelo no settings. Trade-offs:

| Modelo                    | Determinismo               | Qualidade | Custo | Velocidade |
| ------------------------- | -------------------------- | --------- | ----- | ---------- |
| **gpt-4o** / gpt-4-turbo  | ✅ Determinístico com T=0.0 | Excelente | Alto  | Média      |
| **google/gemini-2.5-pro** | ⚠️ Variável mesmo com T=0.0 | Excelente | Baixo | Rápido     |
| **gpt-4o-mini**           | ⚠️ Suporte limitado         | Bom       | Baixo | Rápido     |

---

## Comportamento Esperado

### Com `google/gemini-2.5-pro` (atual)
```
Execução 1: 16 achados (padrão A)
Execução 2: 16 achados (padrão B - DIFERENTE, conforme antes)
```
**Tradeoff**: Qualidade + custo baixo vs. variação de achados

### Com `openai/gpt-4o` (alternativa)
```
Execução 1: 16 achados (padrão X)
Execução 2: 16 achados (padrão X - IDÊNTICO)
```
**Tradeoff**: Determinismo total vs. custo mais alto

---

## Próximas Ações (Opcionais)

Se você quiser determinismo total em algum momento:
1. Ir para **FAP Review → Settings**
2. Mudar **Modelo** para `openai/gpt-4o` (ou `openai/gpt-4-turbo`)
3. Deixar **Temperatura** em `0.0` (já está por padrão)

---

## Documentação

- **Scripts diagnóstico criado**: `scripts/diagnose_reviewer_inconsistency.py`
  - Compara 2 execuções e identifica achados faltantes
  - Uso: `uv run python scripts/diagnose_reviewer_inconsistency.py 14 15`

- **Repo memory**: `/memories/repo/fap-reviewer-determinism-fix.md`
  - Análise técnica detalhada

---

## Resumo

✅ **temperature=0.0** = máximo determinismo para o modelo  
✅ Usuário tem controle total sobre modelo (settings)  
✅ Trade-offs documentados e transparentes  
⚠️ Determinismo **total** requer modelo que suporte (gpt-4o, não gemini)

