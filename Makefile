# PromoPilot developer entry points. Recipes are POSIX sh.
# Windows: run make from Git Bash (cmd.exe/PowerShell have no sh on PATH).

ifeq ($(OS),Windows_NT)
ifeq ($(shell echo posix),$(shell echo 'posix'))
else
$(error make must run from a POSIX shell (Git Bash on Windows))
endif
endif

.DEFAULT_GOAL := help

ifneq (,$(wildcard .env))
include .env
export
endif

API_PORT ?= 8000
WEB_PORT ?= 3000
DATA_DIR ?= ../data

BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup

.PHONY: setup
setup: .env ## Install backend + frontend deps and git hooks
	$(BACKEND) uv sync --locked
	$(FRONTEND) pnpm install --frozen-lockfile
	@if [ -d .git ]; then uvx pre-commit install; fi

.env:
	cp .env.example .env

# ---------------------------------------------------------------- run

.PHONY: db
db: ## Start Postgres in Docker and wait until healthy
	docker compose up -d --wait postgres

.PHONY: dev
dev: db ## Postgres in Docker; API + web natively with hot reload
	$(MAKE) -j2 dev-api dev-web

.PHONY: dev-api
dev-api:
	$(BACKEND) uv run uvicorn --factory promopilot.api.main:build_app --reload --host 127.0.0.1 --port $(API_PORT)

.PHONY: dev-web
dev-web:
	$(FRONTEND) pnpm dev --port $(WEB_PORT)

.PHONY: up
up: ## Build and run the full stack (postgres, api, web) in Docker
	docker compose up -d --build --wait

.PHONY: down
down: ## Stop the Docker stack
	docker compose down

.PHONY: build
build: ## Build the Docker images
	docker compose build

# ---------------------------------------------------------------- quality

.PHONY: lint
lint: ## Lint + format check (ruff, eslint, prettier)
	$(BACKEND) uv run ruff check . && uv run ruff format --check .
	$(FRONTEND) pnpm lint && pnpm format:check

.PHONY: format
format: ## Auto-format backend and frontend
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .
	$(FRONTEND) pnpm format

.PHONY: typecheck
typecheck: ## mypy strict + tsc strict
	$(BACKEND) uv run mypy
	$(FRONTEND) pnpm typecheck

.PHONY: test
test: ## Unit/API tests for both apps (no Docker, no LLM) + core coverage gate
	$(BACKEND) uv run pytest --cov --cov-report=term && uv run coverage json -q -o coverage.json && uv run python -m tools.coverage_gate coverage.json
	$(FRONTEND) pnpm test

.PHONY: test-integration
test-integration: ## Backend integration tests (testcontainers; needs Docker)
	$(BACKEND) uv run pytest -m integration

.PHONY: test-e2e
test-e2e: ## Playwright against a running stack (make dev or make up)
	$(FRONTEND) pnpm test:e2e

.PHONY: api-types
api-types: ## Export OpenAPI and regenerate frontend API types
	$(BACKEND) uv run python -m promopilot.api.openapi > ../docs/openapi.json
	$(FRONTEND) pnpm exec openapi-typescript ../docs/openapi.json -o src/lib/api/schema.d.ts

# ---------------------------------------------------------------- data + later epics

.PHONY: data
data: db ## Generate the seeded synthetic dataset + ground truth into DATA_DIR and load Postgres
	$(BACKEND) uv run python -m promopilot.datagen --out $(DATA_DIR) --load

.PHONY: record-cassettes
record-cassettes: db ## Re-record the LLM cassettes live (OPENAI_API_KEY, OPENAI_MODEL; run make data first)
	$(BACKEND) LLM_PROVIDER=openai uv run python -m promopilot.cassettes --briefs cassettes/briefs.json

.PHONY: train eval demo
train: ## (E4) Train demand + relations models
	@echo "make train arrives in epic E4 (SPEC.md §15)" >&2; exit 1
eval: ## (E9) Run the eval suite
	@echo "make eval arrives in epic E9 (SPEC.md §15)" >&2; exit 1
demo: ## (E11) One-command demo, no API key
	@echo "make demo arrives in epic E11 (SPEC.md §15)" >&2; exit 1
