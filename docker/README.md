# Docker Setup - Intellexia

Este diretório contém os arquivos para executar Intellexia em containers Docker.

## 📋 Pré-requisitos

- Docker Engine 20.10 ou superior
- Docker Compose 1.29 ou superior

### Instalação Docker (Windows)

1. Baixe [Docker Desktop para Windows](https://www.docker.com/products/docker-desktop)
2. Instale seguindo as instruções
3. Configure o WSL 2 (Windows Subsystem for Linux)

## 🚀 Iniciando os Serviços

### 1. Iniciar MySQL e Qdrant

```bash
cd docker
docker-compose up -d
```

**Parâmetros opcionais:**
- `-d` : Rodar em background (detached mode)
- `--build` : Rebuildar as imagens
- `-v` : Verbose (mostrar logs)

### 2. Verificar Status

```bash
docker-compose ps
```

Você deve ver algo como:

```
NAME                  STATUS
intellexia-mysql      Up (healthy)
intellexia-qdrant     Up (healthy)
```

### 3. Parar os Serviços

```bash
docker-compose down
```

### 4. Remover Dados Persistidos (Limpar Banco)

```bash
docker-compose down -v
```

Aviso: Isso deletará todos os dados no MySQL e Qdrant!

## 📊 Acessar os Serviços

### MySQL

```bash
# Via MySQL client
mysql -h localhost -u intellexia -p intellexia_password_123 -D intellexia

# Via Docker
docker exec -it intellexia-mysql mysql -u intellexia -p intellexia_password_123 intellexia
```

**Credenciais:**
- Host: `localhost` (ou `mysql` dentro da rede docker)
- Port: `3306`
- User: `intellexia`
- Password: `intellexia_password_123`
- Database: `intellexia`

### Qdrant

```bash
# Interface Web
http://localhost:6333/dashboard

# API REST
curl http://localhost:6333/health

# Ou da aplicação dentro da rede docker:
http://qdrant:6333
```

**Credenciais:**
- Host: `localhost` (ou `qdrant` dentro da rede docker)
- Port: `6333` (HTTP)
- Port: `6334` (gRPC)
- API Key: `qdrant_api_key_123`

## 🔧 Arquivos de Configuração

- **docker-compose.yml** - Orquestração dos containers
- **init-db.sql** - Script de inicialização do MySQL
- **qdrant_config.yaml** - Configuração do Qdrant
- **.env** - Variáveis de ambiente
- **Dockerfile** - Imagem para aplicação Intellexia

## 📝 Configurações Personalizadas

### Mudar Portas

Edite `docker-compose.yml` e altere os ports:

```yaml
mysql:
  ports:
    - "3307:3306"  # Mapeamento: HOST:CONTAINER

qdrant:
  ports:
    - "6334:6333"
```

### Mudar Senhas

Edite `.env` ou `docker-compose.yml`:

```yaml
environment:
  MYSQL_ROOT_PASSWORD: sua_nova_senha
  MYSQL_PASSWORD: nova_senha_user
  QDRANT_API_KEY: sua_nova_chave
```

Depois recrie os containers:

```bash
docker-compose down -v
docker-compose up -d
```

### Persistência de Dados

Os dados são guardados em volumes Docker:

- `mysql_data` - Dados do MySQL
- `qdrant_data` - Índices do Qdrant

Para listar volumes:

```bash
docker volume ls | grep intellexia
```

Para inspecionar um volume:

```bash
docker volume inspect docker_mysql_data
```

## 🐛 Troubleshooting

### Containers não iniciam

```bash
docker-compose logs -f
```

### MySQL recusa conexão

Aguarde alguns segundos para ele iniciar completamente. Verifique com:

```bash
docker-compose ps
# Coluna STATUS deve mostrar "(healthy)"
```

### Limpar tudo completamente

```bash
docker-compose down -v --remove-orphans
docker system prune -a
docker-compose up -d
```

### Ver logs em tempo real

```bash
docker-compose logs -f mysql
docker-compose logs -f qdrant
```

## 🏗️ Construir Imagem da Aplicação

Se você quer rodar a aplicação em container também:

```bash
# Build
docker build -t intellexia:latest -f ./Dockerfile ..

# Run (na rede docker)
docker run --network docker_intellexia-network \
  -p 5000:5000 \
  --env-file .env \
  intellexia:latest
```

Ou adicione ao `docker-compose.yml`:

```yaml
services:
  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "5000:5000"
    environment:
      DATABASE_URL: mysql+pymysql://intellexia:intellexia_password_123@mysql:3306/intellexia
    depends_on:
      mysql:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    networks:
      - intellexia-network
    restart: unless-stopped
```

## 📦 Próximas Etapas

1. Atualize o `.env` principal com as credenciais Docker
2. Configure a aplicação para conectar ao MySQL Docker:

```python
# Em main.py ou .env
DATABASE_URL = "mysql+pymysql://intellexia:intellexia_password_123@localhost:3306/intellexia"
```

3. Execute `uv run python populate_sample_data.py` para carregar dados iniciais

## 🔗 Recursos Úteis

- [Docker Compose Docs](https://docs.docker.com/compose/)
- [MySQL Docker](https://hub.docker.com/_/mysql)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [Docker on Windows](https://docs.docker.com/desktop/install/windows-install/)
