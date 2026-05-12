#!/usr/bin/env python3
"""
Script de diagnóstico: Compara duas execuções do revisor FAP para entender
por que achados desapareceram entre execuções.

Uso:
  uv run python scripts/diagnose_reviewer_inconsistency.py <execution_id_1> <execution_id_2>
"""

import json
import sys
from datetime import datetime
from app.models import (
    FapReviewExecution, 
    FapReviewPromptVersion, 
    FapReviewReferenceVersion,
    AgentExecutionHistory,
    AgentTokenUsage
)
from main import app

def format_diff(val1, val2, label: str):
    """Formata diferença entre dois valores"""
    if val1 == val2:
        print(f"  ✅ {label}: IDÊNTICO")
        return
    print(f"  ⚠️  {label}: DIFERENTE")
    print(f"      Execução 1: {val1}")
    print(f"      Execução 2: {val2}")

def diagnose_executions(exec_id_1: int, exec_id_2: int):
    """Analisa duas execuções e compara contexto"""
    
    with app.app_context():
        print("\n" + "="*70)
        print("DIAGNÓSTICO: Inconsistência de Achados no Revisor FAP")
        print("="*70)
        
        exec1 = FapReviewExecution.query.get(exec_id_1)
        exec2 = FapReviewExecution.query.get(exec_id_2)
        
        if not exec1:
            print(f"❌ Execução {exec_id_1} não encontrada")
            return
        if not exec2:
            print(f"❌ Execução {exec_id_2} não encontrada")
            return
        
        print(f"\n📋 EXECUÇÃO 1 (ID: {exec_id_1})")
        print(f"   Data: {exec1.created_at}")
        print(f"   Status: {exec1.status}")
        print(f"   Documento: {exec1.petition_file_name}")
        print(f"   Modo: {exec1.analysis_type}")
        
        print(f"\n📋 EXECUÇÃO 2 (ID: {exec_id_2})")
        print(f"   Data: {exec2.created_at}")
        print(f"   Status: {exec2.status}")
        print(f"   Documento: {exec2.petition_file_name}")
        print(f"   Modo: {exec2.analysis_type}")
        
        # ===== COMPARAR CONTEXTO DE EXECUÇÃO
        print(f"\n🔍 CONTEXTO DE EXECUÇÃO:")
        format_diff(
            exec1.petition_file_name, 
            exec2.petition_file_name,
            "Arquivo de petição"
        )
        format_diff(
            exec1.analysis_type,
            exec2.analysis_type,
            "Tipo de análise"
        )
        format_diff(
            len(exec1.auxiliary_documents_json or "[]"),
            len(exec2.auxiliary_documents_json or "[]"),
            "Quantidade docs auxiliares"
        )
        
        # ===== COMPARAR VERSÕES DE REFERÊNCIA
        print(f"\n📚 VERSÕES DE REFERÊNCIA:")
        ref1 = FapReviewReferenceVersion.query.get(exec1.reference_version_id) if exec1.reference_version_id else None
        ref2 = FapReviewReferenceVersion.query.get(exec2.reference_version_id) if exec2.reference_version_id else None
        
        if ref1 and ref2:
            format_diff(
                ref1.id,
                ref2.id,
                "Reference Version ID"
            )
            format_diff(
                ref1.manual_content_hash[:16] + "...",
                ref2.manual_content_hash[:16] + "...",
                "Manual Hash"
            )
            format_diff(
                ref1.cases_content_hash[:16] + "...",
                ref2.cases_content_hash[:16] + "...",
                "Cases Hash"
            )
        
        # ===== COMPARAR VERSÕES DE PROMPT
        print(f"\n⚙️  VERSÕES DE PROMPT:")
        pv1 = FapReviewPromptVersion.query.get(exec1.prompt_version_id) if exec1.prompt_version_id else None
        pv2 = FapReviewPromptVersion.query.get(exec2.prompt_version_id) if exec2.prompt_version_id else None
        
        if pv1 and pv2:
            format_diff(
                pv1.id,
                pv2.id,
                "Prompt Version ID"
            )
            format_diff(
                pv1.reviewer_identity_hash[:16] + "...",
                pv2.reviewer_identity_hash[:16] + "...",
                "Identity Hash"
            )
            format_diff(
                pv1.reviewer_rules_hash[:16] + "...",
                pv2.reviewer_rules_hash[:16] + "...",
                "Rules Hash"
            )
        
        # ===== COMPARAR TOKENS/CUSTO
        print(f"\n💰 TOKENS E CUSTO:")
        print(f"   Execução 1:")
        print(f"      Tokens: {exec1.tokens_used or 'N/A'}")
        print(f"      Custo: ${exec1.execution_cost_usd or 0:.4f}")
        print(f"   Execução 2:")
        print(f"      Tokens: {exec2.tokens_used or 'N/A'}")
        print(f"      Custo: ${exec2.execution_cost_usd or 0:.4f}")
        
        if exec1.tokens_used and exec2.tokens_used:
            diff = exec2.tokens_used - exec1.tokens_used
            print(f"      Diferença: {diff:+d} tokens")
            if abs(diff) > 500:
                print(f"      ⚠️  DIFERENÇA SIGNIFICATIVA DE TOKENS!")
        
        # ===== COMPARAR ACHADOS
        print(f"\n🎯 ACHADOS IDENTIFICADOS:")
        findings1 = json.loads(exec1.findings_json or "[]")
        findings2 = json.loads(exec2.findings_json or "[]")
        
        print(f"   Execução 1: {len(findings1)} achados")
        for i, finding in enumerate(findings1[:3], 1):
            sev = finding.get('severity', 'N/A')
            desc = finding.get('description', '')[:60]
            print(f"      {i}. [{sev}] {desc}...")
        if len(findings1) > 3:
            print(f"      ... +{len(findings1) - 3} mais")
        
        print(f"\n   Execução 2: {len(findings2)} achados")
        for i, finding in enumerate(findings2[:3], 1):
            sev = finding.get('severity', 'N/A')
            desc = finding.get('description', '')[:60]
            print(f"      {i}. [{sev}] {desc}...")
        if len(findings2) > 3:
            print(f"      ... +{len(findings2) - 3} mais")
        
        # ===== ENCONTRAR ACHADO FALTANTE
        print(f"\n🔎 ACHADOS QUE DESAPARECERAM:")
        finding_sigs_1 = {f['description'][:40] for f in findings1}
        finding_sigs_2 = {f['description'][:40] for f in findings2}
        missing = finding_sigs_1 - finding_sigs_2
        
        if missing:
            print(f"   ⚠️  {len(missing)} achado(s) presente(s) na execução 1 MAS NÃO na 2:")
            for desc in missing:
                print(f"      - {desc}...")
        else:
            print(f"   ✅ Todos os achados da execução 1 estão na 2")
        
        # ===== SUGESTÕES
        print(f"\n💡 POSSÍVEIS CAUSAS E RECOMENDAÇÕES:")
        print(f"\n   1. NON-DETERMINISMO DO LLM:")
        print(f"      Temperature atual: 0.2 (baixo mas NÃO determinístico)")
        print(f"      → Considerar usar temperature=0.0 ou seed do OpenAI")
        
        if ref1 != ref2:
            print(f"\n   2. ⚠️  VERSÃO DE REFERÊNCIA MUDOU!")
            print(f"      → Manual ou Casos foram atualizados entre execuções")
            print(f"      → Revisor usou contexto de referência diferente")
        
        if pv1 != pv2:
            print(f"\n   3. ⚠️  VERSÃO DE PROMPT MUDOU!")
            print(f"      → Prompts do revisor foram alterados")
            print(f"      → Sistema de instruções evoluiu entre execuções")
        
        if exec1.tokens_used and exec2.tokens_used:
            diff = abs(exec2.tokens_used - exec1.tokens_used)
            if diff > 500:
                print(f"\n   4. ⚠️  TRUNCATION POR TOKENS!")
                print(f"      → Diferença: {diff} tokens")
                print(f"      → Segunda execução pode ter truncado contexto")
                print(f"      → Página 14 pode ter ficado fora do window")
        
        print(f"\n" + "="*70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: uv run python scripts/diagnose_reviewer_inconsistency.py <execution_id_1> <execution_id_2>")
        print("\nExemplo:")
        print("  uv run python scripts/diagnose_reviewer_inconsistency.py 123 456")
        sys.exit(1)
    
    try:
        exec_id_1 = int(sys.argv[1])
        exec_id_2 = int(sys.argv[2])
        diagnose_executions(exec_id_1, exec_id_2)
    except ValueError:
        print("❌ IDs de execução devem ser números inteiros")
        sys.exit(1)
