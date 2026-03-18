from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


judicial_process_benefit_legal_theses = db.Table(
    'judicial_process_benefit_legal_theses',
    db.Column('id', db.Integer, primary_key=True),
    db.Column('benefit_id', db.Integer, db.ForeignKey('judicial_process_benefits.id'), nullable=False, index=True),
    db.Column('legal_thesis_id', db.Integer, db.ForeignKey('judicial_legal_theses.id'), nullable=False, index=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow, nullable=False),
    db.UniqueConstraint(
        'benefit_id',
        'legal_thesis_id',
        name='uq_judicial_process_benefit_legal_theses'
    ),
)


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
    judicial_processes_as_plaintiff = db.relationship(
        'JudicialProcess',
        foreign_keys='JudicialProcess.plaintiff_client_id',
        back_populates='plaintiff_client'
    )
    
    def __repr__(self):
        return f'<Client {self.name}>'


class JudicialDefendant(db.Model):
    """Tabela judicial_defendants - Polos passivos (réus) dos processos judiciais."""
    __tablename__ = 'judicial_defendants'
    __table_args__ = (
        db.UniqueConstraint('law_firm_id', 'name', name='uq_judicial_defendants_law_firm_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    judicial_processes = db.relationship(
        'JudicialProcess',
        foreign_keys='JudicialProcess.defendant_id',
        back_populates='defendant'
    )

    def __repr__(self):
        return f'<JudicialDefendant {self.name}>'


class Court(db.Model):
    """Tabela courts - Varas judiciais"""
    __tablename__ = 'courts'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    tribunal = db.Column(db.String(255))
    secao_judiciaria = db.Column(db.String(255))
    subsecao_judiciaria = db.Column(db.String(255))
    orgao_julgador = db.Column(db.String(255))
    city = db.Column(db.String(150))
    state = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    cases = db.relationship('Case', back_populates='court')

    # Compatibilidade legada com código que ainda usa os nomes antigos.
    section = db.synonym('secao_judiciaria')
    vara_name = db.synonym('orgao_julgador')
    
    def __repr__(self):
        return f'<Court {self.orgao_julgador}>'


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


class CaseStatus(db.Model):
    """Tabela case_status - Situações do processo"""
    __tablename__ = 'case_status'
    
    id = db.Column(db.Integer, primary_key=True)
    status_name = db.Column(db.String(100), nullable=False, unique=True)
    status_order = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamento
    cases = db.relationship('Case', back_populates='status_obj')
    
    def __repr__(self):
        return f'<CaseStatus {self.status_name}>'


class Case(db.Model):
    """Tabela cases - Casos jurídicos"""
    __tablename__ = 'cases'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    court_id = db.Column(db.Integer, db.ForeignKey('courts.id'), index=True)
    case_status_id = db.Column(db.Integer, db.ForeignKey('case_status.id'), default=1, index=True)
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
    status_obj = db.relationship('CaseStatus', back_populates='cases')
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
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
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
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), nullable=False, index=True)
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
    accident_summary = db.Column(db.Text)  # Resumo do acidente
    fap_reason = db.Column(db.String(100))  # Motivo/Enquadramento FAP (movido de Case para CaseBenefit)
    fap_reason_id = db.Column(db.Integer, db.ForeignKey('fap_reasons.id'), index=True)  # Foreign key para fap_reasons
    fap_vigencia_years = db.Column(db.String(500))  # Anos de vigência FAP (comma-separated, ex: "2019,2020,2021")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='benefits')
    documents = db.relationship('Document', back_populates='related_benefit')
    fap_reason_obj = db.relationship('FapReason', foreign_keys=[fap_reason_id])
    
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


