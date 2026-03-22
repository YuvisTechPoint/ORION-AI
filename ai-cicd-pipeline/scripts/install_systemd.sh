#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

id -u orion &>/dev/null || useradd --system --create-home --home-dir /var/lib/orion --shell /usr/sbin/nologin orion

install -d -m 755 /opt/orion /etc/orion /var/log/orion /var/lib/orion

rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  "${ROOT_DIR}/" /opt/orion/

chown -R orion:orion /opt/orion /var/log/orion /var/lib/orion

python3 -m venv /opt/orion/venv
/opt/orion/venv/bin/pip install --upgrade pip
/opt/orion/venv/bin/pip install -r /opt/orion/requirements.txt

if [[ -f "${ROOT_DIR}/.env" ]]; then
  install -m 600 "${ROOT_DIR}/.env" /etc/orion/orion.env
else
  install -m 600 "${ROOT_DIR}/.env.example" /etc/orion/orion.env
fi

install -m 644 "${ROOT_DIR}/systemd/orion-api.service" /etc/systemd/system/orion-api.service
install -m 644 "${ROOT_DIR}/systemd/orion-worker.service" /etc/systemd/system/orion-worker.service
install -m 644 "${ROOT_DIR}/systemd/orion-beat.service" /etc/systemd/system/orion-beat.service
install -m 644 "${ROOT_DIR}/systemd/orion-monitor.service" /etc/systemd/system/orion-monitor.service

systemctl daemon-reload
systemctl enable orion-api orion-worker orion-beat orion-monitor
systemctl restart orion-api || true

ln -sf /opt/orion/scripts/orion_cli.py /usr/local/bin/orion
chmod +x /usr/local/bin/orion

echo "ORION systemd units installed."
