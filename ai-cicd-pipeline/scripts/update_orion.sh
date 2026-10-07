#!/usr/bin/env bash
# Pull the latest code, sync it to /opt/orion, migrate, and restart with minimal downtime.
#   sudo bash scripts/update_orion.sh            (run from the git checkout)
#   sudo ORION_SRC_DIR=/srv/orion-src orion-update
set -euo pipefail

SRC_DIR="${ORION_SRC_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR=/opt/orion
ENV_FILE=/etc/orion/orion.env
BRANCH="${ORION_BRANCH:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must run as root (use sudo)." >&2
  exit 1
fi
if [[ ! -d "${SRC_DIR}/.git" ]]; then
  echo "${SRC_DIR} is not a git checkout; set ORION_SRC_DIR to your clone of the repository." >&2
  exit 1
fi

echo "==> Pulling latest code in ${SRC_DIR}"
OWNER="$(stat -c '%U' "${SRC_DIR}")"
if [[ -n "${BRANCH}" ]]; then
  runuser -u "${OWNER}" -- git -C "${SRC_DIR}" fetch origin "${BRANCH}"
  runuser -u "${OWNER}" -- git -C "${SRC_DIR}" checkout "${BRANCH}"
fi
runuser -u "${OWNER}" -- git -C "${SRC_DIR}" pull --ff-only
OLD_REQ_HASH="$(sha256sum "${APP_DIR}/requirements.txt" 2>/dev/null | cut -d' ' -f1 || true)"

echo "==> Syncing to ${APP_DIR}"
rsync -a --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='venv' \
  --exclude='.pytest_cache' --exclude='nginx/logs' --exclude='.env' \
  "${SRC_DIR}/" "${APP_DIR}/"
chown -R orion:orion "${APP_DIR}"

if [[ "$(sha256sum "${APP_DIR}/requirements.txt" | cut -d' ' -f1)" != "${OLD_REQ_HASH}" ]]; then
  echo "==> requirements.txt changed; installing dependencies"
  "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
fi

echo "==> Running migrations"
(
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  cd "${APP_DIR}"
  runuser -u orion -- "${APP_DIR}/venv/bin/alembic" upgrade head
)

if ! cmp -s "${APP_DIR}/systemd/orion-api.service" /etc/systemd/system/orion-api.service; then
  echo "==> Unit files changed; reinstalling"
  for svc in orion-api orion-worker orion-beat orion-monitor; do
    cp "${APP_DIR}/systemd/${svc}.service" "/etc/systemd/system/${svc}.service"
  done
  systemctl daemon-reload
fi

echo "==> Reloading API (graceful worker restart via SIGHUP)"
systemctl reload orion-api || systemctl restart orion-api

echo "==> Restarting Celery worker (warm shutdown finishes in-flight tasks), beat and monitor"
systemctl restart orion-worker orion-beat orion-monitor

sleep 3
for svc in orion-api orion-worker orion-beat orion-monitor; do
  printf '  %-15s %s\n' "${svc}" "$(systemctl is-active "${svc}" || true)"
done
echo "ORION updated to $(git -C "${SRC_DIR}" rev-parse --short HEAD)."
