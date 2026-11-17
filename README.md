# FitFirst

Your job alerts, scored against your profile. FitFirst reads the LinkedIn and Naukri alert emails you
forward to it, scores each job against your search profiles, picks the best of your resumes with
suggested edits, and prepares a tailored resume and cover letter. **You always submit the application
yourself.**

## How it works

```
LinkedIn / Naukri alert email
        │  you forward it to your personal address: alerts-<token>@<INBOUND_DOMAIN>
        ▼
Cloudflare Email Worker ──HMAC──▶ API /internal/inbound
        ▼
Parse the alert ─▶ shared job catalog (deduplicated by fingerprint)
        ▼
Score each job against your search profiles (hard filters + weighted factors)
        ▼
Recommend your best resume, suggest edits, draft a tailored resume + cover letter (Word / PDF)
        ▼
You review it and apply on the portal yourself, then track the application in FitFirst
```

What FitFirst will never do:

- Automate anything on LinkedIn, Naukri or any other job portal: no scraping, no auto-apply, no auto-connect.
- Store your portal or email passwords. Jobs arrive only by email forwarding.
- Put claims in generated text that your own resumes don't support.

Every user's data is isolated with PostgreSQL row-level security from day one.

## Status

Milestone 1 (foundation) is done. **What works today:** sign up and sign in with silent session refresh,
the candidate profile, up to five weighted search profiles, notification settings, your personal
forwarding address, and a demo account. Alert emails are not processed yet; that is milestone 2.

| # | Scope | Status |
|---|---|---|
| 1 | Accounts, profiles, search profiles, RLS, web shell, CI | done |
| 2 | Alert email ingestion and the job catalog | next |
| 3 | Resumes and AI matching | |
| 4 | Job detail, readiness, tailored packs (Word/PDF) | |
| 5 | Applications tracker | |
| 6 | Notifications and mobile app | |
| 7 | LinkedIn networking helper | |
| 8 | Deployment and hardening | |

What each finished milestone delivered (endpoints, tests, known gaps): [docs/milestones.md](docs/milestones.md).

## Quick start

You need Docker (on Windows: Docker Desktop with WSL 2, and the repo inside the Ubuntu file system).

```bash
git clone https://github.com/ajithmecheeri/FitFirst.git && cd FitFirst
make up
```

- App: **http://localhost:8080**. Sign in as `demo@example.com` / `FitFirst-demo-2026` (a fictional
  sample profile), or create an account.
- API docs: http://localhost:8000/api/docs
- Stop with `make down` (data is kept). `make reset-db` wipes the database.

### Working on the code

Rebuilding Docker images on every change is slow. While coding, run only Postgres in Docker and the
API and web app on your machine (needs Node 22 + pnpm and Python 3.12+):

```bash
make setup    # once: .env, JS packages, Python virtualenv (.venv)
make dev      # Postgres + API (:8000) + web (:3000); Ctrl+C stops the API and web
```

Then use http://localhost:3000. Run `make down` first if `make up` is still running, so that the ports are free.

Full instructions, VS Code, Claude Code and troubleshooting: **[SETUP.md](SETUP.md)**.

## Commands

| Command | What it does |
|---|---|
| `make up` / `make down` | Whole stack in Docker / stop it |
| `make dev` / `make stop` | Fast-edit loop / stop API, web and database |
| `make test` / `make test-local` | Backend tests in Docker / on your machine (real Postgres) |
| `make test-web` | Web unit tests (vitest) and type check |
| `make e2e` | Playwright journey against a running stack |
| `make lint` / `make fmt` | Ruff + tsc / auto-format the backend |
| `make migration m="add jobs"` | New hand-written SQL migration |
| `make api-gen` | Regenerate the typed API client after changing an endpoint |
| `make psql` | SQL prompt as the schema owner |
| `make help` | Everything else |

## Repository layout

```
backend/            FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic migrations, pytest
  app/core/         config, RLS-aware DB session, auth (Argon2id, EdDSA JWT), errors
  app/modules/      one folder per module: models, router, schemas, service
apps/web/           Next.js App Router web app (+ Playwright e2e)
packages/api/       typed API client generated from the OpenAPI schema
packages/ui-tokens/ shared colours and radii
infra/              Caddy, Postgres init (roles), Cloudflare email worker
docs/               requirements (BRD), low-level design (LLD), milestone log
```

The Expo mobile app (`apps/mobile/`) arrives in milestone 6.

## Stack

FastAPI · PostgreSQL 16 with pgvector · Next.js · Caddy · Docker Compose · GitHub Actions CI.
Coming later: Procrastinate background worker (M2), MinIO file storage and Claude Haiku 5.5 / Sonnet 5.5
with Voyage embeddings (M3), React Native (Expo) (M6).

## Documentation

| File | For |
|---|---|
| [SETUP.md](SETUP.md) | Getting it running, editor setup, configuration, troubleshooting |
| [CLAUDE.md](CLAUDE.md) | Rules and conventions for working in the code (people and Claude Code) |
| [docs/README.md](docs/README.md) | Design documents, and which one wins when they disagree with the code |
| [docs/BRD.md](docs/BRD.md) | Business requirements: scope, users, features, screens |
| [docs/LLD.md](docs/LLD.md) | Low-level design: modules, API contracts, schema, jobs, deployment |
| [docs/milestones.md](docs/milestones.md) | What each finished milestone delivered |

## Contributing

Read [CLAUDE.md](CLAUDE.md) first. In short: every endpoint gets a happy-path and an error-path test,
every new private table gets RLS and a cross-user isolation test, and `make test-local` and `make lint`
must pass before you commit.
