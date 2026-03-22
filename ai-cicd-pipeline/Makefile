.PHONY: dev worker dev-nginx prod-nginx nginx-reload nginx-logs migrate test install docker-up docker-down

dev:
	uvicorn app.main:app --reload --port 8001

worker:
	celery -A app.tasks.pipeline_tasks.celery_app worker -l info

dev-nginx:
	cp nginx/nginx.conf /tmp/nginx-orion.conf
	sed -i.bak 's|include /etc/nginx/conf.d/orion.conf;|include /etc/nginx/conf.d/orion_dev.conf;|' /tmp/nginx-orion.conf || true
	@echo "Use: docker compose exec nginx nginx -s reload (after mounting orion_dev.conf as orion.conf)"

prod-nginx:
	bash nginx/generate_dev_ssl.sh
	@echo "Ensure nginx/ssl/fullchain.pem and privkey.pem exist; use nginx/conf.d/orion.conf"

nginx-reload:
	docker compose exec nginx nginx -s reload

nginx-logs:
	docker compose logs -f nginx

migrate:
	alembic upgrade head

test:
	pytest -q

install:
	pip install -r requirements.txt

docker-up:
	docker compose up --build

docker-down:
	docker compose down
