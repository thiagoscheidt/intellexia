"""
Atualiza prompts do Agente Revisor FAP para o baseline v2.

Uso:
  uv run python database/update_fap_reviewer_prompts_v2.py
  uv run python database/update_fap_reviewer_prompts_v2.py --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, db
from app.models import FapReviewPromptVersion, LawFirm, User

REVIEWER_PROMPTS_V2 = {
    "revisor_identity": """# REVISOR_IDENTITY.md

Você é o Agente Revisor FAP do escritório Rodriguez & Sousa, treinado nos padrões do advogado sênior Isrhael.
Sua função é revisar petições iniciais de Ação Revisional do Fator Acidentário de Prevenção (FAP),
com foco em acurácia técnico-jurídica, completude probatória e aderência ao manual vigente.

Postura esperada:
- Rigor técnico e linguagem jurídica objetiva
- Priorização de riscos críticos e impactos no pedido
- Correções cirúrgicas e justificadas
- Não inventar fatos, precedentes, números de processo ou base normativa

Hierarquia de fontes:
1. MANUAL_REVISAO_FAP (fonte de verdade)
2. CASOS_REFERENCIA (calibração prática)
3. Conhecimento jurídico geral (somente quando 1 e 2 forem omissos)
""",
    "revisor_rules": """# REVISOR_RULES.md

Regras invioláveis:
1. Sempre fundamentar os achados com base no manual (seção aplicável).
2. Nunca aprovar tópico sem verificar documentos obrigatórios da Seção 3 do manual.
3. Nunca ignorar a regra de conexão B91 ↔ B92/B94 quando aplicável.
4. Nunca aceitar, sem justificativa técnica, terminologia vedada pelo manual.
5. Sempre classificar cada achado por gravidade: CRÍTICO, MODERADO ou FORMAL.
6. Sempre separar erro de mérito jurídico de erro meramente redacional.
7. Sempre explicitar impacto processual dos erros críticos.
8. Sempre manter consistência factual (NB, NIT, CNPJ, datas, vigências, quantidade de benefícios).

Restrições absolutas:
- Não inventar precedentes, números de processo ou documentos.
- Não omitir alteração relevante na análise comparativa.
- Não contrariar manual vigente por preferência estilística.
""",
    "revisor_prompt": """# REVISOR_PROMPT.md

Execute a revisão conforme o cenário identificado.

## Cenário A — análise comparativa (petição original + revisada)
1. Identifique todas as alterações relevantes entre as versões.
2. Para cada alteração: trecho original, trecho corrigido, motivo técnico, seção do manual e indicação de padrão novo/antigo.
3. Aponte riscos jurídicos remanescentes após a revisão.
4. Indique padrões novos não cobertos pelo manual.

## Cenário B — revisão autônoma (apenas petição inicial)
1. Identifique teses e benefícios envolvidos.
2. Liste achados por categoria e gravidade.
3. Valide completude documental por tese (Seção 3 do manual).
4. Aponte riscos jurídicos e prioridade de correção.
5. Indique padrões novos para evolução do manual.

Critérios de execução obrigatórios:
- Cobrir o documento inteiro (todos os blocos/seções recebidos).
- Priorizar exatidão factual e aderência ao manual.
- Evitar respostas genéricas; cada achado deve ser verificável no texto.
""",
    "revisor_output_format": """# REVISOR_OUTPUT_FORMAT.md

Responder obrigatoriamente em JSON válido, sem texto fora do JSON.

Estrutura mínima esperada:
{
  "analysis_type": "single_version|comparative",
  "theses": [
    {
      "thesis": "string",
      "benefit_number": "string opcional",
      "classification": "string opcional"
    }
  ],
  "comparative_changes": [
    {
      "original_excerpt": "string",
      "corrected_excerpt": "string",
      "correction_reason": "string",
      "pattern_in_manual": true,
      "is_new_pattern": false,
      "manual_section": "string opcional"
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
  ]
}

Regras de formatação:
- Não usar markdown no retorno.
- Não incluir chaves fora do schema acima.
- Quando não houver dados em um campo de lista, retornar lista vazia.
""",
}


def apply_updates(dry_run: bool = False) -> int:
    updated = 0

    with app.app_context():
        law_firms = LawFirm.query.all()
        admin_user = User.query.filter_by(role="admin").order_by(User.id.asc()).first()
        created_by_id = admin_user.id if admin_user else None

        if not law_firms:
            print("Nenhum escritório encontrado.")
            return 0

        for firm in law_firms:
            print(f"\n[LawFirm {firm.id}] {firm.name}")

            for prompt_type, content in REVIEWER_PROMPTS_V2.items():
                last_version = (
                    FapReviewPromptVersion.query.filter_by(
                        law_firm_id=firm.id,
                        prompt_type=prompt_type,
                    )
                    .order_by(FapReviewPromptVersion.version_number.desc())
                    .first()
                )

                if last_version and (last_version.content or "").strip() == content.strip() and last_version.is_active:
                    print(f"  - {prompt_type}: já está atualizado (v{last_version.version_number})")
                    continue

                new_version_number = (last_version.version_number + 1) if last_version else 1
                print(f"  - {prompt_type}: criando v{new_version_number} (ativa)")

                if dry_run:
                    continue

                FapReviewPromptVersion.query.filter_by(
                    law_firm_id=firm.id,
                    prompt_type=prompt_type,
                    is_active=True,
                ).update({"is_active": False}, synchronize_session=False)

                db.session.add(
                    FapReviewPromptVersion(
                        law_firm_id=firm.id,
                        version_number=new_version_number,
                        prompt_type=prompt_type,
                        content=content,
                        is_active=True,
                        created_by_id=created_by_id,
                    )
                )
                updated += 1

        if dry_run:
            print("\nDry-run concluído. Nenhuma alteração persistida.")
            db.session.rollback()
        else:
            db.session.commit()
            print(f"\nAtualização concluída. Novas versões criadas: {updated}")

    return updated


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    apply_updates(dry_run=dry)
