#!/usr/bin/env bash
# Deploy do MCP em PRODUÇÃO (rs.intellexia.com.br).
#
#   sudo bash deploy/deploy_mcp_prod.sh --dry-run   # só confere, não altera nada
#   sudo bash deploy/deploy_mcp_prod.sh
#
# Mantém o nome (intellexia-mcp) e a porta (8001) do deploy_mcp.sh antigo, para
# atualizar a instalação existente em vez de subir um segundo MCP ao lado.
# O site do nginx é achado pelo server_name; se não achar, informe NGINX_SITE=...
set -euo pipefail

ENV_NAME=prod
SITE_DIR="${SITE_DIR:-/sites/intellexia}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-rs.intellexia.com.br}"
MCP_SERVICE="${MCP_SERVICE:-intellexia-mcp}"
MCP_PORT="${MCP_PORT:-8001}"
NGINX_SITE="${NGINX_SITE:-}"
APP_SERVICE="${APP_SERVICE:-intellexia.service}"

source "$(dirname "${BASH_SOURCE[0]}")/mcp/core.sh" "$@"
