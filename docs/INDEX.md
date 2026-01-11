# 📚 Índice de Documentação - Intellexia

Bem-vindo à documentação do **IntellexIA**! Aqui você encontrará guias, tutoriais e referências para trabalhar com o sistema.

## 🎯 Documentação Principal

### Arquitetura e Rotas
- **[ESTRUTURA_BLUEPRINTS.md](ESTRUTURA_BLUEPRINTS.md)** - Guia completo de todas as rotas, endpoints e blueprints do sistema
- **[MIGRACAO_ROTAS.md](MIGRACAO_ROTAS.md)** - Como adicionar novas rotas, criar blueprints e estender o sistema
- **[REORGANIZACAO_ROTAS.md](REORGANIZACAO_ROTAS.md)** - O que mudou na reorganização, benefícios e impacto
- **[ARQUITETURA_VISUAL.md](ARQUITETURA_VISUAL.md)** - Diagramas visuais, fluxos e relacionamentos entre blueprints
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - FAQ, solução de problemas e debugging
- **[RESUMO_REORGANIZACAO.md](RESUMO_REORGANIZACAO.md)** - Resumo executivo da reorganização de código

### Funcionalidades
- **[ASSISTENTE_JURIDICO.md](ASSISTENTE_JURIDICO.md)** - Guia do Assistente Jurídico com IA
- **[AUTENTICACAO.md](AUTENTICACAO.md)** - Sistema de autenticação e segurança
- **[DASHBOARD.md](DASHBOARD.md)** - Dashboard e estatísticas
- **[DADOS_EXEMPLO.md](DADOS_EXEMPLO.md)** - Dados de exemplo para testes

### Ferramentas e Integração
- **[VISUALIZACAO_DOCX.md](VISUALIZACAO_DOCX.md)** - Como visualizar e gerar documentos DOCX
- **[TEMPLATE_FAP_INSTRUCOES.md](TEMPLATE_FAP_INSTRUCOES.md)** - Instruções para trabalhar com templates FAP
- **[INSTRUCOES_PARA_IA.md](INSTRUCOES_PARA_IA.md)** - Guia para integração com IA

### Instalação e Setup
- **[INSTALACAO_RESUMO_DOCUMENTOS.md](INSTALACAO_RESUMO_DOCUMENTOS.md)** - Instalação e configuração de resumo de documentos
- **[QUICKSTART_RESUMO_DOCUMENTOS.md](QUICKSTART_RESUMO_DOCUMENTOS.md)** - Início rápido com resumos

### Resumos
- **[RESUMO_DOCUMENTOS.md](RESUMO_DOCUMENTOS.md)** - Resumo geral de funcionalidades
- **[RESUMO_IMPLEMENTACAO.md](RESUMO_IMPLEMENTACAO.md)** - Resumo de implementação
- **[ARQUITETURA_RESUMO_DOCUMENTOS.md](ARQUITETURA_RESUMO_DOCUMENTOS.md)** - Resumo de arquitetura

### Multi-Tenant
- **[MULTI_TENANT.md](MULTI_TENANT.md)** - Sistema multi-tenant e isolamento de dados

---

## 🚀 Iniciando

### Para Desenvolvedores

1. **Comece por**: [MIGRACAO_ROTAS.md](MIGRACAO_ROTAS.md)
   - Entenda como adicionar novas funcionalidades

2. **Depois leia**: [ESTRUTURA_BLUEPRINTS.md](ESTRUTURA_BLUEPRINTS.md)
   - Conheça todas as rotas disponíveis

3. **Se tiver problemas**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
   - Solução de problemas comuns

### Para Usuários

1. **Comece por**: [DASHBOARD.md](DASHBOARD.md)
   - Entenda o dashboard principal

2. **Explore**: [ASSISTENTE_JURIDICO.md](ASSISTENTE_JURIDICO.md)
   - Use o assistente com IA

3. **Aprenda**: [VISUALIZACAO_DOCX.md](VISUALIZACAO_DOCX.md)
   - Como trabalhar com documentos

---

## 📊 Estrutura do Projeto

