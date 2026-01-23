# IntellexIA

Sistema inteligente de gestão jurídica para casos de revisão de FAP (Fator Acidentário de Prevenção) e contestação de benefícios acidentários.

## � Documentação

Toda a documentação do projeto está organizada na pasta [`docs/`](docs/):

- **[ESTRUTURA_BLUEPRINTS.md](docs/ESTRUTURA_BLUEPRINTS.md)** - Guia completo de todas as rotas do sistema
- **[MIGRACAO_ROTAS.md](docs/MIGRACAO_ROTAS.md)** - Como adicionar novas rotas e blueprints
- **[REORGANIZACAO_ROTAS.md](docs/REORGANIZACAO_ROTAS.md)** - O que mudou na estrutura de rotas
- **[ARQUITETURA_VISUAL.md](docs/ARQUITETURA_VISUAL.md)** - Diagramas e fluxos visuais da arquitetura
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - FAQ e solução de problemas
- **[RESUMO_REORGANIZACAO.md](docs/RESUMO_REORGANIZACAO.md)** - Resumo completo da reorganização

Veja a pasta [`docs/`](docs/) para documentação adicional sobre funcionalidades, autenticação, dashboards e mais.

## �📋 Sobre o Sistema

O **IntellexIA** é uma plataforma desenvolvida para escritórios de advocacia especializados em direito previdenciário e trabalhista, focada na gestão de casos de contestação de benefícios acidentários que impactam o FAP das empresas.

### 🎯 Objetivo

Auxiliar advogados na contestação de benefícios B91 (Auxílio-Acidente) e B94 (Auxílio-Doença Acidentário) que foram concedidos indevidamente pelo INSS, reduzindo assim o FAP das empresas clientes e diminuindo seus custos previdenciários.

## � Tecnologias

- **Backend**: Flask + SQLAlchemy
- **Banco de Dados**: SQLite (dev) / MySQL (prod)
- **Gerenciador de Dependências**: uv
- **Python**: 3.13+

## 🚀 Instalação e Configuração

### Pré-requisitos
- Python 3.13+
- uv (gerenciador de dependências)
- MySQL 8.0+ (apenas para produção)

### 1. Clonar o repositório
```bash
git clone <repository-url>
cd intellexia
```

### 2. Instalar dependências
```bash
# Desenvolvimento (SQLite)
uv sync

# Produção (adicionar suporte MySQL)
uv sync --extra production
```

### 3. Configurar ambiente
```bash
# Copiar arquivo de configuração
cp .env.example .env

# Editar configurações conforme necessário
# Por padrão usa SQLite em desenvolvimento
```

### 4. Executar aplicação
```bash
uv run python main.py
```
(As tabelas serão criadas automaticamente na primeira execução)

## 📁 Estrutura do Banco de Dados

O sistema utiliza SQLAlchemy com os seguintes models:

### 🏢 Client (Clientes)
- Dados das empresas autoras dos processos
- CNPJ, endereço e informações de filiais
- Relacionamento 1:N com casos

### ⚖️ Case (Casos)
- Processos judiciais principais
- Tipos: FAP Trajeto, FAP Outros, etc.
- Status, valores e datas importantes
- Relacionamentos com clientes, varas e advogados

### 🏛️ Court (Varas)
- Varas judiciais onde os processos tramitam
- Seção judiciária, cidade e estado

### 👨‍⚖️ Lawyer (Advogados)
- Advogados responsáveis pelos casos
- OAB, contatos e função (publicações, responsável, etc.)

### 🎯 CaseBenefit (Benefícios)
- Benefícios B91/B94 contestados
- Dados do segurado e do acidente
- Relacionados aos casos

### 📄 Document (Documentos)
- CATs, laudos médicos, relatórios
- Controle de upload e uso em IA
- Relacionados aos casos e benefícios

### 📅 CaseCompetence (Competências)
- Períodos de competência dos casos
- Status: válido ou prescrito

