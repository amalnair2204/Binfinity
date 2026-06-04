.PHONY: build up down migrate logs test monitor monitor-down

COMPOSE         = docker compose -f infra/docker-compose.yml
COMPOSE_MONITOR = docker compose -f infra/docker-compose.yml -f infra/docker-compose.monitoring.yml

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) run --rm migrate

logs:
	$(COMPOSE) logs -f

test:
	pytest tests/ -x -q

monitor:
	$(COMPOSE_MONITOR) up -d

monitor-down:
	$(COMPOSE_MONITOR) down
