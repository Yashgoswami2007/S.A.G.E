.PHONY: dev up down build migrate lint test clean

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

migrate:
	cd backend && alembic upgrade head

lint:
	cd backend && ruff check .

test:
	cd backend && pytest

clean:
	docker compose down -v
	find . -type d -name "__pycache__" -exec rm -rf {} +
