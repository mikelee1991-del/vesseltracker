#!/usr/bin/env bash
# Bootstrap aisstream collector on Ubuntu 22.04/24.04 (Oracle/GCP free-tier VM).
# Run as root:  sudo bash deploy/aisstream/install.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/mikelee1991-del/vesseltracker.git}"
REPO_REF="${REPO_REF:-main}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/vesseltracker}"
DATA_ROOT="${DATA_ROOT:-/var/lib/aisstream}"
ENV_FILE="${ENV_FILE:-/etc/aisstream.env}"
SERVICE_USER="${SERVICE_USER:-aisstream}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl git python3 python3-venv python3-pip

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$DATA_ROOT/ais_daily" /opt
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_ROOT"

if [[ ! -d "$INSTALL_ROOT/.git" ]]; then
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_ROOT"
else
  git -C "$INSTALL_ROOT" fetch --depth 1 origin "$REPO_REF"
  git -C "$INSTALL_ROOT" checkout "$REPO_REF"
  git -C "$INSTALL_ROOT" pull --ff-only origin "$REPO_REF" || true
fi

cd "$INSTALL_ROOT"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
# Collector-only deps (skip scrape/duckdb stack on the tiny VM).
.venv/bin/pip install 'pandas>=2.2' 'pyarrow>=16.0' 'websockets>=12.0' 'python-dateutil>=2.9'

install -d -m 0755 /etc/systemd/system
install -m 0644 deploy/aisstream/aisstream-collector.service /etc/systemd/system/aisstream-collector.service

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 deploy/aisstream/env.example "$ENV_FILE"
  echo
  echo "Created $ENV_FILE — edit it and set AISSTREAM_API_KEY, then:"
  echo "  sudo systemctl daemon-reload"
  echo "  sudo systemctl enable --now aisstream-collector"
  echo "  sudo journalctl -u aisstream-collector -f"
else
  chmod 600 "$ENV_FILE"
  systemctl daemon-reload
  systemctl enable aisstream-collector
  if grep -q 'REPLACE_ME' "$ENV_FILE"; then
    echo "WARNING: $ENV_FILE still has REPLACE_ME — set your key before starting."
  else
    systemctl restart aisstream-collector
    echo "Service restarted. Follow logs with:"
    echo "  sudo journalctl -u aisstream-collector -f"
  fi
fi

echo
echo "Data directory: $DATA_ROOT/ais_daily"
echo "Repo:           $INSTALL_ROOT"
ls -la deploy/aisstream/accepted_names.json