class JudicialSentenceAnalysis(db.Model):
    """Tabela judicial_sentence_analysis - Análise de sentenças judiciais por IA"""
    __tablename__ = 'judicial_sentence_analysis'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    
    # Informações do arquivo da sentença
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # Tamanho em bytes
    file_type = db.Column(db.String(50))  # PDF, DOCX, TXT, etc.
    
    # Informações do arquivo da petição inicial (opcional)
    petition_filename = db.Column(db.String(255))
    petition_file_path = db.Column(db.String(500))
    petition_file_size = db.Column(db.Integer)
    petition_file_type = db.Column(db.String(50))
    
    # Número do processo judicial (opcional, para vincular ao painel de processos)
    process_number = db.Column(db.String(25), index=True)  # CNJ format: NNNNNNN-DD.AAAA.J.TR.OOOO
    
    # Status e análise
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, error
    analysis_result = db.Column(db.Text)  # Resultado da análise pela IA
    error_message = db.Column(db.Text)  # Mensagem de erro caso falhe
    
    # Metadados
    processed_at = db.Column(db.DateTime)  # Data/hora do processamento
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    appeals = db.relationship('JudicialAppeal', back_populates='sentence_analysis', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<JudicialSentenceAnalysis {self.original_filename}>'


class JudicialAppeal(db.Model):
    """Tabela judicial_appeals - Recursos judiciais gerados por IA"""
    __tablename__ = 'judicial_appeals'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    sentence_analysis_id = db.Column(db.Integer, db.ForeignKey('judicial_sentence_analysis.id'), nullable=False, index=True)
    
    # Informações do recurso
    appeal_type = db.Column(db.String(100), nullable=False)  # Apelação, Embargos de Declaração, Agravo, etc.
    user_notes = db.Column(db.Text)  # Observações e argumentos adicionais do usuário
    
    # Status e resultado
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, error
    generated_content = db.Column(db.Text)  # Conteúdo gerado pela IA
    generated_file_path = db.Column(db.String(500))  # Caminho do arquivo DOCX gerado
    error_message = db.Column(db.Text)  # Mensagem de erro caso falhe
    
    # Metadados
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)  # Data/hora do processamento
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    sentence_analysis = db.relationship('JudicialSentenceAnalysis', back_populates='appeals')
    
    def __repr__(self):
        return f'<JudicialAppeal {self.appeal_type} - Sentence #{self.sentence_analysis_id}>'


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
    file_hash = db.Column(db.String(64), index=True)  # SHA-256 do conteúdo do arquivo
    
    # Descrição e categorização
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # Jurisprudência, Legislação, Modelos, etc.
    tags = db.Column(db.String(500))  # Tags separadas por vírgula
    lawsuit_number = db.Column(db.String(100))  # Número do processo judicial (opcional)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    processing_status = db.Column(db.String(20), default='pending')  # pending, processing, completed, error
    processing_error_message = db.Column(db.Text)
    processed_at = db.Column(db.DateTime)
    
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
    chat_session_id = db.Column(db.Integer, db.ForeignKey('knowledge_chat_sessions.id'), index=True)
    
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
    chat_session = db.relationship('KnowledgeChatSession', back_populates='messages')
    
    def __repr__(self):
        return f'<KnowledgeChatHistory {self.id}>'


class AgentTokenUsage(db.Model):
    """Tabela agent_token_usage - Log de uso de tokens por ação dos agentes."""
    __tablename__ = 'agent_token_usage'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), index=True)
    chat_session_id = db.Column(db.Integer, db.ForeignKey('knowledge_chat_sessions.id'), index=True)

    agent_name = db.Column(db.String(120), nullable=False, index=True)
    action_name = db.Column(db.String(160), nullable=False, index=True)
    model_name = db.Column(db.String(120), index=True)
    model_provider = db.Column(db.String(80), index=True)
    request_id = db.Column(db.String(120), index=True)
    message_role = db.Column(db.String(40), index=True)
    finish_reason = db.Column(db.String(80), index=True)
    status = db.Column(db.String(20), default='success', index=True)
    error_message = db.Column(db.Text)

    message_index = db.Column(db.Integer)
    latency_ms = db.Column(db.Integer)
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    total_tokens = db.Column(db.Integer, default=0, nullable=False, index=True)
    estimated_cost_usd = db.Column(db.Numeric(14, 8), default=Decimal('0'))
    currency = db.Column(db.String(10), default='USD')

    usage_payload = db.Column(db.JSON)
    metadata_payload = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    chat_session = db.relationship('KnowledgeChatSession')

    def __repr__(self):
        return f'<AgentTokenUsage {self.agent_name}:{self.action_name} total={self.total_tokens}>'


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


