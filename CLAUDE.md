# Sunstream Lead Generation App (started as a copy of FitFirst/BrewMyJob, 2026-11-17)

> **Read `docs/SUNSTREAM-SPEC.md` first.** It holds the Sunstream requirements, the decisions made so far and the
> open questions. Where it disagrees with the FitFirst notes below, the spec wins: this is an internal presales
> app (team-shared data, criteria-only Match Profiles, US market, ZoomInfo company details), and the marketing page,
> plans and payments, Job sources, extension and autofill, resumes and packs are to be removed. The notes below are
> the inherited FitFirst notes and are being replaced as the strip-down proceeds.

# FitFirst — notes for Claude Code

FitFirst reads the job-alert emails a user forwards (LinkedIn, Naukri), scores every job against the
user's search profiles, recommends the best of their resumes with suggested edits, and prepares a
tailored resume and cover letter. **The user always submits the application themselves.**

The design documents are in `docs/`: `docs/BRD.md` (requirements) and `docs/LLD.md` (low-level design:
modules, API contracts, schema, jobs, deployment). Read `docs/README.md` first: it says what to do where
the documents and the code differ. This file is the short version for working in the code.

## Non-negotiables

- No automation on job portals (LinkedIn, Naukri, Indeed…): no scraping, no auto-apply, no auto-connect, not even
  click-to-fill. On a company's own application form (Greenhouse, Lever, Workday…), the browser extension fills
  fields only when the user clicks, in the user's browser, and never submits, signs up or signs in (user, 2026-11-09).
  LinkedIn, Naukri and Foundit jobs come only from email alerts, or from a Google or free job API (Adzuna, Jooble,
  Careerjet…) that returns them; then only the API's fields are used and the portal page is never fetched
  (user, 2026-11-13; `docs/jobsearch-plan-discovery.md`), or the user adds them by hand after a Google search
  in their own browser (Find on Google, `jobs/found.py`; only the job id is read from the link). Paid search
  APIs wait for revenue (backlog, user 2026-11-14).
- Never store portal or email passwords. Jobs arrive by email forwarding; OAuth only where a
  provider offers it (Phase 2).
- Every private table has `user_id`, row-level security (`FORCE`) and a policy on
  `current_setting('app.user_id')`. Shared tables (the job catalog) have no `user_id`.
- The API connects as `fitfirst_app` (no superuser, no BYPASSRLS). Migrations run as the owner.
- Generated text (packs, notes) must pass the claim check: nothing the user's resumes don't support.

## Layout

```
backend/                 FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic
  app/core/              config, db (RLS session), security (Argon2id, EdDSA JWT), errors, deps
  app/modules/<name>/    models.py, router.py, schemas.py, service.py (one folder per module)
  app/models.py          imports every model (Alembic metadata)
  migrations/versions/   hand-written SQL migrations, numbered 0001, 0002…
  tests/                 pytest against real Postgres (the *_test database)
apps/web/                Next.js App Router, client-side session (access token in memory)
apps/mobile/             Expo app (milestone 6)
apps/extension/          browser extension for company application forms (milestone 14; plain JS, load unpacked)
services/jobsearch/      Job Search Service: employer boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workday,
                         Oracle, Eightfold, companies' own careers sites),
                         job APIs, listings history and the event feed; own DB, no user data, no RLS
packages/api/            typed client generated from the OpenAPI schema (shared by web + mobile)
packages/ui-tokens/      colours and radii as CSS variables and a JS object
infra/                   caddy, postgres init, cloudflare email worker (M2), terraform (Phase 2)
```

## Commands

