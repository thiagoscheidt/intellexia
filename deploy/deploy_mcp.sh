#!/usr/bin/env bash
# Deploy do servidor MCP OAuth.
#
# O domínio NÃO é fixo: cada instalação (dev, produção) tem o seu. Informe em
# MCP_DOMAIN — é ele que define a URL anunciada pelo MCP (MCP_PUBLIC_URL) e o
# site do nginx a configurar.
#
#   sudo bash deploy/deploy_mcp.sh                              # usa o padrão (dev)
#   sudo MCP_DOMAIN=app.intellexia.com.br bash deploy/deploy_mcp.sh   # produção
#
# Outras variáveis: SITE_DIR (padrão /sites/intellexia), NGINX_SITE, APP_SERVICE.
set -euo pipefail

MCP_DOMAIN="${MCP_DOMAIN:-rs-dev.intellexia.com.br}"
SITE_DIR="${SITE_DIR:-/sites/intellexia}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/$MCP_DOMAIN}"
APP_SERVICE="${APP_SERVICE:-intellexia.service}"
UV=/root/.local/bin/uv

MCP_PUBLIC_URL="https://$MCP_DOMAIN/mcp"

echo "── Domínio desta instalação: $MCP_DOMAIN"
echo "   MCP_PUBLIC_URL=$MCP_PUBLIC_URL"
echo "   nginx site: $NGINX_SITE"

if [ ! -f "$NGINX_SITE" ]; then
    echo "❌ Site do nginx não encontrado: $NGINX_SITE"
    echo "   Informe o caminho correto em NGINX_SITE=... (ou o domínio em MCP_DOMAIN=...)."
    exit 1
fi

echo "── 1/5 Atualizando código em $SITE_DIR"
git -C "$SITE_DIR" pull --ff-only
(cd "$SITE_DIR" && "$UV" sync)

echo "── 2/5 Migrations (OAuth do MCP + notificações)"
(cd "$SITE_DIR" && "$UV" run python database/add_mcp_oauth_tables.py)
(cd "$SITE_DIR" && "$UV" run python database/add_notification_settings_table.py)

echo "── 3/5 Instalando serviço systemd intellexia-mcp"
sed "s|__MCP_PUBLIC_URL__|$MCP_PUBLIC_URL|" \
    "$SITE_DIR/deploy/intellexia-mcp.service" > /etc/systemd/system/intellexia-mcp.service
systemctl daemon-reload
systemctl enable --now intellexia-mcp.service
systemctl restart intellexia-mcp.service

echo "── 4/5 Configurando nginx (locations /mcp + discovery OAuth)"
if grep -q 'IntellexIA MCP' "$NGINX_SITE"; then
    echo "   locations já presentes — pulando edição"
else
    cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%s)"
    python3 - "$NGINX_SITE" "$SITE_DIR/deploy/nginx-rs-dev-mcp.conf" <<'PYEOF'
import sys
site_path, snippet_path = sys.argv[1], sys.argv[2]
site = open(site_path).read()
snippet = open(snippet_path).read()
# Remove a linha de instrução "colar dentro do bloco" do snippet
snippet = "\n".join(l for l in snippet.splitlines() if not l.startswith("# Colar DENTRO"))
# Insere antes da última chave de fechamento (fim do server block 443)
idx = site.rstrip().rfind("}")
new = site[:idx] + "\n" + snippet + "\n" + site[idx:]
open(site_path, "w").write(new)
print("   snippet inserido no server block 443")
PYEOF
fi
nginx -t
systemctl reload nginx

echo "── 5/5 Reiniciando app Flask"
systemctl restart "$APP_SERVICE"

echo
echo "✅ Deploy concluído. Validações:"
sleep 2
systemctl --no-pager --lines 3 status intellexia-mcp.service | head -8
echo
curl -s "https://$MCP_DOMAIN/.well-known/oauth-authorization-server/mcp" | head -c 400
echo
echo
echo "Conecte o Claude Code com:"
echo "  claude mcp add --transport http intellexia $MCP_PUBLIC_URL"