## ⚙️ Configuração de Ambiente

O sistema utiliza um arquivo `.env` para configurar o ambiente:

```bash
# development = SQLite (padrão)
# production = MySQL
ENVIRONMENT=development

# Configurações MySQL (apenas para produção)
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=sua_senha
MYSQL_DATABASE=intellexia
```

### 🗄️ Bancos de Dados por Ambiente:

- **Desenvolvimento**: SQLite (`instance/intellexia.db`) - Zero configuração
- **Produção**: MySQL - Requer configuração das variáveis

## 💻 Uso dos Models

### Exemplo básico
```python
from app.models import db, Client, Case, Lawyer

# Criar cliente
client = Client(
    name="Exemplo Empresa Ltda",
    cnpj="12.345.678/0001-90",
    city="São Paulo",
    state="SP"
)
db.session.add(client)
db.session.commit()

# Consultar casos de um cliente
cases = Case.query.filter_by(client_id=client.id).all()
```

### Exemplo de uso
```python
from app.models import db, Client, Case
from main import app

with app.app_context():
    # Criar cliente
    client = Client(name="Empresa Teste", cnpj="12.345.678/0001-90")
    db.session.add(client)
    db.session.commit()
```

## �🚀 Funcionalidades

### 📁 Gestão de Clientes
- Cadastro de empresas (Pessoas Jurídicas)
- Controle de dados cadastrais e endereços
- Gerenciamento de filiais
- CNPJ e informações fiscais

### ⚖️ Gestão de Casos
- Criação e acompanhamento de processos judiciais
- Tipos de caso: FAP Trajeto, FAP Outros, Previdenciário, Trabalhista
- Controle de anos FAP (período de revisão)
- Status do processo: Rascunho, Ativo, Suspenso, Encerrado, Arquivado
- Resumo de fatos, teses jurídicas e informações de prescrição
- Valor da causa e data de ajuizamento

### 👨‍⚖️ Gestão de Advogados
- Cadastro de advogados responsáveis
- Número da OAB, contato e email
- Configuração de advogado padrão para publicações
- Vinculação de advogados aos casos

### 🏛️ Gestão de Varas Judiciais
- Cadastro de varas federais
- Seção judiciária e comarca
- Vinculação de casos às varas competentes

### 💼 Gestão de Benefícios
Sistema de registro e contestação de benefícios previdenciários:

#### Tipos de Benefícios
- **B91 - Auxílio-Acidente**: Benefício permanente por sequelas de acidente
- **B94 - Auxílio-Doença Acidentário**: Benefício temporário durante afastamento

#### Motivos de Contestação
- **Ausência de Nexo Causal**: O acidente não tem relação com o trabalho
- **Acidente de Trajeto**: Ocorreu no percurso casa-trabalho (não deve impactar FAP)
- **Acidente Fora da Empresa**: Não aconteceu nas dependências da empresa
- **Outros motivos**: Casos específicos

#### Informações Registradas
- Número do benefício
- Dados do segurado (nome, NIT/PIS)
- Data e local do acidente
- Empresa onde ocorreu o acidente (pode ser terceirizada)
- Observações e notas do caso

### 📄 Gestão de Documentos
Sistema integrado de documentos vinculados aos casos:

#### Tipos de Documentos Suportados
- **CAT** - Comunicação de Acidente de Trabalho
- **Laudo Médico** - Laudos periciais e médicos
- **INFBEN** - Informações de Benefícios do INSS
- **CNIS** - Cadastro Nacional de Informações Sociais
- **Contrato Social** - Documentos da empresa
- **Procuração** - Poderes dos advogados
- **Outros** - Documentos complementares

#### Recursos
- Upload de arquivos (PDF, DOC, DOCX, JPG, PNG)
- Vinculação opcional a benefícios específicos
- Controle de uso pela IA para geração de petições
- Descrição e categorização
- Download e visualização

