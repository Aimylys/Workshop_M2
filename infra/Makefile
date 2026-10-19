COMPOSE = docker compose -f docker-compose.yml -f docker-compose.monitoring.yml

.PHONY: check up down ps logs reset

check:
	$(COMPOSE) config --quiet && echo "Configuration valide"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

reset:
	$(COMPOSE) down -v
