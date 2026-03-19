.PHONY: help dev prod build stop logs shell clean db-shell worker beat status restart

help: ## Show help
	@echo 'Available commands:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

dev: ## Start development server (web + db + redis + celery)
	docker compose up --build

prod: ## Start production with nginx
	docker compose --profile production up --build -d

build: ## Build images
	docker compose build

stop: ## Stop services
	docker compose --profile production down

logs: ## Show logs (all services)
	docker compose logs -f

logs-web: ## Show web server logs
	docker compose logs -f web

logs-worker: ## Show Celery worker logs
	docker compose logs -f celery-worker

logs-beat: ## Show Celery beat logs
	docker compose logs -f celery-beat

shell: ## Open shell in web container
	docker compose exec web bash

db-shell: ## Open PostgreSQL shell
	docker compose exec db psql -U $${POSTGRES_USER:-horilla_user} -d $${POSTGRES_DB:-horilla_db}

worker: ## Start Celery worker standalone
	docker compose up -d celery-worker

beat: ## Start Celery beat standalone
	docker compose up -d celery-beat

status: ## Show status of all services
	docker compose ps

restart: ## Restart all services
	docker compose restart

clean: ## Clean up (removes volumes — data loss!)
	docker compose --profile production down -v
	docker system prune -f
