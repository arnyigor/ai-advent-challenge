#!/usr/bin/env bash
set -euo pipefail
# Run after uploading this day's folder. Existing day18 services are untouched.
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="$(id -un)"
DATA_DIR="${DAY33_DATA_DIR:-$(dirname "$APP_DIR")/data/day33}"
PUBLIC_HOST="${DAY33_PUBLIC_HOST:?Set DAY33_PUBLIC_HOST}"
APP_PORT="${DAY33_PORT:-8833}"
if [[ ! "$PUBLIC_HOST" =~ ^[a-zA-Z0-9.-]+$ || ! "$APP_PORT" =~ ^[0-9]+$ ]]; then
  echo 'Invalid host or port' >&2; exit 1
fi
mkdir -p "$DATA_DIR"
sudo -n apt-get update -qq
sudo -n apt-get install -y -qq python3-venv caddy
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --quiet -r "$APP_DIR/requirements.txt"
"$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR"
CONFIG_DIR="$(dirname "$APP_DIR")/deploy/day33"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/day33-support.service" <<EOF
[Unit]
Description=SrokOK warranty tracker and AI support
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$CONFIG_DIR/service.env
Environment=DAY33_HOST=127.0.0.1
Environment=DAY33_PORT=$APP_PORT
Environment=DAY33_DATA_DIR=$DATA_DIR
Environment=DAY33_SECURE_COOKIE=1
Environment=PYTHONIOENCODING=utf-8
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/server.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA_DIR
MemoryMax=512M
TasksMax=64
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
cat > "$CONFIG_DIR/Caddyfile" <<EOF
$PUBLIC_HOST {
    encode gzip
    request_body {
        max_size 16KB
    }
    reverse_proxy 127.0.0.1:$APP_PORT
}
EOF
sudo -n caddy validate --config "$CONFIG_DIR/Caddyfile" --adapter caddyfile
sudo -n install -m 644 "$CONFIG_DIR/day33-support.service" /etc/systemd/system/day33-support.service
sudo -n install -m 644 "$CONFIG_DIR/Caddyfile" /etc/caddy/day33.caddy
if sudo -n cmp -s "$CONFIG_DIR/Caddyfile" /etc/caddy/Caddyfile; then
    sudo -n cp /etc/caddy/Caddyfile "$CONFIG_DIR/Caddyfile.before-import"
    printf 'import /etc/caddy/day33.caddy\n' | sudo -n tee /etc/caddy/Caddyfile >/dev/null
fi
if ! sudo -n grep -qxF 'import /etc/caddy/day33.caddy' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/day33.caddy\n' | sudo -n tee -a /etc/caddy/Caddyfile >/dev/null
fi
sudo -n caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo -n systemctl daemon-reload
sudo -n systemctl enable caddy day33-support.service
echo 'Installed. Configure environment over stdin, then start day33-support and reload Caddy.'
