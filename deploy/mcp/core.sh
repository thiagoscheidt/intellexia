#!/usr/bin/env bash
# Núcleo do deploy do servidor MCP — NÃO rode direto: use o arquivo do ambiente
#   deploy/deploy_mcp_prod.sh | deploy/deploy_mcp_hml.sh | deploy/deploy_mcp_dev.sh
#
# O arquivo do ambiente define as variáveis abaixo e faz `source` deste:
#   ENV_NAME         rótulo (prod/hml/dev) — só para mensagens
#   SITE_DIR         pasta da instalação (a que tem o .env)
#   EXPECTED_DOMAIN  domínio que o .env TEM de ter em APP_PUBLIC_URL — trava
#                    contra .env copiado de outro ambiente
#   MCP_SERVICE      nome da unit systemd do MCP (sem .service)
#   MCP_PORT         porta local do uvicorn; única por máquina
#   NGINX_SITE       arquivo do site no nginx (vazio = procurar pelo server_name)
#   APP_SERVICE      unit do app Flask a reiniciar depois do pull (vazio = não reinicia)
#   MCP_USER         usuário que roda o MCP, o uv e o git (padrão root)
#   REPLACES_SERVICE unit antiga que ESTE ambiente substitui (é parada e
#                    desabilitada); só é aceita se o .env dela for do mesmo domínio
#   PULL_DEFAULT     1 = atualiza código por padrão; 0 = só com --pull
#
# Opções: --yes (não pergunta), --dry-run (só confere e mostra o plano),
#         --pull / --no-pull (atualizar código e dependências ou não).
#
# Nada é alterado antes de todas as conferências passarem. Cada uma existe por um
# motivo concreto: pasta errada faz pull/migration na instalação do vizinho; unit
# com o mesmo nome sobrescreve o MCP de outro ambiente; porta ocupada derruba o
# serviço em loop; snippet no bloco da porta 80 passa no `nginx -t` e não funciona.
set -euo pipefail

: "${ENV_NAME:?}" "${SITE_DIR:?}" "${EXPECTED_DOMAIN:?}" "${MCP_SERVICE:?}" "${MCP_PORT:?}"
NGINX_SITE="${NGINX_SITE:-}"
APP_SERVICE="${APP_SERVICE:-}"
MCP_USER="${MCP_USER:-root}"
REPLACES_SERVICE="${REPLACES_SERVICE:-}"

ASSUME_YES=0; DRY_RUN=0; PULL="${PULL_DEFAULT:-1}"
for arg in "$@"; do
    case "$arg" in
        --yes|-y)  ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --pull)    PULL=1 ;;
        --no-pull) PULL=0 ;;
        *) echo "opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_PY="$HERE/nginx_mcp.py"
UNIT_FILE="/etc/systemd/system/$MCP_SERVICE.service"
SITES_AVAILABLE=/etc/nginx/sites-available
SITES_ENABLED=/etc/nginx/sites-enabled
UV="${UV:-$(command -v uv || echo /root/.local/bin/uv)}"

die()  { echo "❌ $*" >&2; exit 1; }
warn() { echo "⚠️  $*" >&2; }
step() { echo; echo "── $*"; }

_from_env() {
    # Lê a chave do .env sem executá-lo (evita surpresa com aspas/expansão).
    sed -n "s/^$1=[\"']\?\([^\"'#]*\).*/\1/p" "$SITE_DIR/.env" | tail -1 | tr -d '[:space:]'
}
_host_of() { echo "$1" | sed -E 's#^[a-z]+://##; s#/.*$##'; }
# Roda como MCP_USER: numa pasta de trabalho de outro usuário, uv/git como root
# deixariam .venv, cache e .git com dono root.
as_user() {
    if [ "$MCP_USER" = root ]; then "$@"; else runuser -u "$MCP_USER" -- "$@"; fi
}

