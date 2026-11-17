# Milestone 2 plan: alert email ingestion and the Jobs list

Goal: a forwarded LinkedIn or Naukri alert becomes jobs in the Jobs list, end to end locally
(`make inbound FILE=…`) without Cloudflare, and through Cloudflare once a domain is set up.

## Build order: thin slice first

1. **Slice:** modules 0–7 with the minimum in each, so `make inbound FILE=<linkedin alert>` shows jobs on
   the Jobs page.
2. **Widen:** Naukri parsers wired in, cross-source dedupe, Inbox and Mail setup pages, filters, job detail.
3. **Cloudflare Email Worker** (module 8), when a domain is available.
4. **Docs and e2e** (module 9).

## Modules

| # | Module | Status |
|---|---|---|
| 0 | `app/core`: Procrastinate worker (`core/worker.py`, as `fitfirst_app`), `user_scope(user_id)` for code outside a request, settings (`inbound_hmac_secret`, 5 MB limit, 90-day retention), `worker` container, `make dev-worker`, worker in `make dev` | **done** |
| 1 | Migration `0002`: `inbound_messages`, `inbound_raw`, `user_jobs` (private, RLS FORCE); `jobs`, `job_sources` (shared, no delete for the app role); Procrastinate 3.9.0 schema (vendored in `migrations/sql/`); models; isolation tests | **done** |
| 2 | `catalog/parsers`: LinkedIn digest, Naukri recommendations, Naukri recruiter invite; normalisation and fingerprint; golden tests; `make parse` | **done** |
| 3 | `catalog/service.py`: `upsert_cards(db, cards)`: dedupe by listing, URL, fingerprint; merge facts; advisory locks against concurrent workers. Lines about the recipient (`JobCard.card_lines`) stay out of the catalog | **done** |
| 4 | `ingestion`: `POST /internal/inbound` (HMAC), `GET /mail`, `POST /mail/address/rotate`, `GET /inbox/messages`; Gmail forwarding-confirmation code; `parse_alert` task (parse → catalog → `user_jobs`); `make inbound` | **done** (paste/upload moved to "Widen") |
| 5 | `jobs`: `GET /jobs` (status, source, lead, search, date range in the user's time zone, paging), `GET /jobs/stats`, `GET/PATCH /jobs/{id}`, `POST /jobs/{id}/description`; migration `0003` (`user_jobs.description`); local-only `POST /inbox/upload` | **done** |
| 6 | Worker tasks: ~~`parse_alert`~~ (built in module 4: 5 attempts, ~30 s apart), `sweep_inbound` (every 5 min: re-queue lost messages, mark `failed` after the retries), `purge_raw_email` (daily 02:00 UTC) | **done** |
| 7 | Web: `/settings/mail`, `/inbox` (with "Upload .eml" locally), `/jobs`, `/jobs/[id]`, dashboard Jobs card, nav; vitest for `lib/jobs.ts`; e2e `alerts-to-jobs.spec.ts`; `make e2e-docker` | **done** |
| 8 | Cloudflare Email Worker (DKIM, allow-list, HMAC, retries): `infra/cloudflare/email-worker` for brewmyjob.com (`alerts-<token>@in.brewmyjob.com`); Cloudflare Tunnel (`make tunnel`) to the api container until the server exists; KV outbox + 10-minute cron retry for 7 days; 20 vitest tests | **built** (2026-11-03), waiting for the one-time Cloudflare setup and a real Gmail test |
| 9 | `make inbound`, docs (CLAUDE.md, milestones, docs/README, SETUP), README status | |

## Decisions (differences from the LLD are also listed in docs/README.md when the migration lands)

- **Raw email** is stored in Postgres (`inbound_raw`, bytea, private) and deleted after 90 days; milestone 3
  moves it to MinIO. The purge runs per user inside `user_scope`, because RLS (FORCE) hides other users'
  rows even from the table owner.
- **Dedupe order:** `(source, source_job_id)`, then canonical URL, then fingerprint
  (sha256 of normalised company | title | location; none when the company is unknown or truncated).
  Semantic dedupe waits for embeddings in milestone 3.
- **`job_sources.url` is nullable** with a unique `(source, source_job_id)`: recruiter invites have no
  public page. Sources: `linkedin`, `naukri`, `naukri_rdx`.
- **`jobs.company` is nullable**: recruiter invites don't name the employer.
- **Private apply links** (recruiter invites carry the user's Naukri login token) are stored on the user's
  own `user_jobs.apply_url`, never in the shared catalog, and never opened by the server.
- **Public URLs never keep a query string** (alert links carry tracking and sign-in tokens).
- **`user_jobs`** is created in milestone 2 (the LLD lists it under matching) with `lead`
  (`alert`/`recommendation`/`recruiter_invite`), `outside_preference` and `version`.
- **Sender allow-list:** LinkedIn alert senders, `naukrialerts@naukri.com`, any `@naukri.com` sender with DKIM
  passing (recruiter invites), Gmail forwarding confirmations. Parsers pick by sender and headers, never by
  subject. Unrecognised mail is stored as `unparsed`, never guessed at.
- **Secret name:** `INBOUND_HMAC_SECRET` (the LLD says `INBOUND_SHARED_SECRET`).
- **Signature:** `X-Signature: sha256=HMAC(secret, "<X-Timestamp>.<body>")`. The LLD signs the body only,
  which would let a captured request be replayed later with a fresh timestamp.
- **Rejections** (unknown recipient, sender not allowed, duplicate, too large, unreadable) return 200 with
  `accepted: false` and are not stored, so the email worker doesn't retry them. Bad signatures get 401.
- **Paste/upload is deferred** to the "Widen" step. An uploaded email has no verified DKIM signature, so a
  user could plant a fake listing (e.g. "LinkedIn job 123") in the *shared* catalog that a later genuine
  alert would merge into. It needs a safeguard first: unverified cards stay private to the uploader, or a
  verified source may overwrite facts that only unverified sources supplied.
- **The parse task** links jobs to the user in the same transaction as the catalog upsert. Seeing a job again
  refreshes the card details and keeps the user's status (ignored stays ignored) and the strongest lead
  (recruiter invite > alert > recommendation).
- **RLS and the inbound endpoint:** `users` has no RLS (only the auth service reads it), so the endpoint
  looks up the recipient by `inbound_token` the way sign-in looks up an email, then does everything else
  inside `user_scope(user_id)`. No `SECURITY DEFINER` function is needed.
- **Queueing after commit:** the inbound endpoint commits the message first, then defers `parse_alert`. A
  periodic sweep re-queues messages left in `accepted` (e.g. if the defer failed), so none is lost.
- **Procrastinate** runs on psycopg 3 (binary build); the app keeps asyncpg. Its schema is a vendored copy,
  so upgrading Procrastinate means a new migration that applies its migration files.
- **Shared catalog writes by users:** a pasted full description (`POST /jobs/{id}/description`) is stored
  on the user's own row (`user_jobs.description`, migration 0003), so one user can't change what others see.
  The job detail shows it in place of the catalog's description, marked "pasted by you".
- **Job ids in the API** are the user's `user_jobs.id` (as in the LLD's example), never the catalog id.
  `PATCH` only bumps `version` when the status actually changes.
- **Upload .eml (local only):** `POST /inbox/upload` exists only when `ENV=local` (404 otherwise; `GET /mail`
  says `upload_enabled`). It runs the same checks as forwarding, with DKIM taken as passing for the From
  domain, and stores the message with `channel = 'paste'`. It is how to try real alerts before the
  Cloudflare worker exists; production keeps it off because of the catalog-poisoning risk above.
- **Sweep:** every 5 minutes, per user, messages still `accepted` after 2 minutes are checked against
  `procrastinate_jobs`: a queued/running parse is left alone, a failed one marks the message `failed`,
  none at all (the defer was lost) queues it again. A message whose raw email was purged before parsing
  is marked `failed` by the parse task, so the sweep never loops on it.
- **Purge** runs at 02:00 in the worker's time zone (UTC in Docker) and keeps the Inbox rows; only the raw
  email goes.

## Parsers (module 2)

`backend/app/modules/catalog/parsers/`: `base.py` (`JobCard`, `ParseResult`), `normalize.py`,
`linkedin.py`, `naukri.py`, `registry.py` (`parse_email(raw) → ParseResult | None`), `__main__.py`
(`make parse FILE=…`). Samples and their expected parses: `backend/tests/fixtures/emails/`.
New samples are dropped in `TestFiles/` (originals in the git-ignored `TestFiles/raw/`).

Waiting for samples (optional): Naukri saved-search alert, a hand-forwarded email, a Gmail
forwarding-confirmation email. Until then those arrive as `unparsed`.