```
make up            # whole stack in Docker → http://localhost:8080 (demo: demo@example.com / FitFirst-demo-2026)
make dev           # day-to-day: Postgres in Docker + API (:8000) + worker + job search service (:8100 + worker) + web (:3000); Ctrl+C stops all
make stop          # stop API, web and the database container
make db / dev-api / dev-worker / dev-web   # the same pieces, one per terminal
make test          # backend tests in Docker      | make test-local  (on your machine)
make test-web      # vitest + tsc                 | make e2e         (Playwright, stack must be up)
make e2e-docker    # the e2e in Playwright's Docker image, against make up (no browser install needed)
make lint / fmt    # ruff + tsc
make migration m="add jobs"   # new migration file
make api-gen       # regenerate packages/api after changing any endpoint or schema
make parse FILE=backend/tests/fixtures/emails/x.eml   # show the jobs a parser finds in an alert email
make inbound FILE=x.eml [TO=address] [AGAIN=1]        # deliver a saved email to the running API (demo user)
make admin EMAIL=you@example.com [REVOKE=1]          # make an account super admin (sign in again after); admins and coupons by invite on Admin settings
make feedback [ALL=1]                                 # "Not for me" answers not reviewed yet, with each job's score now
make feedback-done IDS="id1 id2" NOTE="what changed"  # stamp them reviewed once the rules are tuned
```

**Tuning from feedback (user, 2026-11-11).** When the user asks to address their feedback: run `make feedback`
and show the list first (job, reason, note, score now; "still a match" marks the ones the rules got wrong), say
what change each needs, then make the changes (rules in `app/modules/matching`, a test per case from the job's
wording), re-score, and `make feedback-done` the ones handled.

Finding jobs ourselves is a separate Job Search Service (`services/jobsearch/`, including the Job sources), designed in `docs/jobsearch-plan-discovery.md` (user, 2026-11-13). Steps 0, 1 and 2 built 2026-11-14 (`docs/plan-jobsearch-build.md`; step 2 added Oracle, Eightfold and a generic careers-page reader that follows robots.txt and refuses job portals): the service has its own database, API (:8100, token) and worker (boards every 3 h, job APIs every 6 h) and holds no user data; the app pulls its event feed every 5 minutes (`app/modules/sources/sync.py`) and keeps who-gets-what (relevance), scoring and alerts. Job locations are asked at sign-up.
Milestone 2 is being built as planned in `docs/plan-m2.md` and milestone 3 in `docs/plan-m3.md` (module status and decisions).
Milestone 5 was built as planned in `docs/plan-m5.md` (user feedback of 2026-11-02, decisions, modules).
Milestone 6 is being built as planned in `docs/plan-m6.md` (WhatsApp first).
Milestone 7 was built in `docs/plan-m7.md` while the user was away (decisions to review are listed there).
Milestones 13 A and 14 were built in `docs/plan-m13.md` and `docs/plan-m14.md` while the user was away (2026-11-09; decisions to review there).
Sample alert emails: sanitised copies with expected parses in `backend/tests/fixtures/emails/`; parser
tests are marked `nodb` and run without Postgres. Never commit an unsanitised email.

## Conventions

- **API**: everything under `/api/v1`. Errors always use the envelope
  `{"error": {"code", "message", "details", "request_id"}}` — raise `AppError`/`NotFound`/`Conflict`.
- **Background jobs**: Procrastinate (`app/core/worker.py`), connected as the app role. A task that touches
  private tables takes `user_id` and works inside `async with user_scope(user_id) as db:`; add its module
  to `TASK_MODULES`.
- **Sessions**: routes for a signed-in user take `user: User, db: UserDB`. `UserDB` is a transaction
  that has already run `set_config('app.user_id', …)`. Don't filter by `user_id` by hand to "be safe";
  RLS does it, and the isolation tests prove it. Do set `user_id` on inserts.
- **Concurrency**: editable records carry `version`; clients send it back and get 409 on a stale write.
- **Migrations**: plain SQL in `op.execute`. For every new private table: enable + force RLS, add the
  `own_rows` policy (copy from 0001), and add a cross-user test in `tests/test_isolation.py`.
- **Tests**: every endpoint gets a happy-path test and an error-path test. Run `make test-local`
  before committing. The web e2e (`apps/web/e2e`) covers the main user journey; extend it per milestone.
