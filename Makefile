PYTHON := rtk uv run
WEB := rtk bun run --cwd apps/web
BUN_INSTALL := rtk bun install --cwd apps/web
-include .env
ifneq (,$(wildcard .env))
PYTHON_ENV := rtk uv run --env-file .env
else
PYTHON_ENV := rtk uv run
endif

API_HOST ?= 127.0.0.1
API_PORT ?= 8000
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 5173

.PHONY: help install test check \
	backend-test backend-lint backend-format backend-format-check backend-type backend-check backend-server backend-test-server \
	frontend-install frontend-test frontend-lint frontend-format frontend-format-check frontend-build frontend-check frontend-server frontend-test-server

help:
	@echo "Targets:"
	@echo "  make install              Install Python dev deps and frontend bun deps"
	@echo "  make test                 Run backend and frontend tests"
	@echo "  make check                Run tests, lint, type checks, and web build"
	@echo "  make backend-server       Start FastAPI from voice_toolbox.toml or fallback config"
	@echo "  make frontend-server      Start Vite on $(WEB_HOST):$(WEB_PORT)"

install:
	rtk uv sync --extra dev
	$(BUN_INSTALL)

test: backend-test frontend-test

check: backend-check frontend-check

backend-test:
	$(PYTHON) pytest -v

backend-lint:
	$(PYTHON) ruff check .

backend-format:
	$(PYTHON) ruff format .

backend-format-check:
	$(PYTHON) ruff format --check .

backend-type:
	$(PYTHON) ty check packages/voice_toolbox/src apps/api/src

backend-check: backend-lint backend-format-check backend-type backend-test

backend-server:
	$(PYTHON_ENV) python -m voice_toolbox_api.server

backend-test-server: backend-server

frontend-install:
	$(BUN_INSTALL)

frontend-test:
	$(WEB) test

frontend-lint:
	$(WEB) lint

frontend-format:
	$(WEB) format

frontend-format-check:
	$(WEB) format:check

frontend-build:
	$(WEB) build

frontend-check: frontend-lint frontend-format-check frontend-test frontend-build

frontend-server:
	$(WEB) dev -- --host $(WEB_HOST) --port $(WEB_PORT)

frontend-test-server: frontend-server
