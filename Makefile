.PHONY: help install dev backend frontend worker migrate revision test lint up down logs clean

ROOT := $(shell pwd)

help:
	@echo "Photo Album Creator — common commands"
	@echo ""
	@echo "  make install      install backend (uv/pip) + frontend (npm) deps"
	@echo "  make up           start postgres + redis (docker compose)"
	@echo "  make down         stop docker services"
	@echo "  make migrate      apply alembic migrations"
	@echo "  make revision m='msg'  create a new alembic migration"
	@echo "  make dev          run backend + frontend in parallel"
	@echo "  make backend      run backend only (uvicorn, reload)"
	@echo "  make frontend     run frontend only (vite)"
	@echo "  make worker       run celery vision worker"
	@echo "  make test         run backend + frontend tests"
	@echo "  make lint         ruff + eslint"
	@echo "  make clean        remove caches, build dirs"

install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
	cd frontend && npm install

up:
	docker compose up -d
	@echo "Waiting for postgres + redis to become healthy..."
	@until docker compose ps --format json | grep -q '"Health":"healthy"' ; do sleep 1 ; done
	@echo "Services up."

down:
	docker compose down

migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

revision:
	@test -n "$(m)" || (echo "Usage: make revision m='your message'" && exit 1)
	cd backend && . .venv/bin/activate && alembic revision --autogenerate -m "$(m)"

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

worker:
	cd backend && . .venv/bin/activate && OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
	  celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

dev:
	@$(MAKE) -j2 backend frontend

test:
	cd backend && . .venv/bin/activate && pytest -q
	cd frontend && npm test -- --run

lint:
	cd backend && . .venv/bin/activate && ruff check app tests
	cd frontend && npm run lint

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -rf frontend/dist frontend/.vite frontend/coverage
