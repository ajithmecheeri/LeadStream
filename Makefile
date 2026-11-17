# BrewMyJob developer commands. `make help` lists them.
SHELL := /bin/bash
COMPOSE := docker compose
API := $(COMPOSE) exec api
# Use the project virtualenv when it exists (created by `make setup`).
PY ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)

.DEFAULT_GOAL := help
.PHONY: help setup up down restart logs ps reset-db db dev dev-api dev-worker dev-web stop test test-local test-web e2e e2e-docker lint fmt \
        migrate migration seed seed-reset admin api-gen keys psql parse inbound \
        tunnel email-worker-secret email-worker-deploy email-worker-logs

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## First-time setup: .env, JS packages, Python virtualenv (.venv) for VS Code
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	corepack enable || true
	pnpm install
	@python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required (python3 is %d.%d)" % sys.version_info[:2])'
	@test -x .venv/bin/pip || (rm -rf .venv && python3 -m venv .venv) || \
		(echo "Could not create .venv. On Ubuntu run: sudo apt install -y python3-venv python3-pip" && exit 1)
	@test -x .venv/bin/pip || (echo "pip is missing from .venv. Run: sudo apt install -y python3-venv, then make setup" && rm -rf .venv && exit 1)
	.venv/bin/pip install -e "backend[dev]"

# --- Everything in Docker --------------------------------------------------
up: ## Build and start the whole stack (http://localhost:8080)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build
	@echo "BrewMyJob: http://localhost:8080   API docs: http://localhost:8000/api/docs"
	@echo "Demo sign-in: demo@example.com / FitFirst-demo-2026"

down: ## Stop the stack (keeps the database)
	$(COMPOSE) --profile tunnel down

restart: ## Restart api, worker and web
	$(COMPOSE) restart api worker web

logs: ## Follow logs (make logs s=api for one service)
	$(COMPOSE) logs -f $(s)

ps: ## Show running services
	$(COMPOSE) ps

reset-db: ## DELETE the local database volume and start fresh
	$(COMPOSE) down -v

# --- Hybrid: database in Docker, code on your machine (fastest edit loop) --
db: ## Start only Postgres
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d db

dev: db ## Start database + API + worker + web in ONE terminal; Ctrl+C stops them
	@./scripts/dev.sh

stop: ## Stop everything: API, web and the database container
	-@fuser -k 8000/tcp 3000/tcp 2>/dev/null || true
	$(COMPOSE) --profile tunnel stop
	@echo "Stopped. Data is kept."

dev-api: ## Run the API locally with reload (needs `make db`)
	cd backend && $(PY) -m alembic upgrade head && $(PY) -m app.seed && $(PY) -m uvicorn app.main:app --reload --port 8000

dev-worker: ## Run the background worker locally (needs dev-api to have applied migrations)
	cd backend && $(PY) -m procrastinate --app=app.core.worker.app worker

dev-web: ## Run the web app locally with hot reload on http://localhost:3000 (needs dev-api)
	pnpm --filter @fitfirst/web dev

# --- Quality ----------------------------------------------------------------
test: ## Backend tests inside Docker (stack must be up)
	$(API) python -m pytest -q

test-local: ## Backend tests on your machine (needs `make db`)
	cd backend && $(PY) -m pytest -q

test-web: ## Web unit tests and type check
	pnpm --filter @fitfirst/web test
	pnpm --filter @fitfirst/web typecheck
	pnpm --filter @fitfirst/email-worker test

e2e: ## Browser end-to-end tests against a running stack (E2E_BASE_URL, default :3000)
	pnpm --filter @fitfirst/web e2e

