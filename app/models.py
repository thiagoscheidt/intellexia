from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class LawFirm(db.Model):
    """Tabela law_firms - Escritórios de advocacia que usam o sistema"""
    __tablename__ = 'law_firms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # Razão social
    trade_name = db.Column(db.String(255))  # Nome fantasia
    cnpj = db.Column(db.String(20), unique=True, nullable=False, index=True)
    
    # Endereço
    street = db.Column(db.String(255))
    number = db.Column(db.String(20))
    complement = db.Column(db.String(100))
    district = db.Column(db.String(150))
    city = db.Column(db.String(150))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    
    # Contato
    phone = db.Column(db.String(50))
    email = db.Column(db.String(255))
    website = db.Column(db.String(255))
    
    # Status e configurações
    is_active = db.Column(db.Boolean, default=True)
    subscription_plan = db.Column(db.String(50), default='trial')  # trial, basic, premium, enterprise
    subscription_expires_at = db.Column(db.DateTime)
    max_users = db.Column(db.Integer, default=5)
    max_cases = db.Column(db.Integer, default=50)
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    users = db.relationship('User', back_populates='law_firm', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<LawFirm {self.name}>'


class User(db.Model):
    """Tabela users - Usuários do sistema"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Dados pessoais
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Dados profissionais
    oab_number = db.Column(db.String(50))  # Opcional, só para advogados
    phone = db.Column(db.String(50))
    
    # Permissões e status
    role = db.Column(db.String(30), nullable=False, default='user')  # admin, lawyer, assistant, user
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    
    # Controle de sessão
    last_login = db.Column(db.DateTime)
    last_activity = db.Column(db.DateTime)
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm', back_populates='users')
    
    def set_password(self, password):
        """Define a senha do usuário (hash)"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verifica se a senha está correta"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """Retorna um dicionário com os dados do usuário"""
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'oab_number': self.oab_number,
            'phone': self.phone,
            'is_active': self.is_active,
            'law_firm': {
                'id': self.law_firm.id,
                'name': self.law_firm.name,
                'trade_name': self.law_firm.trade_name,
                'cnpj': self.law_firm.cnpj
            } if self.law_firm else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<User {self.email}>'


class Client(db.Model):
    """Tabela clients - Empresas autoras dos casos"""
    __tablename__ = 'clients'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)  # Razão social
    cnpj = db.Column(db.String(20), nullable=False, index=True)
    street = db.Column(db.String(255))
    number = db.Column(db.String(20))
    district = db.Column(db.String(150))
    city = db.Column(db.String(150))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    has_branches = db.Column(db.Boolean, default=False)
    branches_description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    cases = db.relationship('Case', back_populates='client')
    
    def __repr__(self):
        return f'<Client {self.name}>'


class Court(db.Model):
    """Tabela courts - Varas judiciais"""
    __tablename__ = 'courts'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    section = db.Column(db.String(255))  # Seção judiciária
    vara_name = db.Column(db.String(255))  # Nome da vara
    city = db.Column(db.String(150))
    state = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    cases = db.relationship('Case', back_populates='court')
    
    def __repr__(self):
        return f'<Court {self.vara_name}>'


class Lawyer(db.Model):
    """Tabela lawyers - Advogados"""
    __tablename__ = 'lawyers'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    oab_number = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    is_default_for_publications = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    case_lawyers = db.relationship('CaseLawyer', back_populates='lawyer')
    
    def __repr__(self):
        return f'<Lawyer {self.name} - OAB: {self.oab_number}>'


