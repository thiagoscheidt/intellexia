"""
Script para cadastrar os templates padrão de casos FAP no banco de dados.
Este script copia os arquivos da pasta templates_padrao e cria os registros no banco.

Para executar:
    python database/populate_case_templates.py
"""

import sys
from pathlib import Path
import shutil
from datetime import datetime

# Adicionar o diretório raiz ao path do Python
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, CaseTemplate, User, LawFirm
from main import app


# Mapeamento dos templates com seus dados
TEMPLATES_DATA = [
    {
        "id": 1,
        "nome_arquivo": "Peticao Inicial.docx",
        "resumo_curto": "Peça principal da ação judicial para revisão do FAP e restituição/compensação de valores pagos a maior.",
        "categoria": "Documento principal"
    },
    {
        "id": 2,
        "nome_arquivo": "Acidente Ocorrido em outra Empresa.docx",
        "resumo_curto": "Benefício atribuído a empresa diferente da real empregadora do segurado.",
        "categoria": "Erro de vínculo empregatício"
    },
    {
        "id": 3,
        "nome_arquivo": "Acidente Ocorrido em outro Estabelecimento.docx",
        "resumo_curto": "Acidente imputado ao CNPJ errado (filial diversa).",
        "categoria": "Erro de estabelecimento"
    },
    {
        "id": 4,
        "nome_arquivo": "Acidente nao Relacionado ao Trabalho.docx",
        "resumo_curto": "Evento sem nexo com o trabalho foi classificado como acidentário.",
        "categoria": "Erro de nexo causal"
    },
    {
        "id": 5,
        "nome_arquivo": "Acidente de Trajeto.docx",
        "resumo_curto": "Acidente de trajeto incluído indevidamente no FAP.",
        "categoria": "Acidente de trajeto"
    },
    {
        "id": 6,
        "nome_arquivo": "Acidente de Trajeto - CAT Erro material.docx",
        "resumo_curto": "CAT preenchida incorretamente como típica quando era de trajeto.",
        "categoria": "Acidente de trajeto / erro material"
    },
    {
        "id": 7,
        "nome_arquivo": "Acidente de Trajeto - CAT Extemporanea.docx",
        "resumo_curto": "CAT registrada fora do prazo e incluída indevidamente no FAP.",
        "categoria": "Acidente de trajeto / CAT fora do prazo"
    },
    {
        "id": 8,
        "nome_arquivo": "60 Dias - B91.docx",
        "resumo_curto": "Benefícios concedidos com intervalo inferior a 60 dias deveriam ser restabelecimento.",
        "categoria": "Duplicidade de benefício"
    },
    {
        "id": 9,
        "nome_arquivo": "Exclusão dos bloqueios causados pelo B92.docx",
        "resumo_curto": "Aposentadoria por invalidez bloqueou bonificação indevidamente.",
        "categoria": "Bloqueio indevido do FAP"
    },
    {
        "id": 10,
        "nome_arquivo": "Revogação da antecipação dos efeitos da tutela.docx",
        "resumo_curto": "Benefício judicial cancelado permaneceu no FAP.",
        "categoria": "Benefício judicial cancelado"
    },
    {
        "id": 11,
        "nome_arquivo": "B91 com aposentadoria - REVISADA.docx",
        "resumo_curto": "B91 concedido junto com aposentadoria.",
        "categoria": "Benefício concomitante"
    },
    {
        "id": 12,
        "nome_arquivo": "B91 com auxílio-acidente - REVISADA.docx",
        "resumo_curto": "B91 concedido simultaneamente ao B94.",
        "categoria": "Benefício concomitante"
    },
    {
        "id": 13,
        "nome_arquivo": "B91 com auxílio-doença - REVISADA.docx",
        "resumo_curto": "Dois B91 no mesmo período.",
        "categoria": "Duplicidade de benefício"
    },
    {
        "id": 14,
        "nome_arquivo": "B92 com aposentadoria - REVISADA.docx",
        "resumo_curto": "B92 concedido simultaneamente com aposentadoria.",
        "categoria": "Benefício concomitante"
    },
    {
        "id": 15,
        "nome_arquivo": "B94 com aposentadoria - REVISADA.docx",
        "resumo_curto": "Auxílio-acidente concedido junto com aposentadoria.",
        "categoria": "Benefício concomitante"
    },
    {
        "id": 16,
        "nome_arquivo": "B94 com auxílio-acidente - REVISADA.docx",
        "resumo_curto": "Dois auxílios-acidente concedidos.",
        "categoria": "Duplicidade de benefício"
    },
    {
        "id": 17,
        "nome_arquivo": "Beneficio Concomitante.docx",
        "resumo_curto": "Documento geral sobre acumulação ilegal de benefícios.",
        "categoria": "Benefícios concomitantes"
    },
    {
        "id": 18,
        "nome_arquivo": "Bloqueio de malus – B92 – B91 – Acidente de trajeto.docx",
        "resumo_curto": "Bloqueio indevido do FAP por acidente de trajeto.",
        "categoria": "Bloqueio indevido do FAP"
    },
    {
        "id": 19,
        "nome_arquivo": "CAT Duplicada.docx",
        "resumo_curto": "Duas CATs para o mesmo evento.",
        "categoria": "Duplicidade administrativa"
    },
    {
        "id": 20,
        "nome_arquivo": "Convertido B31.docx",
        "resumo_curto": "Benefício previdenciário incluído indevidamente.",
        "categoria": "Inclusão indevida"
    },
    {
        "id": 21,
        "nome_arquivo": "Convertido para B31 – Acordao do CRPS.docx",
        "resumo_curto": "Benefício convertido para previdenciário e mantido no FAP.",
        "categoria": "Inclusão indevida"
    },
    {
        "id": 22,
        "nome_arquivo": "Correcao da CNAE Preponderante.docx",
        "resumo_curto": "CNAE preponderante incorreta.",
        "categoria": "Erro de CNAE"
    },
    {
        "id": 23,
        "nome_arquivo": "Custo B94 - Beneficio Cessado por Obito.docx",
        "resumo_curto": "Custo calculado como vitalício apesar do óbito.",
        "categoria": "Erro no índice de custo"
    },
    {
        "id": 24,
        "nome_arquivo": "Custo B94 Generico.docx",
        "resumo_curto": "Metodologia incorreta de cálculo do custo.",
        "categoria": "Erro metodológico"
    },
    {
        "id": 25,
        "nome_arquivo": "DIB=DCB.docx",
        "resumo_curto": "Benefício com início e fim na mesma data.",
        "categoria": "Erro cadastral"
    },
    {
        "id": 26,
        "nome_arquivo": "Divergencia entre o beneficio concedido e o implementado pelo INSS.docx",
        "resumo_curto": "INSS implantou benefício diferente do judicial.",
        "categoria": "Erro judicial"
    },
    {
        "id": 27,
        "nome_arquivo": "Exclusao das admissoes que representarem crescimento da empresa.docx",
        "resumo_curto": "Admissões de crescimento incluídas na rotatividade.",
        "categoria": "Erro na rotatividade"
    },
    {
        "id": 28,
        "nome_arquivo": "Judicial.docx",
        "resumo_curto": "Benefícios judiciais sem contraditório incluídos no FAP.",
        "categoria": "Benefício judicial"
    },
    {
        "id": 29,
        "nome_arquivo": "Massa Salarial.docx",
        "resumo_curto": "Massa salarial incorreta.",
        "categoria": "Erro na massa salarial"
    },
    {
        "id": 30,
        "nome_arquivo": "Media de Vinculos.docx",
        "resumo_curto": "Número médio de vínculos incorreto.",
        "categoria": "Erro no número de vínculos"
    },
    {
        "id": 31,
        "nome_arquivo": "Nexo afastado.docx",
        "resumo_curto": "Nexo causal afastado judicialmente.",
        "categoria": "Nexo técnico afastado"
    },
    {
        "id": 32,
        "nome_arquivo": "NTP Duplicado.docx",
        "resumo_curto": "CAT e NTP lançados para o mesmo evento.",
        "categoria": "Duplicidade de nexo"
    },
    {
        "id": 33,
        "nome_arquivo": "NTP Indevido.docx",
        "resumo_curto": "Nexo atribuído sem relação com o trabalho.",
        "categoria": "Nexo indevido"
    },
    {
        "id": 34,
        "nome_arquivo": "Pre-FAP.docx",
        "resumo_curto": "Eventos anteriores a abril/2007 incluídos.",
        "categoria": "Evento fora do período legal"
    },
    {
        "id": 35,
        "nome_arquivo": "Rotatividade.docx",
        "resumo_curto": "Bloqueio por rotatividade é ilegal.",
        "categoria": "Ilegalidade da rotatividade"
    }
]