# Playwright's own image has Chromium and the system libraries it needs (no sudo on the laptop).
PW_VERSION = $(shell node -p "require('./apps/web/package.json').devDependencies['@playwright/test']")
e2e-docker: ## e2e in the Playwright Docker image, against `make up` (http://localhost:8080)
	docker run --rm --network host --user $$(id -u):$$(id -g) -e HOME=/tmp \
		-e E2E_BASE_URL=$${E2E_BASE_URL:-http://localhost:8080} -v "$(CURDIR)":/repo -w /repo/apps/web \
		mcr.microsoft.com/playwright:v$(PW_VERSION)-noble node_modules/.bin/playwright test $(ARGS)

lint: ## Lint and format checks
	cd backend && $(PY) -m ruff check . && $(PY) -m ruff format --check .
	pnpm -r typecheck

fmt: ## Auto-format the backend
	cd backend && $(PY) -m ruff check --fix . && $(PY) -m ruff format .

# --- Database ---------------------------------------------------------------
migrate: ## Apply migrations (Docker)
	$(API) python -m alembic upgrade head

migration: ## New migration file: make migration m="add jobs table"
	$(API) python -m alembic revision -m "$(m)"

seed: ## Load the demo user (Docker)
	$(API) python -m app.seed

seed-reset: ## Recreate the demo user (Docker)
	$(API) python -m app.seed --reset

admin: ## Make an account super admin: make admin EMAIL=you@example.com [REVOKE=1]
	@test -n "$(EMAIL)" || (echo 'usage: make admin EMAIL=you@example.com [REVOKE=1]' && exit 2)
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -qx api; then \
		$(API) python -m app.admin $(EMAIL) $(if $(REVOKE),--revoke); \
	else cd backend && $(PY) -m app.admin $(EMAIL) $(if $(REVOKE),--revoke); fi

feedback: ## "Not for me" answers to review, with the job and its score now: make feedback [ALL=1]
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -qx api; then \
		$(API) python -m app.feedback_review $(if $(ALL),--all); \
	else cd backend && $(PY) -m app.feedback_review $(if $(ALL),--all); fi

feedback-done: ## Mark feedback reviewed: make feedback-done IDS="1a2b3c4d 5e6f7a8b" NOTE="what changed"
	@test -n "$(IDS)" || (echo 'usage: make feedback-done IDS="id1 id2" NOTE="what changed"' && exit 2)
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -qx api; then \
		$(API) python -m app.feedback_review --done $(IDS) --note "$(NOTE)"; \
	else cd backend && $(PY) -m app.feedback_review --done $(IDS) --note "$(NOTE)"; fi

psql: ## Open psql as the schema owner
	$(COMPOSE) exec db psql -U $${DB_OWNER:-fitfirst} -d $${DB_NAME:-fitfirst}

# --- Alert emails -------------------------------------------------------------
parse: ## Show the jobs found in alert emails: make parse FILE=backend/tests/fixtures/emails/x.eml
	@test -n "$(FILE)" || (echo 'usage: make parse FILE=path/to/alert.eml' && exit 2)
	cd backend && $(PY) -m app.modules.catalog.parsers $(abspath $(FILE))

inbound: ## Send a saved alert email to the running API as if forwarded: make inbound FILE=x.eml [TO=address] [AGAIN=1]
	@test -n "$(FILE)" || (echo 'usage: make inbound FILE=path/to/alert.eml [TO=alerts-…@…] [AGAIN=1]' && exit 2)
	cd backend && $(PY) scripts/send_inbound.py $(abspath $(FILE)) $(if $(TO),--to $(TO)) $(if $(AGAIN),--again)

# --- Real forwarding: Cloudflare email worker + tunnel (infra/cloudflare/email-worker/README.md) ----------
EMAIL_WORKER := pnpm --filter @fitfirst/email-worker exec wrangler

tunnel: ## Connect this machine to Cloudflare so forwarded alerts reach the API (needs CLOUDFLARE_TUNNEL_TOKEN)
	@grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env || (echo 'Add CLOUDFLARE_TUNNEL_TOKEN=… to .env first (see infra/cloudflare/email-worker/README.md)' && exit 2)
	$(COMPOSE) --profile tunnel up -d tunnel
	@echo "Tunnel started. Check it: make logs s=tunnel"

email-worker-secret: ## New INBOUND_HMAC_SECRET in .env and in the email worker (never printed)
	@secret=$$(openssl rand -hex 32) && \
		if grep -q '^INBOUND_HMAC_SECRET=' .env; then sed -i "s/^INBOUND_HMAC_SECRET=.*/INBOUND_HMAC_SECRET=$$secret/" .env; \
		else echo "INBOUND_HMAC_SECRET=$$secret" >> .env; fi && \
		printf '%s' "$$secret" | $(EMAIL_WORKER) secret put INBOUND_HMAC_SECRET
	@if $(COMPOSE) ps --status running api | grep -q api; then $(COMPOSE) up -d api worker; fi
	@echo "Secret set in .env and in the worker. If you use make dev, restart it."

email-worker-deploy: ## Deploy the Cloudflare email worker
	$(EMAIL_WORKER) deploy

email-worker-logs: ## Live log of the email worker (one line per email: recipient prefix, DKIM, outcome)
	$(EMAIL_WORKER) tail --format pretty

# --- Codegen and secrets -----------------------------------------------------
api-gen: ## Regenerate the typed API client after changing endpoints
	pnpm api:gen

keys: ## Print a JWT key pair for .env (needed in prod)
	$(PY) backend/scripts/gen_jwt_keys.py