class Case(db.Model):
    """Tabela cases - Casos jurídicos"""
    __tablename__ = 'cases'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    court_id = db.Column(db.Integer, db.ForeignKey('courts.id'), index=True)
    title = db.Column(db.String(255), nullable=False)
    case_type = db.Column(db.String(50), nullable=False)
    fap_start_year = db.Column(db.SmallInteger)
    fap_end_year = db.Column(db.SmallInteger)
    facts_summary = db.Column(db.Text)
    thesis_summary = db.Column(db.Text)
    prescription_summary = db.Column(db.Text)
    value_cause = db.Column(db.Numeric(15, 2))
    status = db.Column(db.String(30), default='draft')
    filing_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    client = db.relationship('Client', back_populates='cases')
    court = db.relationship('Court', back_populates='cases')
    case_lawyers = db.relationship('CaseLawyer', back_populates='case', cascade='all, delete-orphan')
    competences = db.relationship('CaseCompetence', back_populates='case', cascade='all, delete-orphan')
    benefits = db.relationship('CaseBenefit', back_populates='case', cascade='all, delete-orphan')
    documents = db.relationship('Document', back_populates='case', cascade='all, delete-orphan')
    petitions = db.relationship('Petition', back_populates='case', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Case {self.title}>'


class CaseLawyer(db.Model):
    """Tabela case_lawyers - Relacionamento entre casos e advogados"""
    __tablename__ = 'case_lawyers'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
    lawyer_id = db.Column(db.Integer, db.ForeignKey('lawyers.id'), nullable=False, index=True)
    role = db.Column(db.String(50))  # Função do advogado no caso
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='case_lawyers')
    lawyer = db.relationship('Lawyer', back_populates='case_lawyers')
    
    def __repr__(self):
        return f'<CaseLawyer Case: {self.case_id}, Lawyer: {self.lawyer_id}>'


class CaseCompetence(db.Model):
    """Tabela case_competences - Competências dos casos"""
    __tablename__ = 'case_competences'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.BigInteger, db.ForeignKey('cases.id'), nullable=False, index=True)
    competence_month = db.Column(db.SmallInteger, nullable=False)  # 1 a 12
    competence_year = db.Column(db.SmallInteger, nullable=False)
    status = db.Column(db.Enum('prescribed', 'valid', name='competence_status'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='competences')
    
    def __repr__(self):
        return f'<CaseCompetence {self.competence_month}/{self.competence_year}>'


class CaseBenefit(db.Model):
    """Tabela case_benefits - Benefícios relacionados aos casos"""
    __tablename__ = 'case_benefits'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.BigInteger, db.ForeignKey('cases.id'), nullable=False, index=True)
    benefit_number = db.Column(db.String(50), nullable=False, index=True)
    benefit_type = db.Column(db.String(10), nullable=False)  # B91, B94, etc.
    insured_name = db.Column(db.String(255), nullable=False)
    insured_nit = db.Column(db.String(50))
    numero_cat = db.Column(db.String(100))
    numero_bo = db.Column(db.String(100))
    data_inicio_beneficio = db.Column(db.Date)
    data_fim_beneficio = db.Column(db.Date)
    accident_date = db.Column(db.Date)
    accident_company_name = db.Column(db.String(255))
    fap_reason = db.Column(db.String(100))  # Motivo/Enquadramento FAP (movido de Case para CaseBenefit)
    fap_vigencia_years = db.Column(db.String(500))  # Anos de vigência FAP (comma-separated, ex: "2019,2020,2021")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='benefits')
    documents = db.relationship('Document', back_populates='related_benefit')
    
    def __repr__(self):
        return f'<CaseBenefit {self.benefit_number}>'


class FapReason(db.Model):
    """Tabela fap_reasons - Motivos de contestação FAP"""
    __tablename__ = 'fap_reasons'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    display_name = db.Column(db.String(100), nullable=False)  # Nome simples para exibição no select
    description = db.Column(db.Text)  # Descrição completa do motivo
    template_id = db.Column(db.Integer, db.ForeignKey('case_templates.id'), index=True)  # Template relacionado (opcional)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    template = db.relationship('CaseTemplate', foreign_keys=[template_id])
    
    def __repr__(self):
        return f'<FapReason {self.display_name}>'


