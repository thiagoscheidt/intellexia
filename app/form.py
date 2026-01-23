from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, PasswordField, SubmitField, TextAreaField,
    SelectField, IntegerField, DecimalField, DateField,
    BooleanField, HiddenField
)
from wtforms.validators import DataRequired, Length, Email, Optional, NumberRange


# ========================
# Formulário: Clients (Empresas Autoras)
# ========================
class ClientForm(FlaskForm):
    name = StringField('Razão Social', validators=[DataRequired(), Length(min=2, max=255)])
    cnpj = StringField('CNPJ', validators=[DataRequired(), Length(min=14, max=20)])
    street = StringField('Rua', validators=[Optional(), Length(max=255)])
    number = StringField('Número', validators=[Optional(), Length(max=20)])
    district = StringField('Bairro', validators=[Optional(), Length(max=150)])
    city = StringField('Cidade', validators=[Optional(), Length(max=150)])
    state = StringField('Estado (UF)', validators=[Optional(), Length(max=50)])
    zip_code = StringField('CEP', validators=[Optional(), Length(max=20)])
    has_branches = BooleanField('Possui Filiais?')
    branches_description = TextAreaField('Descrição das Filiais', validators=[Optional()])
    submit = SubmitField('Salvar Cliente')


# ========================
# Formulário: Courts (Varas Judiciais)
# ========================
class CourtForm(FlaskForm):
    section = StringField('Seção Judiciária', validators=[Optional(), Length(max=255)])
    vara_name = StringField('Nome da Vara', validators=[Optional(), Length(max=255)])
    city = StringField('Cidade', validators=[Optional(), Length(max=150)])
    state = StringField('Estado (UF)', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Salvar Vara')


# ========================
# Formulário: Lawyers (Advogados)
# ========================
class LawyerForm(FlaskForm):
    name = StringField('Nome Completo', validators=[DataRequired(), Length(min=2, max=255)])
    oab_number = StringField('Número da OAB', validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=255)])
    phone = StringField('Telefone', validators=[Optional(), Length(max=50)])
    is_default_for_publications = BooleanField('Advogado Padrão para Publicações?')
    submit = SubmitField('Salvar Advogado')


# ========================
# Formulário: Cases (Casos)
# ========================
class CaseForm(FlaskForm):
    # Step 1: Informações Básicas
    client_id = SelectField('Cliente (Empresa Autora)', coerce=int, validators=[DataRequired()])
    court_id = SelectField('Vara Judicial', coerce=int, validators=[Optional()])
    title = StringField('Título do Caso', validators=[DataRequired(), Length(min=2, max=255)])
    case_type = SelectField(
        'Tipo de Caso',
        choices=[
            ('fap_trajeto', 'FAP - Acidente de Trajeto'),
            ('fap_outros', 'FAP - Outros'),
            ('previdenciario', 'Previdenciário'),
            ('trabalhista', 'Trabalhista'),
            ('outros', 'Outros')
        ],
        validators=[DataRequired()]
    )
    status = SelectField(
        'Status',
        choices=[
            ('draft', 'Rascunho'),
            ('active', 'Ativo'),
            ('suspended', 'Suspenso'),
            ('closed', 'Encerrado'),
            ('archived', 'Arquivado')
        ],
        default='draft',
        validators=[DataRequired()]
    )
    filing_date = DateField('Data de Ajuizamento', format='%Y-%m-%d', validators=[Optional()])
    
    # Step 2: Informações FAP
    fap_reason = SelectField(
        'Motivo / Enquadramento',
        choices=[
            ('', 'Selecione um motivo'),
            ('inclusao_indevida_trajeto', 'Inclusão indevida de benefício de trajeto'),
            ('erro_material_cat', 'Erro material no preenchimento da CAT'),
            ('cat_trajeto_extemporanea', 'CAT de trajeto transmitida extemporaneamente')
        ],
        validators=[Optional()]
    )
    fap_start_year = IntegerField(
        'Ano Inicial FAP',
        validators=[Optional(), NumberRange(min=1900, max=2100)]
    )
    fap_end_year = IntegerField(
        'Ano Final FAP',
        validators=[Optional(), NumberRange(min=1900, max=2100)]
    )
    value_cause = DecimalField(
        'Valor da Causa (R$)',
        places=2,
        validators=[Optional(), NumberRange(min=0)]
    )
    
    # Step 3: Resumos
    facts_summary = TextAreaField('Resumo dos Fatos', validators=[Optional()])
    thesis_summary = TextAreaField('Resumo das Teses Jurídicas', validators=[Optional()])
    prescription_summary = TextAreaField('Informações sobre Prescrição', validators=[Optional()])
    
    # Campo hidden para controlar o step atual
    current_step = HiddenField('Current Step', default='1')
    
    submit = SubmitField('Próximo')


