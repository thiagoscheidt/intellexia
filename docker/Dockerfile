# Dockerfile para Intellexia
# Build: docker build -t intellexia:latest -f Dockerfile .
# Run: docker run -p 5000:5000 --network intellexia-network intellexia:latest

FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    mysql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependências Python com uv
RUN pip install uv && uv pip install -r requirements.txt

# Copiar projeto
COPY . .

# Expor porta
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:5000/health || exit 1

# Comando de inicialização
CMD ["python", "main.py"]