- **Web**: pages are client components using `api` from `lib/api.ts`. Form state updates use the
  functional form `setForm(f => …)` (two updates can land in one tick). Errors: `errorMessage(e)` and
  `fieldErrors(e)` from `components/ui.tsx`. Look (user, 2026-11-13): the "command center" design: light grouped
  sidebar, indigo accent, Plus Jakarta Sans, ringed score circles, tokens in `packages/ui-tokens`, icons inline in
  `components/Icon.tsx` (no icon CDN). The previous look is backed up in `~/code/FitFirst-backups/ui-before-redesign-2026-11-13/`
  (`restore.sh` puts it back).
- **Roles and access** (user, 2026-11-17; `docs/plan-roles-and-plans.md`): `job_seeker` (everyone who signs up), `admin`
  (Job sources), `super_admin` (Admin settings, invites). Feature routers are included with `require_access` in
  `app/main.py`: a job seeker needs a plan or coupon period (402 otherwise). Job sources is one shared list
  (`platform_companies`) kept by admins; every user gets the jobs that fit and sees the rest in Jobs → From sources.
  Local test accounts (`FREE_ACCESS_EMAILS`, e2e-…@example.com and the demo) need no plan. Find on Google has one
  set of roles (`candidate_profiles.alert_roles`) for its searches and Google Alerts.
- **Skill Match profiles** (user, 2026-11-13): one search profile per resume (`search_profiles.resume_id`, deleted
  with the resume), made from it by `profiles/service.ensure_match_profiles`. `resume_skills` are read from the
  resume and refreshed when it changes (Replace file); `skills` are the ones the user added (kept, and flagged
  when the resume doesn't show them). A resume is scored only with its own profile; a profile with no resume (API
  only, legacy) judges every resume. The Profile page has three tabs: Profile, Skill Match Profile, Application
  Autofill Information; `/search-profiles` redirects there. No shared skills list: each resume stands alone.
- **Style**: ruff (line length 110) for Python; TypeScript strict. Keep modules small and boring.
- **AI calls** (from M3): only through the LLM gateway (`app/modules/llm`), with a versioned prompt in
  `backend/prompts/`, Pydantic-validated output, a rule-based fallback, and a row in `llm_calls`.
  Models: `claude-haiku-5-5` for extraction and scoring, `claude-sonnet-5-5` for resume ranking and packs.

## Milestones

