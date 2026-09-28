#!/usr/bin/env bash
# Deploy do MCP em HOMOLOGAÇÃO (rs-hml.intellexia.com.br).
#
#   sudo bash deploy/deploy_mcp_hml.sh --dry-run   # só confere, não altera nada
#   sudo bash deploy/deploy_mcp_hml.sh
#
# O site do nginx de homologação chama-se `hml` (não o domínio) e tem o bloco 443
# antes do bloco 80 — por isso o deploy_mcp.sh antigo não serve aqui.
# Porta 8002 e unit própria: a máquina também tem /sites/intellexia, e um MCP
# daquela instalação usaria o nome e a porta do prod (intellexia-mcp, 8001).
# Qualquer valor pode ser sobrescrito na chamada: sudo MCP_PORT=8012 bash ...
set -euo pipefail

ENV_NAME=hml
SITE_DIR="${SITE_DIR:-/sites/intellexia_hml}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-rs-hml.intellexia.com.br}"
MCP_SERVICE="${MCP_SERVICE:-intellexia-hml-mcp}"
MCP_PORT="${MCP_PORT:-8002}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/hml}"
# O app de homologação escuta na 5055; a unit dele ainda não foi identificada.
# Preencha (ex.: APP_SERVICE=intellexia-hml.service) para reiniciar após o pull.
APP_SERVICE="${APP_SERVICE:-}"

source "$(dirname "${BASH_SOURCE[0]}")/mcp/core.sh" "$@"
