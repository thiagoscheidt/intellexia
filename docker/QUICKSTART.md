# QUICKSTART.md - Comece em 5 minutos

⚡ **Guia rápido para começar com Docker + Intellexia**

## 1️⃣ Instalar Docker (primeira vez)

Baixe e instale [Docker Desktop](https://www.docker.com/download) para seu SO.

Verifique:
```bash
docker --version
docker-compose --version
```

## 2️⃣ Iniciar Containers

Abra terminal na pasta `docker`:

```bash
cd docker
docker-compose up -d
```

Aguarde ~30 segundos. Verificar:

```bash
docker-compose ps
```

Deve mostrar:
```
NAME           STATUS
intellexia-mysql    Up (healthy)
intellexia-qdrant   Up (healthy)
```

## 3️⃣ Atualizar .env

Edite `../.env` (pasta raiz do projeto):

```env
DATABASE_TYPE=mysql
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=intellexia
MYSQL_PASSWORD=intellexia_password_123
MYSQL_DATABASE=intellexia

QDRANT_HOST=localhost
QDRANT_PORT=6333

DATABASE_URL=mysql+pymysql://intellexia:intellexia_password_123@localhost:3306/intellexia
```

## 4️⃣ Instalar Dependências

Na pasta raiz:

```bash
uv sync
uv pip install PyMySQL  # Para MySQL (se necessário)
```

## 5️⃣ Rodar Aplicação

```bash
uv run python main.py
```

Vai criar tabelas automaticamente. Acesse: **http://localhost:5000**

## 🎁 Bônus: Popular com Dados Exemplo

```bash
uv run python populate_sample_data.py
```

---

## ⚡ Próximos Comandos Úteis

### Ver logs
```bash
docker-compose logs -f
```

### Parar
```bash
docker-compose down
```

### Reiniciar
```bash
docker-compose restart
```

### Acessar MySQL
```bash
./manage.bat mysql
```

### Acessar Qdrant
```
http://localhost:6333/dashboard
```

---

## 🚨 Problemas?

### Docker não inicia?
- Abra Docker Desktop
- Aguarde carregar completamente

### MySQL recusa conexão?
- Aguarde 10 segundos após `up -d`
- Verifique credenciais no `.env`

### Porta já em uso?
Edite `docker-compose.yml` e mude as portas

---

**Mais help?** Leia `docker/SETUP.md` ou `docker/README.md`

Boa sorte! 🚀
