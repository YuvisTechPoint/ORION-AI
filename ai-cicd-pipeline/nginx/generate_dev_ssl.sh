#!/usr/bin/env sh
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SSL_DIR="${SCRIPT_DIR}/ssl"
mkdir -p "${SSL_DIR}"
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout "${SSL_DIR}/privkey.pem" \
  -out "${SSL_DIR}/fullchain.pem" \
  -subj "/CN=localhost/O=ORION/C=US"