# ── Conferências (nada é alterado aqui) ───────────────────────────────────────
step "[$ENV_NAME] Conferindo o ambiente"

[ "$(id -u)" -eq 0 ] || die "rode como root (sudo)."
id "$MCP_USER" >/dev/null 2>&1 || die "usuário MCP_USER=$MCP_USER não existe."
[ -x "$UV" ] || die "uv não encontrado ($UV). Defina UV=/caminho/do/uv."
[ -d "$SITE_DIR/.git" ] || die "$SITE_DIR não é a instalação do IntellexIA (sem .git)."
[ -f "$SITE_DIR/.env" ] || die "$SITE_DIR/.env não existe."
command -v python3 >/dev/null || die "python3 não encontrado."

APP_URL="$(_from_env APP_PUBLIC_URL)"
[ -n "$APP_URL" ] || die "APP_PUBLIC_URL vazio em $SITE_DIR/.env."
DOMAIN="$(_host_of "$APP_URL")"
[ "$DOMAIN" = "$EXPECTED_DOMAIN" ] || die "APP_PUBLIC_URL de $SITE_DIR/.env aponta para '$DOMAIN', mas este é o ambiente $ENV_NAME ($EXPECTED_DOMAIN). O .env foi copiado de outro ambiente? Corrija antes — o MCP anunciaria o domínio errado."
MCP_PUBLIC_URL="$(_from_env MCP_PUBLIC_URL)"
[ -n "$MCP_PUBLIC_URL" ] || MCP_PUBLIC_URL="https://$DOMAIN/mcp"

# Unit: se já existe com este nome, tem de ser DESTA instalação.
if [ -f "$UNIT_FILE" ]; then
    EXISTING_DIR="$(sed -n 's/^WorkingDirectory=//p' "$UNIT_FILE" | tail -1)"
    [ "$EXISTING_DIR" = "$SITE_DIR" ] || die "$UNIT_FILE já existe e roda de '$EXISTING_DIR', não de $SITE_DIR. É o MCP de outro ambiente — escolha outro MCP_SERVICE."
fi

# Unit antiga a substituir: só se servir este mesmo domínio — senão seria
# derrubar o MCP de outro ambiente.
REPLACES_FILE=""
if [ -n "$REPLACES_SERVICE" ] && [ -f "/etc/systemd/system/$REPLACES_SERVICE.service" ]; then
    REPLACES_FILE="/etc/systemd/system/$REPLACES_SERVICE.service"
    OLD_DIR="$(sed -n 's/^WorkingDirectory=//p' "$REPLACES_FILE" | tail -1)"
    if [ "$OLD_DIR" != "$SITE_DIR" ]; then
        OLD_DOMAIN="$(SITE_DIR="$OLD_DIR" _from_env APP_PUBLIC_URL 2>/dev/null || true)"
        OLD_DOMAIN="$(_host_of "$OLD_DOMAIN")"
        [ "$OLD_DOMAIN" = "$DOMAIN" ] || die "$REPLACES_SERVICE roda de $OLD_DIR, cujo .env é de '$OLD_DOMAIN' e não de $DOMAIN — não vou derrubá-lo."
    fi
fi

# Porta: nenhuma outra unit pode declará-la, e nenhum outro processo pode ouvi-la.
OUTRA_UNIT="$(grep -lE "^Environment=MCP_PORT=$MCP_PORT\s*$" /etc/systemd/system/*.service 2>/dev/null \
              | grep -vx "$UNIT_FILE" | { [ -n "$REPLACES_FILE" ] && grep -vx "$REPLACES_FILE" || cat; } || true)"
