SHELL := /bin/bash

.PHONY: dev-nginx prod-nginx nginx-reload nginx-logs

dev-nginx:
	@if [ -f nginx/conf.d/orion.conf ]; then mv nginx/conf.d/orion.conf nginx/conf.d/orion.conf.disabled; fi
	@if [ -f nginx/conf.d/orion_dev.conf.disabled ]; then mv nginx/conf.d/orion_dev.conf.disabled nginx/conf.d/orion_dev.conf; fi
	docker compose up -d nginx

prod-nginx:
	@if [ ! -f nginx/ssl/fullchain.pem ] || [ ! -f nginx/ssl/privkey.pem ]; then bash nginx/generate_dev_ssl.sh; fi
	@if [ -f nginx/conf.d/orion_dev.conf ]; then mv nginx/conf.d/orion_dev.conf nginx/conf.d/orion_dev.conf.disabled; fi
	@if [ -f nginx/conf.d/orion.conf.disabled ]; then mv nginx/conf.d/orion.conf.disabled nginx/conf.d/orion.conf; fi
	docker compose up -d nginx

nginx-reload:
	docker compose exec nginx nginx -s reload

nginx-logs:
	docker compose logs -f nginx