class Document(db.Model):
    """Tabela documents - Documentos dos casos"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
    related_benefit_id = db.Column(db.Integer, db.ForeignKey('case_benefits.id'), index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    document_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    use_in_ai = db.Column(db.Boolean, default=True)
    
    # Campos para análise de IA
    ai_summary = db.Column(db.Text)  # Resumo gerado pela IA sobre informações importantes
    ai_processed_at = db.Column(db.DateTime)  # Data/hora do processamento pela IA
    ai_status = db.Column(db.String(20), default='pending')  # pending, processing, completed, error
    ai_error_message = db.Column(db.Text)  # Mensagem de erro caso o processamento falhe
    
    uploaded_by_user_id = db.Column(db.Integer)  # FK de usuário (futuro)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='documents')
    related_benefit = db.relationship('CaseBenefit', back_populates='documents')
    
    def __repr__(self):
        return f'<Document {self.original_filename}>'


class Petition(db.Model):
    """Tabela petitions - Petições geradas pela IA"""
    __tablename__ = 'petitions'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)  # Número da versão (1, 2, 3...)
    title = db.Column(db.String(255), nullable=False)  # Título da petição
    content = db.Column(db.Text, nullable=False)  # Conteúdo completo da petição
    
    # Arquivo DOCX gerado
    file_path = db.Column(db.String(500))  # Caminho do arquivo DOCX (para casos FAP)
    
    # Metadados da geração
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    generated_by_user_id = db.Column(db.Integer)  # FK de usuário (futuro)
    
    # Status da geração
    status = db.Column(db.String(20), default='completed')  # pending, processing, completed, error
    error_message = db.Column(db.Text)  # Mensagem de erro caso falhe
    
    # Contexto usado na geração (para referência)
    context_summary = db.Column(db.Text)  # Resumo do contexto usado (docs, benefícios, etc.)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='petitions')
    
    def __repr__(self):
        return f'<Petition v{self.version} - Case {self.case_id}>'


class AiDocumentSummary(db.Model):
    """Tabela ai_document_summaries - Documentos para resumo por IA"""
    __tablename__ = 'ai_document_summaries'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações do arquivo
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # Tamanho em bytes
    file_type = db.Column(db.String(50))  # PDF, DOCX, TXT, etc.
    
    # Status e resumo
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, error
    summary_text = db.Column(db.Text)  # Resumo gerado pela IA
    error_message = db.Column(db.Text)  # Mensagem de erro caso falhe
    
    # Metadados
    processed_at = db.Column(db.DateTime)  # Data/hora do processamento
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<AiDocumentSummary {self.original_filename}>'


class KnowledgeBase(db.Model):
    """Tabela knowledge_base - Base de conhecimento com arquivos do escritório"""
    __tablename__ = 'knowledge_base'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações do arquivo
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # Tamanho em bytes
    file_type = db.Column(db.String(50))  # PDF, DOCX, TXT, etc.
    
    # Descrição e categorização
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # Jurisprudência, Legislação, Modelos, etc.
    tags = db.Column(db.String(500))  # Tags separadas por vírgula
    lawsuit_number = db.Column(db.String(100))  # Número do processo judicial (opcional)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Auditoria
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<KnowledgeBase {self.original_filename}>'


class KnowledgeCategory(db.Model):
    """Tabela knowledge_categories - Categorias para organização da base de conhecimento"""
    __tablename__ = 'knowledge_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações da categoria
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50))  # Emoji ou classe de ícone Bootstrap
    description = db.Column(db.Text)
    color = db.Column(db.String(20))  # Cor em hexadecimal
    
    # Ordem de exibição
    display_order = db.Column(db.Integer, default=0)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<KnowledgeCategory {self.name}>'


class KnowledgeTag(db.Model):
    """Tabela knowledge_tags - Tags para marcação da base de conhecimento"""
    __tablename__ = 'knowledge_tags'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações da tag
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50))  # Emoji ou classe de ícone Bootstrap
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='#007bff')  # Cor em hexadecimal
    
    # Ordem de exibição
    display_order = db.Column(db.Integer, default=0)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<KnowledgeTag {self.name}>'


class KnowledgeChatHistory(db.Model):
    """Tabela knowledge_chat_history - Histórico de perguntas e respostas do chat da base de conhecimento"""
    __tablename__ = 'knowledge_chat_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Pergunta e resposta
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    sources = db.Column(db.Text)  # JSON array com as fontes utilizadas
    
    # Métricas
    response_time_ms = db.Column(db.Integer)  # Tempo de resposta em milissegundos
    tokens_used = db.Column(db.Integer)  # Quantidade de tokens utilizados
    
    # Feedback do usuário (opcional)
    user_rating = db.Column(db.Integer)  # 1-5 estrelas
    user_feedback = db.Column(db.Text)  # Comentário do usuário
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<KnowledgeChatHistory {self.id}>'


class KnowledgeSummary(db.Model):
    """Tabela knowledge_summaries - Resumos gerados pela IA para arquivos da base de conhecimento"""
    __tablename__ = 'knowledge_summaries'
    
    id = db.Column(db.Integer, primary_key=True)
    knowledge_base_id = db.Column(db.Integer, db.ForeignKey('knowledge_base.id'), nullable=False, index=True)
    
    # Dados do resumo
    payload = db.Column(db.JSON, nullable=False)  # JSON com o resumo e metadados
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    knowledge_base = db.relationship('KnowledgeBase')
    
    def __repr__(self):
        return f'<KnowledgeSummary {self.id}>'


class CasesKnowledgeBase(db.Model):
    """Tabela cases_knowledge_base - Base de conhecimento geral para casos (não específica de um caso)"""
    __tablename__ = 'cases_knowledge_base'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações do arquivo
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # Tamanho em bytes
    file_type = db.Column(db.String(50))  # PDF, DOCX, TXT, etc.
    
    # Descrição e categorização
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # Jurisprudência, Legislação, Modelos, etc.
    tags = db.Column(db.String(500))  # Tags separadas por vírgula
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Auditoria
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<CasesKnowledgeBase {self.original_filename}>'


class CaseTemplate(db.Model):
    """Tabela case_templates - Templates de documentos para geração de casos"""
    __tablename__ = 'case_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações do template
    template_name = db.Column(db.String(255), nullable=False)  # Nome do arquivo (ex: "Peticao Inicial.docx")
    resumo_curto = db.Column(db.Text, nullable=False)  # Descrição breve do template
    categoria = db.Column(db.String(150), nullable=False, index=True)  # Categoria do erro/situação
    
    # Arquivo do template
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # Tamanho em bytes
    file_type = db.Column(db.String(50))  # DOCX, PDF, etc.
    
    # Status e controle
    is_active = db.Column(db.Boolean, default=True)  # Se pode ser usado
    status = db.Column(db.String(30), default='available')  # available, draft, archived
    
    # Metadata adicional
    tags = db.Column(db.String(500))  # Tags separadas por vírgula
    usage_count = db.Column(db.Integer, default=0)  # Quantas vezes foi usado
    
    # Auditoria
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)  # Última vez que foi usado
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    
    def __repr__(self):
        return f'<CaseTemplate {self.template_name}>'


class CaseActivity(db.Model):
    """Tabela case_activities - Registro de todas as ações e alterações em um caso"""
    __tablename__ = 'case_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'comment', 'status_change', 'document_added', etc
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    related_id = db.Column(db.Integer)  # ID do documento, benefício, comentário, etc
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', backref='activities')
    user = db.relationship('User', backref='activities')
    
    def __repr__(self):
        return f'<CaseActivity {self.activity_type}>'


class CaseComment(db.Model):
    """Tabela case_comments - Comentários e discussões internas sobre casos"""
    __tablename__ = 'case_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment_type = db.Column(db.String(50), default='internal')  # 'internal', 'external', 'note'
    title = db.Column(db.String(255))
    content = db.Column(db.Text, nullable=False)
    
    # Thread (respostas)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('case_comments.id'), index=True)
    replies = db.relationship('CaseComment', remote_side=[id], backref='parent')
    
    # Status
    is_pinned = db.Column(db.Boolean, default=False)
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolved_at = db.Column(db.DateTime)
    
    # Mentions (JSON array de user_ids)
    mentions = db.Column(db.JSON, default=list)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', backref='comments')
    user = db.relationship('User', backref='comments', foreign_keys=[user_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])
    
    def __repr__(self):
        return f'<CaseComment {self.id}>'