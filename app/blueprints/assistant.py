from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from app.models import db, Case, Client
from datetime import datetime
from functools import wraps

assistant_bp = Blueprint('assistant', __name__, url_prefix='/assistente-juridico')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('law_firm_id'):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@assistant_bp.route('/')
def legal_assistant():
    """Interface do Assistente Jurídico - Chat com IA"""
    return render_template('assistant/chat.html')

@assistant_bp.route('/api', methods=['POST'])
def legal_assistant_api():
    """API para processar mensagens do Assistente Jurídico"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Mensagem é obrigatória'}), 400
        
        context = get_system_context()
        ai_response = process_legal_assistant_message(user_message, context)
        
        return jsonify({
            'response': ai_response,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': f'Erro interno: {str(e)}'}), 500

def get_system_context():
    """Obtém contexto atual do sistema para a IA"""
    try:
        context = {
            'total_cases': Case.query.count(),
            'active_cases': Case.query.filter_by(status='active').count(),
            'total_clients': Client.query.count(),
            'recent_cases': Case.query.order_by(Case.created_at.desc()).limit(3).all(),
            'case_types': db.session.query(Case.case_type, db.func.count(Case.id)).group_by(Case.case_type).all(),
            'clients_list': Client.query.all(),
        }
        return context
    except Exception as e:
        return {'error': str(e)}

def process_legal_assistant_message(message, context):
    """Processa mensagem do usuário e gera resposta da IA"""
    message_lower = message.lower()
    
    if 'quantos casos' in message_lower or 'total de casos' in message_lower:
        total = context.get('total_cases', 0)
        active = context.get('active_cases', 0)
        return f"📊 **Estatísticas de Casos:**\n\n• **Total de casos:** {total}\n• **Casos ativos:** {active}\n• **Casos inativos:** {total - active}\n\nPosso ajudar com mais informações sobre algum caso específico?"
    
    elif 'clientes' in message_lower and ('quantos' in message_lower or 'total' in message_lower):
        total = context.get('total_clients', 0)
        return f"👥 **Clientes cadastrados:** {total} empresas\n\nGostaria de saber mais detalhes sobre algum cliente específico?"
    
    elif 'fap' in message_lower:
        recent = context.get('recent_cases', [])
        fap_cases = [case for case in recent if case.case_type and 'fap' in str(case.case_type).lower()]
        count = len(fap_cases)
        return f"⚖️ **Casos FAP:** Encontrei {count} casos relacionados ao FAP\n\n**Tipos de FAP mais comuns:**\n• FAP Trajeto\n• FAP Nexo Causal\n• FAP Múltiplos Benefícios\n\nQuer detalhes sobre algum tipo específico?"
    
    elif 'casos recentes' in message_lower or 'últimos casos' in message_lower:
        recent = context.get('recent_cases', [])
        if recent:
            response = "📋 **Casos mais recentes:**\n\n"
            for case in recent[:3]:
                status_emoji = "🟢" if case.status == 'active' else "🟡" if case.status == 'draft' else "⚪"
                response += f"• {status_emoji} **{case.title}**\n  Cliente: {case.client.name if case.client else 'N/A'}\n  Status: {case.status}\n\n"
            return response + "Precisa de mais detalhes sobre algum destes casos?"
        else:
            return "📋 Nenhum caso encontrado no sistema. Que tal criar o primeiro caso?"
    
    elif 'tipos de caso' in message_lower or 'case_type' in message_lower:
        types = context.get('case_types', [])
        if types:
            response = "📂 **Tipos de casos no sistema:**\n\n"
            for case_type, count in types:
                type_name = {
                    'fap': 'Revisão FAP - AÇÃO REVISIONAL DO FATOR ACIDENTÁRIO DE PREVENÇÃO',
                    'previdenciario': 'Previdenciário',
                    'trabalhista': 'Trabalhista',
                    'outros': 'Outros'
                }.get(case_type, case_type.title() if case_type else 'Não especificado')
                response += f"• **{type_name}:** {count} casos\n"
            return response + "\nQual tipo você gostaria de analisar em detalhes?"
        else:
            return "📂 Nenhum tipo de caso encontrado no sistema."
    
    elif 'ajuda' in message_lower or 'help' in message_lower:
        return "🤖 **Como posso ajudar?**\n\n**Perguntas que posso responder:**\n\n📊 • Quantos casos temos?\n👥 • Informações sobre clientes\n⚖️ • Casos FAP\n📋 • Casos recentes\n📂 • Tipos de casos\n\n**Exemplos de perguntas:**\n• \"Quantos casos ativos temos?\"\n• \"Quais são os casos recentes?\"\n• \"Informações sobre FAP\"\n• \"Tipos de casos no sistema\""
    
    elif 'oi' in message_lower or 'olá' in message_lower or 'hello' in message_lower:
        return "👋 **Olá! Sou o Assistente Jurídico do IntellexIA**\n\nSou especializado em casos trabalhistas e posso ajudar você com:\n\n• 📊 Estatísticas e relatórios\n• ⚖️ Informações sobre casos FAP\n• 👥 Dados de clientes\n• 📋 Consultas sobre processos\n\nO que gostaria de saber?"
    
    else:
        return f"🤔 Entendi sua pergunta: \"{message}\"\n\n💡 **Sugestões do que posso ajudar:**\n\n• Digite \"ajuda\" para ver todas as funcionalidades\n• Pergunte sobre \"casos\", \"clientes\" ou \"benefícios\"\n• Peça \"estatísticas\" para um resumo geral\n• Mencione \"FAP\" para casos específicos\n\nEstou aqui para ajudar com informações jurídicas do sistema! 💼⚖️"
