#!/usr/bin/env bash
# Remove the ORION systemd deployment. Run as root: sudo bash scripts/uninstall_systemd.sh
set -euo pipefail

SERVICES=(orion-monitor orion-beat orion-worker orion-api)

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must run as root (use sudo)." >&2
  exit 1
fi

echo "Stopping and disabling ORION services"
for svc in "${SERVICES[@]}"; do
  systemctl stop "${svc}" 2>/dev/null || true
  systemctl disable "${svc}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

echo "Removing Nginx ORION config"
rm -f /etc/nginx/conf.d/orion.conf /etc/nginx/conf.d/00-orion-http.conf
if command -v nginx >/dev/null && nginx -t 2>/dev/null; then
  systemctl reload nginx 2>/dev/null || true
fi

echo "Removing files"
rm -f /usr/local/bin/orion
rm -rf /opt/orion /etc/orion /var/log/orion

read -r -p "Also remove /var/lib/orion (database backups, beat schedule)? [y/N] " wipe_lib
if [[ "${wipe_lib,,}" == "y" ]]; then
  rm -rf /var/lib/orion
fi

if id -u orion >/dev/null 2>&1; then
  read -r -p "Remove the 'orion' system user? [y/N] " remove_user
  if [[ "${remove_user,,}" == "y" ]]; then
    userdel orion && echo "User 'orion' removed"
  fi
fi

echo "ORION uninstalled."
