# =============================================================================
# Plateforme RH — Makefile
# =============================================================================

.PHONY: help install dev test lint format migrate upgrade shell docker-up docker-down

help:                        ## Afficher cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:                     ## Installer les dépendances de développement
	pip install -r requirements-dev.txt

dev:                         ## Lancer le serveur de développement
	APP_ENV=development flask --app wsgi:application run --debug --reload

test:                        ## Lancer la suite de tests
	pytest tests/ -v --cov=app --cov-report=term-missing

lint:                        ## Vérifier la qualité du code
	ruff check app/ tests/
	mypy app/ --ignore-missing-imports

format:                      ## Formater le code
	ruff format app/ tests/
	black app/ tests/

migrate:                     ## Générer une nouvelle migration
	flask --app wsgi:application db migrate -m "$(MSG)"

upgrade:                     ## Appliquer les migrations en attente
	flask --app wsgi:application db upgrade

downgrade:                   ## Annuler la dernière migration
	flask --app wsgi:application db downgrade

shell:                       ## Ouvrir un shell Flask interactif
	flask --app wsgi:application shell

docker-up:                   ## Démarrer tous les services Docker
	docker compose up -d

docker-down:                 ## Arrêter tous les services Docker
	docker compose down

docker-logs:                 ## Suivre les logs de l'application
	docker compose logs -f app worker

worker:                      ## Lancer le worker Celery en développement
	celery -A wsgi.celery worker --loglevel=info

beat:                        ## Lancer le scheduler Celery Beat
	celery -A wsgi.celery beat --loglevel=info
