#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root."
  exit 1
fi

for svc in orion-monitor orion-beat orion-worker orion-api; do
  systemctl stop "${svc}" 2>/dev/null || true
  systemctl disable "${svc}" 2>/dev/null || true
done

rm -f /etc/systemd/system/orion-api.service
rm -f /etc/systemd/system/orion-worker.service
rm -f /etc/systemd/system/orion-beat.service
rm -f /etc/systemd/system/orion-monitor.service

systemctl daemon-reload

rm -rf /opt/orion /etc/orion /var/log/orion /var/lib/orion
rm -f /usr/local/bin/orion

read -r -p "Remove system user 'orion'? (y/N): " RESP
if [[ "${RESP}" =~ ^[Yy]$ ]]; then
  userdel orion 2>/dev/null || true
fi

echo "ORION systemd uninstall complete."
