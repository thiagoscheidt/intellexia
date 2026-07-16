#!/usr/bin/env bash
# Deploy do servidor MCP OAuth.
#
#   sudo bash deploy/deploy_mcp.sh
#
# O domínio NÃO se define aqui: ele vem do `.env` da instalação (APP_PUBLIC_URL).
# É o mesmo arquivo que configura o resto do sistema, e cada ambiente tem o seu —
# então dev e produção se resolvem sozinhos, sem argumento na linha de comando.
#
# Ordem de resolução do domínio:
#   1. APP_PUBLIC_URL (ou MCP_PUBLIC_URL) no .env  ← o caminho normal
#   2. Detecção pelo site do nginx que serve a aplicação (quando o .env não diz)
#   3. Falha com instrução clara — melhor do que publicar o domínio errado
#
# Overrides opcionais: MCP_DOMAIN, SITE_DIR, NGINX_SITE, APP_SERVICE.
set -euo pipefail

SITE_DIR="${SITE_DIR:-/sites/intellexia}"
APP_SERVICE="${APP_SERVICE:-intellexia.service}"
UV=/root/.local/bin/uv
ENV_FILE="$SITE_DIR/.env"

# ── 0/6 Descobrir o domínio ───────────────────────────────────────────────────
_from_env() {
    # Lê a chave do .env sem executá-lo (evita surpresa com aspas/expansão).
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^$1=[\"']\?\([^\"'#]*\).*/\1/p" "$ENV_FILE" | tail -1 | tr -d '[:space:]'
}

_host_of() { echo "$1" | sed -E 's#^[a-z]+://##; s#/.*$##'; }

DOMAIN="${MCP_DOMAIN:-}"
ORIGEM="MCP_DOMAIN (linha de comando)"

if [ -z "$DOMAIN" ]; then
    RAW="$(_from_env APP_PUBLIC_URL)"
    [ -n "$RAW" ] && { DOMAIN="$(_host_of "$RAW")"; ORIGEM="APP_PUBLIC_URL do .env"; }
fi
if [ -z "$DOMAIN" ]; then
    RAW="$(_from_env MCP_PUBLIC_URL)"
    [ -n "$RAW" ] && { DOMAIN="$(_host_of "$RAW")"; ORIGEM="MCP_PUBLIC_URL do .env"; }
fi
NGINX_SITES_ENABLED="${NGINX_SITES_ENABLED:-/etc/nginx/sites-enabled}"
if [ -z "$DOMAIN" ] && [ -d "$NGINX_SITES_ENABLED" ]; then
    # Sem .env: deduz pelo site que faz proxy para a aplicação.
    DOMAIN="$(grep -rlE "proxy_pass .*127\.0\.0\.1:(5051|5000|8000)" "$NGINX_SITES_ENABLED/" 2>/dev/null \
              | head -1 | xargs -r basename)"
    [ -n "$DOMAIN" ] && ORIGEM="detectado no nginx (o .env não define o domínio)"
fi

if [ -z "$DOMAIN" ]; then
    cat >&2 <<MSG
❌ Não consegui descobrir o domínio desta instalação.
   Defina no .env ($ENV_FILE):

       APP_PUBLIC_URL=https://seu-dominio.com.br

   É a mesma variável usada nos links dos e-mails. Depois rode o deploy de novo.
MSG
    exit 1
fi

NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-available/$DOMAIN}"
MCP_PUBLIC_URL="$(_from_env MCP_PUBLIC_URL)"
[ -z "$MCP_PUBLIC_URL" ] && MCP_PUBLIC_URL="https://$DOMAIN/mcp"

echo "── 0/6 Domínio: $DOMAIN  (origem: $ORIGEM)"
echo "        MCP: $MCP_PUBLIC_URL"
echo "        nginx: $NGINX_SITE"

if [ ! -f "$NGINX_SITE" ]; then
    echo "❌ Site do nginx não encontrado: $NGINX_SITE" >&2
    echo "   Informe o caminho em NGINX_SITE=... e rode de novo." >&2
    exit 1
fi

echo "── 1/6 Atualizando código em $SITE_DIR"
git -C "$SITE_DIR" pull --ff-only
(cd "$SITE_DIR" && "$UV" sync)

echo "── 2/6 Migrations (OAuth do MCP + notificações)"
(cd "$SITE_DIR" && "$UV" run python database/add_mcp_oauth_tables.py)
(cd "$SITE_DIR" && "$UV" run python database/add_notification_settings_table.py)

echo "── 3/6 Instalando serviço systemd intellexia-mcp"
# Sem domínio no unit: o servidor lê o .env (o main.py o carrega por cima do
# ambiente do processo, então um valor aqui venceria o do .env e confundiria).
cp "$SITE_DIR/deploy/intellexia-mcp.service" /etc/systemd/system/intellexia-mcp.service
systemctl daemon-reload
systemctl enable --now intellexia-mcp.service
systemctl restart intellexia-mcp.service

echo "── 4/6 Configurando nginx (locations /mcp + discovery OAuth)"
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

echo "── 5/6 Reiniciando app Flask"
systemctl restart "$APP_SERVICE"

echo "── 6/6 Validando"
sleep 2
systemctl --no-pager --lines 3 status intellexia-mcp.service | head -8
echo
ANUNCIADO="$(curl -s "https://$DOMAIN/.well-known/oauth-authorization-server/mcp" \
             | python3 -c 'import sys,json; print(json.load(sys.stdin).get("issuer",""))' 2>/dev/null || true)"
echo "   Endereço anunciado pelo MCP: ${ANUNCIADO:-(não respondeu)}"
if [ -n "$ANUNCIADO" ] && [ "$ANUNCIADO" != "$MCP_PUBLIC_URL" ]; then
    echo "   ⚠️  Diferente do esperado ($MCP_PUBLIC_URL) — confira APP_PUBLIC_URL no .env." >&2
fi

echo
echo "✅ Deploy concluído. Conecte o Claude Code com:"
echo "   claude mcp add --transport http intellexia $MCP_PUBLIC_URL"
