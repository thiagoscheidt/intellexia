# Mapeamento dos Arquivos do Cliente para o FAP Review

Este documento define como os conteúdos fornecidos pelo cliente devem ser distribuídos na configuração atual do agente revisor.

## Decisão de Estrutura

Manter 4 arquivos de prompt do revisor:
- REVISOR_IDENTITY.md
- REVISOR_RULES.md
- REVISOR_PROMPT.md
- REVISOR_OUTPUT_FORMAT.md

Motivo:
- A estrutura já está integrada no backend e no painel de configuração.
- Evita mudanças de contrato entre UI, banco e agente no pré-implantação.
- Permite evolução de conteúdo sem risco de regressão funcional.

## Encaixe dos Materiais Recebidos

### 1) PERSONA DO PROJETO.txt
Destino principal: REVISOR_IDENTITY.md

Conteúdo aproveitado:
- Identidade do agente
- Papel do revisor no escritório
- Objetivo de longo prazo

### 2) INSTRUÇÕES GERAIS DO PROJETO.txt
Destinos:
- REVISOR_RULES.md (regras invioláveis e hierarquia)
- REVISOR_PROMPT.md (fluxo operacional dos cenários A e B)
- REVISOR_OUTPUT_FORMAT.md (obrigatoriedade de estrutura de saída)

### 3) MANUAL GERAL.txt
Destino: referência compartilhada manual_fap
Nome no sistema: MANUAL_REVISAO_FAP.md

### 4) CASOS DE REFERENCIA.txt
Destino: referência compartilhada casos_referencia
Nome no sistema: CASOS_REFERENCIA.md

### 5) INSTRUÇÕES GERAIS DO PROJETO (comportamento global)
Destino: referência compartilhada project_instructions
Nome no sistema: PROJECT_INSTRUCTIONS.md

## Observação Importante

Mesmo mantendo 4 prompts, a granularidade foi aumentada no conteúdo interno:
- identidade separada de regras
- regras separadas de execução por cenário
- execução separada do contrato de saída JSON

Isso preserva compatibilidade e melhora a acurácia do comportamento do agente.
