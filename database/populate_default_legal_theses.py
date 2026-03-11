"""
Script para popular teses juridicas padrao para todos os escritorios.

Uso:
    python database/populate_default_legal_theses.py
"""

import sys
from pathlib import Path
from datetime import datetime

# Adiciona o diretorio raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, JudicialLegalThesis


DEFAULT_LEGAL_THESES = [
    {
        "name": "60 DIAS",
        "slug": "beneficio_60_dias",
        "description": "Beneficio com duracao superior a 60 dias considerado para calculo previdenciario.",
    },
    {
        "name": "ACIDENTE NAO RELACIONADO AO TRABALHO",
        "slug": "acidente_nao_relacionado_ao_trabalho",
        "description": "Beneficio classificado como acidentario indevidamente, sendo o evento nao relacionado ao trabalho.",
    },
    {
        "name": "ACIDENTE OCORRIDO EM OUTRA EMPRESA",
        "slug": "acidente_ocorrido_em_outra_empresa",
        "description": "Evento acidentario ocorrido quando o segurado estava vinculado a outra empresa.",
    },
    {
        "name": "ACIDENTE OCORRIDO EM OUTRO ESTABELECIMENTO",
        "slug": "acidente_ocorrido_em_outro_estabelecimento",
        "description": "Evento acidentario ocorrido em estabelecimento diferente daquele considerado no calculo.",
    },
    {
        "name": "APURACAO DO INDICE DE CUSTO",
        "slug": "apuracao_do_indice_de_custo",
        "description": "Questionamento sobre a forma de apuracao do indice de custo utilizado no calculo do FAP.",
    },
    {
        "name": "BENEFICIO DUPLICADO",
        "slug": "beneficio_duplicado",
        "description": "Existencia de dois beneficios registrados indevidamente para o mesmo evento ou segurado.",
    },
    {
        "name": "BENEFICIO PREVIDENCIARIO",
        "slug": "beneficio_previdenciario",
        "description": "Beneficio classificado como previdenciario em vez de acidentario.",
    },
    {
        "name": "BENEFICIO PROVENIENTE DE PENSAO ALIMENTICIA",
        "slug": "beneficio_proveniente_de_pensao_alimenticia",
        "description": "Beneficio com origem vinculada a pensao alimenticia ou determinacao judicial correlata.",
    },
    {
        "name": "BENEFICIOS DO MESMO SEGURADO",
        "slug": "beneficios_do_mesmo_segurado",
        "description": "Beneficios distintos vinculados ao mesmo segurado que impactam os indicadores previdenciarios.",
    },
    {
        "name": "BLOQUEIO DE ROTATIVIDADE",
        "slug": "bloqueio_de_rotatividade",
        "description": "Bloqueio aplicado pelo sistema em razao da taxa de rotatividade considerada irregular.",
    },
    {
        "name": "CAT DE OBITO",
        "slug": "cat_de_obito",
        "description": "Comunicacao de Acidente de Trabalho vinculada a obito do segurado.",
    },
    {
        "name": "CAT DUPLICADA",
        "slug": "cat_duplicada",
        "description": "Registro duplicado de Comunicacao de Acidente de Trabalho para o mesmo evento.",
    },
    {
        "name": "CAT FORA DO PERIODO BASE",
        "slug": "cat_fora_do_periodo_base",
        "description": "Comunicacao de acidente registrada fora do periodo base considerado no calculo do FAP.",
    },
    {
        "name": "CAT NAO VINCULADA",
        "slug": "cat_nao_vinculada",
        "description": "Comunicacao de acidente sem vinculo correto com beneficio ou segurado.",
    },
    {
        "name": "CONCESSAO CONCOMITANTE DE BENEFICIOS",
        "slug": "concessao_concomitante_de_beneficios",
        "description": "Ocorrencia de concessao simultanea de dois ou mais beneficios.",
    },
    {
        "name": "CONCESSAO DUPLICADA DE BENEFICIO",
        "slug": "concessao_duplicada_de_beneficio",
        "description": "Concessao repetida de beneficio para o mesmo evento ou segurado.",
    },
    {
        "name": "CONTESTACAO ADMINISTRATIVA",
        "slug": "contestacao_administrativa",
        "description": "Contestacao apresentada administrativamente perante o orgao competente.",
    },
    {
        "name": "CONVERTIDO PARA B31",
        "slug": "convertido_para_b31",
        "description": "Beneficio originalmente acidentario convertido para auxilio-doenca previdenciario (B31).",
    },
    {
        "name": "CONVERTIDO PARA B32",
        "slug": "convertido_para_b32",
        "description": "Beneficio convertido para aposentadoria por invalidez previdenciaria.",
    },
    {
        "name": "CONVERTIDO PARA B36",
        "slug": "convertido_para_b36",
        "description": "Beneficio convertido para auxilio-acidente previdenciario.",
    },
    {
        "name": "CORRECAO DO CNAE PREPONDERANTE",
        "slug": "correcao_do_cnae_preponderante",
        "description": "Correcao do CNAE preponderante utilizado para calculo de indicadores.",
    },
    {
        "name": "CUMULACAO DE BENEFICIOS",
        "slug": "cumulacao_de_beneficios",
        "description": "Situacao em que dois beneficios sao acumulados indevidamente.",
    },
    {
        "name": "CUSTO DE BENEFICIO",
        "slug": "custo_de_beneficio",
        "description": "Impacto financeiro do beneficio considerado no calculo do FAP.",
    },
    {
        "name": "CUSTO CESSADO",
        "slug": "custo_cessado",
        "description": "Custo de beneficio que deveria ter sido cessado, mas permanece impactando o calculo.",
    },
    {
        "name": "DIB = DCB",
        "slug": "dib_igual_dcb",
        "description": "Data de inicio do beneficio igual a data de cessacao.",
    },
    {
        "name": "DIVERGENCIA ENTRE BENEFICIO CONCEDIDO E IMPLEMENTADO",
        "slug": "divergencia_entre_beneficio_concedido_e_implementado",
        "description": "Diferenca entre o beneficio concedido e o implementado pelo INSS.",
    },
    {
        "name": "DOENCA NAO RELACIONADA AO TRABALHO",
        "slug": "doenca_nao_relacionada_ao_trabalho",
        "description": "Doenca sem relacao causal com as atividades laborais.",
    },
    {
        "name": "ERRO NA MASSA SALARIAL",
        "slug": "erro_na_massa_salarial",
        "description": "Erro nos valores da massa salarial utilizados no calculo do FAP.",
    },
    {
        "name": "ERRO NO NUMERO MEDIO DE VINCULOS",
        "slug": "erro_no_numero_medio_de_vinculos",
        "description": "Erro na apuracao do numero medio de vinculos empregaticios.",
    },
    {
        "name": "ERRO NA ATIVIDADE PREPONDERANTE",
        "slug": "erro_na_atividade_preponderante",
        "description": "Erro na definicao da atividade economica predominante da empresa.",
    },
    {
        "name": "ERRO NO CALCULO DA ROTATIVIDADE",
        "slug": "erro_no_calculo_da_rotatividade",
        "description": "Erro na metodologia ou calculo da taxa de rotatividade.",
    },
    {
        "name": "ERRO NA NATUREZA ACIDENTARIA DO BENEFICIO",
        "slug": "erro_na_natureza_acidentaria_do_beneficio",
        "description": "Beneficio classificado incorretamente como acidentario.",
    },
    {
        "name": "INDIVIDUALIZACAO DO FAP POR ESTABELECIMENTO",
        "slug": "individualizacao_do_fap_por_estabelecimento",
        "description": "Defesa da individualizacao do FAP por estabelecimento da empresa.",
    },
    {
        "name": "JUDICIAL",
        "slug": "judicial",
        "description": "Questao decorrente de decisao judicial ou processo judicial.",
    },
    {
        "name": "NEXO AFASTADO",
        "slug": "nexo_afastado",
        "description": "Reconhecimento de inexistencia de nexo causal entre doenca/acidente e atividade laboral.",
    },
    {
        "name": "NTP SEM CAT VINCULADA",
        "slug": "ntp_sem_cat_vinculada",
        "description": "Aplicacao do Nexo Tecnico Previdenciario sem registro correspondente de CAT.",
    },
    {
        "name": "NTP DUPLICADO",
        "slug": "ntp_duplicado",
        "description": "Registro duplicado de Nexo Tecnico Previdenciario.",
    },
    {
        "name": "OUTRA EMPRESA",
        "slug": "outra_empresa",
        "description": "Evento ou beneficio relacionado a outra empresa.",
    },
    {
        "name": "OUTRO ESTABELECIMENTO",
        "slug": "outro_estabelecimento",
        "description": "Evento ocorrido em estabelecimento diferente dentro do mesmo grupo.",
    },
    {
        "name": "PRESCRICAO QUINQUENAL",
        "slug": "prescricao_quinquenal",
        "description": "Aplicacao da prescricao quinquenal sobre os efeitos financeiros.",
    },
    {
        "name": "PRE-FAP",
        "slug": "pre_fap",
        "description": "Questionamento referente ao calculo preliminar do FAP.",
    },
    {
        "name": "RECALCULO E REFLEXOS",
        "slug": "recalculo_e_reflexos",
        "description": "Pedido de recalculo do FAP e seus reflexos.",
    },
    {
        "name": "RESTABELECIMENTO DE BENEFICIO",
        "slug": "restabelecimento_de_beneficio",
        "description": "Restabelecimento de beneficio anteriormente cessado.",
    },
    {
        "name": "REVOGACAO DA TUTELA / LIMINAR",
        "slug": "revogacao_da_tutela_ou_liminar",
        "description": "Revogacao de tutela antecipada ou decisao liminar.",
    },
    {
        "name": "ROTATIVIDADE",
        "slug": "rotatividade",
        "description": "Discussao sobre a taxa de rotatividade considerada no calculo do FAP.",
    },
    {
        "name": "SOBREPOSICAO DE BENEFICIOS",
        "slug": "sobreposicao_de_beneficios",
        "description": "Sobreposicao temporal de dois ou mais beneficios.",
    },
    {
        "name": "TRAJETO - B91",
        "slug": "trajeto_b91",
        "description": "Acidente de trajeto vinculado ao beneficio B91.",
    },
    {
        "name": "TRAJETO - B92",
        "slug": "trajeto_b92",
        "description": "Acidente de trajeto vinculado ao beneficio B92.",
    },
    {
        "name": "TRAJETO - B93",
        "slug": "trajeto_b93",
        "description": "Acidente de trajeto vinculado ao beneficio B93.",
    },
    {
        "name": "TRAJETO - B94",
        "slug": "trajeto_b94",
        "description": "Acidente de trajeto vinculado ao beneficio B94.",
    },
]


