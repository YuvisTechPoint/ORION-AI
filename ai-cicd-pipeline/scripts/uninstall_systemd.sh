#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

systemctl disable --now orion-api orion-worker orion-beat orion-monitor 2>/dev/null || true

rm -f /etc/systemd/system/orion-api.service
rm -f /etc/systemd/system/orion-worker.service
rm -f /etc/systemd/system/orion-beat.service
rm -f /etc/systemd/system/orion-monitor.service
rm -f /usr/local/bin/orion

systemctl daemon-reload

echo "ORION systemd units removed."
