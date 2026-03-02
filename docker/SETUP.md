# SETUP.md - Guia de Configuração do Ambiente Docker

## 🎯 Objetivo

Configurar o ambiente Docker local com MySQL e Qdrant para desenvolvimento de Intellexia.

## 📋 Checklist de Setup

- [ ] Instalar Docker Desktop para Windows
- [ ] Clonar/atualizar repositório
- [ ] Iniciar containers
- [ ] Configurar variáveis de ambiente
- [ ] Executar migrations/população de dados
- [ ] Testar conexões

## 🔧 Passo 1: Instalação do Docker

### Windows

1. Baixe [Docker Desktop](https://www.docker.com/products/docker-desktop)
2. Execute o instalador
3. Verifique instalação:
   ```cmd
   docker --version
   docker-compose --version
   ```

### Configurar WSL2 para melhor performance

Recomendado para Windows 11:

1. Abra PowerShell como Admin
2. Execute:
   ```powershell
   wsl --install
   wsl --update
   ```
3. No Docker Desktop: Settings → Resources → WSL integration

## 🚀 Passo 2: Iniciar Containers

### Primeira vez

```cmd
cd docker
docker-compose up -d
```

### Verificar status

```cmd
docker-compose ps
```

Espere até que ambos containers mostrem "Up (healthy)".

## 🔐 Passo 3: Credenciais e Configuração

### Atualizar arquivo .env principal

Abra `c:\Users\thiago\projetos\intellexia\.env` e atualize com:

```env
# Database
DATABASE_TYPE=mysql
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=intellexia
MYSQL_PASSWORD=intellexia_password_123
MYSQL_DATABASE=intellexia

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=qdrant_api_key_123

# URL de conexão
DATABASE_URL=mysql+pymysql://intellexia:intellexia_password_123@localhost:3306/intellexia
```

## 📦 Passo 4: Instalar Dependências Python

```bash
cd /path/to/intellexia
uv sync
```

Se precisar instalar pacotes adicionais:

```bash
uv pip install PyMySQL
```

## 🗄️ Passo 5: Inicializar Banco de Dados

### Opção A: Criar todas as tabelas automaticamente

```bash
uv run python main.py
# A aplicação criará as tabelas via SQLAlchemy
```

### Opção B: Popular com dados de exemplo

```bash
uv run python populate_sample_data.py
```

### Passo 6: Teste de Conectividade

#### MySQL

Abra novo terminal:

```bash
cd docker
./manage.bat mysql
```

Ou direto:

```bash
docker exec -it intellexia-mysql mysql -u intellexia -p intellexia_password_123 intellexia
```

Teste query:
```sql
SHOW TABLES;
```

#### Qdrant

Abra navegador:
```
http://localhost:6333/dashboard
```

Ou via CLI:
```bash
curl http://localhost:6333/health
```

## 🔍 Passo 7: Executar Aplicação

### Em desenvolvimento

```bash
uv run python main.py
```

A aplicação rodará em `http://localhost:5000`

### Com reload automático (hot reload)

```bash
uv run flask run --reload
```

### Em production (com Gunicorn)

```bash
uv pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 main:app
```

## 🔗 URLs e Acessos

| Serviço   | URL                    | Usuário          | Senha                    |
|-----------|------------------------|------------------|--------------------------|
| App       | http://localhost:5000  | admin            | (usar login)             |
| Qdrant    | http://localhost:6333  | -                | qdrant_api_key_123       |
| MySQL CLI | localhost:3306         | intellexia       | intellexia_password_123  |
| PHPMyAdmin| http://localhost:8080  | root             | root_password_123        |

## 🛠️ Comandos Úteis

### Ver logs em tempo real

```bash
cd docker
./manage.bat logs mysql      # Logs do MySQL
./manage.bat logs qdrant     # Logs do Qdrant
./manage.bat logs            # Todos os logs
```

### Reiniciar containers

```bash
cd docker
./manage.bat restart
```

### Parar containers

```bash
cd docker
./manage.bat stop
```

### Health check

```bash
cd docker
./manage.bat health
```

### Limpeza total (apaga dados!)

```bash
cd docker
./manage.bat clean
```

## 📁 Estrutura de Arquivos

```
intellexia/
├── docker/
│   ├── docker-compose.yml      ← Orquestração
│   ├── Dockerfile              ← Imagem app (opcional)
│   ├── init-db.sql             ← Setup MySQL
│   ├── qdrant_config.yaml      ← Config Qdrant
│   ├── .env                    ← Vars ambiente
│   ├── manage.sh               ← Script Linux/Mac
│   ├── manage.bat              ← Script Windows
│   ├── README.md               ← Documentação
│   └── SETUP.md                ← Este arquivo
├── .env                        ← Config principal (ATUALIZAR)
├── requirements.txt            ← Deps Python
├── main.py                     ← App Flask
└── ...
```

## 🐛 Troubleshooting

### Erro: "Docker daemon is not running"

Abra a aplicação Docker Desktop

### Erro: "MySQL Access denied"

Verifique credenciais em `docker/.env` e `docker-compose.yml`

Resete o container:
```bash
docker-compose down -v
docker-compose up -d
```

### Erro: "PyMySQL not installed"

```bash
uv pip install PyMySQL
```

### Porta 3306 já em uso

Mude a porta em `docker-compose.yml`:

```yaml
mysql:
  ports:
    - "3307:3306"  # Novo mapeamento
```

Então atualize `.env`:
```env
MYSQL_PORT=3307
```

### Qdrant respondendo lentamente

Verifique espaço em disco e performance de I/O

## ✅ Verificação Final

Após setup completo:

1. ✓ Docker Desktop rodando
2. ✓ Containers MySQL e Qdrant up (healthy)
3. ✓ Consegue conectar ao MySQL
4. ✓ Dashboard Qdrant acessível
5. ✓ Aplicação Flask inicia sem erros
6. ✓ Banco de dados tem tabelas (se ran populate)

## 📚 Próximas Etapas

1. Explore a interface web em http://localhost:5000
2. Teste funcionalidades (se dados populados)
3. Configure integração com OpenAI (OPENAI_API_KEY)
4. Comece desenvolvimento com hot reload

## 🆘 Suporte

Consulte:
- `docker/README.md` - Documentação detalhada Docker
- Logs dos containers: `docker-compose logs -f`
- Documentação oficial: https://docs.docker.com

---

**Última atualização:** 2026-03-02
**Versão:** 1.0
