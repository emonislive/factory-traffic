.PHONY: up down test-domain test-all lint migrate seed

up:
	docker compose up -d

down:
	docker compose down

test-domain:
	PYTHONPATH=backend pytest backend/tests/domain/

test-all:
	PYTHONPATH=backend pytest backend/tests/

lint:
	ruff check backend/ && mypy --config-file backend/pyproject.toml backend/

migrate:
	alembic -c backend/alembic.ini upgrade head

seed:
	PYTHONPATH=backend python -m app.seed
