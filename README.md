# IntellexIA

Sistema inteligente de gestão jurídica para casos de revisão de FAP (Fator Acidentário de Prevenção) e contestação de benefícios acidentários.

## 📋 Sobre o Sistema

O **IntellexIA** é uma plataforma desenvolvida para escritórios de advocacia especializados em direito previdenciário e trabalhista, focada na gestão de casos de contestação de benefícios acidentários que impactam o FAP das empresas.

### 🎯 Objetivo

Auxiliar advogados na contestação de benefícios B91 (Auxílio-Acidente) e B94 (Auxílio-Doença Acidentário) que foram concedidos indevidamente pelo INSS, reduzindo assim o FAP das empresas clientes e diminuindo seus custos previdenciários.

## 🚀 Funcionalidades

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

