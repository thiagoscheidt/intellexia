#!/usr/bin/env bash
# Deploy do servidor MCP OAuth em rs-dev.intellexia.com.br.
# Rodar como root:  sudo bash deploy/deploy_mcp.sh
set -euo pipefail

SITE_DIR=/sites/intellexia
NGINX_SITE=/etc/nginx/sites-available/rs-dev.intellexia.com.br
UV=/root/.local/bin/uv

echo "── 1/5 Atualizando código em $SITE_DIR"
git -C "$SITE_DIR" pull --ff-only
(cd "$SITE_DIR" && "$UV" sync)

echo "── 2/5 Migration das tabelas OAuth"
(cd "$SITE_DIR" && "$UV" run python database/add_mcp_oauth_tables.py)

echo "── 3/5 Instalando serviço systemd intellexia-mcp"
cp "$SITE_DIR/deploy/intellexia-mcp.service" /etc/systemd/system/intellexia-mcp.service
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

echo "── 5/5 Reiniciando app Flask (suporte a ?next= no login)"
systemctl restart intellexia.service

echo
echo "✅ Deploy concluído. Validações:"
sleep 2
systemctl --no-pager --lines 3 status intellexia-mcp.service | head -8
echo
curl -s https://rs-dev.intellexia.com.br/.well-known/oauth-authorization-server/mcp | head -c 400
echo
echo
echo "Conecte o Claude Code com:"
echo "  claude mcp add --transport http intellexia https://rs-dev.intellexia.com.br/mcp"
