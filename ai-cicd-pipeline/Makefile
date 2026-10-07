.PHONY: dev worker beat install migrate test lint verify smoke docker-up docker-down \
        htpasswd dev-nginx prod-nginx nginx-reload nginx-logs nginx-test \
        install-systemd uninstall-systemd update

PYTHON ?= python3
COMPOSE ?= docker compose

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	celery -A app.tasks.pipeline_tasks.celery_app worker --loglevel=info --concurrency=4

beat:
	celery -A app.tasks.pipeline_tasks.celery_app beat --loglevel=info

install:
	$(PYTHON) -m pip install -r requirements.txt

migrate:
	alembic upgrade head

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m pylint app --disable=C0111,C0301,R0903,R0913 --fail-under=8

verify:
	$(PYTHON) scripts/verify_imports.py

smoke:
	$(PYTHON) scripts/smoke_test.py

docker-up: htpasswd
	$(COMPOSE) up -d --build

docker-down:
	$(COMPOSE) down

# ---- Nginx (Feature 2) -------------------------------------------------------------
htpasswd:
	@test -f nginx/.htpasswd || $(PYTHON) scripts/generate_htpasswd.py

dev-nginx: htpasswd
	NGINX_SITE_CONF=orion_dev.conf $(COMPOSE) up -d nginx

prod-nginx: htpasswd
	@test -f nginx/ssl/fullchain.pem -a -f nginx/ssl/privkey.pem || bash nginx/generate_dev_ssl.sh
	NGINX_SITE_CONF=orion.conf $(COMPOSE) up -d --force-recreate nginx

nginx-test:
	$(COMPOSE) exec nginx nginx -t

nginx-reload:
	$(COMPOSE) exec nginx nginx -s reload

nginx-logs:
	$(COMPOSE) logs -f nginx

# ---- systemd (Feature 4) -----------------------------------------------------------
install-systemd:
	sudo bash scripts/install_systemd.sh

uninstall-systemd:
	sudo bash scripts/uninstall_systemd.sh

update:
	sudo bash scripts/update_orion.sh
