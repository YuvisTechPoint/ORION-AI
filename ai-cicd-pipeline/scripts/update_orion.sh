#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

systemctl stop orion-api orion-worker orion-beat orion-monitor 2>/dev/null || true

rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  "${ROOT_DIR}/" /opt/orion/

chown -R orion:orion /opt/orion

/opt/orion/venv/bin/pip install -r /opt/orion/requirements.txt

cd /opt/orion
sudo -u orion /opt/orion/venv/bin/alembic upgrade head

systemctl start orion-api orion-worker orion-beat orion-monitor

echo "ORION updated."