class KnowledgeChatSession(db.Model):
    """Tabela knowledge_chat_sessions - Conversas do chat da base de conhecimento"""
    __tablename__ = 'knowledge_chat_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, default='Novo chat')
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User')
    law_firm = db.relationship('LawFirm')
    messages = db.relationship(
        'KnowledgeChatHistory',
        back_populates='chat_session',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<KnowledgeChatSession {self.id}>'


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


class JudicialPhase(db.Model):
    """Tabela judicial_phases - Fases processuais configuráveis por escritório."""
    __tablename__ = 'judicial_phases'
    __table_args__ = (
        db.UniqueConstraint('law_firm_id', 'key', name='uq_judicial_phases_law_firm_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)

    key = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    document_types = db.relationship(
        'JudicialDocumentType',
        back_populates='phase',
        cascade='all, delete-orphan'
    )
    process_phase_history = db.relationship(
        'JudicialProcessPhaseHistory',
        back_populates='phase'
    )

    def __repr__(self):
        return f'<JudicialPhase {self.key}>'


class JudicialDocumentType(db.Model):
    """Tabela judicial_document_types - Tipos documentais vinculados a fases processuais."""
    __tablename__ = 'judicial_document_types'
    __table_args__ = (
        db.UniqueConstraint('law_firm_id', 'key', name='uq_judicial_document_types_law_firm_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey('judicial_phases.id'), nullable=False, index=True)

    key = db.Column(db.String(120), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    phase = db.relationship('JudicialPhase', back_populates='document_types')

    def __repr__(self):
        return f'<JudicialDocumentType {self.key}>'


class JudicialLegalThesis(db.Model):
    """Tabela judicial_legal_theses - Teses jurídicas configuráveis por escritório."""
    __tablename__ = 'judicial_legal_theses'
    __table_args__ = (
        db.UniqueConstraint('law_firm_id', 'key', name='uq_judicial_legal_theses_law_firm_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)

    key = db.Column(db.String(120), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    benefits = db.relationship(
        'JudicialProcessBenefit',
        secondary=judicial_process_benefit_legal_theses,
        back_populates='legal_theses'
    )

    def __repr__(self):
        return f'<JudicialLegalThesis {self.key}>'


class JudicialProcess(db.Model):
    """Tabela judicial_processes - Painel centralizado de processos judiciais"""
    __tablename__ = 'judicial_processes'
    
    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey('cases.id'), index=True)  # Opcional - pode não ter caso criado
    court_id = db.Column(db.Integer, db.ForeignKey('courts.id'), index=True)
    plaintiff_client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), index=True)
    defendant_id = db.Column(db.Integer, db.ForeignKey('judicial_defendants.id'), index=True)
    
    # Identificação do processo (CNJ format: NNNNNNN-DD.AAAA.J.TR.OOOO)
    process_number = db.Column(db.String(25), nullable=True, index=True)
    
    # Informações do processo
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    
    # Status
    status = db.Column(db.String(50), default='ativo')  # ativo, suspenso, encerrado, aguardando
    
    # Dados do processo (preenchidos por DataJud ou manualmente)
    judge_name = db.Column(db.String(255))
    tribunal = db.Column(db.String(255))
    section = db.Column(db.String(100))
    origin_unit = db.Column(db.String(255))
    case_value = db.Column(db.Numeric(15, 2))
    filing_date = db.Column(db.Date)
    last_update = db.Column(db.DateTime)  # Última atualização de dados do processo

    # Dados extraídos automaticamente pela IA
    process_class = db.Column(db.String(255))  # Classe processual
    valor_causa_texto = db.Column(db.String(100))  # Valor da causa (texto original)
    assuntos = db.Column(db.JSON)  # Lista de assuntos
    segredo_justica = db.Column(db.Boolean)  # Segredo de justiça
    justica_gratuita = db.Column(db.Boolean)  # Justiça gratuita requerida/deferida
    liminar_tutela = db.Column(db.Boolean)  # Pedido de liminar ou tutela antecipada

    # Notas internas
    internal_notes = db.Column(db.Text)
    
    # Auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    law_firm = db.relationship('LawFirm')
    user = db.relationship('User')
    case = db.relationship('Case', backref='judicial_processes')
    court = db.relationship('Court')
    plaintiff_client = db.relationship('Client', back_populates='judicial_processes_as_plaintiff')
    defendant = db.relationship('JudicialDefendant', back_populates='judicial_processes')
    notes = db.relationship('JudicialProcessNote', back_populates='process', cascade='all, delete-orphan')
    events = db.relationship('JudicialEvent', back_populates='process', cascade='all, delete-orphan')
    benefits = db.relationship('JudicialProcessBenefit', back_populates='process', cascade='all, delete-orphan')
    phase_history = db.relationship(
        'JudicialProcessPhaseHistory',
        back_populates='process',
        cascade='all, delete-orphan',
        order_by='JudicialProcessPhaseHistory.occurred_at.desc()'
    )
    sentence_analyses = db.relationship('JudicialSentenceAnalysis', 
                                       primaryjoin='JudicialProcess.process_number==foreign(JudicialSentenceAnalysis.process_number)',
                                       foreign_keys='[JudicialSentenceAnalysis.process_number]',
                                       viewonly=True)

    @property
    def tribunal_name(self):
        if self.court and self.court.orgao_julgador:
            return self.court.orgao_julgador
        return self.tribunal
    
    def __repr__(self):
        return f'<JudicialProcess {self.process_number}>'


class JudicialProcessNote(db.Model):
    """Tabela judicial_process_notes - Notas e comentários vinculados ao processo judicial."""
    __tablename__ = 'judicial_process_notes'

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    content = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    process = db.relationship('JudicialProcess', back_populates='notes')
    user = db.relationship('User')

    def __repr__(self):
        return f'<JudicialProcessNote {self.id} - Process {self.process_id}>'


class JudicialEvent(db.Model):
    """Tabela judicial_events - Eventos processuais agregadores de movimentações e documentos.

    Exemplos de evento:
    - petição inicial protocolada
    - contestação apresentada
    - sentença proferida
    - apelação interposta
    - audiência realizada
    - documento juntado
    """
    __tablename__ = 'judicial_events'

    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)

    # Tipo do evento (slug): peticao_inicial, contestacao, sentenca, apelacao, etc.
    type = db.Column(db.String(100), nullable=False)

    # Fase do processo: inicio_processo, defesa_reu, julgamento, recursos, execucao
    phase = db.Column(db.String(100), nullable=False)

    description = db.Column(db.Text)
    event_date = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos
    process = db.relationship('JudicialProcess', back_populates='events')
    movements = db.relationship('JudicialMovement', back_populates='event', cascade='all, delete-orphan')
    documents = db.relationship('JudicialDocument', back_populates='event', cascade='all, delete-orphan')
    phase_history_entries = db.relationship('JudicialProcessPhaseHistory', back_populates='source_event')

    def __repr__(self):
        return f'<JudicialEvent {self.type} - Process {self.process_id}>'


class JudicialProcessPhaseHistory(db.Model):
    """Tabela judicial_process_phase_history - Histórico de fases do processo judicial."""
    __tablename__ = 'judicial_process_phase_history'
    __table_args__ = (
        db.Index('ix_jpph_process_occurred_at', 'process_id', 'occurred_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)
    phase_id = db.Column(db.Integer, db.ForeignKey('judicial_phases.id'), nullable=False, index=True)
    source_event_id = db.Column(db.Integer, db.ForeignKey('judicial_events.id'), index=True)
    entered_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    occurred_at = db.Column(db.DateTime, nullable=False, index=True)
    recorded_at = db.Column(db.DateTime)

    judge_name_snapshot = db.Column(db.String(255))
    tribunal_snapshot = db.Column(db.String(255))
    section_snapshot = db.Column(db.String(100))
    origin_unit_snapshot = db.Column(db.String(255))
    location_text = db.Column(db.String(255))

    notes = db.Column(db.Text)
    metadata_payload = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    law_firm = db.relationship('LawFirm')
    process = db.relationship('JudicialProcess', back_populates='phase_history')
    phase = db.relationship('JudicialPhase', back_populates='process_phase_history')
    source_event = db.relationship('JudicialEvent', back_populates='phase_history_entries')
    entered_by_user = db.relationship('User', foreign_keys=[entered_by_user_id])

    def __repr__(self):
        return f'<JudicialProcessPhaseHistory Process {self.process_id} Phase {self.phase_id}>'


class JudicialMovement(db.Model):
    """Tabela judicial_movements - Movimentações cronológicas (timeline) de um evento processual."""
    __tablename__ = 'judicial_movements'

    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('judicial_events.id'), nullable=False, index=True)

    title = db.Column(db.String(255), nullable=False)
    movement_date = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos
    process = db.relationship('JudicialProcess')
    event = db.relationship('JudicialEvent', back_populates='movements')

    def __repr__(self):
        return f'<JudicialMovement {self.title} - Event {self.event_id}>'


class JudicialDocument(db.Model):
    """Tabela judicial_documents - Documentos anexados a um evento processual.

    O documento pode opcionalmente referenciar um item já existente em KnowledgeBase.
    """
    __tablename__ = 'judicial_documents'

    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('judicial_events.id'), nullable=False, index=True)
    knowledge_base_id = db.Column(db.Integer, db.ForeignKey('knowledge_base.id'), index=True)

    type = db.Column(db.String(100), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos
    process = db.relationship('JudicialProcess')
    event = db.relationship('JudicialEvent', back_populates='documents')
    knowledge_base = db.relationship('KnowledgeBase')
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    def __repr__(self):
        return f'<JudicialDocument {self.file_name} - Event {self.event_id}>'


class JudicialProcessBenefit(db.Model):
    """Tabela judicial_process_benefits - Benefícios vinculados ao processo judicial."""
    __tablename__ = 'judicial_process_benefits'
    __table_args__ = (
        db.UniqueConstraint('process_id', 'benefit_number', name='uq_judicial_process_benefit_process_number'),
    )

    id = db.Column(db.Integer, primary_key=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)

    benefit_number = db.Column(db.String(50), nullable=False, index=True)
    nit_number = db.Column(db.String(50), index=True)
    insured_name = db.Column(db.String(255))
    benefit_type = db.Column(db.String(20), index=True)
    fap_vigencia_year = db.Column(db.String(10), index=True)
    legal_thesis_id = db.Column(db.Integer, db.ForeignKey('judicial_legal_theses.id'), index=True)

    legal_thesis = db.Column(db.Text)
    pfn_technical_note = db.Column(db.Text)
    first_instance_decision = db.Column(db.Text)
    second_instance_decision = db.Column(db.Text)
    third_instance_decision = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    process = db.relationship('JudicialProcess', back_populates='benefits')
    legal_theses = db.relationship(
        'JudicialLegalThesis',
        secondary=judicial_process_benefit_legal_theses,
        back_populates='benefits',
        order_by='JudicialLegalThesis.name.asc()'
    )

    def __repr__(self):
        return f'<JudicialProcessBenefit {self.benefit_number} - Process {self.process_id}>'
