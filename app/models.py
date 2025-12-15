from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from decimal import Decimal

db = SQLAlchemy()

class Client(db.Model):
    """Tabela clients - Empresas autoras dos casos"""
    __tablename__ = 'clients'
    
    id = db.Column(db.Integer, primary_key=True)
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
    cases = db.relationship('Case', back_populates='client')
    
    def __repr__(self):
        return f'<Client {self.name}>'


class Court(db.Model):
    """Tabela courts - Varas judiciais"""
    __tablename__ = 'courts'
    
    id = db.Column(db.Integer, primary_key=True)
    section = db.Column(db.String(255))  # Seção judiciária
    vara_name = db.Column(db.String(255))  # Nome da vara
    city = db.Column(db.String(150))
    state = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    cases = db.relationship('Case', back_populates='court')
    
    def __repr__(self):
        return f'<Court {self.vara_name}>'


class Lawyer(db.Model):
    """Tabela lawyers - Advogados"""
    __tablename__ = 'lawyers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    oab_number = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    is_default_for_publications = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case_lawyers = db.relationship('CaseLawyer', back_populates='lawyer')
    
    def __repr__(self):
        return f'<Lawyer {self.name} - OAB: {self.oab_number}>'


class Case(db.Model):
    """Tabela cases - Casos jurídicos"""
    __tablename__ = 'cases'
    
    id = db.Column(db.Integer, primary_key=True)
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
    client = db.relationship('Client', back_populates='cases')
    court = db.relationship('Court', back_populates='cases')
    case_lawyers = db.relationship('CaseLawyer', back_populates='case', cascade='all, delete-orphan')
    competences = db.relationship('CaseCompetence', back_populates='case', cascade='all, delete-orphan')
    benefits = db.relationship('CaseBenefit', back_populates='case', cascade='all, delete-orphan')
    documents = db.relationship('Document', back_populates='case', cascade='all, delete-orphan')
    
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
    accident_date = db.Column(db.Date)
    accident_company_name = db.Column(db.String(255))
    error_reason = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='benefits')
    documents = db.relationship('Document', back_populates='related_benefit')
    
    def __repr__(self):
        return f'<CaseBenefit {self.benefit_number}>'


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
    uploaded_by_user_id = db.Column(db.Integer)  # FK de usuário (futuro)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamentos
    case = db.relationship('Case', back_populates='documents')
    related_benefit = db.relationship('CaseBenefit', back_populates='documents')
    
    def __repr__(self):
        return f'<Document {self.original_filename}>'