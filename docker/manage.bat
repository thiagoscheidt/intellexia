@echo off
REM Script para gerenciar containers Docker - Intellexia (Windows)
REM Uso: manage.bat [start|stop|restart|status|logs|health|mysql|clean]

setlocal enabledelayedexpansion

set DOCKER_COMPOSE_FILE=docker-compose.yml
set PROJECT_NAME=intellexia

REM Verificar Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Docker nao esta instalado ou nao esta no PATH
    exit /b 1
)

REM Se nenhum argumento for passado, mostrar ajuda
if "%1"=="" goto help

REM Rodar comando
goto %1

:start
echo [INFO] Iniciando containers...
docker-compose -f %DOCKER_COMPOSE_FILE% up -d
echo [OK] Containers iniciados!
echo [INFO] Aguardando servicos ficarem prontos...
timeout /t 5 /nobreak
call :status
exit /b 0

:stop
echo [INFO] Parando containers...
docker-compose -f %DOCKER_COMPOSE_FILE% down
echo [OK] Containers parados!
exit /b 0

:restart
echo [INFO] Reiniciando containers...
docker-compose -f %DOCKER_COMPOSE_FILE% restart
echo [OK] Containers reiniciados!
timeout /t 5 /nobreak
call :status
exit /b 0

:status
echo [INFO] Status dos containers:
docker-compose -f %DOCKER_COMPOSE_FILE% ps
echo.
echo [INFO] Verificando conectividade...

REM Verificar MySQL
docker exec intellexia-mysql mysqladmin ping -h localhost >nul 2>&1
if errorlevel 0 (
    echo [OK] MySQL esta responsivo
) else (
    echo [AVISO] MySQL nao esta responsivo ainda
)

REM Verificar Qdrant
curl -s http://localhost:6333/health >nul 2>&1
if errorlevel 0 (
    echo [OK] Qdrant esta responsivo
) else (
    echo [AVISO] Qdrant nao esta responsivo ainda
)
exit /b 0

:logs
if "%2"=="" (
    echo [INFO] Mostrando logs de todos os containers...
    docker-compose -f %DOCKER_COMPOSE_FILE% logs -f
) else (
    echo [INFO] Mostrando logs de %2...
    docker-compose -f %DOCKER_COMPOSE_FILE% logs -f %2
)
exit /b 0

:mysql
echo [INFO] Conectando ao MySQL...
docker exec -it intellexia-mysql mysql -u intellexia -p intellexia_password_123 intellexia
exit /b 0

:health
echo [INFO] Realizando health check completo...
echo.
echo [INFO] Testando MySQL...
docker exec intellexia-mysql mysqladmin ping -h localhost
echo.
echo [INFO] Testando Qdrant...
curl -s http://localhost:6333/health
echo.
exit /b 0

:volumes
echo [INFO] Informacoes de volumes:
docker volume ls | find "%PROJECT_NAME%"
echo.
echo [INFO] Detalhes do volume MySQL:
docker volume inspect %PROJECT_NAME%_mysql_data
exit /b 0

:clean
echo [AVISO] Isso vai remover todos os containers e dados!
set /p confirm="Tem certeza? (s/n): "
if /i "%confirm%"=="s" (
    echo [INFO] Removendo containers e volumes...
    docker-compose -f %DOCKER_COMPOSE_FILE% down -v
    echo [OK] Limpeza concluida!
) else (
    echo [INFO] Cancelado
)
exit /b 0

:help
echo Uso: manage.bat [COMANDO]
echo.
echo Comandos:
echo   start              Iniciar todos os containers
echo   stop               Parar todos os containers
echo   restart            Reiniciar todos os containers
echo   status             Mostrar status dos containers
echo   logs [SERVICE]     Mostrar logs (SERVICE: mysql, qdrant)
echo   mysql              Conectar ao MySQL via CLI
echo   health             Realizar health check completo
echo   volumes            Mostrar informacao de volumes
echo   clean              Remover containers e dados (DESTRUTIVO)
echo   help               Mostrar esta mensagem
echo.
echo Exemplos:
echo   manage.bat start
echo   manage.bat logs mysql
echo   manage.bat restart
exit /b 0

:error
echo [ERRO] Comando desconhecido: %1
echo.
goto help
