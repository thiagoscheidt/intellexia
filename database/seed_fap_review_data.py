"""
Migration: Seed inicial de prompts e referências para FAP Review
Data: 2026-05-09
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, db
from app.models import FapReviewPromptVersion, FapReviewReferenceVersion, LawFirm, User
from datetime import datetime


DEFAULT_PROMPTS = {
    'revisor_identity': """Você é um especialista jurídico em Direito Previdenciário e Acidentário,
focado em revisar petições iniciais de Ação Revisional do FAP (Fator Acidentário de Prevenção).

Sua missão: Identificar inconsistências, erros jurídicos e desvios em relação ao padrão esperado.
Você NÃO atualiza manualmente nenhum documento oficial - apenas identifica padrões e encaminha 
ao Agente de Treinamento.""",

    'revisor_rules': """1. APLIQUE RIGOR JURÍDICO: Toda conclusão deve ser fundamentada em lei
2. SIGA O MANUAL: Use manual, jurisprudência e casos de referência
3. IDENTIFIQUE RISCOS: Destaque exposições legais e procedimentais
4. NÃO ATUALIZE: Apenas identifique - não modifique documentos
5. ESTRUTURE: Use categorias claras (CRÍTICO, MODERADO, FORMAL)
6. DOCUMENTE: Cite manual e jurisprudência em cada achado
7. SEJA JUSTO: Reconheça boas práticas, não apenas erros""",

    'revisor_prompt': """Revise esta petição inicial de FAP verificando:
1. Enquadramento correto do benefício
2. Documentação obrigatória
3. Fundamentação jurídica
4. Conformidade com jurisprudência
5. Desvios do manual de procedimentos
6. Riscos processuais identificáveis

Estruture a resposta em JSON com as chaves:
- theses (array de teses identificadas)
- findings (array de achados com severity)
- missing_documents (documentos obrigatórios faltantes)
- executive_summary (resumo com risk_level)
- new_patterns (padrões não cobertos pelo manual)""",

    'revisor_output_format': """Retorne um JSON estruturado com:
{
  "theses": [{"thesis": "...", "benefit_number": "B91", "classification": "..."}],
  "findings": [{"severity": "CRÍTICO|MODERADO|FORMAL", "description": "...", "correction": "..."}],
  "missing_documents": [{"document_type": "...", "thesis": "..."}],
  "executive_summary": {"total_findings": N, "critical_findings": N, "correction_priority": "..."},
  "new_patterns": [{"pattern": "...", "suggested_update": "..."}]
}""",

    'training_identity': """Você é um agente de aprendizado contínuo especializado em FAP.
Sua função: Processar achados do Revisor, consolidar padrões, e manter atualizado o manual
de referência e banco de casos.""",

    'training_rules': """1. CONSOLIDAR: Agrupe padrões similares de múltiplas revisões
2. VERSIONAR: Crie versões incrementais do manual
3. REFERENCIAR: Cite casos que validam novas orientações
4. APROVAR: Requer aprovação antes de publicar mudanças
5. RETROCEDER: Permita rollback para versões anteriores
6. APRENDER: Use feedback para evoluir continuamente""",

    'training_prompt': """Processe estes achados do revisor e:
1. Identifique padrões recorrentes
2. Consolide em orientações claras
3. Proponha atualizações do manual
4. Crie novos casos de referência
5. Gere resumo de aprendizados

Retorne estrutura JSON com propostas de atualização.""",

    'training_update_policy': """Política de atualização:
- Auto: Se habilitado, publica automaticamente
- Aprovação: Requer aprovação de supervisor
- Versionamento: Incremento semântico (patch/minor/major)
- Rollback: Disponível por 30 dias após publicação
- Auditoria: Todos os eventos registrados com user_id"""
}


DEFAULT_REFERENCES = {
    'manual_fap': """# MANUAL DE REVISÃO - FAP (Ação Revisional)

## Seção 1: Enquadramentos de Benefício