[ -z "$OUTRA_UNIT" ] || die "a porta $MCP_PORT já é usada por $OUTRA_UNIT. Escolha outro MCP_PORT."
LISTEN_PIDS="$(ss -Hltnp "sport = :$MCP_PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
for pid in $LISTEN_PIDS; do
    grep -q "/$MCP_SERVICE.service" "/proc/$pid/cgroup" 2>/dev/null && continue
    if [ -n "$REPLACES_FILE" ] && grep -q "/$REPLACES_SERVICE.service" "/proc/$pid/cgroup" 2>/dev/null; then continue; fi
    die "a porta $MCP_PORT está ocupada pelo processo $pid ($(ps -o comm= -p "$pid" 2>/dev/null)), que não é o $MCP_SERVICE."
done

# nginx: site do domínio, habilitado, com um único bloco 443 para ele.
if [ -z "$NGINX_SITE" ]; then
    NGINX_SITE="$(python3 "$NGINX_PY" find --domain "$DOMAIN" --sites-dir "$SITES_AVAILABLE")" \
        || die "não achei um site em $SITES_AVAILABLE com bloco 443 para $DOMAIN. Informe NGINX_SITE=..."
fi
[ -f "$NGINX_SITE" ] || die "site do nginx não encontrado: $NGINX_SITE"
ENABLED=0
for f in "$SITES_ENABLED"/*; do
    if [ "$(readlink -f "$f")" = "$(readlink -f "$NGINX_SITE")" ]; then ENABLED=1; fi
done
[ "$ENABLED" -eq 1 ] || die "$NGINX_SITE não está habilitado em $SITES_ENABLED."
set +e
python3 "$NGINX_PY" apply --file "$NGINX_SITE" --domain "$DOMAIN" --port "$MCP_PORT" --dry-run
NGINX_RC=$?
set -e
[ "$NGINX_RC" -eq 0 ] || [ "$NGINX_RC" -eq 3 ] || die "o site do nginx não pode ser editado com segurança (ver acima)."

if [ -n "$APP_SERVICE" ]; then
    APP_DIR="$(systemctl show -p WorkingDirectory --value "$APP_SERVICE" 2>/dev/null || true)"
    [ "$APP_DIR" = "$SITE_DIR" ] || die "APP_SERVICE=$APP_SERVICE roda de '$APP_DIR', não de $SITE_DIR — reiniciaria o app de outro ambiente."
fi

BRANCH="$(git -C "$SITE_DIR" rev-parse --abbrev-ref HEAD)"

cat <<PLANO

   Ambiente ......... $ENV_NAME
   Instalação ....... $SITE_DIR  (branch $BRANCH)
   Endereço do MCP .. $MCP_PUBLIC_URL
   Serviço .......... $MCP_SERVICE  →  127.0.0.1:$MCP_PORT  (usuário $MCP_USER)
   Substitui ........ ${REPLACES_FILE:+$REPLACES_SERVICE (será parado e desabilitado)}${REPLACES_FILE:-—}
   nginx ............ $NGINX_SITE
   Atualizar código . $([ "$PULL" -eq 1 ] && echo "sim (git pull --ff-only + uv sync)" || echo "não")
   Reiniciar app .... ${APP_SERVICE:-não}
PLANO

[ "$DRY_RUN" -eq 1 ] && { echo; echo "✅ [dry-run] todas as conferências passaram; nada foi alterado."; exit 0; }
if [ "$ASSUME_YES" -ne 1 ]; then
    read -r -p "Continuar? [s/N] " resp
    [[ "$resp" =~ ^[sSyY]$ ]] || die "cancelado."
fi

# ── Execução ──────────────────────────────────────────────────────────────────
if [ "$PULL" -eq 1 ]; then
    step "1/6 Atualizando código ($BRANCH)"
    as_user git -C "$SITE_DIR" pull --ff-only
    (cd "$SITE_DIR" && as_user "$UV" sync)
else
    step "1/6 Código mantido como está (sem --pull)"
fi

step "2/6 Migrations (OAuth do MCP + notificações)"
(cd "$SITE_DIR" && as_user "$UV" run python database/add_mcp_oauth_tables.py)
(cd "$SITE_DIR" && as_user "$UV" run python database/add_notification_settings_table.py)

step "3/6 Serviço systemd $MCP_SERVICE"
# Sem domínio na unit: o servidor lê o .env (o main.py o carrega por cima do
# ambiente do processo, então um valor aqui venceria o do .env e confundiria).
cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=IntellexIA MCP Server (OAuth) - $ENV_NAME
After=network.target

[Service]
User=$MCP_USER
WorkingDirectory=$SITE_DIR
ExecStart=$UV run python mcp_server/server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=MCP_HOST=127.0.0.1
Environment=MCP_PORT=$MCP_PORT

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
if [ -n "$REPLACES_FILE" ]; then
    # Libera a porta antes de subir o novo. A unit antiga fica no disco,
    # desabilitada: voltar atrás é `systemctl enable --now $REPLACES_SERVICE`.
    systemctl disable --now "$REPLACES_SERVICE.service"
    echo "   $REPLACES_SERVICE parado e desabilitado"
fi
systemctl enable "$MCP_SERVICE.service" >/dev/null
systemctl restart "$MCP_SERVICE.service"

step "4/6 nginx"
if [ "$NGINX_RC" -eq 3 ]; then
    echo "   trecho do MCP já presente — sem edição"
else
    BACKUP="$NGINX_SITE.bak.$(date +%s)"
    cp -p "$NGINX_SITE" "$BACKUP"
    python3 "$NGINX_PY" apply --file "$NGINX_SITE" --domain "$DOMAIN" --port "$MCP_PORT"
    if ! nginx -t; then
        cp -p "$BACKUP" "$NGINX_SITE"
        die "nginx -t falhou — site restaurado do backup ($BACKUP). O nginx não foi recarregado."
    fi
    echo "   backup: $BACKUP"
fi
systemctl reload nginx

step "5/6 App Flask"
if [ -n "$APP_SERVICE" ]; then
    systemctl restart "$APP_SERVICE"
    echo "   $APP_SERVICE reiniciado"
elif [ "$PULL" -eq 1 ]; then
    warn "o código foi atualizado, mas o app não foi reiniciado (APP_SERVICE vazio). Reinicie-o para as telas usarem o código novo."
fi

step "6/6 Validando"
LOCAL_OK=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$MCP_PORT/.well-known/oauth-authorization-server"; then
        LOCAL_OK=1; break
    fi
    sleep 1
done
if [ "$LOCAL_OK" -ne 1 ]; then
    systemctl --no-pager --lines 20 status "$MCP_SERVICE.service" || true
    die "o MCP não respondeu em 127.0.0.1:$MCP_PORT em 30s — veja: journalctl -u $MCP_SERVICE -n 100"
fi
echo "   local 127.0.0.1:$MCP_PORT ✔"

ANUNCIADO="$(curl -fsS "https://$DOMAIN/.well-known/oauth-authorization-server/mcp" 2>/dev/null \
             | python3 -c 'import sys,json; print(json.load(sys.stdin).get("issuer",""))' 2>/dev/null || true)"
ANUNCIADO="${ANUNCIADO%/}"
if [ -z "$ANUNCIADO" ]; then
    die "o endereço público https://$DOMAIN/.well-known/oauth-authorization-server/mcp não respondeu JSON. O serviço está de pé; confira o nginx (e o Cloudflare, se houver)."
elif [ "$ANUNCIADO" != "${MCP_PUBLIC_URL%/}" ]; then
    die "o MCP anuncia '$ANUNCIADO', esperado '$MCP_PUBLIC_URL' — confira APP_PUBLIC_URL/MCP_PUBLIC_URL no .env e reinicie $MCP_SERVICE."
fi
echo "   público $ANUNCIADO ✔"

echo
echo "✅ [$ENV_NAME] MCP no ar. Conecte o Claude Code com:"
echo "   claude mcp add --transport http intellexia-$ENV_NAME $MCP_PUBLIC_URL"
