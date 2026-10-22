SERVICES ?= 0
COMPOSE = docker compose -f docker-compose.yml -f docker-compose.monitoring.yml
ANSIBLE_EXTRA =
ifeq ($(SERVICES),1)
COMPOSE += -f docker-compose.services.yml
ANSIBLE_EXTRA = -e with_services=true
endif
ANSIBLE = cd ansible && ansible-playbook $(ANSIBLE_EXTRA)

.PHONY: check up down ps logs deploy backup restore restore-db reset wipe

check:
	$(COMPOSE) config --quiet && echo "Configuration valide"

up: networks
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

deploy:
	$(ANSIBLE) deploy.yml

backup:
	$(ANSIBLE) backup.yml

restore:
	$(ANSIBLE) restore.yml -e service=$(SERVICE)

restore-db:
	$(ANSIBLE) restore.yml -e restore_db=true

reset:
	$(ANSIBLE) reset.yml

wipe:
	$(COMPOSE) down -v

.PHONY: networks

networks:
	docker network inspect resilience-alpha_front >/dev/null 2>&1 || docker network create resilience-alpha_front
	docker network inspect resilience-alpha_back >/dev/null 2>&1 || docker network create --internal resilience-alpha_back
	docker network inspect resilience-alpha_monitoring >/dev/null 2>&1 || docker network create --internal resilience-alpha_monitoring
	docker network inspect resilience-alpha_remediation >/dev/null 2>&1 || docker network create --internal resilience-alpha_remediation