### 🖼️ Inserção Automática de Imagens em Petições (NOVO!)
Sistema avançado de inserção de imagens de documentos em petições Word:

#### ⚡ Como Funciona
1. **Anexar Documento**: Faça upload de CAT, FAP, INFBEN ou outros documentos ao caso
2. **Selecionar Tipo**: Escolha o tipo correto do documento (CAT, FAP, INFBEN, etc.)
3. **Usar Placeholder**: No template Word, use `{{imagem_cat}}`, `{{imagem_fap}}`, etc.
4. **Gerar Petição**: A imagem é inserida automaticamente no local do placeholder!

#### 🏷️ Placeholders Disponíveis
- `{{imagem_cat}}` - Comunicação de Acidente de Trabalho
- `{{imagem_fap}}` - Fator Acidentário de Prevenção
- `{{imagem_info_beneficiario}}` - INFBEN
- `{{imagem_declaracao_beneficio}}` - Declaração de Benefício
- `{{imagem_inss_beneficiario}}` - CNIS
- `{{imagem_vigencia_beneficio}}` - Vigência do Benefício

#### 📋 Formatos Suportados
- **PDFs**: Primeira página convertida automaticamente (150 DPI)
- **Imagens**: PNG, JPG, JPEG, BMP, GIF

#### 🔧 Recursos Técnicos
- Conversão automática PDF → Imagem com `pdf2image`
- Redimensionamento inteligente (6" parágrafos, 5" tabelas)
- Centralização automática
- Tratamento gracioso de erros (se uma imagem falhar, as outras continuam)
- Preservação de qualidade (150 DPI)

#### 📚 Documentação Completa
- **[Quickstart](docs/QUICKSTART_IMAGENS_PETICOES.md)** - Início rápido em 3 passos
- **[Documentação](docs/INSERCAO_IMAGENS_DOCUMENTOS.md)** - Guia completo
- **[Testes](docs/TESTE_INSERCAO_IMAGENS.md)** - Como testar e validar
- **[Exemplos](docs/TEMPLATE_EXEMPLO_IMAGENS.md)** - Templates de exemplo

#### ⚙️ Pré-requisito: Poppler
Para converter PDFs, instale o Poppler:

**Windows (Chocolatey):**
```bash
choco install poppler
```

**Windows (Scoop):**
```bash
scoop install poppler
```

**Linux:**
```bash
sudo apt-get install poppler-utils
```

**macOS:**
```bash
brew install poppler
```

### 🤖 Integração com IA (Planejado)
- Análise automática de documentos
- Extração de informações relevantes
- Geração de petições e peças processuais
- Sugestão de teses jurídicas baseadas no contexto

## 🛠️ Tecnologias

### Backend
- **Python 3.x**
- **Flask** - Framework web
- **Flask-WTF** - Formulários com validação
- **WTForms** - Geração e validação de formulários

### Frontend
- **AdminLTE 4** - Template administrativo baseado em Bootstrap 5
- **Bootstrap 5** - Framework CSS
- **Bootstrap Icons** - Ícones
- **Jinja2** - Template engine

### Banco de Dados
- **MySQL** - Banco de dados relacional
- Schema completo com relacionamentos entre entidades

## 📦 Instalação

### Pré-requisitos
- Python 3.8+
- MySQL 8.0+
- uv (gerenciador de pacotes Python)

### Passos

1. Clone o repositório:
```bash
git clone https://github.com/thiagoscheidt/intellexia.git
cd intellexia
```

2. Crie e configure o banco de dados:
```bash
mysql -u root -p < banco.sql
```

3. Instale as dependências:
```bash
uv sync
```

4. Configure as variáveis de ambiente:
```bash
export SECRET_KEY="sua-chave-secreta-aqui"
export DATABASE_URL="mysql://user:password@localhost/intellexia"
```

5. Execute a aplicação:
```bash
uv run main.py
```