def populate_templates():
    """Popula os templates padrão no banco de dados para todas as firmas"""
    
    with app.app_context():
        print("=" * 80)
        print("CADASTRO DE TEMPLATES PADRÃO DE CASOS FAP")
        print("=" * 80)
        
        # Buscar todas as law_firms
        all_law_firms = LawFirm.query.all()
        
        if not all_law_firms:
            print("❌ ERRO: Nenhum escritório cadastrado no sistema!")
            print("   Execute primeiro os scripts de população de dados básicos.")
            return
        
        print(f"\n📋 Encontrados {len(all_law_firms)} escritório(s) no sistema")
        print(f"\n{'=' * 80}\n")
        
        # Diretório de origem dos templates
        templates_source_dir = root_dir / "templates_padrao"
        
        if not templates_source_dir.exists():
            print(f"❌ ERRO: Diretório {templates_source_dir} não encontrado!")
            return
        
        # Contadores globais
        total_success = 0
        total_error = 0
        total_skipped = 0
        
        # Processar cada law_firm
        for law_firm in all_law_firms:
            law_firm_id = law_firm.id
            
            # Buscar primeiro usuário da firma ou usar o primeiro do sistema
            user = User.query.filter_by(law_firm_id=law_firm_id).first()
            if not user:
                user = User.query.first()
            
            if not user:
                print(f"⚠️  Escritório '{law_firm.name}': Nenhum usuário encontrado. Pulando...")
                continue
            
            user_id = user.id
            
            print(f"\n📁 Processando escritório: {law_firm.name} (ID: {law_firm_id})")
            print(f"   Usuário: {user.name}")
            print(f"   {'-' * 76}")
            
            # Criar diretório de destino para esta firma
            templates_dest_dir = root_dir / "uploads" / "templates" / str(law_firm_id)
            templates_dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Contadores por firma
            success_count = 0
            error_count = 0
            skipped_count = 0
            
            # Processar cada template
            for template_data in TEMPLATES_DATA:
                template_id = template_data["id"]
                nome_arquivo = template_data["nome_arquivo"]
                resumo_curto = template_data["resumo_curto"]
                categoria = template_data["categoria"]
                
                # Verificar se já existe para esta firma
                existing = CaseTemplate.query.filter_by(
                    law_firm_id=law_firm_id,
                    template_name=nome_arquivo
                ).first()
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Buscar arquivo na pasta templates_padrao
                source_file = templates_source_dir / nome_arquivo
                
                if not source_file.exists():
                    error_count += 1
                    continue
                
                try:
                    # Copiar arquivo para diretório de uploads
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    dest_filename = f"{timestamp}_{nome_arquivo}"
                    dest_file = templates_dest_dir / dest_filename
                    
                    shutil.copy2(source_file, dest_file)
                    
                    # Obter informações do arquivo
                    file_size = dest_file.stat().st_size
                    file_type = dest_file.suffix.upper().replace('.', '')
                    
                    # Criar registro no banco
                    template = CaseTemplate(
                        user_id=user_id,
                        law_firm_id=law_firm_id,
                        template_name=nome_arquivo,
                        resumo_curto=resumo_curto,
                        categoria=categoria,
                        original_filename=nome_arquivo,
                        file_path=str(dest_file),
                        file_size=file_size,
                        file_type=file_type,
                        is_active=True,
                        status='available',
                        tags='fap, padrão, template'
                    )
                    
                    db.session.add(template)
                    db.session.commit()
                    
                    success_count += 1
                    
                except Exception as e:
                    db.session.rollback()
                    error_count += 1
            
            # Resumo por firma
            print(f"   ✅ Cadastrados: {success_count} | ⚠️  Pulados: {skipped_count} | ❌ Erros: {error_count}")
            
            # Acumular totais
            total_success += success_count
            total_error += error_count
            total_skipped += skipped_count
        
        # Resumo final global
        print("\n" + "=" * 80)
        print("RESUMO GERAL DO CADASTRO")
        print("=" * 80)
        print(f"🏢 Escritórios processados: {len(all_law_firms)}")
        print(f"✅ Templates cadastrados com sucesso: {total_success}")
        print(f"⚠️  Templates já existentes (pulados): {total_skipped}")
        print(f"❌ Erros: {total_error}")
        print(f"📊 Total processado: {total_success + total_error + total_skipped}")
        print("=" * 80)
        
        if total_success > 0:
            print(f"\n🎉 Templates cadastrados e disponíveis para uso!")
            print(f"   Acesse: /cases/templates para visualizar")


if __name__ == "__main__":
    populate_templates()
