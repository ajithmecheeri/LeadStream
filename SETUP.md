# Setting up FitFirst on your laptop

This gets the app running locally, then sets up VS Code and Claude Code for building the next
milestones. Allow about 20 minutes the first time (most of it is Docker downloading images).

## 1. Install the tools

| Tool | Why | Get it |
|---|---|---|
| Docker Desktop | Runs the whole stack | docker.com/products/docker-desktop |
| Git | Clone and commit | git-scm.com |
| VS Code | Editor | code.visualstudio.com |
| Node.js 22 + pnpm | Web app, only for the fast-edit setup (step 5) | nodejs.org, then `corepack enable` |
| Python 3.12 or newer | API, only for the fast-edit setup (step 5) | python.org |
| Claude Code | AI pair programmer in the terminal and VS Code | macOS/Linux/WSL: `curl -fsSL https://claude.ai/install.sh \| bash` · Windows PowerShell: `irm https://claude.ai/install.ps1 \| iex` (needs a Pro, Max, Team, Enterprise or Console account) |

**Windows:** use WSL 2 (Ubuntu). Install Docker Desktop with the WSL 2 backend, then do everything
below inside the Ubuntu terminal, and keep the repo in the Linux file system (`~/code/FitFirst`,
not `/mnt/c/...`), which is much faster. Run `sudo apt install make` if `make` is missing.

**macOS:** `xcode-select --install` gives you `git` and `make`.

Check: `docker --version`, `docker compose version`, `git --version`, `make --version`.

## 2. Get the code

```bash
git clone https://github.com/ajithmecheeri/FitFirst.git
cd FitFirst
```

## 3. Start everything

```bash
make up
```

The first run builds the API and web images and starts five containers:

| Container | What | Port on your laptop |
|---|---|---|
| caddy | Front door: `/api` → API, everything else → web | **8080** |
| web | Next.js app | (behind Caddy) |
| api | FastAPI; runs migrations and loads the demo user on start | 8000 (API docs) |
| worker | Background jobs (reading alert emails); same image as the API. Restart after editing a task: `make restart` | — |
| db | PostgreSQL 16 with pgvector; also holds the job queue | 5432 |

When it finishes:

- App: **http://localhost:8080**. Sign in as `demo@example.com` / `FitFirst-demo-2026`, or create an account.
- API docs (try any endpoint): http://localhost:8000/api/docs
- `make ps` shows status, `make logs` follows logs (`make logs s=api` for one service).

## 4. Check it works

```bash
make test        # 24 backend tests, run inside the api container
```

In the browser: sign up with a new email, fill in **Profile**, create a **Search profile**, sign out,
sign back in, reload the page (you should stay signed in).

Useful commands: `make down` (stop), `make up` (start again; data is kept), `make reset-db`
(wipe the database), `make psql` (SQL prompt), `make help` (everything else).

## 5. Fast-edit setup (optional, recommended while coding)

Docker rebuilds the web image on every change, which is slow. For day-to-day work run only the
database in Docker and the code directly:

```bash
make setup       # once: creates .env, installs JS packages and a Python virtualenv (.venv)
make dev         # Postgres in Docker + API (:8000) + web (:3000) in one terminal
```

Ctrl+C stops the API and the web app together; `make stop` also stops the database (data is kept).
If you prefer separate terminals: `make db`, then `make dev-api` and `make dev-web`, each in its own terminal.

Then use **http://localhost:3000**. Tests: `make test-local`, `make test-web`, and with both servers
running, `make e2e` (first time: `pnpm --filter @fitfirst/web exec playwright install chromium`; if Chromium
then complains about missing libraries such as `libnspr4.so`, use `make e2e-docker` against `make up` instead:
it runs the same tests in Playwright's Docker image).

> If you ran `make up` before, stop it first (`make down`) so ports 8000 and 3000 are free, then `make db`.

## 6. VS Code

```bash
code .
```

Accept the recommended extensions (Python, Ruff, Docker, Playwright, Claude Code). Choose the
interpreter `.venv/bin/python` if VS Code asks. The Run and Debug panel has **API (debug)** for
breakpoints in the API and **Backend tests**.

## 7. Claude Code

From the repo root:

```bash
claude
```

Claude Code reads `CLAUDE.md` automatically: the rules (no portal automation, RLS on every private
table), the layout, the commands and the milestone plan. Good ways to use it:

- "Start milestone 2 as described in CLAUDE.md. Plan first, then build it module by module, with tests."
- "Add a `headline` field to search profiles: migration, model, schema, API, web form, tests, api-gen."
- "Run `make test-local` and fix any failures."

Ask it to run the tests and the e2e journey before you commit, and review each diff. When a milestone
is done, ask it to update `CLAUDE.md` and `docs/milestones.md`.

## 8. Configuration

Settings live in `.env` (created from `.env.example`). Defaults work locally. What changes later:

| Variable | When |
|---|---|
| `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` | Production. Generate with `make keys`. Locally a key is created at start-up. |
| `INBOUND_DOMAIN` | Milestone 2, your real mail domain (e.g. `in.fitfirst.in`) |
| `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` | Milestone 3 (AI scoring, resume ranking, packs) |
| `SITE_ADDRESS`, `COOKIE_SECURE=true`, `ENV=prod` | Deployment (milestone 8) |

Never commit `.env`; it's in `.gitignore`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `port is already allocated` | Something else uses 8080/8000/5432/3000. Stop it, or change the left-hand port in `docker-compose.yml`. A local Postgres is the usual culprit for 5432. |
| API keeps restarting, logs say `role "fitfirst_app" does not exist` | The database volume predates the init script. `make reset-db && make up`. |
| `make: command not found` on Windows | Use the WSL Ubuntu terminal and `sudo apt install make`. |
| Web shows "Something went wrong" | `make logs s=api` and look for the `request_id` shown in the error. |
| Tests fail with connection refused | `make up` (for `make test`) or `make db` (for `make test-local`) first. |
