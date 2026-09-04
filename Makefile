.PHONY: install migrate seed test lint schema build e2e load up

install:
	python -m pip install -r apps/api/requirements.txt
	cd apps/web && npm ci

migrate:
	cd apps/api && python manage.py migrate

seed:
	cd apps/api && python manage.py seed_demo

test:
	cd apps/api && pytest

lint:
	cd apps/api && ruff check .
	cd apps/web && npm run lint && npm run typecheck

schema:
	cd apps/api && python manage.py spectacular --file schema.yml --validate --fail-on-warn

build:
	cd apps/web && npm run build

e2e:
	cd apps/web && npm run test:e2e

load:
	python infra/load_smoke.py

up:
	docker compose up --build