### B91 - Auxílio-Acidente Acidentário
- Conceito: Indenização mensal devida ao segurado que, após sofrer acidente de trabalho, fica com sequela permanente
- Percentual: De 15% a 100% do salário benefício
- Requisitos:
  1. Filiação à Previdência Social
  2. Sofrer acidente de trabalho
  3. Sofrer sequela que reduza capacidade de trabalho
  4. Contribuição mínima (12 meses de filiação)

### B94 - Auxílio-Doença Acidentário  
- Conceito: Renda mensal temporária para segurado incapaz de trabalhar por mais de 15 dias
- Duração: Até 120 dias (depois vira aposentadoria por invalidez)
- Requisitos:
  1. Acidente de trabalho comprovado
  2. Incapacidade temporária
  3. Contribuição mínima

## Seção 2: Documentação Obrigatória

- Petição Inicial devidamente assinada
- Procuração (se houver representante)
- Identidade e CPF do autor
- Comprovante de residência
- CAT (Comunicação de Acidente de Trabalho)
- Laudos médicos e periciais
- Documentação previdenciária (CNIS)
- Contracheques e documentação laboral

## Seção 3: Jurisprudência Consolidada

### TJ: Responsabilidade Empresarial em FAP
- Súmula #1: Empresa responsável por danos a empregado em acidente
- Precedente STF: Devem ser indenizados todos danos morais e materiais
- Jurisprudência pacífica: FAP não afasta responsabilidade civil

### TST: Procedimentos Especiais FAP
- Orientação: Ações devem ser autuadas como revisional (classe 1)
- Prazo: 30 anos de prescrição para ações acidentárias
- Competência: Vara do Trabalho do domicílio do autor

## Seção 4: Padrões Comuns de Erro

- Falta de CAT no processo
- Incompletude de laudos médicos
- Desconexão entre DAT (Documento de Acidente de Trabalho) e lesão
- Perícia inadequada sem quesitos específicos
- Falta de demonstração de causalidade

## Seção 5: Checklist de Revisão

- [ ] Petição adequadamente formalizada
- [ ] Procuração válida (se houver)
- [ ] Documentação pessoal do autor
- [ ] CAT com todas as informações
- [ ] Laudos médicos recentes (< 6 meses)
- [ ] Prova de filiação à Previdência
- [ ] Comprovação de nexo causal
- [ ] Pedidos claros e específicos
"""[: 2000],

    'casos_referencia': """# CASOS DE REFERÊNCIA - FAP

## Caso #001: Acidente com Sequela Permanente - B91

**Data:** 2024-03-15  
**Resultado:** Procedente com indenização de 40% do salário benefício  
**Pontos-Chave:**
- CAT preenchida corretamente
- Laudo médico com sequela permanente documentada
- Comprovação adequada de nexo causal
- Documentação previdenciária completa

**Aprendizado:** Documentação precisa é fundamental para sucesso processual.

---

## Caso #002: Negativa de Benefício - Insuficiência de Prova

**Data:** 2024-02-10  
**Resultado:** Improcedente - Insuficiência de prova de nexo causal  
**Pontos-Chave:**
- CAT incompleta
- Laudo médico genérico sem especificidade
- Falta de relatório técnico
- Sem testemunhas

**Aprendizado:** Nexo causal deve ser provado com documentação técnica robusta.

---

## Caso #003: Indenização por Acidente em Home Office - Jurisprudência Nova

**Data:** 2024-01-20  
**Resultado:** Procedente - Reconhecimento de acidente em ambiente doméstico  
**Pontos-Chave:**
- Acidente durante jornada de trabalho remota
- Comprovação de vínculo empregatício
- CAT registrada mesmo em home office
- Jurisprudência mais recente reconhece

**Aprendizado:** Modernização: acidentes em home office são reconhecidos se durante jornada.

---

## Caso #004: Seguro de Acidente - Cobertura Complementar

**Data:** 2023-12-05  
**Resultado:** Dupla condenação (INSS + Seguradora)  
**Pontos-Chave:**
- Existência de apólice de seguro
- INSS não exonera responsabilidade de seguradora
- Cumulatividade reconhecida em jurisprudência

