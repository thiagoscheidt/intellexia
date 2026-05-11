# Mapeamento dos Arquivos do Cliente para o FAP Review

Este documento define como os conteúdos fornecidos pelo cliente devem ser distribuídos na configuração atual do agente revisor.

## Decisão de Estrutura

Manter 3 arquivos de prompt do revisor:
- REVISOR_IDENTITY.md
- REVISOR_RULES.md
- REVISOR_OUTPUT_FORMAT.md

Motivo:
- A revisão operacional foi consolidada diretamente no código do agente.
- O painel mantém apenas identidade, regras e formato de saída como pontos configuráveis.
- Reduz ambiguidade entre instrução fixa do sistema e prompts editáveis.

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

Mesmo mantendo 3 prompts, a granularidade foi preservada entre identidade, regras e contrato de saída:
- identidade separada de regras
- regras separadas do contrato de saída JSON

O fluxo de execução por cenário fica embutido no código do agente, preservando previsibilidade operacional.
