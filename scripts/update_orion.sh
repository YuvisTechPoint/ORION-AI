#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root."
  exit 1
fi

if [[ ! -d /opt/orion/.git ]]; then
  echo "/opt/orion is not a git repo. Aborting update."
  exit 1
fi

cd /opt/orion
git pull --ff-only

if [[ -x /opt/orion/venv/bin/pip ]]; then
  /opt/orion/venv/bin/pip install -r /opt/orion/backend/requirements.txt
fi

if [[ -x /opt/orion/venv/bin/alembic ]]; then
  /opt/orion/venv/bin/alembic upgrade head || true
fi

systemctl reload orion-api || systemctl restart orion-api
systemctl restart orion-worker orion-beat orion-monitor

echo "ORION update complete."
