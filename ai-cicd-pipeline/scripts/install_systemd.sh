#!/usr/bin/env bash
# Install ORION as systemd services on Ubuntu 22.04 / Debian 12. Run as root from the repo root:
#   sudo bash scripts/install_systemd.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/orion
ENV_DIR=/etc/orion
ENV_FILE="${ENV_DIR}/orion.env"
LOG_DIR=/var/log/orion
LIB_DIR=/var/lib/orion
SERVICES=(orion-api orion-worker orion-beat orion-monitor)
INSTALL_NGINX="${ORION_INSTALL_NGINX:-1}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must run as root (use sudo)." >&2
  exit 1
fi

for bin in rsync systemctl; do
  command -v "${bin}" >/dev/null || { echo "Missing required command: ${bin}" >&2; exit 1; }
done

PYTHON_BIN="$(command -v python3.11 || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
  echo "python3.11 not found; falling back to ${PYTHON_BIN:-<none>}"
fi
[[ -n "${PYTHON_BIN}" ]] || { echo "Python 3 is required" >&2; exit 1; }

log "Creating system user 'orion'"
if ! id -u orion >/dev/null 2>&1; then
  useradd -r -s /sbin/nologin -d "${APP_DIR}" orion
fi

log "Creating directories"
mkdir -p "${APP_DIR}" "${ENV_DIR}" "${LOG_DIR}" "${LIB_DIR}/backups"

log "Copying project files to ${APP_DIR}"
rsync -av --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='venv' \
  --exclude='.pytest_cache' --exclude='nginx/logs' --exclude='.env' \
  "${SRC_DIR}/" "${APP_DIR}/"
chown -R orion:orion "${APP_DIR}" "${LOG_DIR}" "${LIB_DIR}"

log "Creating virtualenv at ${APP_DIR}/venv"
"${PYTHON_BIN}" -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
chown -R orion:orion "${APP_DIR}/venv"

log "Installing environment file ${ENV_FILE}"
if [[ -f "${ENV_FILE}" ]]; then
  echo "${ENV_FILE} already exists; leaving it untouched"
elif [[ -f "${SRC_DIR}/.env" ]]; then
  cp "${SRC_DIR}/.env" "${ENV_FILE}"
else
  cp "${SRC_DIR}/.env.example" "${ENV_FILE}"
  echo "WARNING: no .env found; copied .env.example — edit ${ENV_FILE} with real credentials"
fi
sed -i 's/^APP_PORT=.*/APP_PORT=8000/' "${ENV_FILE}"
# systemd reads EnvironmentFile as root before dropping to User=orion, so 600 is sufficient.
chmod 600 "${ENV_FILE}"
chown root:orion "${ENV_FILE}"

log "Running database migrations"
(
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  cd "${APP_DIR}"
  runuser -u orion -- "${APP_DIR}/venv/bin/alembic" upgrade head
) || echo "WARNING: migrations failed — check DATABASE_URL in ${ENV_FILE}, then run: orion db-migrate"

log "Installing systemd units"
for svc in "${SERVICES[@]}"; do
  cp "${APP_DIR}/systemd/${svc}.service" "/etc/systemd/system/${svc}.service"
  chmod 644 "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
systemctl enable "${SERVICES[@]}"
systemctl start orion-api && sleep 3 && systemctl start orion-worker orion-beat orion-monitor

if [[ "${INSTALL_NGINX}" == "1" ]]; then
  log "Configuring Nginx reverse proxy"
  if ! command -v nginx >/dev/null; then
    if command -v apt-get >/dev/null; then
      apt-get update && apt-get install -y nginx
    else
      echo "nginx not installed and apt-get unavailable; skipping proxy setup"
      INSTALL_NGINX=0
    fi
  fi
fi

if [[ "${INSTALL_NGINX}" == "1" ]]; then
  mkdir -p /etc/nginx/conf.d /etc/nginx/ssl
  if [[ -f "${APP_DIR}/nginx/ssl/fullchain.pem" && -f "${APP_DIR}/nginx/ssl/privkey.pem" ]]; then
    cp "${APP_DIR}/nginx/ssl/fullchain.pem" "${APP_DIR}/nginx/ssl/privkey.pem" /etc/nginx/ssl/
    chmod 600 /etc/nginx/ssl/privkey.pem
  fi
  SITE_CONF=orion_dev.conf
  if [[ -f /etc/nginx/ssl/fullchain.pem && -f /etc/nginx/ssl/privkey.pem ]]; then
    SITE_CONF=orion.conf
  fi
  cp "${APP_DIR}/nginx/host/orion_http.conf" /etc/nginx/conf.d/00-orion-http.conf
  sed -e 's/server app:8000;/server 127.0.0.1:8000;/' \
      -e 's/server flower:5555;/server 127.0.0.1:5555;/' \
      "${APP_DIR}/nginx/conf.d/${SITE_CONF}" > /etc/nginx/conf.d/orion.conf
  if [[ ! -f /etc/nginx/.htpasswd ]]; then
    (
      set -a; source "${ENV_FILE}"; set +a
      "${APP_DIR}/venv/bin/python" "${APP_DIR}/scripts/generate_htpasswd.py" --out /etc/nginx/.htpasswd
    )
  fi
  chmod 644 /etc/nginx/.htpasswd
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable nginx && systemctl start nginx
  systemctl reload nginx
  echo "Nginx configured with ${SITE_CONF}"
fi

log "Installing 'orion' CLI"
chmod +x "${APP_DIR}/scripts/orion_cli.py"
ln -sf "${APP_DIR}/scripts/orion_cli.py" /usr/local/bin/orion

log "Service status"
for svc in "${SERVICES[@]}" $([[ "${INSTALL_NGINX}" == "1" ]] && echo nginx); do
  printf '  %-15s %s\n' "${svc}" "$(systemctl is-active "${svc}" || true)"
done

cat <<EOF

ORION installed.
  API:      http://$(hostname -I 2>/dev/null | awk '{print $1}'):8000  (proxied on :80/:443 by nginx)
  Logs:     orion logs orion-api --lines 100
  Status:   orion status
  Config:   ${ENV_FILE}
EOF
