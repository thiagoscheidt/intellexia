#!/usr/bin/env bash
# Deploy do MCP em DESENVOLVIMENTO (rs-dev.intellexia.com.br).
#
#   sudo bash deploy/deploy_mcp_dev.sh --dry-run   # só confere, não altera nada
#   sudo bash deploy/deploy_mcp_dev.sh
#
# O dev é a pasta de trabalho /home/thiago/projetos/intellexia (o app sobe na
# 5051 a partir dela). Por isso:
#   - o MCP, o uv e as migrations rodam como `thiago`, não root — senão .venv,
#     cache e __pycache__ da pasta de trabalho ganhariam dono root;
#   - NÃO faz git pull por padrão: é a cópia em que se trabalha, com alteração
#     não commitada. Use --pull se quiser.
#
# Substitui o intellexia-mcp antigo, que rodava de /sites/intellexia (cópia
# desatualizada, com o .env também apontando para rs-dev) — o MCP do dev servia
# código velho. Mantém a porta 8001 para o trecho que já está no nginx do rs-dev
# continuar valendo sem edição.
set -euo pipefail

ENV_NAME=dev
SITE_DIR="${SITE_DIR:-/home/thiago/projetos/intellexia}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-rs-dev.intellexia.com.br}"
MCP_SERVICE="${MCP_SERVICE:-intellexia-dev-mcp}"
MCP_PORT="${MCP_PORT:-8001}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/rs-dev.intellexia.com.br}"
MCP_USER="${MCP_USER:-thiago}"
UV="${UV:-/home/thiago/.local/bin/uv}"
REPLACES_SERVICE="${REPLACES_SERVICE:-intellexia-mcp}"
PULL_DEFAULT="${PULL_DEFAULT:-0}"
# O app do dev não é unit do systemd (roda na mão, na 5051).
APP_SERVICE="${APP_SERVICE:-}"

source "$(dirname "${BASH_SOURCE[0]}")/mcp/core.sh" "$@"