# ========================
# Formulário: Case Lawyers (Advogados do Caso)
# ========================
class CaseLawyerForm(FlaskForm):
    case_id = SelectField('Caso', coerce=int, validators=[DataRequired()])
    lawyer_id = SelectField('Advogado', coerce=int, validators=[DataRequired()])
    role = StringField('Função/Papel', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Adicionar Advogado ao Caso')


# ========================
# Formulário: Case Competences (Competências do Caso)
# ========================
class CaseCompetenceForm(FlaskForm):
    case_id = SelectField('Caso', coerce=int, validators=[DataRequired()])
    competence_month = IntegerField(
        'Mês da Competência',
        validators=[DataRequired(), NumberRange(min=1, max=12)]
    )
    competence_year = IntegerField(
        'Ano da Competência',
        validators=[DataRequired(), NumberRange(min=1900, max=2100)]
    )
    status = SelectField(
        'Situação',
        choices=[
            ('prescribed', 'Prescrito'),
            ('valid', 'Válido')
        ],
        validators=[DataRequired()]
    )
    submit = SubmitField('Salvar Competência')


# ========================
# Formulário: Case Benefits (Benefícios) - Versão Global
# ========================
class CaseBenefitForm(FlaskForm):
    case_id = SelectField('Caso', coerce=int, validators=[DataRequired()])
    benefit_number = StringField('Número do Benefício', validators=[DataRequired(), Length(max=50)])
    benefit_type = SelectField(
        'Tipo de Benefício',
        choices=[
            ('B91', 'B91 - Auxílio-doença acidentário'),
            ('B92', 'B92 - Aposentadoria por invalidez acidentária'),
            ('B93', 'B93 - Pensão por morte acidentária'),
            ('B94', 'B94 - Auxílio-acidente'),
            ('outros', 'Outros')
        ],
        validators=[DataRequired()]
    )
    insured_name = StringField('Nome do Segurado', validators=[DataRequired(), Length(max=255)])
    insured_nit = StringField('NIT/PIS do Segurado', validators=[Optional()])
    numero_cat = StringField('Número da CAT', validators=[Optional(), Length(max=100)])
    numero_bo = StringField('Número do BO', validators=[Optional(), Length(max=100)])
    data_inicio_beneficio = DateField('Início do Benefício', format='%Y-%m-%d', validators=[Optional()])
    data_fim_beneficio = DateField('Fim do Benefício', format='%Y-%m-%d', validators=[Optional()])
    accident_date = DateField('Data do Acidente', format='%Y-%m-%d', validators=[Optional()])
    accident_company_name = StringField(
        'Empresa onde ocorreu o Acidente',
        validators=[Optional(), Length(max=255)]
    )
    error_reason = SelectField(
        'Motivo da Contestação',
        choices=[
            ('nexo_causal', 'Ausência de Nexo Causal'),
            ('trajeto', 'Acidente de Trajeto'),
            ('fora_empresa', 'Acidente Fora da Empresa'),
            ('outros', 'Outros')
        ],
        validators=[Optional()]
    )
    notes = TextAreaField('Observações Adicionais', validators=[Optional()])
    submit = SubmitField('Salvar Benefício')


# ========================
# Formulário: Case Benefits (Benefícios) - Versão Contextual (dentro do caso)
# ========================
class CaseBenefitContextForm(FlaskForm):
    # Não inclui case_id pois será definido automaticamente pela URL
    benefit_number = StringField('Número do Benefício', validators=[DataRequired(), Length(max=50)])
    benefit_type = SelectField(
        'Tipo de Benefício',
        choices=[
            ('B91', 'B91 - Auxílio-doença acidentário'),
            ('B92', 'B92 - Aposentadoria por invalidez acidentária'),
            ('B93', 'B93 - Pensão por morte acidentária'),
            ('B94', 'B94 - Auxílio-acidente'),
            ('outros', 'Outros')
        ],
        validators=[DataRequired()]
    )
    insured_name = StringField('Nome do Segurado', validators=[DataRequired(), Length(max=255)])
    insured_nit = StringField('NIT/PIS do Segurado', validators=[Optional()])
    numero_cat = StringField('Número da CAT', validators=[Optional(), Length(max=100)])
    numero_bo = StringField('Número do BO', validators=[Optional(), Length(max=100)])
    data_inicio_beneficio = DateField('Início do Benefício', format='%Y-%m-%d', validators=[Optional()])
    data_fim_beneficio = DateField('Fim do Benefício', format='%Y-%m-%d', validators=[Optional()])
    accident_date = DateField('Data do Acidente', format='%Y-%m-%d', validators=[Optional()])
    accident_company_name = StringField(
        'Empresa onde ocorreu o Acidente',
        validators=[Optional(), Length(max=255)]
    )
    error_reason = SelectField(
        'Motivo da Contestação',
        choices=[
            ('nexo_causal', 'Ausência de Nexo Causal'),
            ('trajeto', 'Acidente de Trajeto'),
            ('fora_empresa', 'Acidente Fora da Empresa'),
            ('outros', 'Outros')
        ],
        validators=[Optional()]
    )
    notes = TextAreaField('Observações Adicionais', validators=[Optional()])
    submit = SubmitField('Salvar Benefício')


# ========================
# Formulário: Documents (Documentos do Caso)
# ========================
class DocumentForm(FlaskForm):
    # case_id virá da URL, não precisa estar no formulário
    related_benefit_id = SelectField('Benefício Relacionado (Opcional)', coerce=int, validators=[Optional()])
    file = FileField(
        'Selecione o Arquivo',
        validators=[DataRequired(), FileAllowed(['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'], 'Apenas documentos e imagens!')]
    )
    document_type = SelectField(
        'Tipo de Documento',
        choices=[
            ('cat', 'CAT - Comunicação de Acidente de Trabalho'),
            ('extrato_beneficio', 'Extrato de Benefício Previdenciário'),
            ('decisao_administrativa', 'Decisão Administrativa do INSS'),
            ('calculo_judicial', 'Cálculo Judicial Previdenciário'),
            ('peticao_inicial', 'Petição Inicial'),
            ('laudo_medico', 'Laudo Médico'),
            ('laudo_medico_administrativo', 'Laudo Médico Administrativo (INSS)'),
            ('laudo_pericial_judicial', 'Laudo Pericial Judicial - Medicina do Trabalho'),
            ('laudo_psiquiatrico', 'Laudo Psiquiátrico Judicial'),
            ('sentenca_judicial', 'Sentença Judicial'),
            ('infben', 'INFBEN - Informações de Benefícios'),
            ('cnis', 'CNIS - Cadastro Nacional de Informações Sociais'),
            ('contrato_social', 'Contrato Social'),
            ('procuracao', 'Procuração'),
            ('outros', 'Outros')
        ],
        validators=[DataRequired()]
    )
    description = TextAreaField('Descrição (Opcional)', validators=[Optional()])
    use_in_ai = BooleanField('Usar na IA?', default=True)
    submit = SubmitField('Enviar Documento')


# ========================
# Formulários de Autenticação e Usuário
# ========================
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Senha', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Entrar')


class RegisterForm(FlaskForm):
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Senha', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Senha', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Registrar')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField('Enviar Link de Recuperação')


# ========================
# Formulário: AI Document Summary
# ========================
class AiDocumentSummaryForm(FlaskForm):
    file = FileField(
        'Documento',
        validators=[
            DataRequired(),
            FileAllowed(['pdf', 'docx', 'txt', 'doc'], 'Somente arquivos PDF, DOCX ou TXT são permitidos!')
        ]
    )
    submit = SubmitField('Enviar para Resumo')