6. Acesse no navegador:
```
http://localhost:5000
```

### Credenciais de Teste
- **Email**: admin@intellexia.com.br
- **Senha**: admin123

## 📁 Estrutura do Projeto

```
intellexia/
├── app/
│   ├── form.py              # Formulários WTForms
│   └── __pycache__/
├── templates/
│   ├── layout/
│   │   └── base.html        # Template base
│   ├── partials/
│   │   ├── header.html      # Cabeçalho
│   │   ├── sidebar.html     # Menu lateral
│   │   └── footer.html      # Rodapé
│   ├── cases/               # Templates de casos
│   │   ├── list.html
│   │   ├── form.html
│   │   ├── detail.html
│   │   ├── documents_list.html
│   │   └── document_form.html
│   ├── clients/             # Templates de clientes
│   │   ├── list.html
│   │   └── form.html
│   ├── lawyers/             # Templates de advogados
│   │   ├── list.html
│   │   └── form.html
│   ├── courts/              # Templates de varas
│   │   ├── list.html
│   │   └── form.html
│   ├── benefits/            # Templates de benefícios
│   │   ├── list.html
│   │   └── form.html
│   ├── login.html
│   ├── register.html
│   └── dashboard1.html
├── static/
│   ├── css/                 # AdminLTE CSS
│   ├── js/                  # AdminLTE JS
│   └── assets/              # Imagens e recursos
├── main.py                  # Arquivo principal
├── routes.py                # Rotas da aplicação
├── banco.sql                # Schema do banco de dados
├── pyproject.toml           # Dependências do projeto
└── README.md
```

## 🔒 Segurança

- Sessões seguras com Flask
- Validação de formulários server-side
- Proteção contra CSRF
- Controle de acesso por sessão
- Validação de tipos de arquivo no upload

## 🗃️ Modelo de Dados

### Entidades Principais

1. **Clients** (Clientes/Empresas)
   - Dados cadastrais da empresa
   - CNPJ, endereço, filiais

2. **Cases** (Casos Jurídicos)
   - Informações do processo
   - Relacionado a um cliente
   - Pode ter vários benefícios e documentos

3. **Lawyers** (Advogados)
   - Dados profissionais
   - OAB, contato
   - Vinculação aos casos

4. **Courts** (Varas Judiciais)
   - Seção judiciária
   - Localização e competência

5. **Case Benefits** (Benefícios)
   - Benefícios contestados (B91, B94)
   - Dados do segurado
   - Informações do acidente

6. **Documents** (Documentos)
   - Arquivos do caso
   - Tipos categorizados
   - Controle de uso na IA

### Relacionamentos
```
Clients (1) ──→ (N) Cases
Cases (1) ──→ (N) Benefits
Cases (1) ──→ (N) Documents
Cases (N) ←──→ (N) Lawyers (case_lawyers)
Courts (1) ──→ (N) Cases
Benefits (1) ←── (N) Documents (opcional)
```

## 🚧 Roadmap

### Em Desenvolvimento
- [ ] Integração com banco de dados MySQL
- [ ] Sistema de autenticação completo
- [ ] Upload real de arquivos
- [ ] Módulo de IA para análise de documentos
- [ ] Geração automática de petições

### Futuras Implementações
- [ ] Dashboard com estatísticas e gráficos
- [ ] Relatórios em PDF
- [ ] Agenda e lembretes de prazos
- [ ] Integração com e-mail
- [ ] API REST para integrações
- [ ] Controle de versões de documentos
- [ ] Sistema de notificações
- [ ] Módulo financeiro

## 👥 Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## 📝 Licença

Este projeto é proprietário. Todos os direitos reservados.

## 📧 Contato

**Desenvolvedor**: Thiago Scheidt
**GitHub**: [@thiagoscheidt](https://github.com/thiagoscheidt)
**Projeto**: [intellexia](https://github.com/thiagoscheidt/intellexia)

