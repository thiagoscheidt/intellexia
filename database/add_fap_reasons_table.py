"""
Script de migração: Cria tabela fap_reasons

Cria a tabela fap_reasons para gerenciar motivos de contestação FAP
com relacionamento opcional para templates.

Executar com:
    python database/add_fap_reasons_table.py
    python database/add_fap_reasons_table.py --law-firm-id 1
"""

import sys
import os
import argparse

# Adicionar o diretório raiz ao path para importar o módulo app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db
from sqlalchemy import text

def create_fap_reasons_table(law_firm_id=None):
    """Cria tabela fap_reasons e insere motivos padrão para um ou todos os escritórios"""
    
    with app.app_context():
        print("=" * 80)
        print("CADASTRO DE MOTIVOS FAP")
        print("=" * 80)
        
        try:
            print("\nCriando tabela fap_reasons...")
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS fap_reasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    law_firm_id INTEGER NOT NULL,
                    display_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    template_id INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (law_firm_id) REFERENCES law_firms(id) ON DELETE CASCADE,
                    FOREIGN KEY (template_id) REFERENCES case_templates(id) ON DELETE SET NULL
                )
            """))
            db.session.commit()
            
            # Criar índices separadamente (sintaxe SQLite)
            print("Criando índices...")
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fap_reasons_law_firm_id ON fap_reasons(law_firm_id)
            """))
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fap_reasons_template_id ON fap_reasons(template_id)
            """))
            db.session.commit()
            print("✓ Tabela fap_reasons criada com sucesso")
            
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("→ Tabela fap_reasons já existe")
                db.session.rollback()
            else:
                print(f"✗ Erro ao criar tabela: {e}")
                db.session.rollback()
                return
        
        # Limpar dados existentes da tabela se foi especificado um law_firm_id
        if law_firm_id:
            try:
                print("\n🗑️  Limpando dados existentes para este escritório...")
                db.session.execute(
                    text("DELETE FROM fap_reasons WHERE law_firm_id = :law_firm_id"),
                    {'law_firm_id': law_firm_id}
                )
                db.session.commit()
                print("  ✅ Dados anteriores removidos")
            except Exception as clean_error:
                print(f"  ⚠️  Aviso ao limpar: {clean_error}")
                db.session.rollback()
        
        # Definir motivos com template_id
        motivos_padrao = [
            (1, "Benefício Revogado Judicialmente", "Benefício concedido por liminar e posteriormente revogado judicialmente", 9),
            (2, "Duplicidade de Benefício em Restabelecimento", "B91 concedido duas vezes em menos de 60 dias (restabelecimento indevido)", 7),
            (3, "Erro Material na CAT", "CAT com erro material classificando acidente típico em vez de trajeto", 5),
            (4, "CAT de Trajeto Extemporânea", "CAT de trajeto enviada fora do prazo (extemporânea)", 6),
            (5, "Inclusão Indevida de Acidente de Trajeto no FAP", "Inclusão de acidente de trajeto no cálculo do FAP", 4),
            (6, "Acidente Sem Relação com o Trabalho", "Acidente ocorrido sem relação com o trabalho", 3),
            (7, "Acidente Vinculado a Outra Empresa", "Acidente ocorrido quando empregado estava vinculado a outra empresa", 1),
            (8, "Acidente em Outro Estabelecimento", "Acidente ocorrido em outro estabelecimento (outro CNPJ)", 2),
            (9, "Benefício Concomitante com Aposentadoria (B91)", "B91 concedido concomitante com aposentadoria", 10),
            (10, "Bloqueio Indevido do FAP por B92", "Bloqueio do FAP causado por B92 indevido", 8),
            (11, "Benefício Concomitante B91 com B94", "B91 concedido junto com auxílio-acidente (B94)", 11),
            (12, "Duplicidade de Benefício B91", "Dois B91 concedidos ao mesmo tempo", 12),
            (13, "Benefício Concomitante B92 com Aposentadoria", "B92 concedido juntamente com aposentadoria", 13),
            (14, "Benefício Concomitante B94 com Aposentadoria", "B94 concedido juntamente com aposentadoria", 14),
            (15, "Duplicidade de Benefício B94", "Dois B94 concedidos simultaneamente", 15),
            (16, "Benefícios Concomitantes Diversos", "Benefícios concomitantes (B91 + B91 / B91 + B92)", 16),
            (17, "Bloqueio Indevido do FAP por Acidente de Trajeto", "Bloqueio de malus por B92 decorrente de acidente de trajeto", 17),
            (18, "CAT Duplicada", "Duas CATs para o mesmo acidente", 18),
            (19, "Inclusão Indevida de Benefício Previdenciário no FAP", "Inclusão de benefício B31 (previdenciário) no FAP", 19),
            (20, "Conversão para B31 por Decisão do CRPS", "Benefício convertido para B31 por decisão do CRPS", 20),
            (21, "Enquadramento Incorreto de CNAE", "CNAE preponderante incorreta no enquadramento do FAP", 21),
            (22, "Custo Indevido após Óbito", "Custo do B94 calculado após óbito do segurado", 22),
            (23, "Custo Indevido por Expectativa de Vida", "Custo do B94 calculado por expectativa de vida (metodologia ilegal)", 23),
            (24, "Benefício Sem Período de Duração", "Benefício com DIB igual à DCB (sem duração)", 24),
            (25, "Divergência entre Sentença e Implantação", "Benefício judicial implantado diferente do determinado na sentença", 25),
            (26, "Erro na Rotatividade por Crescimento da Empresa", "Inclusão de admissões que representam apenas crescimento da empresa", 26),
            (27, "Benefício Judicial sem Contraditório da Empresa", "Benefício concedido judicialmente sem participação da empresa", 27),
            (28, "Erro na Massa Salarial Declarada", "Massa salarial considerada incorreta (divergente da GFIP)", 28),
            (29, "Erro no Número Médio de Vínculos", "Número médio de vínculos considerado incorretamente", 29),
            (30, "Ausência de Nexo Causal Reconhecida Judicialmente", "Benefício classificado como acidentário sem nexo causal (nexo afastado judicialmente)", 30),
            (31, "NTP Contado em Duplicidade", "NTP contado duas vezes (B91 convertido em B92)", 31),
            (32, "NTP Indevido com CAT Existente", "NTP lançado indevidamente quando já existia CAT", 32),
            (33, "Inclusão de Acidente Pré-FAP", "Inclusão de acidentes ocorridos antes de abril de 2007 (Pré-FAP)", 33),
            (34, "Bloqueio por Alta Rotatividade", "Aplicação da trava de rotatividade (>75%) impedindo bonificação", 34),

        ]
        
        # Inserir motivos
        try:
            print("\nInserindo motivos FAP...")
            
            # Determinar quais escritórios processar
            if law_firm_id:
                # Escritório específico
                from app.models import LawFirm
                law_firm = LawFirm.query.filter_by(id=law_firm_id).first()
                if not law_firm:
                    print(f"❌ ERRO: Escritório com ID {law_firm_id} não encontrado!")
                    return
                law_firms_to_process = [law_firm_id]
                print(f"\n🎯 Processando escritório ID {law_firm_id}: {law_firm.name}")
            else:
                # Todos os escritórios
                law_firms_result = db.session.execute(text("SELECT id FROM law_firms")).fetchall()
                law_firms_to_process = [lf[0] for lf in law_firms_result]
                print(f"\n📋 Processando {len(law_firms_to_process)} escritório(s)")
            
            total_inserted = 0
            
            for target_law_firm_id in law_firms_to_process:
                # Verificar quantos motivos já existem
                existing_count = db.session.execute(
                    text("SELECT COUNT(*) FROM fap_reasons WHERE law_firm_id = :law_firm_id"),
                    {'law_firm_id': target_law_firm_id}
                ).fetchone()[0]
                
                if existing_count > 0:
                    print(f"  ⚠️  Escritório ID {target_law_firm_id}: Já existem {existing_count} motivo(s) cadastrados")
                    continue
                
                # Inserir motivos para este escritório
                inserted_for_firm = 0
                for id_seq, display_name, description, template_id in motivos_padrao:
                    try:
                        # Verificar se template_id existe antes de inserir
                        template_check = db.session.execute(
                            text("SELECT id FROM case_templates WHERE id = :template_id"),
                            {'template_id': template_id}
                        ).fetchone()
                        
                        # Se não encontrar o template, usar NULL
                        final_template_id = template_id if template_check else None
                        
                        db.session.execute(text("""
                            INSERT INTO fap_reasons (law_firm_id, display_name, description, template_id, is_active)
                            VALUES (:law_firm_id, :display_name, :description, :template_id, 1)
                        """), {
                            'law_firm_id': target_law_firm_id,
                            'display_name': display_name,
                            'description': description,
                            'template_id': final_template_id
                        })
                        inserted_for_firm += 1
                    except Exception as insert_error:
                        print(f"    ⚠️  Erro ao inserir motivo '{display_name}': {insert_error}")
                        db.session.rollback()
                        continue
                
                try:
                    db.session.commit()
                    total_inserted += inserted_for_firm
                    print(f"  ✅ Escritório ID {target_law_firm_id}: {inserted_for_firm} motivo(s) inserido(s)")
                except Exception as commit_error:
                    print(f"  ❌ Erro ao confirmar insert para escritório {target_law_firm_id}: {commit_error}")
                    db.session.rollback()
            
            if total_inserted > 0:
                print(f"\n✓ Total de motivos inseridos: {total_inserted}")
            
        except Exception as e:
            print(f"✗ Erro ao inserir motivos: {e}")
            db.session.rollback()
            return
        
        print("\n" + "=" * 80)
        print("✅ PROCESSO CONCLUÍDO COM SUCESSO!")
        print("=" * 80)
        print("\nResumo:")
        print(f"  • Tabela fap_reasons criada/atualizada")
        print(f"  • 34 motivos FAP padrão cadastrados")
        print(f"  • Correlação com templates (template_id 1-34)")
        print("\nPróximos passos:")
        print("  1. Acesse 'Casos > Motivos FAP' para gerenciar os motivos")
        print("  2. Atualize os benefícios para usar os novos motivos")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Cadastra motivos FAP no banco de dados',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  # Processar todos os escritórios
  python database/add_fap_reasons_table.py
  
  # Processar apenas o escritório com ID 1
  python database/add_fap_reasons_table.py --law-firm-id 1
  
  # Usando uv
  uv run database/add_fap_reasons_table.py --law-firm-id 1
        """
    )
    
    parser.add_argument(
        '--law-firm-id',
        type=int,
        dest='law_firm_id',
        default=None,
        help='ID do escritório a processar (opcional). Se omitido, processa todos os escritórios.'
    )
    
    args = parser.parse_args()
    create_fap_reasons_table(law_firm_id=args.law_firm_id)
