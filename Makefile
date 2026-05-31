.PHONY: install dev build prod

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