def populate_default_legal_theses():
    with app.app_context():
        try:
            law_firms = LawFirm.query.all()
            if not law_firms:
                print("⚠️ Nenhum escritorio encontrado.")
                return

            created_count = 0
            updated_count = 0

            for law_firm in law_firms:
                print(f"\n🏢 Processando escritorio: {law_firm.name} (ID: {law_firm.id})")

                for item in DEFAULT_LEGAL_THESES:
                    existing = JudicialLegalThesis.query.filter_by(
                        law_firm_id=law_firm.id,
                        key=item["slug"],
                    ).first()

                    if existing:
                        existing.name = item["name"]
                        existing.description = item["description"]
                        existing.is_active = True
                        existing.updated_at = datetime.utcnow()
                        updated_count += 1
                    else:
                        db.session.add(
                            JudicialLegalThesis(
                                law_firm_id=law_firm.id,
                                name=item["name"],
                                key=item["slug"],
                                description=item["description"],
                                is_active=True,
                            )
                        )
                        created_count += 1

            db.session.commit()
            print("\n✅ Teses juridicas populadas com sucesso!")
            print(f"✅ Criadas: {created_count}")
            print(f"✅ Atualizadas: {updated_count}")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao popular teses juridicas: {e}")
            raise


if __name__ == "__main__":
    print("=" * 80)
    print("📚 POPULAR TESES JURIDICAS PADRAO")
    print("=" * 80)
    populate_default_legal_theses()
    print("=" * 80)
