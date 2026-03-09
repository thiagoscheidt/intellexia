"""
Script para verificar se a tabela agent_token_usage existe e testar inserção.

Para executar:
    python database/test_agent_token_usage.py
"""

import sys
from pathlib import Path
from decimal import Decimal

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, AgentTokenUsage
from main import app


def test_table():
    """Verifica se a tabela existe e testa inserção"""
    with app.app_context():
        # Detectar tipo de banco
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri
        
        if is_mysql:
            db_type = "MySQL"
            display_uri = db_uri.split('@')[1] if '@' in db_uri else db_uri
        else:
            db_type = "SQLite"
            display_uri = db_uri.replace('sqlite:///', '')
        
        print(f"Banco de dados detectado: {db_type}")
        print(f"Conexão: {display_uri}")
        
        # Verificar se a tabela existe
        print("\n1. Verificando se a tabela 'agent_token_usage' existe...")
        
        if is_mysql:
            result = db.session.execute(db.text("SHOW TABLES LIKE 'agent_token_usage'"))
            exists = result.fetchone() is not None
        else:
            result = db.session.execute(db.text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_token_usage'"))
            exists = result.fetchone() is not None
        
        if exists:
            print("✓ Tabela 'agent_token_usage' existe!")
        else:
            print("✗ Tabela 'agent_token_usage' NÃO existe!")
            print("\nExecute primeiro: python database/add_agent_token_usage_table.py")
            return
        
        # Verificar estrutura da tabela
        print("\n2. Verificando estrutura da tabela...")
        
        if is_mysql:
            result = db.session.execute(db.text("SHOW COLUMNS FROM agent_token_usage"))
            columns = [row[0] for row in result.fetchall()]
        else:
            result = db.session.execute(db.text("PRAGMA table_info(agent_token_usage)"))
            columns = [row[1] for row in result.fetchall()]
        
        print(f"Colunas encontradas ({len(columns)}):")
        for col in columns:
            print(f"  - {col}")
        
        # Contar registros existentes
        print("\n3. Verificando registros existentes...")
        count = db.session.query(AgentTokenUsage).count()
        print(f"Total de registros na tabela: {count}")
        
        # Tentar inserir um registro de teste
        print("\n4. Testando inserção de um registro...")
        
        try:
            test_record = AgentTokenUsage(
                agent_name="TestAgent",
                action_name="test_action",
                model_name="gpt-4o-mini",
                model_provider="openai",
                status="success",
                message_index=0,
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=Decimal("0.00015"),
                currency="USD",
                usage_payload={"test": True},
                metadata_payload={"testing": True},
            )
            
            db.session.add(test_record)
            db.session.commit()
            
            print(f"✓ Registro de teste inserido com sucesso! ID: {test_record.id}")
            
            # Verificar se foi salvo
            saved = db.session.query(AgentTokenUsage).filter_by(id=test_record.id).first()
            if saved:
                print(f"✓ Registro confirmado no banco: {saved}")
                
                # Deletar registro de teste
                db.session.delete(saved)
                db.session.commit()
                print("✓ Registro de teste removido")
            else:
                print("✗ Registro não foi encontrado após inserção")
                
        except Exception as e:
            db.session.rollback()
            print(f"✗ ERRO ao inserir registro: {e}")
            print(f"Tipo do erro: {type(e).__name__}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "="*60)
        print("Teste concluído!")


if __name__ == '__main__':
    test_table()
