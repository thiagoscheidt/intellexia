#!/usr/bin/env python3
"""
Migration: Atualizar temperatura padrão do revisor para determinismo

Objetivo: Mudar reviewer_temperature de 0.2 para 0.0 em todas as FapReviewSetting
para garantir respostas determinísticas do revisor FAP com seed=42.

Problema: Com temperature=0.2, o LLM pode produzir achados diferentes a cada execução
mesmo com o mesmo documento e prompts. Com temperature=0.0 + seed, garante 100% determinismo.

Execução:
    uv run python database/update_reviewer_temperature_to_deterministic.py

O script é idempotente e seguro - pode ser executado múltiplas vezes.
"""

from main import app
from app.models import FapReviewSetting, db
from datetime import datetime

def migrate():
    """Atualiza reviewer_temperature para 0.0"""
    with app.app_context():
        # Contar registros com temperature != 0.0
        old_count = FapReviewSetting.query.filter(
            FapReviewSetting.reviewer_temperature != 0.0
        ).count()
        
        if old_count == 0:
            print("✅ Já estão atualizados - nenhuma mudança necessária")
            return
        
        print(f"📋 Atualizando {old_count} registro(s)...")
        
        # Atualizar
        FapReviewSetting.query.filter(
            FapReviewSetting.reviewer_temperature != 0.0
        ).update(
            {FapReviewSetting.reviewer_temperature: 0.0},
            synchronize_session='fetch'
        )
        
        db.session.commit()
        
        print(f"✅ {old_count} registro(s) atualizado(s) para temperature=0.0")
        print(f"   Timestamp: {datetime.now().isoformat()}")
        print("\n💡 Próximas execuções do revisor usarão:")
        print("   - temperature=0.0 (determinístico)")
        print("   - seed=42 (OpenAI garante mesma resposta)")
        print("   - Achados serão 100% consistentes entre runs")

if __name__ == "__main__":
    try:
        migrate()
        print("\n✅ Migração completada com sucesso!")
    except Exception as e:
        print(f"\n❌ Erro durante migração: {e}")
        raise
