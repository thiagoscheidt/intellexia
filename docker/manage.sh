#!/bin/bash
# Script para gerenciar containers Docker - Intellexia
# Uso: ./manage.sh [start|stop|restart|status|logs|restart|clean]

set -e

DOCKER_COMPOSE_FILE="docker-compose.yml"
PROJECT_NAME="intellexia"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Função para imprimir
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[AVISO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERRO]${NC} $1"
}

# Função para verificar se docker está rodando
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker não está instalado ou não está no PATH"
        exit 1
    fi

    if ! docker ps &> /dev/null; then
        print_error "Docker daemon não está rodando"
        exit 1
    fi

    print_success "Docker está disponível"
}

# Iniciar containers
start() {
    print_info "Iniciando containers..."
    docker-compose -f $DOCKER_COMPOSE_FILE up -d
    print_success "Containers iniciados!"
    
    print_info "Aguardando serviços ficarem prontos..."
    sleep 5
    
    status
}

# Parar containers
stop() {
    print_info "Parando containers..."
    docker-compose -f $DOCKER_COMPOSE_FILE down
    print_success "Containers parados!"
}

# Reiniciar containers
restart() {
    print_info "Reiniciando containers..."
    docker-compose -f $DOCKER_COMPOSE_FILE restart
    print_success "Containers reiniciados!"
    
    print_info "Aguardando serviços ficarem prontos..."
    sleep 5
    
    status
}

# Status dos containers
status() {
    print_info "Status dos containers:"
    docker-compose -f $DOCKER_COMPOSE_FILE ps
    echo ""
    
    print_info "Verificando conectividade..."
    
    # MySQL
    if docker exec intellexia-mysql mysqladmin ping -h localhost &> /dev/null; then
        print_success "MySQL está responsivo"
    else
        print_warning "MySQL não está responsivo ainda"
    fi
    
    # Qdrant
    if curl -s http://localhost:6333/health > /dev/null 2>&1; then
        print_success "Qdrant está responsivo"
    else
        print_warning "Qdrant não está responsivo ainda"
    fi
}

# Ver logs
logs() {
    SERVICE=${2:-""}
    if [ -z "$SERVICE" ]; then
        print_info "Mostrando logs de todos os containers..."
        docker-compose -f $DOCKER_COMPOSE_FILE logs -f
    else
        print_info "Mostrando logs de $SERVICE..."
        docker-compose -f $DOCKER_COMPOSE_FILE logs -f $SERVICE
    fi
}

# Acessar MySQL
mysql_cli() {
    print_info "Conectando ao MySQL..."
    docker exec -it intellexia-mysql mysql -u intellexia -p intellexia_password_123 intellexia
}

# Acessar bash do MySQL
mysql_bash() {
    print_info "Abrindo bash no container MySQL..."
    docker exec -it intellexia-mysql bash
}

# Limpar tudo
clean() {
    print_warning "Isso vai remover todos os containers e dados!"
    read -p "Tem certeza? (s/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        print_info "Removendo containers e volumes..."
        docker-compose -f $DOCKER_COMPOSE_FILE down -v
        print_success "Limpeza concluída!"
    else
        print_info "Cancelado"
    fi
}

# Verificar volume de dados
volume_info() {
    print_info "Informações de volumes:"
    docker volume ls | grep $PROJECT_NAME || echo "Nenhum volume encontrado"
    echo ""
    
    if docker volume inspect ${PROJECT_NAME}_mysql_data &> /dev/null; then
        print_info "Detalhes do volume MySQL:"
        docker volume inspect ${PROJECT_NAME}_mysql_data
    fi
}

# Health check detalhado
health_check() {
    print_info "Realizando health check completo..."
    echo ""
    
    # MySQL
    print_info "Testando MySQL..."
    if docker exec intellexia-mysql mysqladmin ping -h localhost &> /dev/null; then
        print_success "MySQL OK"
        docker exec intellexia-mysql mysqladmin -u root -proot_password_123 ping
    else
        print_error "MySQL não respondendo"
    fi
    echo ""
    
    # Qdrant
    print_info "Testando Qdrant..."
    if curl -s http://localhost:6333/health > /dev/null 2>&1; then
        print_success "Qdrant OK"
        curl -s http://localhost:6333/health | python -m json.tool || true
    else
        print_error "Qdrant não respondendo"
    fi
    echo ""
}

# Menu de ajuda
help() {
    echo "Uso: $0 [COMANDO] [OPCOES]"
    echo ""
    echo "Comandos:"
    echo "  start              Iniciar todos os containers"
    echo "  stop               Parar todos os containers"
    echo "  restart            Reiniciar todos os containers"
    echo "  status             Mostrar status dos containers"
    echo "  logs [SERVICE]     Mostrar logs (SERVICE opcional: mysql, qdrant)"
    echo "  mysql              Conectar ao MySQL via CLI"
    echo "  mysql-bash         Acessar bash no container MySQL"
    echo "  health             Realizar health check completo"
    echo "  volumes            Mostrar informação de volumes"
    echo "  clean              Remover containers e dados (DESTRUTIVO)"
    echo "  help               Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  ./manage.sh start"
    echo "  ./manage.sh logs mysql"
    echo "  ./manage.sh restart"
}

# Main
check_docker

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$@"
        ;;
    mysql)
        mysql_cli
        ;;
    mysql-bash)
        mysql_bash
        ;;
    health)
        health_check
        ;;
    volumes)
        volume_info
        ;;
    clean)
        clean
        ;;
    help|--help|-h|"")
        help
        ;;
    *)
        print_error "Comando desconhecido: $1"
        echo ""
        help
        exit 1
        ;;
esac