**Aprendizado:** Quando há seguro, ambas as entidades são condenadas solidariamente.
"""[: 1500],

    'project_instructions': """# INSTRUÇÕES DO PROJETO FAP REVIEW

## Objetivo Geral
Automatizar revisão jurídica de petições iniciais de FAP com garantia de qualidade 
através de dupla análise (Revisor + Treinamento).

## Fluxo de Trabalho

1. **Upload** → Usuário envia petição (PDF/Word)
2. **Extração** → Sistema extrai texto do documento
3. **Revisão** → Agente Revisor analisa contra manual
4. **Resultado** → Resultado estruturado em JSON
5. **Treinamento** → Agente Treinamento consolida padrões
6. **Evolução** → Manual é atualizado com novos aprendizados

## Qualidade Esperada

- Cobertura de 95%+ de inconsistências
- Falsos positivos < 5%
- Tempo de análise < 5 minutos
- Estrutura JSON sempre válida

## Escalabilidade

- Suporte a múltiplos escritórios (multi-tenant)
- Fila de processamento para picos
- Cache de referências para performance
- Métricas de uso por escritório

## Segurança

- Isolamento total entre writings (law_firm_id)
- Auditoria de todas as ações
- Permissões baseadas em role
- Backup automático de referências
"""[: 1000]
}


def seed_initial_data():
    """Cria dados iniciais de prompts e referências"""
    with app.app_context():
        print("\n" + "="*80)
        print("📝 CRIANDO SEEDS INICIAIS DE PROMPTS E REFERÊNCIAS")
        print("="*80)
        
        try:
            # Obter primeiro escritório
            law_firm = LawFirm.query.first()
            if not law_firm:
                print("❌ Nenhum escritório encontrado. Crie um primeiro.")
                return False
            
            # Obter primeiro usuário admin
            user = User.query.filter_by(role='admin').first()
            if not user:
                print("❌ Nenhum usuário admin encontrado.")
                return False
            
            print(f"\n✅ Usando Escritório: {law_firm.name}")
            print(f"✅ Usando Usuário: {user.name}")
            
            # Criar prompts iniciais
            print("\n📌 Criando PROMPTS...")
            for prompt_type, content in DEFAULT_PROMPTS.items():
                # Verificar se já existe
                existing = FapReviewPromptVersion.query.filter_by(
                    law_firm_id=law_firm.id,
                    prompt_type=prompt_type,
                    is_active=True
                ).first()
                
                if not existing:
                    prompt = FapReviewPromptVersion(
                        law_firm_id=law_firm.id,
                        version_number=1,
                        prompt_type=prompt_type,
                        content=content,
                        is_active=True,
                        created_by_id=user.id
                    )
                    db.session.add(prompt)
                    print(f"   ✅ {prompt_type} v1 criado")
                else:
                    print(f"   ⏭️  {prompt_type} já existe - pulando")
            
            db.session.commit()
            
            # Criar referências iniciais
            print("\n📌 Criando REFERÊNCIAS...")
            for ref_type, content in DEFAULT_REFERENCES.items():
                # Verificar se já existe
                existing = FapReviewReferenceVersion.query.filter_by(
                    law_firm_id=law_firm.id,
                    reference_type=ref_type,
                    is_active=True
                ).first()
                
                if not existing:
                    reference = FapReviewReferenceVersion(
                        law_firm_id=law_firm.id,
                        version_number=1,
                        reference_type=ref_type,
                        content=content,
                        is_active=True,
                        created_by_id=user.id
                    )
                    db.session.add(reference)
                    print(f"   ✅ {ref_type} v1 criado")
                else:
                    print(f"   ⏭️  {ref_type} já existe - pulando")
            
            db.session.commit()
            
            print("\n" + "="*80)
            print("✅ SEEDS CRIADAS COM SUCESSO")
            print("="*80)
            return True
            
        except Exception as e:
            print(f"❌ Erro: {e}")
            db.session.rollback()
            return False


if __name__ == '__main__':
    seed_initial_data()
