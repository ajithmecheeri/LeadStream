# Design documents

| File | What it is |
|---|---|
| [BRD.md](BRD.md) / [BRD.pdf](BRD.pdf) | Business requirements and technical design: scope, users, features, screens, Phase 1 and Phase 2 |
| [LLD.md](LLD.md) / [LLD.pdf](LLD.pdf) | Low-level design: modules, API contracts, database schema, background jobs, deployment and cost |
| [milestones.md](milestones.md) | What each finished milestone delivered |
| `plan-m*.md`, [plan-jobsearch-build.md](plan-jobsearch-build.md), [plan-roles-and-plans.md](plan-roles-and-plans.md) | Each milestone's build plan: decisions, what was built, what is left for review |
| [jobsearch-plan-discovery.md](jobsearch-plan-discovery.md) | The Job Search Service: how jobs are found beyond alert emails |
| [FitFirst-Conversation-Log.docx](FitFirst-Conversation-Log.docx) | The design and build conversation (8–29 Oct 2026): requests, decisions and answers |

The Markdown files are for reading in the editor and by Claude Code. The PDFs carry the diagrams and
screenshots too. The editable originals are Claude Docs: the
[BRD](https://claude.ai/artifact/VAdx2EPmd5E6Bhy53UvkrE) and the
[LLD](https://claude.ai/artifact/SNapWgURadqbuDChXtzyBC). On 2026-11-17 the originals got the roles, plans,
shared job sources and Find on Google changes and the current milestone status, and the PDFs were exported from
them again. The originals and the Markdown copies were edited separately in places since 2026-11-04, so their
wording can differ; the facts in the newest sections match.

## When the documents and the code disagree

The documents were written before the code. Where they differ, follow this order:

1. **The code and `CLAUDE.md`** (rules, conventions, milestone plan) — these are current.
2. **LLD.md** — the detailed design: tables, endpoints, jobs, prompts.
3. **BRD.md** — the requirements and the reasons behind them.

Known differences:

- **Name:** the documents say "AI Job Assistant" / "AI Job Search & Application Assistant", and the code "FitFirst".
  The product is **BrewMyJob** (user, 2026-11-03).
- **Roles, plans and job sources (2026-11-17, [plan-roles-and-plans.md](plan-roles-and-plans.md)):** users are job
  seekers, admins or the super admin (the documents have one kind of user and a super admin). Job seekers need a
  plan or an invite's coupon (₹199 / 500 / 750 / 1,200 for 1, 3, 6, 12 months); payment isn't built yet. Job
  sources is one shared list of companies kept by admins (the LLD's per-user company feeds), and every user sees
  its jobs in Jobs → From sources.
- **Milestone order:** use the table in `CLAUDE.md`. It merges the LLD's milestones 3 (matching) and 4
  (resume library) into milestone 3, then packs (4), tracker (5), notifications and mobile (6),
  networking (7), release (8).
- **Local stack:** the LLD lists MinIO, Mailpit and a worker container in Docker Compose. They're added
  in the milestone that first needs them (worker in 2, MinIO in 3, Mailpit in 6). Day-to-day development
  runs only Postgres in Docker (`make dev`).
- **Schema:** the LLD's DDL is the target. Migrations add tables milestone by milestone; vector columns
  and the HNSW index arrive in milestone 3. Private tables also get `FORCE ROW LEVEL SECURITY`.
- **Python tooling:** the repo uses `pip` and a `.venv` (via `make setup`), not `uv`.
- **Ingestion schema (migration 0002)** differs from the LLD's DDL, for reasons recorded in
  [plan-m2.md](plan-m2.md):
  - `job_sources` has its own `id`, a nullable `url` and a unique `(source, source_job_id)`. Naukri recruiter
    invites have no public page.
  - `jobs.company` and `jobs.fingerprint` are nullable. Recruiter invites don't name the employer.
  - `jobs` adds `work_model`, `skills` and `details`; `structure` and `embedding` arrive in milestone 3.
  - `user_jobs` is created in milestone 2, not with matching. It adds `lead`, `outside_preference`,
    `apply_url` (private apply links), `card_details` and `version`.
  - `inbound_messages` adds `channel`, `alert_name`, `forwarding_code` and `processed_at`. The raw email is
    in the private `inbound_raw` table until MinIO arrives in milestone 3.
- **Inbound secret and signature:** `INBOUND_HMAC_SECRET` (the LLD says `INBOUND_SHARED_SECRET`), and the
  HMAC covers `<timestamp>.<body>`, not the body alone, so a captured request can't be replayed later.
- **`POST /inbox/paste`** isn't built yet: unverified emails need a safeguard before they may write to the
  shared catalog (see plan-m2.md). A local-only `POST /inbox/upload` (`ENV=local`) delivers a saved `.eml`
  for testing.
- **Jobs API (milestone 2):** `/jobs` filters by `status=active|new|seen|ignored|all` (the LLD's
  `open|applied` arrive with matching and the tracker), plus `source`, `lead`, `q`, `from`/`to`. A pasted
  description is stored on `user_jobs.description` (migration 0003), not in the shared catalog.
  `GET /jobs/stats` feeds the dashboard. The mail setup page is `/settings/mail` (as in the LLD).
- **Resumes and matching (milestone 3, migration 0004)**, reasons in [plan-m3.md](plan-m3.md):
  - Uploads are JSON with base64, not multipart; originals are kept in the private `stored_files` table, not
    object storage.
  - Embeddings are `real[]` compared in Python, not pgvector columns with an HNSW index.
  - One `job_matches` row per user job (with every resume's score in `ranking`) replaces `job_scores` +
    `resume_recommendations`; `GET /jobs?tab=top|other|unscored|all` replaces `band=`, and the job detail
    carries the match, so there is no separate `/jobs/{id}/resume-recommendation` yet.
  - `GET /matching/status` and `POST /matching/rescore` are new.
  - Until an Anthropic key is set, scoring is rules + Voyage similarity; `job_score` and `resume_rank` (with
    suggested edits) arrive with the key.
- **Readiness and the answer bank (milestone 4, migration 0005)**, reasons in [plan-m4.md](plan-m4.md): there are no
  `readiness`/`blockers` tables (readiness is computed on every read); blockers are resolved with
  `POST /jobs/{id}/blockers/{key}/resolve` (keys like `question:notice_period`, `gap:skills`), not
  `/blockers/{id}/resolve`; answers are saved with `PUT /answers/{key}` and custom questions added with
  `POST /answers`. Sign-up requires `password_confirm` and takes `first_name`, `middle_name`, `last_name` (not `name`).
