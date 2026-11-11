# SmartStock RPA — common commands.
# By default backend commands run inside the `api` container.
# For a local (non-Docker) setup with an activated venv, add LOCAL=1, e.g. `make test LOCAL=1`.

ifeq ($(LOCAL),1)
PY := cd backend && python
NPM := cd frontend && npm
else
PY := docker compose exec -T api python
NPM := cd frontend && npm
endif

.PHONY: up down logs ps migrate seed test test-backend test-frontend e2e eval lint fmt backup

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

migrate:
	$(PY) -m alembic upgrade head

seed:
	$(PY) -m app.seed

test: test-backend test-frontend

test-backend:
	$(PY) -m pytest --cov=app --cov-report=term-missing

ifeq ($(LOCAL),1)
test-frontend:
	$(NPM) test
else
test-frontend:
	docker build --target test -t smartstock-web-test ./frontend
endif

e2e:
	$(NPM) run e2e

eval:
	$(PY) scripts/evaluate.py

ifeq ($(LOCAL),1)
lint:
	cd backend && ruff check .
	$(NPM) run lint
else
lint:
	docker compose exec -T api ruff check .
	docker build --target test -t smartstock-web-test ./frontend
endif

fmt:
	cd backend && ruff format . && ruff check --fix .
	$(NPM) run format

backup:
	$(PY) -m app.tasks.run backup
