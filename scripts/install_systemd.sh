#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root."
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! id -u orion >/dev/null 2>&1; then
  useradd -r -s /sbin/nologin -d /opt/orion orion
fi

mkdir -p /opt/orion /etc/orion /var/log/orion /var/lib/orion /var/lib/orion/backups
chown -R orion:orion /opt/orion /var/log/orion /var/lib/orion

rsync -av --exclude='.git' --exclude='__pycache__' "${PROJECT_ROOT}/" /opt/orion/

python3.11 -m venv /opt/orion/venv
/opt/orion/venv/bin/pip install --upgrade pip
/opt/orion/venv/bin/pip install -r /opt/orion/backend/requirements.txt

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  cp "${PROJECT_ROOT}/.env" /etc/orion/orion.env
elif [[ -f "${PROJECT_ROOT}/.env.example" ]]; then
  cp "${PROJECT_ROOT}/.env.example" /etc/orion/orion.env
else
  touch /etc/orion/orion.env
fi
chmod 600 /etc/orion/orion.env
chown root:orion /etc/orion/orion.env

cp /opt/orion/systemd/orion-api.service /etc/systemd/system/
cp /opt/orion/systemd/orion-worker.service /etc/systemd/system/
cp /opt/orion/systemd/orion-beat.service /etc/systemd/system/
cp /opt/orion/systemd/orion-monitor.service /etc/systemd/system/

mkdir -p /etc/nginx/conf.d /etc/nginx/ssl
if [[ -f /opt/orion/nginx/nginx.conf ]]; then
  cp /opt/orion/nginx/nginx.conf /etc/nginx/nginx.conf
fi
if [[ -d /opt/orion/nginx/conf.d ]]; then
  cp -r /opt/orion/nginx/conf.d/* /etc/nginx/conf.d/ 2>/dev/null || true
fi
if [[ -d /opt/orion/nginx/ssl ]]; then
  cp -r /opt/orion/nginx/ssl/* /etc/nginx/ssl/ 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable orion-api orion-worker orion-beat orion-monitor
systemctl start orion-api
sleep 3
systemctl start orion-worker orion-beat orion-monitor
systemctl enable nginx || true
systemctl start nginx || true

chmod +x /opt/orion/scripts/orion_cli.py
ln -sf /opt/orion/scripts/orion_cli.py /usr/local/bin/orion

echo "Service status:"
systemctl --no-pager --full status orion-api orion-worker orion-beat orion-monitor || true
systemctl --no-pager --full status nginx || true