```
intellexia/
├── README.md                          ← Voltar para a raiz
├── docs/                              ← 📍 Você está aqui
│   ├── INDEX.md                      ← Índice (este arquivo)
│   ├── ESTRUTURA_BLUEPRINTS.md       ← Rotas principais
│   ├── MIGRACAO_ROTAS.md             ← Como estender
│   ├── ARQUITETURA_VISUAL.md         ← Diagramas
│   ├── TROUBLESHOOTING.md            ← Problemas
│   ├── REORGANIZACAO_ROTAS.md        ← O que mudou
│   ├── RESUMO_REORGANIZACAO.md       ← Resumo
│   └── ... (outros arquivos)
├── app/
│   ├── blueprints/                   ← Rotas organizadas
│   ├── models.py                     ← Modelos DB
│   ├── middlewares.py                ← Autenticação
│   └── ...
├── templates/                        ← Templates HTML
├── static/                           ← CSS, JS, Imagens
└── main.py                           ← Ponto de entrada
```

---

## 🎯 Guias Rápidos

### Adicionar Nova Rota

```python
# 1. Abra app/blueprints/sua_feature.py
# 2. Adicione:
@blueprint_name.route('/nova-rota')
def nova_funcao():
    return render_template('template.html')
```

Veja [MIGRACAO_ROTAS.md](MIGRACAO_ROTAS.md) para mais detalhes.

### Criar Novo Blueprint

Siga o passo-a-passo em [MIGRACAO_ROTAS.md](MIGRACAO_ROTAS.md#como-adicionar-novas-rotas).

### Debugar Problemas

Consulte [TROUBLESHOOTING.md](TROUBLESHOOTING.md) para:
- Erros comuns
- Como debugar
- FAQ

---

## 📞 Suporte

### Documentação Externa
- [Flask Blueprints](https://flask.palletsprojects.com/en/latest/blueprints/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/)
- [Jinja2 Templates](https://jinja.palletsprojects.com/)

### Buscar no Índice

Use `Ctrl+F` ou `Cmd+F` para buscar neste documento:
- Busque por nome de arquivo
- Busque por tema
- Busque por tecnologia

---

## 🏗️ Arquitetura em Alto Nível

```
┌──────────────────────────────────────────┐
│  IntellexIA - Gestão Jurídica com IA    │
├──────────────────────────────────────────┤
│                                          │
│  Frontend (Jinja2 Templates)            │
│  ↓                                       │
│  Flask (main.py)                        │
│  ↓                                       │
│  Blueprints (12 rotas organizadas)      │
│  ├─ auth, dashboard, cases, clients     │
│  ├─ lawyers, courts, benefits           │
│  ├─ documents, petitions, assistant     │
│  ├─ tools, settings                     │
│  ↓                                       │
│  Middlewares (autenticação, validação)  │
│  ↓                                       │
│  Models (SQLAlchemy)                    │
│  ↓                                       │
│  Database (SQLite/MySQL)                │
│                                          │
└──────────────────────────────────────────┘
```

---

## ✅ Checklist de Aprendizado

- [ ] Li o [README.md](../README.md) principal
- [ ] Entendi a [ESTRUTURA_BLUEPRINTS.md](ESTRUTURA_BLUEPRINTS.md)
- [ ] Aprendi a [MIGRACAO_ROTAS.md](MIGRACAO_ROTAS.md)
- [ ] Visualizei a [ARQUITETURA_VISUAL.md](ARQUITETURA_VISUAL.md)
- [ ] Revisei o [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [ ] Testei adicionar uma rota novo
- [ ] Estou pronto para contribuir!

---

## 🎓 Próximos Passos

1. **Explore o código**: Veja `app/blueprints/cases.py` para exemplo
2. **Teste localmente**: Execute `python main.py`
3. **Adicione funcionalidade**: Crie uma pequena feature
4. **Entenda a IA**: Veja [ASSISTENTE_JURIDICO.md](ASSISTENTE_JURIDICO.md)

---

**Última atualização:** 11 de janeiro de 2026  
**Versão:** 1.0  
**Status:** ✅ Documentação Completa
