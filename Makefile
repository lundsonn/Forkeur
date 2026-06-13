.PHONY: install dev build prod migrate migrate-check migrate-baseline

install:
	cd backend && uv sync
	cd backend/dashboard && npm install
	cd backend && uv run playwright install chromium

dev:
	cd backend && uv run uvicorn main:app --reload --port 8000 &
	cd backend/dashboard && npm run dev

build:
	cd backend/dashboard && npm run build

prod:
	cd backend && uv run uvicorn main:app --port 8000

migrate:
	cd backend && uv run python ops/migrate.py up

migrate-check:
	cd backend && uv run python ops/migrate.py check

migrate-baseline:
	cd backend && uv run python ops/migrate.py baseline