| # | Scope | Status |
|---|-------|--------|
| 1 | Foundation: repo, Docker, CI, auth (signup/login/refresh/logout), candidate profile, search profiles, notification settings, RLS, web shell | **done** |
| 2 | Ingestion: forwarding address → Cloudflare Email Worker → `/internal/inbound` (HMAC), LinkedIn + Naukri alert parsers, shared job catalog with fingerprint dedupe, Procrastinate worker, Jobs list | in progress (Cloudflare worker built for brewmyjob.com 2026-11-03; one-time Cloudflare setup and a real Gmail test left — `infra/cloudflare/email-worker/README.md`) |
| 3 | Resumes and matching: resume + cover-letter library (PDF/DOCX/ODT/RTF/TXT), text extraction, profile from resume, LLM gateway, hard filters, factor scoring, Voyage similarity, match % per resume, Top matches / Other jobs tabs, suggested resume + cover letter | in progress (all built with rules + Voyage; Claude scoring and resume edit suggestions wait for the API key) — see `docs/plan-m3.md` |
| 4 | Job detail and packs: readiness (ready / needs input / manual only), blockers, answer bank, resume edit suggestions, tailored resume + cover letter as Word and PDF, claim check. Also sign-up: re-enter password, show password (Google and Microsoft sign-in deferred until there is a domain) | in progress (sign-up, readiness and answer bank done; resume edits and packs wait for the Anthropic key) — see `docs/plan-m4.md` |
| 5 | Applications tracker: statuses and events, follow-up dates, date/month/year filters. Also (feedback 2026-11-02): Applied and Expired queues, expiry days set by the super admin, contacts on a job, amber to-dos, missing skills and points lost | **done** (2026-11-02) — see `docs/plan-m5.md` |
| 6 | Notifications (web first): WhatsApp (Meta Cloud API) for new strong matches (user, 2026-11-05), in-app bell, email digest, quiet hours, caps. Teams later. **6b** (after the web is stable): Expo app (iOS/Android) and push | in progress (started 2026-11-05) — WhatsApp alerts built; in-app bell built 2026-11-09; sending waits for the one-time Meta setup (test number, templates, token) — see `docs/plan-m6.md` |
| 7 | Networking: LinkedIn connections CSV import, daily warm/target suggestions, notes, outreach tracker | **done** (2026-11-02), waiting for the user's review — see `docs/plan-m7.md` |
| 8 | Release: Lightsail deploy, backups, monitoring, rate limits, data export/delete, security pass | |
| 9 | More sources and duplicates (India first): ATS company feeds (Greenhouse, Lever, Ashby, SmartRecruiters), Adzuna India, more alert-email parsers (iimjobs, hirist, Indeed, Foundit…); clear duplicates merged (incl. into applied jobs), potential duplicates flagged with Same job / Different job | in progress (started 2026-11-03) — company feeds built (moved to the Job Search Service 2026-11-14, with Workday added; Job sources page); Adzuna built, waits for the key; duplicates built 2026-11-07; new alert-email parsers wait for samples; AI assistant (ChatGPT) job lists read 2026-11-08 — see `docs/plan-m9.md` |
| 10 | Marketing home page: public landing site from a commercially licensed template, SEO, social previews, analytics, cookie consent; truthful content only | **built** (2026-11-03; the four plans on the pricing section 2026-11-17) from the user's "Home page — light" design: `/` (`app/page.tsx`, `app/_home/`), waitlist (`POST /waitlist`, list on Admin settings), social preview image, robots + sitemap. Privacy, terms and contact pages built 2026-11-09 (drafts for review). Left: analytics and cookie consent (provider not chosen), a contact mailbox |
| 11 | Subscriptions (India first): Razorpay hosted checkout from the home page pricing, plans and limits, billing page, webhooks | in progress (2026-11-17): roles (job seeker / admin / super admin), invites with 1- or 3-month coupons, plans ₹199 / 500 / 750 / 1,200 and the paywall, one shared list of job sources kept by admins — see `docs/plan-roles-and-plans.md`; Razorpay checkout in the backlog |
| 12 | US market (later): US portals and APIs, USD salary, states and remote-US, work authorization / sponsorship filter, region per search profile; Paddle or Lemon Squeezy for US billing | later |
| 13 | Ask BrewMyJob (user, 2026-11-03): an in-app assistant that answers questions from the user's own data ("why is this a top match?"), "Not for me" feedback with reasons, per-user learning, an admin review queue that turns grouped feedback into reviewed rule fixes and tests, an evaluation set for prompts; changes only with the user's confirmation, read-only tools under RLS | part A **built** 2026-11-09 (Not for me with reasons, learned preferences on Profile) — see `docs/plan-m13.md`; B–E wait for the Anthropic key |
| 14 | Fill application forms (user, 2026-11-04): Apply kit with copy buttons on the job page; later a browser extension that fills company application forms (Greenhouse, Lever, Ashby, SmartRecruiters, then Workday…) on the user's click, never submits, hard-blocked on LinkedIn/Naukri/portals | 14.0–14.5 **built** 2026-11-09 (apply profile, Apply kit, extension in `apps/extension` with pairing; Workday tested on hand-made pages only) — see `docs/plan-m14.md`. Plan 14.0–14.8 with Workday detail and dependencies added 2026-11-09: 14.1 (structured apply profile) and 14.2 (Apply kit) need nothing; the non-negotiable change was approved 2026-11-09; see `docs/milestones.md` |

Working order agreed 2026-11-02: 9 → 6 → 10 → 11; then 8 and 12. Details of 9–12 in `docs/milestones.md`.
Home page improvements (rest of M10) and 6b (mobile) come later, once the web app is stable (user, 2026-11-03).

**Product name (user, 2026-11-03): BrewMyJob.** "FitFirst" is the old name; user-facing text should say BrewMyJob.

When finishing a milestone: update this table, `docs/milestones.md`, and the e2e test.
