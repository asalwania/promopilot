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

# Override to run a second, isolated stack, e.g. COMPOSE="docker compose -p pp-test".
COMPOSE ?= docker compose

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

.PHONY: record-cassettes check-cassettes
record-cassettes: db ## Record every scripted session's LLM calls live (OPENAI_API_KEY, OPENAI_MODEL; make data, make train first; ONLY=name re-records one, asking live only what it never asked)
	$(BACKEND) LLM_PROVIDER=openai uv run python -m promopilot.cassettes --sessions cassettes/sessions.json $(foreach name,$(ONLY),--only $(name))
check-cassettes: db ## Replay every scripted session from the cassettes alone, no key (make data, make train first)
	$(BACKEND) uv run python -m promopilot.cassettes --sessions cassettes/sessions.json --check

.PHONY: train
train: db ## Fit the demand then relations models on the loaded data (make data first) and register both
	$(BACKEND) uv run python -m promopilot.models

.PHONY: eval eval-smoke record-eval-cassettes
eval: ## Run the eval scenarios on their own seeded world into backend/evals/reports/ (ONLY=name, SMOKE=1, RUNS=n, SEED=n; no Docker)
	$(BACKEND) uv run python -m promopilot.evals $(foreach name,$(ONLY),--only $(name)) $(if $(SMOKE),--smoke) $(if $(RUNS),--runs $(RUNS)) $(if $(SEED),--seed $(SEED))
eval-smoke: ## What CI runs: replay the 5 smoke scenarios with no key, and fail on a problem or a cassette miss (no Docker)
	$(BACKEND) LLM_PROVIDER=replay uv run python -m promopilot.evals --smoke --check
record-eval-cassettes: ## Play the eval scenarios live and record what no cassette holds into backend/evals/cassettes/ (OPENAI_API_KEY, OPENAI_MODEL; ONLY=name; costs money; no Docker)
	$(BACKEND) LLM_PROVIDER=openai uv run python -m promopilot.evals --record $(foreach name,$(ONLY),--only $(name))

.PHONY: demo demo-down demo-reset
# The demo stack replays the committed cassettes, or goes live when .env holds a key (ADR 0073).
DEMO := STACK_LLM_PROVIDER=auto $(COMPOSE) --profile demo

demo: ## One-command demo in Docker: seed-42 data, trained models, the app; no API key needed
	@echo "==> Building the images (the first build takes a few minutes)"
	$(DEMO) build
	@echo "==> Starting Postgres"
	$(DEMO) up -d --wait postgres
	@echo "==> Preparing the demo data and models (skipped when already done)"
	$(DEMO) run --rm init
	@echo "==> Starting the API and the web app"
	$(DEMO) up -d --wait api web
	@$(COMPOSE) exec -T api python -c "import json, urllib.request; llm = json.load(urllib.request.urlopen('http://localhost:8000/health'))['llm']; print('LLM: ' + ('replaying the recorded demo sessions (no API key)' if llm['mode'] == 'replay' else 'live, ' + llm['provider'] + ' ' + str(llm['model'])))"
	@echo "PromoPilot is ready: http://localhost:$(WEB_PORT)  (stop: make demo-down; start over: make demo-reset)"

demo-down: ## Stop the demo stack, keeping its data and models for a fast restart
	$(DEMO) down

demo-reset: ## Stop the demo stack and delete its data, models and sessions
	$(DEMO) down -v
