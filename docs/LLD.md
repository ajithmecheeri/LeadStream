# AI Job Assistant — Low-Level Design

Oct 15, 2026 · @Ajith Mecheri

## Summary and key decisions

The same codebase runs at two sizes:

- **Phase 1** serves 2–3 people on one small cloud server for about US$30–40 a month (roughly ₹2,700–3,500), including AI usage.
- **Phase 2** serves 500–1,000 people on managed AWS services in Mumbai for about US$900–1,250 a month (roughly ₹80,000–1,10,000). About US$500 is infrastructure and US$400–700 is AI usage, or roughly US$1–1.25 per user.

The code doesn't change between phases. Only the deployment, the identity provider and the mail-receiving adapter change.

This design implements the BRD (v2.1) and the Phase 1 feedback built into the HTML POC. Phase 2 adds subscriptions and payments, per-user account settings, a master admin, and more job portals.

| Decision | Choice | Why |
| --- | --- | --- |
| Database | PostgreSQL 16 (relational) with JSONB and pgvector | Data is highly relational (users, profiles, jobs, scores, applications). JSONB covers flexible fields, and pgvector covers similarity search. One engine for both phases. |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2 | Best fit for the AI and document work; typed contracts through OpenAPI |
| Background jobs | Postgres-backed task queue (Procrastinate) | No extra queue service in Phase 1; handles Phase 2 volume (a few tasks per second); retries and cron built in |
| Front end | Next.js (web), React Native with Expo (iOS and Android), shared TypeScript packages | One language across clients; native mobile with push |
| AI | Claude Haiku 5.5 for extraction and scoring; Claude Sonnet 5.5 for resume recommendation and documents; Voyage embeddings | Quality where it matters, low cost for high-volume steps |
| Inbound email | Phase 1: Cloudflare Email Routing with an Email Worker (free). Phase 2: Amazon SES receiving in Mumbai | Both feed the same internal inbound endpoint |
| Identity | Phase 1: built-in accounts (Argon2 password hashes, JWT) plus Google and Microsoft sign-in through OpenID Connect (milestone 4). Cognito is optional later, for MFA at scale | Minimal setup now; managed identity and MFA at scale |
| Hosting | Phase 1: one AWS Lightsail server in Mumbai running Docker Compose. Phase 2: ECS Fargate, RDS, ElastiCache, S3, CloudFront in ap-south-1 | Low cost now; managed, scalable and India-resident later |

**Changes from the BRD.** The BRD named Amazon SQS for queues and Cognito from day one. This design replaces SQS with a Postgres-backed queue, because the volume is low enough and it removes a component. It also drops the need for Cognito: Google and Microsoft sign-in run through the built-in auth in Phase 1 (decided 2026-11-01). Both changes sit behind interfaces, so switching later is a configuration change.

**As built: milestone 3 (recorded 2026-11-01).** The code differs from this design in the points below. The rest of this document is the target; these are deliberate simplifications for Phase 1, each with the trigger for moving to the target.

| Area | Design in this document | As built in milestone 3 | Move to the design when |
| --- | --- | --- | --- |
| File uploads | Multipart upload to `/resumes`; originals in object storage (MinIO, then S3) | JSON body with the file in base64; originals kept in a private `stored_files` table in Postgres (row-level security) | Object storage arrives (MinIO in Docker, S3 in Phase 2) |
| Embeddings | pgvector `vector(1024)` columns with an HNSW index | Voyage `voyage-4-lite` vectors (1,024 numbers) stored as `real[]` and compared in the application | Search across many rows needs an index; then move to pgvector |
| Scores and recommendations | `job_scores` per search profile plus `resume_recommendations` | One `job_matches` row per user job: the best search profile's verdict and band, every resume's score in `ranking`, the primary and best resume scores, and the suggested cover letter | Per-profile scores are shown separately in the UI |
| Jobs list API | `GET /jobs?status=…&band=…` | `GET /jobs?tab=top\|other\|unscored\|all` (top = Strong and Good, by score), plus `GET /matching/status` and `POST /matching/rescore` | – (kept) |
| Scoring rules | Weighted factors with an embedding pre-screen | Unknown facts never rule a job out. Factors with no evidence are left out and the remaining weights rescaled. A title in an unrelated job family is capped at 45. Similarity carries 35% of the score, mapping cosine 0.40 to 0 and 0.65 to 100 | – (kept; tune in the pilot) |
| AI spend control | Platform-wide monthly budget (`LLM_MONTHLY_BUDGET_USD`) | Plus a per-user daily cost cap (default US$1) across Claude and Voyage calls (`AI_DAILY_COST_CAP_USD`) | – (kept) |

## Technology stack

Every layer uses one main tool for both phases. Phase 2 swaps hosting and managed services but keeps the code.

| Layer | Phase 1 | Phase 2 | Notes |
| --- | --- | --- | --- |
| Web app | Next.js (App Router, TypeScript), served by `next start` in a container | Same, in ECS Fargate behind CloudFront | Public pages server-rendered; signed-in app uses client components and TanStack Query |
| Mobile app | React Native with Expo (iOS, Android), Expo Router, EAS Build | Same; EAS Update for over-the-air fixes | Push through Expo Push (FCM and APNs) |
| Shared client code | pnpm workspace with Turborepo: `@ja/api` (client generated from OpenAPI), `@ja/schemas` (zod), `@ja/ui-tokens` | Same | Web, mobile and admin use the same API client |
| API | FastAPI on Uvicorn (Python 3.12), Pydantic v2 | Same, 2+ tasks | OpenAPI 3.1 schema is the contract |
| Data access | SQLAlchemy 2.0 (async, asyncpg), Alembic migrations | Same | Row-level security on private tables |
| Background jobs | Procrastinate (Postgres-backed queue, cron, retries) in a worker container | Same, 3+ worker tasks | One queue per kind of work (see Background jobs) |
| Real-time updates | WebSocket from FastAPI, in-process fan-out | WebSocket with Redis pub/sub across API tasks | Server-Sent Events fallback |
| Database | PostgreSQL 16 with pgvector, in Docker on the server | Amazon RDS PostgreSQL 16, Multi-AZ, pgvector | Same schema and migrations |
| Cache and rate limits | Not needed (single API process) | Amazon ElastiCache (Redis) | Rate limits, quota counters, WebSocket fan-out |
| File storage | Local volume through an S3-compatible interface (MinIO), copied nightly to S3 | Amazon S3 with signed URLs, KMS encryption | Original resumes, generated Word and PDF files |
| Inbound email | Cloudflare Email Routing and an Email Worker that POSTs to the API | Amazon SES receiving (Mumbai) to S3 plus SNS to the API | Same internal endpoint and parser |
| Outbound email | Amazon SES (or Resend), a few emails a day | Amazon SES | Digests and alerts |
| AI | Anthropic API: Claude Haiku 5.5 and Claude Sonnet 5.5 | Same, plus prompt caching and the Batch API for nightly re-scoring | All calls go through one LLM gateway module |
| Embeddings | Voyage `voyage-4-lite` | Same | 200 million free tokens, then US$0.02 per million |
| Document parsing | pdfplumber (PDF), python-docx (Word), odfpy (ODT), striprtf (RTF) | Same | Text kept for matching; original file kept |
| Document rendering | docxtpl (Word), WeasyPrint (PDF) | Same | From one HTML/Word template per document type |
| Identity | Built-in: Argon2id passwords, JWT access token (15 min), refresh token (30 days); Google and Microsoft sign-in via OpenID Connect | Same built-in auth; Cognito only if MFA at scale is needed | Same `/auth` contract to the clients |
| Reverse proxy and TLS | Caddy (automatic HTTPS) | Application Load Balancer, AWS WAF, ACM certificates |  |
| Observability | Structured logs (JSON) plus Sentry free tier; UptimeRobot free monitor | CloudWatch, OpenTelemetry, Sentry | Per-user AI cost on the admin page |
| Infrastructure as code | Docker Compose file | Terraform (VPC, ECS, RDS, ElastiCache, S3, SES, CloudFront) |  |
| CI/CD | GitHub Actions: test, build images, deploy over SSH | GitHub Actions to Amazon ECR and ECS; EAS for mobile |  |
| Testing | pytest, Schemathesis (contract tests from OpenAPI), Playwright (web), Maestro (mobile) | Same, plus Locust load tests | Golden-sample tests for every alert parser |
| Payments (Phase 2) | Not used | Razorpay subscriptions with webhooks | GST invoices through Razorpay |

## Module design

The backend is one FastAPI codebase split into 16 modules. Each module owns its tables and exposes a service interface; no module reads another module's tables directly. Modules talk through service calls inside a request and through domain events (stored in an outbox table, then queued) for anything that runs in the background. This keeps Phase 1 as one deployable unit, but lets any module move to its own service later.

| # | Module | Responsibility | Owns tables | Emits events | Consumes events |
| --- | --- | --- | --- | --- | --- |
| M1 | Identity and accounts | Sign-up, login, tokens, consent, data export and deletion | users, sessions, consents, data\_requests | UserCreated, UserDeleted | – |
| M2 | Profiles | Candidate facts, search profiles, weights, thresholds | candidate\_profiles, search\_profiles | ProfileChanged | – |
| M3 | Resume and cover-letter library | One library per user: a primary resume and up to 3 variations, up to 5 cover letters with one default; upload, parse, version, set primary or default; fill the candidate profile from a resume | resumes, cover\_letters | ResumeAdded, ResumeChanged | – |
| M4 | Answer bank | Reusable screening answers | answers | AnswerSaved | – |
| M5 | Ingestion | Inbound mail adapter, optional mailbox OAuth (Phase 2), Greenhouse and Lever board polling | inbound\_messages, mailbox\_connections, ats\_boards | AlertReceived | – |
| M6 | Parsing and job catalog | Alert parsers, normalization, deduplication, JD and company-details split, structured extraction | jobs, job\_sources | JobLinked (per user), JobUpdated | AlertReceived |
| M7 | Matching | Hard filters, embedding pre-screen, per-profile scoring | user\_jobs, job\_scores | JobScored | JobLinked, JobUpdated, ProfileChanged, ResumeChanged |
| M8 | Resume recommender | Rank resumes per job with a % for each (plus the primary resume's %), pick the best cover letter, suggest changes, list gaps | resume\_recommendations | ResumeRecommended | JobScored (strong or good) |
| M9 | Readiness | Ready, Needs input or Manual only; blockers | readiness, blockers | ReadinessChanged | JobScored, AnswerSaved, ProfileChanged |
| M10 | Documents | Tailored resume, cover letter, answers pack, claim check, Word and PDF rendering | documents | PackGenerated | – (called on request) |
| M11 | Applications | Tracker, statuses, follow-up dates, date filters | applications, application\_events | ApplicationChanged | PackGenerated |
| M12 | Networking | Connections import, warm paths, daily suggestions, outreach tracker | connections, connection\_imports, outreach, outreach\_events, daily\_suggestions | SuggestionsReady | JobScored, ApplicationChanged |
| M13 | Notifications | Rules, quiet hours, caps, digests; push, email, in-app, WebSocket | notifications, devices, notification\_settings | – | ReadinessChanged, JobScored, SuggestionsReady, ApplicationChanged |
| M14 | Admin and usage | Parser health, usage and AI cost per user, quotas, support view | usage\_counters, llm\_calls, audit\_events | QuotaExceeded | all (for metering) |
| M15 | Billing (Phase 2) | Plans, Razorpay subscriptions, invoices, webhooks | plans, subscriptions, payments | PlanChanged | – |
| M16 | LLM gateway | One place for every AI call: model routing, prompt registry, caching, retries, cost metering, JSON validation. Providers sit behind an LLMProvider interface (Anthropic now, an OpenAI-compatible self-hosted server later), routed per prompt by the LLM\_ROUTES setting | prompt\_versions (llm\_calls via M14) | – | – |

**Pipeline order.** An alert email flows M5 → M6 → M7. Strong and good matches then flow on to M8 and M9, and from there to M13. M12 and M10 run on a schedule or on request. The section on background jobs has the queue for each step.

**Service contracts.** These are the Python interfaces each module exposes inside the backend. HTTP endpoints call these; nothing calls a module's repository directly.

```python
# M3 Resume and cover-letter library
class LibraryService(Protocol):
    async def add_resume(self, user_id: UUID, file: UploadFile, label: str, focus: list[str]) -> Resume: ...  # parse; primary + up to 3 variations
    async def set_primary(self, resume_id: UUID) -> Resume: ...
    async def add_cover_letter(self, user_id: UUID, label: str, text: str | None, file: UploadFile | None) -> CoverLetter: ...  # up to 5
    async def set_default_cover_letter(self, cover_letter_id: UUID) -> CoverLetter: ...
    async def candidate_from_resume(self, resume_id: UUID) -> CandidateDraft: ...   # LLM resume_extract; shown for review, not saved

# M5 Ingestion
class IngestionService(Protocol):
    async def accept_inbound(self, raw: InboundEmail) -> InboundResult: ...      # verifies DKIM/allow-list, stores, emits AlertReceived
    async def follow_board(self, user_id: UUID, provider: Literal["greenhouse","lever"], board: str) -> AtsBoard: ...

# M6 Parsing and catalog
class CatalogService(Protocol):
    def parse_alert(self, msg: InboundMessage) -> list[JobCard]: ...             # LinkedIn, Naukri, Greenhouse, Lever, generic
    async def upsert(self, card: JobCard) -> tuple[Job, bool]: ...               # (job, merged_with_existing)
    async def set_description(self, job_id: UUID, text: str, about: str | None) -> Job: ...  # splits role / about / offer
    async def extract(self, job_id: UUID) -> JobStructure: ...                   # LLM: must-haves, themes, seniority, years, CTC

# M7 Matching
class MatchingService(Protocol):
    def hard_filter(self, job: Job, sp: SearchProfile) -> FilterResult: ...       # no AI cost
    async def score(self, user_job: UserJob, sp: SearchProfile) -> JobScore: ...  # factors, gaps, rationale, band
    async def rescore_user(self, user_id: UUID, reason: str) -> int: ...

# M8 Resume recommender
class ResumeRecommender(Protocol):
    async def recommend(self, user_job_id: UUID, sp_id: UUID, chosen_resume_id: UUID | None = None) -> Recommendation: ...  # % per resume, primary %, best cover letter

# M9 Readiness
class ReadinessService(Protocol):
    async def evaluate(self, user_job_id: UUID) -> Readiness: ...                # status + blockers, reuses resolved answers
    async def resolve(self, blocker_id: UUID, answer: str, save_to_bank: bool) -> Readiness: ...

# M10 Documents
class DocumentService(Protocol):
    async def build_pack(self, user_job_id: UUID, base_resume_id: UUID, accepted: list[str], save_version: bool) -> Pack: ...
    async def render(self, document_id: UUID, fmt: Literal["docx","pdf"]) -> SignedUrl: ...
    def claim_check(self, text: str, sources: list[str]) -> ClaimCheck: ...

# M12 Networking
class NetworkingService(Protocol):
    async def import_connections(self, user_id: UUID, file: UploadFile, keep_email: bool) -> ImportResult: ...
    async def daily(self, user_id: UUID, day: date, regenerate: bool = False) -> list[Suggestion]: ...
    async def mark(self, suggestion_id: UUID, action: Literal["sent","skipped"], person: PersonRef | None) -> Outreach | None: ...

# M13 Notifications
class Notifier(Protocol):
    async def notify(self, user_id: UUID, event: NotificationEvent) -> Notification: ...  # applies rules, quiet hours, caps

# M16 LLM gateway
class LLMGateway(Protocol):
    async def run(self, prompt: str, version: str, inputs: dict, schema: type[BaseModel], user_id: UUID | None) -> BaseModel: ...  # picks provider + model from LLM_ROUTES

class LLMProvider(Protocol):                     # AnthropicProvider now; OpenAICompatibleProvider (self-hosted) later
    name: str
    async def complete(self, model: str, system: str, messages: list[dict], json_schema: dict | None,
                       max_tokens: int, cache_prefix: bool) -> ProviderResult: ...   # text, tokens in/cached/out, latency
```

**AI calls (M16 prompt registry).** Every prompt is versioned, and every result is checked against a Pydantic schema. A call that fails validation is retried once, then falls back to the rule-based logic proven in the POC.

| Prompt | Model | Input | Output schema | Approx. tokens in / out |
| --- | --- | --- | --- | --- |
| `jd_extract` | Haiku 5.5 | Job description | must\_haves, nice\_to\_haves, themes with weights, seniority, years, CTC, questions | 3,000 / 800 |
| resume\_extract | Haiku 5.5 | Resume text | candidate facts: headline, summary, years, skills, domains, location, notice, CTC (draft for review) | 2,500 / 600 |
| `job_score` | Haiku 5.5 | Job structure plus candidate facts | 9 factor scores, gaps, strengths, rationale | 3,500 / 500 |
| `resume_rank` | Sonnet 5.5 (resume texts prompt-cached) | Job structure plus resume and cover-letter libraries | ranking, coverage, suggestions with sources, gaps | 5,000 / 1,200 |
| `pack_write` | Sonnet 5.5 | Base resume, accepted changes, job, company details | tailored resume blocks, cover letter | 6,000 / 2,500 |
| `answer_draft` | Haiku 5.5 | Question, profile, answer bank | draft answer | 1,500 / 200 |
| `alert_fallback` | Haiku 5.5 | Alert email text when no parser matches | job cards | 2,500 / 600 |

Networking notes use templates, not AI. They are short, and templates keep them predictable and free.

**Front-end modules.**

| Client | Screens or routes | Talks to |
| --- | --- | --- |
| Web (Next.js) | `/` (public), `/signup`, `/login`, `/onboarding`, `/dashboard`, `/jobs`, `/jobs/[id]`, `/applications`, `/networking`, `/inbox`, `/settings/mail`, `/profile`, `/resumes`, `/answers`, `/notifications`, `/settings`, `/admin` (Phase 2) | REST through `@ja/api`; WebSocket `/ws` |
| Mobile (Expo) | Login, Feed (strong matches), Job card, Answer blockers, Networking today, Tracker, Notifications, Settings | REST through `@ja/api`; push through Expo |
| Browser extension (Phase 2) | Capture full job description, autofill from pack, confirm submission | REST through `@ja/api` |

## API specification and contracts

All client traffic goes through one versioned REST API at `/api/v1`, plus one WebSocket for live updates. FastAPI generates the OpenAPI 3.1 schema, and the TypeScript client for web, mobile and extension is generated from it. A breaking change therefore fails the client build before it ships.

**Conventions**

| Topic | Rule |
| --- | --- |
| Auth | `Authorization: Bearer <access JWT>` (15 min). Web keeps the refresh token in an HttpOnly, Secure, SameSite=Lax cookie; mobile keeps it in SecureStore. `POST /auth/refresh` rotates it. |
| Format | JSON, UTF-8, `snake_case` fields, ISO 8601 timestamps in UTC, IDs are UUIDv7 |
| Errors | `{"error": {"code": "blocker_not_found", "message": "…", "details": {}, "request_id": "…"}}`, with HTTP 400 / 401 / 403 / 404 / 409 / 422 / 429 / 500 |
| Pagination | Cursor based: `?limit=50&cursor=…` returns `{"items": [], "next_cursor": "…"}` |
| Filters | Lists accept `from`, `to` (dates), `month=YYYY-MM`, `year=YYYY` and module-specific filters |
| Idempotency | `Idempotency-Key` header on POSTs that create things (packs, imports, outreach); repeats return the first result |
| Rate limits | Per user: 120 requests a minute, 20 AI-backed requests a minute. Headers `X-RateLimit-Remaining` and `Retry-After` |
| Isolation | Every request sets the user id on the database session; row-level security enforces it even if a query forgets |

**Endpoints**

| Module | Method and path | Purpose | Phase |
| --- | --- | --- | --- |
| M1 | `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` | Account and session. Sign-up takes the password twice (must match). Google and Microsoft: GET /auth/oidc/{provider}/start, GET /auth/oidc/{provider}/callback; returns the same tokens as /auth/login. A verified email matching an existing account links to it | 1 |
| M1 | `GET /me`, `PATCH /me`, `POST /me/consent`, `POST /me/export`, `DELETE /me` | Account, consent, export, deletion | 1 |
| M2 | `GET/PUT /candidate`, POST /candidate/from-resume | Candidate facts | 1 |
| M2 | `GET/POST /profiles`, `GET/PATCH/DELETE /profiles/{id}` | Search profiles, weights, thresholds | 1 |
| M3 | `GET/POST /resumes`, `PATCH/DELETE /resumes/{id}`, POST /resumes/{id}/primary, `GET /resumes/{id}/file` | Resume library (JSON upload with the file in base64: pdf, docx, odt, rtf, md, txt; see As built: milestone 3) | 1 |
| M3 | GET/POST /cover-letters, PATCH/DELETE /cover-letters/{id}, POST /cover-letters/{id}/default | Cover-letter library: up to 5, one default; upload or write in the app | 1 |
| M4 | `GET/POST /answers`, `PATCH/DELETE /answers/{key}` | Answer bank | 1 |
| M5 | `GET /mail`, `POST /mail/address/rotate`, `GET /mail/forwarding-code` | Forwarding address and confirmation code | 1 |
| M5 | `POST /mail/oauth/{provider}/start`, `DELETE /mail/oauth/{provider}` | Gmail or Outlook connection | 2 |
| M5 | `GET/POST /boards`, `DELETE /boards/{id}` | Greenhouse and Lever boards | 1 |
| M5 | `GET /inbox/messages`, `POST /inbox/paste` | Received alerts; paste an alert or job | 1 |
| M6/M7 | `GET /jobs?tab=top\|other\|unscored&status=open\|applied\|ignored&band=&profile=&q=&from=&to=` | Job list by tab (top = Strong and Good, highest first; other = Low and filtered, with reason; unscored) and filters; each scored job returns the primary resume's % and the best resume's % | 1 |
| M6/M7 | `GET /jobs/{id}`, `PATCH /jobs/{id}` (ignore, restore), `POST /jobs/{id}/description` | Detail, status, paste full description and company details | 1 |
| M8 | `GET /jobs/{id}/resume-recommendation?profile=&resume=` | Ranked resumes, suggestions, gaps | 1 |
| M9 | `GET /jobs/{id}/readiness`, `POST /blockers/{id}/resolve` | Blockers and answers | 1 |
| M10 | `POST /jobs/{id}/pack`, `GET /documents/{id}`, `GET /documents/{id}/download?format=docx\|pdf` | Generate pack; signed download URL | 1 |
| M11 | `GET /applications?status=&from=&to=&month=&year=`, `POST /applications`, `PATCH /applications/{id}` | Tracker | 1 |
| M12 | `POST /network/imports` (multipart CSV or ZIP), `DELETE /network/connections` | Connections import and deletion | 1 |
| M12 | `GET /network/daily?date=`, `POST /network/suggestions/{id}/mark`, `GET /network/warm-paths` | Daily suggestions, warm paths | 1 |
| M12 | `GET/POST /network/outreach`, `PATCH /network/outreach/{id}` | Outreach tracker | 1 |
| M13 | `GET /notifications`, `POST /notifications/read`, `GET/PUT /notifications/settings`, `POST /devices` | Notifications, settings, push token | 1 |
| M14 | `GET /admin/health`, `GET /admin/users`, `GET /admin/usage` | Parser health, users, AI cost | 1 (minimal), 2 (full) |
| M15 | `GET /plans`, `POST /billing/subscribe`, `GET /billing/invoices`, `POST /billing/webhook` | Subscriptions and payments | 2 |
| internal | `POST /internal/inbound` | Inbound email from Cloudflare Worker or SES | 1 |
| WS | `GET /ws?token=…` | Live events for the signed-in user | 1 |

**Example: job detail** `GET /api/v1/jobs/{id}`

```json
{
  "id": "0192f1c4-…", "status": "open",
  "job": { "title": "VP Engineering, Payments Platform", "company": "Northwind Fintech",
           "location": "Bengaluru (Hybrid)", "work_model": "hybrid", "experience": "18-25 Yrs",
           "salary": "₹1.1-1.4 Cr", "description": "…", "about_company": "…", "offer": "…",
           "description_complete": true,
           "sources": [{ "source": "linkedin", "url": "https://www.linkedin.com/jobs/view/4011001001/" },
                       { "source": "naukri",   "url": "https://www.naukri.com/job-listings-…" }] },
  "first_seen_at": "2026-10-14T03:12:09Z",
  "scores": [{ "profile_id": "…", "profile_name": "VP Engineering", "overall": 91, "band": "strong",
               "provisional": false,
               "factors": { "role": 90, "exp": 100, "core": 100, "cloud": 100, "ai": 100, "domain": 50, "loc": 100, "skills": 90, "comp": 70 },
               "must_have_gaps": [], "gaps": ["upi", "cards"], "strengths": ["aws", "microservices", "pci dss"],
               "rationale": "Strongest on experience and leadership…" }],
  "readiness": { "status": "needs_input",
                  "blockers": [{ "id": "…", "type": "question", "key": "expected_ctc",
                                  "question": "What is your expected annual CTC (INR)?",
                                  "draft": "Open to discussion, in line with the role's band…", "resolved": false }] },
  "application": null
}
```

**Example: resolve a blocker** `POST /api/v1/blockers/{id}/resolve`

```json
// request
{ "answer": "60 days", "save_to_answer_bank": true }
// response 200
{ "readiness": { "status": "ready", "blockers": [ … ] }, "also_cleared_jobs": ["0192f1c9-…"] }
```

**Example: generate an application pack** `POST /api/v1/jobs/{id}/pack`

```json
// request
{ "profile_id": "…", "base_resume_id": "…", "accepted_suggestions": ["mv1", "bi2", "kw_saas"], "save_as_version": false }
// response 201
{ "document_id": "…", "claim_check": { "ok": 13, "total": 13, "unverified": [] },
  "resume": { "blocks": [ { "type": "name", "text": "…" }, { "type": "bullet", "text": "…", "source": "resume:r2#b3" } ] },
  "cover_letter": { "text": "…" },
  "answers": [{ "question": "What is your notice period?", "answer": "60 days", "source": "answer_bank" }],
  "downloads": { "docx": "/api/v1/documents/…/download?format=docx", "pdf": "/api/v1/documents/…/download?format=pdf" } }
```

**Example: today's networking** `GET /api/v1/network/daily?date=2026-10-15`

```json
{ "date": "2026-10-15", "cap": 5, "weekly_sent": 12, "weekly_limit": 100,
  "items": [
    { "id": "…", "kind": "warm", "person": { "name": "Priya Raghavan", "title": "Director, Platform Engineering", "profile_url": "https://www.linkedin.com/in/…" },
      "company": "Helix Cloud Systems", "job_id": "…", "job_score": 99,
      "why": "1st-degree connection at Helix Cloud Systems, which has a 99 match", "note": "Hi Priya, …", "status": "open" },
    { "id": "…", "kind": "target", "role": "CTO", "company": "Northwind Fintech",
      "search_url": "https://www.linkedin.com/search/results/people/?keywords=CTO%20Northwind%20Fintech",
      "note": "Hi, I lead engineering and AI teams…", "status": "open" } ] }
```

**Inbound email contract** `POST /internal/inbound`. Called only by the Cloudflare Email Worker (Phase 1) or the SES-to-SNS handler (Phase 2). It is not reachable from the public API route.

```json
// headers: X-Signature: sha256=<HMAC of body with INBOUND_SHARED_SECRET>, X-Timestamp: <unix seconds, within 5 min>
{ "recipient": "alerts-7f3k9q@in.yourdomain.com", "envelope_from": "jobalerts-noreply@linkedin.com",
  "message_id": "<…@linkedin.com>", "received_at": "2026-10-15T02:31:00Z",
  "dkim": [{ "domain": "linkedin.com", "result": "pass" }], "raw_mime_base64": "…" }
// 202 { "accepted": true, "inbound_message_id": "…" } | 200 { "accepted": false, "reason": "unknown_recipient" | "sender_not_allowed" | "duplicate" }
```

The API accepts a message only for a known, active recipient address. The sender must be on the allow-list (LinkedIn, Naukri, Greenhouse, Lever) with a passing DKIM result, or the message must be a Gmail or Outlook forwarding-confirmation email. Deduplication is by `(user, message_id)`.

**WebSocket events** `wss://app.yourdomain.com/ws`. Server to client only; every event uses one envelope.

```json
{ "type": "job.scored" | "readiness.changed" | "pack.ready" | "notification.created" | "network.suggestions",
  "at": "2026-10-15T02:31:05Z", "data": { … } }
```

**Push payload (Expo).** `{ "title": "Needs your input · 91", "body": "VP Engineering at Northwind Fintech: expected CTC, notice period", "data": { "type": "needs", "job_id": "…" } }`. Tapping it opens the job card in the app.

**Payment webhook (Phase 2).** Razorpay `subscription.activated`, `subscription.charged`, `subscription.halted` and `payment.failed` post to `POST /billing/webhook`. The API verifies the `X-Razorpay-Signature` HMAC and stores each event once by event id.

## Data design

**Use a relational database: PostgreSQL 16, not NoSQL.** The core questions the app answers are joins: this user's jobs scored against each search profile, with readiness, resume recommendations and application status. Those are naturally relational and need transactions, for example resolving a blocker and updating readiness and the tracker together. The flexible parts (factor scores, blockers, suggestions, extracted job structure) fit in JSONB columns in the same database. Job and profile embeddings fit in pgvector. A document store would add a second database to run and back up, with no gain at 1,000 users.

| Data | Store | Why |
| --- | --- | --- |
| Users, profiles, jobs, scores, applications, outreach | PostgreSQL tables | Relations, constraints, transactions, row-level security |
| Flexible structures (factors, blockers, suggestions, job structure) | PostgreSQL JSONB | Schema-light; still indexable with GIN |
| Embeddings (jobs, search profiles, resumes) | pgvector (1,024 dimensions, HNSW index) | Similarity search without a separate vector database |
| Background tasks and schedules | PostgreSQL (Procrastinate tables) | No separate queue service |
| Resume files, generated Word and PDF, raw alert emails | Object storage (MinIO in Phase 1, S3 in Phase 2) | Large binaries stay out of the database |
| Rate limits, WebSocket fan-out (Phase 2) | Redis | Short-lived counters and pub/sub only; nothing that must survive a restart |

**Multi-tenancy.** Every private table has `user_id`. Row-level security policies compare it with `current_setting('app.user_id')`, which the API sets at the start of each transaction. Only `jobs` and `job_sources` are shared: they hold public posting data, extracted once and reused by every user who receives the same posting.

**Schema (DDL).** Columns that are obvious from the BRD are trimmed. Types and keys are complete. Every table also has `created_at` and `updated_at timestamptz default now()`, omitted below.

```sql
create extension if not exists vector;
create extension if not exists citext;

-- M1 Identity
create table users (
  id uuid primary key, email citext unique not null, name text not null,
  password_hash text,                      -- null for accounts created through Google or Microsoft sign-in
  cognito_sub text unique, role text not null default 'user' check (role in ('user','admin')),
  inbound_token text unique not null,      -- the random part of alerts-<token>@in.<domain>
  timezone text not null default 'Asia/Kolkata', status text not null default 'active',
  plan_id text                             -- Phase 2: foreign key to plans added by that migration
);
create table consents (id uuid primary key, user_id uuid not null references users on delete cascade,
  notice_version text not null, purposes text[] not null, granted_at timestamptz not null, withdrawn_at timestamptz);
create table data_requests (id uuid primary key, user_id uuid not null references users on delete cascade,
  kind text check (kind in ('export','delete')), status text not null, completed_at timestamptz, file_key text);

create table user_identities (id uuid primary key, user_id uuid not null references users on delete cascade,
  provider text not null check (provider in ('google','microsoft')), subject text not null,   -- the provider's user id
  email citext not null, created_at timestamptz not null default now(), unique (provider, subject));

-- M2 Profiles
create table candidate_profiles (user_id uuid primary key references users on delete cascade,
  summary text, years_experience int, skills text[] not null default '{}', domains text[] not null default '{}',
  notice_days int, expected_ctc text, current_ctc text, work_authorization text, version int not null default 1);
create table search_profiles (id uuid primary key, user_id uuid not null references users on delete cascade,
  name text not null, target_roles text[] not null, locations text[] not null, work_models text[] not null,
  min_seniority smallint not null, excluded_companies text[] not null default '{}',
  weights jsonb not null, threshold smallint not null default 85, active boolean not null default true,
  default_resume_id uuid, embedding vector(1024), version int not null default 1);

-- M3 Resume and cover-letter library (one per user)
create table resumes (id uuid primary key, user_id uuid not null references users on delete cascade,
  search_profile_id uuid references search_profiles on delete set null,   -- optional: profile a variation targets
  label text not null, focus_tags text[] not null default '{}', text text not null,
  file_key text, file_name text, file_kind text,        -- original upload in object storage
  source text not null default 'upload' check (source in ('upload','paste','tailored')),
  is_primary boolean not null default false, version int not null default 1, embedding vector(1024));
create unique index resumes_one_primary on resumes (user_id) where is_primary;          -- app limit: primary + 3 variations
create table cover_letters (id uuid primary key, user_id uuid not null references users on delete cascade,
  label text not null, text text not null, file_key text, file_name text, file_kind text,
  is_default boolean not null default false, version int not null default 1);
create unique index cover_letters_one_default on cover_letters (user_id) where is_default;  -- app limit: 5 per user

-- M4 Answer bank
create table answers (id uuid primary key, user_id uuid not null references users on delete cascade, key text not null,
  search_profile_id uuid references search_profiles on delete cascade,  -- null = all profiles
  question text not null, answer text not null, confirmed_at timestamptz not null);
create unique index answers_scope on answers (user_id, key, coalesce(search_profile_id, '00000000-0000-0000-0000-000000000000'));

-- M5 Ingestion
create table inbound_messages (id uuid primary key, user_id uuid not null references users on delete cascade,
  message_id text not null, sender text not null, subject text, source text, received_at timestamptz not null,
  raw_key text, parser_version text, status text not null, cards_found int, error text,
  unique (user_id, message_id));
create table mailbox_connections (user_id uuid references users on delete cascade, provider text,
  scope text, token_secret_ref text not null, cursor text, primary key (user_id, provider));      -- Phase 2
create table ats_boards (id uuid primary key, user_id uuid not null references users on delete cascade,
  provider text check (provider in ('greenhouse','lever')), board text not null, last_polled_at timestamptz,
  unique (user_id, provider, board));

-- M6 Shared job catalog (no user_id: public posting data)
create table jobs (id uuid primary key, fingerprint text unique not null, title text not null, company text not null,
  location text, work_model text, experience text, salary text,
  description text, about_company text, offer text, description_complete boolean not null default false,
  structure jsonb, structure_version text, embedding vector(1024), posted_at timestamptz);
create table job_sources (job_id uuid not null references jobs on delete cascade, source text not null,
  url text not null unique, source_job_id text, first_seen_at timestamptz not null default now(),
  primary key (job_id, url));

-- M7 Matching (private)
create table user_jobs (id uuid primary key, user_id uuid not null references users on delete cascade,
  job_id uuid not null references jobs, inbound_message_id uuid references inbound_messages,
  status text not null default 'new' check (status in ('new','seen','ignored')),
  first_seen_at timestamptz not null default now(), unique (user_id, job_id));
create table job_scores (user_job_id uuid references user_jobs on delete cascade,
  search_profile_id uuid references search_profiles on delete cascade, user_id uuid not null,
  overall smallint not null, band text not null check (band in ('strong','good','low','filtered')),
  provisional boolean not null, factors jsonb not null, must_have_gaps text[], gaps text[], strengths text[],
  rationale text, filter_reason text, model text, prompt_version text, profile_version int,
  primary key (user_job_id, search_profile_id));

-- M8 Resume recommender
create table resume_recommendations (user_job_id uuid references user_jobs on delete cascade,
  search_profile_id uuid references search_profiles on delete cascade, user_id uuid not null,
  ranking jsonb not null, recommended_resume_id uuid, chosen_resume_id uuid, themes jsonb,
  suggestions jsonb not null, gaps text[], new_version_hint text, prompt_version text,
  primary_resume_score smallint,                                   -- ranking holds a % per resume
  recommended_cover_letter_id uuid references cover_letters on delete set null,
  primary key (user_job_id, search_profile_id));

-- M9 Readiness
create table readiness (user_job_id uuid primary key references user_jobs on delete cascade, user_id uuid not null,
  status text not null check (status in ('ready','needs_input','manual_only')), checked_at timestamptz not null);
create table blockers (id uuid primary key, user_job_id uuid not null references user_jobs on delete cascade,
  user_id uuid not null, type text not null, key text, question text not null, draft text,
  resolved boolean not null default false, answer text, resolved_at timestamptz);

-- M10 Documents
create table documents (id uuid primary key, user_id uuid not null references users on delete cascade,
  user_job_id uuid references user_jobs on delete set null, kind text check (kind in ('pack')),
  base_resume_id uuid references resumes on delete set null, accepted_suggestions text[],
  resume_blocks jsonb not null, cover_letter text, answers jsonb, claim_check jsonb not null,
  docx_key text, pdf_key text, model text, prompt_version text);

-- M11 Applications
create table applications (id uuid primary key, user_id uuid not null references users on delete cascade,
  user_job_id uuid not null references user_jobs on delete cascade, search_profile_id uuid,
  status text not null check (status in ('interested','needs_input','ready','applied','interview','closed')),
  document_id uuid references documents, applied_at timestamptz, follow_up_at timestamptz, notes text,
  unique (user_id, user_job_id));
create table application_events (id bigserial primary key, application_id uuid references applications on delete cascade,
  user_id uuid not null, from_status text, to_status text not null, at timestamptz not null default now());

-- M12 Networking
create table connections (id uuid primary key, user_id uuid not null references users on delete cascade,
  first_name text, last_name text, profile_url text, email text, company text, position text,
  connected_on date, company_key text, unique (user_id, profile_url));
create table connection_imports (id uuid primary key, user_id uuid not null references users on delete cascade,
  file_name text, total int, added int, updated int);
create table daily_suggestions (id uuid primary key, user_id uuid not null references users on delete cascade,
  day date not null, kind text check (kind in ('warm','target','followup')), payload jsonb not null,
  status text not null default 'open' check (status in ('open','done','skipped')), unique (user_id, day, payload));
create table outreach (id uuid primary key, user_id uuid not null references users on delete cascade,
  kind text not null, person_name text, title text, company text, profile_url text, connection_id uuid references connections on delete set null,
  user_job_id uuid references user_jobs on delete set null, note text,
  stage text not null check (stage in ('sent','accepted','conversation','referral','closed')), stage_at timestamptz not null);
create table outreach_events (id bigserial primary key, outreach_id uuid references outreach on delete cascade,
  user_id uuid not null, stage text not null, at timestamptz not null default now());

-- M13 Notifications
create table notification_settings (user_id uuid primary key references users on delete cascade,
  push boolean default true, email boolean default true, quiet_start time, quiet_end time, max_push_per_day int default 10,
  digest_time time default '19:00', network_daily_cap int default 5, network_weekly_limit int default 100);
create table devices (id uuid primary key, user_id uuid not null references users on delete cascade,
  platform text, expo_token text unique not null, last_seen_at timestamptz);
create table notifications (id uuid primary key, user_id uuid not null references users on delete cascade,
  type text not null, title text not null, body text, user_job_id uuid, channels text[], pushed boolean, held boolean,
  read_at timestamptz);

-- M14 Admin and usage
create table llm_calls (id bigserial primary key, user_id uuid, prompt text, prompt_version text, provider text, model text,
  input_tokens int, cached_tokens int, output_tokens int, cost_usd numeric(10,6), latency_ms int, ok boolean, at timestamptz default now());
create table usage_counters (user_id uuid references users on delete cascade, period char(7),
  scored_jobs int default 0, packs int default 0, llm_cost_usd numeric(10,4) default 0, primary key (user_id, period));
create table audit_events (id bigserial primary key, user_id uuid, actor text, event text, entity text, meta jsonb, at timestamptz default now());
create table outbox (id bigserial primary key, event text not null, payload jsonb not null, published_at timestamptz);

-- M15 Billing (Phase 2)
create table plans (id text primary key, name text, price_inr int, limits jsonb, razorpay_plan_id text);
create table subscriptions (id uuid primary key, user_id uuid references users on delete cascade, plan_id text references plans,
  razorpay_subscription_id text unique, status text, current_period_end timestamptz);
create table payments (id uuid primary key, user_id uuid references users, razorpay_payment_id text unique,
  amount_inr int, status text, invoice_url text, event_id text unique);

-- Indexes (selection)
create index on user_jobs (user_id, status, first_seen_at desc);
create index on job_scores (user_id, band, overall desc);
create index on applications (user_id, status, applied_at desc);
create index on blockers (user_job_id) where not resolved;
create index on connections (user_id, company_key);
create index on daily_suggestions (user_id, day);
create index on jobs using hnsw (embedding vector_cosine_ops);
create index on notifications (user_id, created_at desc) where read_at is null;

-- Row-level security (repeat for every table with user_id)
alter table user_jobs enable row level security;
create policy own_rows on user_jobs using (user_id = current_setting('app.user_id')::uuid);
```

**Retention.** Raw alert emails are kept 90 days, then deleted from object storage; parsed jobs stay. AI call logs are kept 180 days. Deleting an account cascades through every private table, and its objects are removed within 30 days. That 30-day window matches the DPDP commitment in the BRD.

**Expected size at 1,000 users** (Phase 2, first year): about 1.5 million user-job rows, 3 million score rows, 300,000 shared jobs and 1 million connections. That is about 15–25 GB including indexes, well within a db.t4g.medium with 100 GB of storage.

## Background jobs and pipelines

All background work runs in one worker process (Phase 1) or a few worker tasks (Phase 2) on a Postgres-backed queue. Every task is idempotent and keyed by entity id, so a retry never creates duplicates. A task that fails all retries lands in a dead-letter list on the admin page, where it can be re-run.

**How an alert becomes a notification**

1. The inbound endpoint stores the raw email in object storage, inserts `inbound_messages`, and enqueues `parse_alert`. This returns within 1 second.
2. `parse_alert` extracts job cards, upserts each into the shared catalog (merging duplicates), links them to the user, and enqueues `score_job` per user-job. For jobs new to the catalog, it also enqueues `extract_job`.
3. `extract_job` runs once per catalog job. It calls the AI only when the full description is present, otherwise it marks the job provisional.
4. `score_job` applies the hard filters (no AI), then the embedding pre-screen, then AI scoring per active search profile. Strong and good matches enqueue `recommend_resume` and `evaluate_readiness`.
5. `evaluate_readiness` writes blockers, then calls the notifier. The notifier applies quiet hours, daily caps and digest rules, then sends push, email, in-app and WebSocket messages.

Target: under 5 minutes from email arrival to push. In practice this is 20–60 seconds.

| Task | Queue | Trigger | Retries (backoff) | Time limit |
| --- | --- | --- | --- | --- |
| `parse_alert` | ingest | Inbound email accepted | 5 (30 s doubling) | 60 s |
| `extract_job` | ai | New catalog job, or full description added | 3 (1 min doubling) | 120 s |
| `score_job` | ai | Job linked, profile changed, resume changed | 3 | 120 s |
| `recommend_resume` | ai | Score is strong or good; user switches resume | 3 | 180 s |
| `evaluate_readiness` | default | Score is strong or good; answer saved; profile changed | 5 | 30 s |
| `build_pack` | ai | User asks for a pack | 2 | 240 s |
| `render_document` | docs | Pack built, or download asked for a missing format | 3 | 60 s |
| `parse_resume` | docs | Resume uploaded | 3 | 120 s |
| `import_connections` | default | Connections file uploaded | 2 | 120 s |
| `send_notification` | notify | Notifier decides to push or email | 5 | 15 s |
| `poll_ats_board` | ingest | Cron, every 6 hours per followed board | 3 | 60 s |
| `daily_networking` | default | Cron, 07:30 in each user's time zone | 3 | 60 s |
| `daily_digest` | notify | Cron, each user's digest time (default 19:00) | 3 | 60 s |
| `follow_up_reminders` | notify | Cron, 09:00 daily | 3 | 60 s |
| `export_user_data` / `delete_user` | default | User asks | 3 | 15 min |
| `purge_raw_email` | maintenance | Cron, 02:00 daily (older than 90 days) | 1 | 30 min |
| `backup_database` | maintenance | Cron, 01:30 daily (Phase 1 only; RDS does this in Phase 2) | 2 | 30 min |
| `rescore_nightly` | ai (Batch API) | Cron, 03:00 (when prompts or models change) | 1 | 6 h |

**Concurrency.** Phase 1 runs one worker process with 4 concurrent tasks. Phase 2 runs 3 worker tasks with 8 each. The `ai` queue is capped at 10 parallel calls per worker to stay within the Anthropic rate limits. Per-user fairness is enforced by a lock on `user_id` for scoring, so one user's large alert can't delay everyone else.

**AI cost controls.**

- Hard filters and the embedding pre-screen run before any AI call.
- Job extraction runs once per catalog job and is shared across users.
- Resume texts are sent as cached prompt prefixes, which cost 5% of the normal input price on Sonnet.
- Re-scoring after prompt changes uses the Batch API at half price.
- Each user's monthly AI spend is metered in `usage_counters`. Phase 2 plans set a cap.

## Phase 1 deployment: 2–3 users

Phase 1 runs everything on one AWS Lightsail server in Mumbai, with Docker Compose, for about US$30–40 a month. Cloudflare handles DNS and receives alert emails for free. AI is the only usage-based cost, at about US$1–2 per user a month.

&#91;embedded content: Phase 1 deployment · one server, free email routing\]

Everything inside the shaded box runs on the one server. The worker makes every outbound call: AI, embeddings, push, email and the nightly backup.

**On the server (Docker Compose).**

| Container | Purpose | Memory |
| --- | --- | --- |
| caddy | HTTPS (automatic certificates), routes `/` to web and `/api`, `/ws` to the API | \~50 MB |
| web | Next.js (`next start`) | \~300 MB |
| api | FastAPI on Uvicorn (2 workers); also serves the WebSocket | \~350 MB |
| worker | Procrastinate worker and scheduler (cron tasks) | \~400 MB |
| db | PostgreSQL 16 with pgvector (`pgvector/pgvector:pg16` image) | \~600 MB |
| minio | S3-compatible storage for resumes and generated documents | \~200 MB |

Total is about 1.9 GB, so the 4 GB plan leaves room for spikes and updates. The 2 GB plan (US$12) works if you drop MinIO and store files on the local disk, but builds and upgrades get tight. Images are built in GitHub Actions, never on the server.

**Monthly cost** (Mumbai region; US$ at about ₹88 per US$, approximate):

| Item | Choice | US$ per month |
| --- | --- | --- |
| Server | Lightsail Linux, 4 GB RAM, 2 vCPU, 80 GB SSD, 2 TB transfer in Mumbai | 24.00 |
| Server snapshots | Automatic daily Lightsail snapshots (about 20 GB used) | \~1.00 |
| Off-site database backup | Nightly `pg_dump` to an S3 bucket (Standard-IA, about 5 GB) | \~0.20 |
| Domain | `.com` or `.in`, about US$10–12 a year | \~1.00 |
| DNS, alert email receiving | Cloudflare DNS, Email Routing and an Email Worker (free plan) | 0.00 |
| Outbound email | Amazon SES, a few hundred emails ($0.10 per 1,000) | \~0.05 |
| AI | Anthropic API for 3 users: extraction, scoring (Haiku 5.5), resume ranking and packs (Sonnet 5.5) | \~3–6 |
| Embeddings | Voyage `voyage-4-lite`, within the 200 million free tokens | 0.00 |
| Push notifications, mobile builds | Expo Push and EAS Build free tier | 0.00 |
| Monitoring | Sentry free plan, UptimeRobot free monitor | 0.00 |
| iOS distribution (only if you need the iPhone app) | Apple Developer Program, US$99 a year | \~8.25 |
| Android distribution | Google Play developer account, US$25 once | 0.00 |
| **Total** |  | **\~30 (Android only) to \~40 (with iOS)** |

**How the AI estimate is built (per user per month):**

| Step | Model | Calls | Cost per call | Cost |
| --- | --- | --- | --- | --- |
| Job extraction (shared across users) | Haiku 5.5 | \~400 per user | $0.0007 | $0.28 |
| Scoring | Haiku 5.5 | \~360 | $0.0006 | $0.22 |
| Resume ranking (strong matches) | Sonnet 5.5 with cached resumes | \~10 | $0.014 | $0.14 |
| Application packs | Sonnet 5.5 | \~10 | $0.037 | $0.37 |
| Answer drafts | Haiku 5.5 | \~20 | $0.0002 | \~$0.01 |
| **Per user** |  |  |  | **about $1–2** with retries and headroom |

Prices used: Haiku 5.5 at US$0.10 input and US$0.50 output per million tokens; Sonnet 5.5 at US$2 and US$10; cache reads at 5% of the input price on Sonnet.

**Non-cloud alternative.** The same Compose file runs on a home mini PC or an always-on laptop. Cloudflare Tunnel then exposes it without opening ports, and Email Routing still delivers alerts. The infrastructure cost drops to about US$1 a month (domain only) plus AI. The trade-off is uptime: power cuts, home internet outages and sleep mode stop alerts and pushes. I'd use it only for development and trials, and use Lightsail for anything you rely on daily.

**Limits of Phase 1.**

- The server is a single point of failure. A restore from the nightly snapshot loses at most 24 hours.
- There's no managed identity, MFA or payment.
- It's suitable for up to about 20 users before the database and worker need to move off the box.

## Phase 2 deployment: 500–1,000 users

Phase 2 moves to managed AWS services in Mumbai (ap-south-1), keeping data in India. It costs about US$500 a month for infrastructure plus US$400–700 for AI, around US$1–1.25 per user. The same containers run in ECS Fargate; the database moves to RDS with a standby; alert emails arrive through SES. Each piece scales on its own.

&#91;embedded content: Phase 2 deployment · managed AWS in Mumbai\]

The application tasks run in private subnets. Only the load balancer is public. Outbound calls to AI, push and payments leave through one NAT gateway.

**What changes from Phase 1**

| Concern | Phase 1 | Phase 2 |
| --- | --- | --- |
| Compute | One server, Docker Compose | ECS Fargate (ARM): web 2–4 tasks, API 2–6 tasks, workers 3–10 tasks, auto-scaled |
| Database | PostgreSQL container | RDS PostgreSQL 16, db.t4g.medium, Multi-AZ, 100 GB gp3, 7-day point-in-time recovery |
| Files | MinIO | S3 (KMS-encrypted) with CloudFront for downloads through signed URLs |
| Inbound email | Cloudflare Email Worker | SES receiving in Mumbai: rule stores the message in S3 and notifies SNS, which calls `/internal/inbound` |
| Identity | Built-in accounts with Google and Microsoft sign-in | Built-in accounts with Google and Microsoft sign-in (Cognito optional, for MFA) |
| Edge | Caddy | Route 53, CloudFront, AWS WAF, Application Load Balancer, ACM certificates |
| Cache and fan-out | In-process | ElastiCache (Redis) |
| Secrets | `.env` file | Secrets Manager and KMS |
| Observability | Logs, Sentry free | CloudWatch logs, metrics and alarms; Sentry Team; OpenTelemetry traces |
| Payments | None | Razorpay subscriptions and webhooks |
| Provisioning | Compose file | Terraform, applied from GitHub Actions |

**Scaling rules.**

- The API scales at 60% CPU.
- Workers scale on queue depth: one more task for every 200 waiting tasks.
- Web scales at 70% CPU.
- RDS moves to db.t4g.large when CPU stays above 60%, or when connections exceed 300 even with PgBouncer.

**Monthly cost at 1,000 users** (about 700 active; Mumbai; approximate list prices; ₹ at about 88 per US$):

| Item | Sizing | US$ per month |
| --- | --- | --- |
| ECS Fargate (ARM) | 7 tasks: API 2 × (1 vCPU, 2 GB), workers 3 × (1 vCPU, 2 GB), web 2 × (0.5 vCPU, 1 GB) | \~175 |
| RDS PostgreSQL | db.t4g.medium Multi-AZ (US$61 a month per instance in Mumbai) plus 100 GB gp3 storage and backups | \~155 |
| Application Load Balancer | 1 load balancer, low traffic | \~25 |
| NAT gateway | 1, for outbound calls from private subnets | \~37 |
| ElastiCache (Redis) | cache.t4g.small | \~25 |
| CloudWatch | Logs (about 20 GB a month), metrics, alarms | \~25 |
| SES | Receiving about 85,000 alert emails ($0.10 per 1,000 plus $0.09 per 1,000 chunks) and sending about 25,000 | \~18 |
| AWS WAF | 1 web ACL, 5 rules | \~11 |
| S3 and CloudFront | About 100 GB of files; downloads within the free tier | \~10 |
| Secrets Manager, KMS, ECR, Route 53 |  | \~10 |
| Cognito | Essentials tier; first 10,000 monthly active users free | 0 |
| Sentry Team (optional) | Error tracking for web, mobile, API | \~26 |
| **Infrastructure subtotal** |  | **\~490–520** |
| AI: job extraction | Haiku 5.5, about 90,000 unique jobs a month, shared across users | \~65 |
| AI: scoring | Haiku 5.5, about 250,000 user-job scores a month | \~150 |
| AI: resume ranking | Sonnet 5.5 with cached resumes, strong matches only (\~7,000) | \~100 |
| AI: application packs | Sonnet 5.5, about 2,800 packs | \~105 |
| Embeddings | Voyage `voyage-4-lite` | \~5 |
| **AI subtotal** | Estimate, plus headroom for retries and heavier users | **\~400–700** |
| **Total** |  | **\~900–1,250 (₹80,000–1,10,000)** |

Razorpay charges a percentage of each payment instead of a monthly fee, so its cost isn't in the table; it is deducted from revenue.

**Fargate and some Mumbai rates are approximate.** The table uses list prices; confirm them in the AWS Pricing Calculator before committing. A Savings Plan (1 year) lowers Fargate and RDS by about 20–30%.

**Cheaper Phase 2 option.** If budget matters more than resilience, use 2 EC2 t4g.large instances behind the load balancer and a single-AZ RDS. That brings infrastructure to about US$250 a month, at the cost of more patching and longer failover.

## Security, configuration and environment variables

The system stores no job-portal or email passwords. In Phase 1 every setting comes from one `.env` file on the server; in Phase 2 the same names come from Secrets Manager and ECS task definitions.

**Security controls**

| Area | Control |
| --- | --- |
| Accounts | Argon2id password hashes; Google and Microsoft sign-in with OpenID Connect (scopes openid, email, profile only; state and PKCE checked; only the provider's user id and email stored); login rate limit of 5 attempts a minute per IP and per email |
| Tokens | Access JWT 15 minutes (EdDSA signed); refresh token 30 days, rotated on use, revocable; stored HttpOnly on web and in SecureStore on mobile |
| Tenant isolation | `user_id` on every private row, row-level security, and an automated test that tries cross-user access on every endpoint |
| Inbound email | Unguessable per-user address (rotatable), HMAC-signed calls from Cloudflare or SNS, sender allow-list plus DKIM pass |
| Files | Private buckets; downloads only through signed URLs valid for 10 minutes; uploads limited to 10 MB and to the six accepted formats, with file-type sniffing |
| AI data | Only the user's own profile, resumes and job text are sent; no data is used for model training under Anthropic's commercial terms; prompts never include other users' data |
| Secrets | `.env` readable only by root on the server (Phase 1); Secrets Manager with automatic rotation for the database (Phase 2) |
| Transport | HTTPS everywhere (Caddy or ACM); HSTS; database and Redis reachable only from the app network |
| Logging | Structured logs without resume text, answers or tokens; audit events for logins, exports, deletions and admin views |
| Privacy (DPDP) | Consent at sign-up, data export, deletion within 30 days, 90-day raw email retention, grievance contact on the website |

**Environment variables**

| Name | Purpose | Phase 1 value | Phase 2 source |
| --- | --- | --- | --- |
| `APP_ENV` | `development`, `staging` or `production` | `production` | Task definition |
| `APP_BASE_URL` | Public web address | `https://app.yourdomain.com` | Task definition |
| `INBOUND_DOMAIN` | Domain for private alert addresses | `in.yourdomain.com` | Task definition |
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://ja:…@db:5432/ja` | Secrets Manager |
| `REDIS_URL` | Redis (Phase 2 only) | empty | Secrets Manager |
| `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` | Token signing | generated Ed25519 key pair | Secrets Manager |
| `AUTH_PROVIDER` | `local` or `cognito` | `local` | Task definition |
| `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` | Cognito (optional, only if adopted for MFA) | empty | Task definition |
| GOOGLE\_CLIENT\_ID, GOOGLE\_CLIENT\_SECRET, MICROSOFT\_CLIENT\_ID, MICROSOFT\_CLIENT\_SECRET | Google and Microsoft sign-in (OpenID Connect, sign-in scopes only) | from Google Cloud console and Microsoft Entra app registration | Secrets Manager |
| AI\_DAILY\_COST\_CAP\_USD | Per-user daily AI spend cap across Claude and Voyage | 1 | Task definition |
| `INBOUND_SHARED_SECRET` | HMAC between email receiver and API | random 32 bytes | Secrets Manager |
| `INBOUND_ADAPTER` | `cloudflare` or `ses` | `cloudflare` | Task definition |
| `STORAGE_ENDPOINT`, `STORAGE_BUCKET`, `STORAGE_KEY`, `STORAGE_SECRET` | S3-compatible storage | MinIO values | S3 with task role (no keys) |
| `ANTHROPIC_API_KEY` | AI calls | from the Claude Console | Secrets Manager |
| `LLM_MODEL_FAST`, `LLM_MODEL_SMART` | Model routing | `claude-haiku-5-5`, `claude-sonnet-5-5` | Task definition |
| LLM\_ROUTES | Per-prompt provider and model, overriding the defaults (e.g. resume\_extract=selfhosted:qwen-…) | empty (all prompts on Anthropic) | Task definition |
| `LLM_MONTHLY_BUDGET_USD` | Platform-wide AI ceiling | `20` | `1000` |
| `VOYAGE_API_KEY`, `EMBEDDING_MODEL` | Embeddings | from Voyage, `voyage-4-lite` | Secrets Manager |
| `EXPO_ACCESS_TOKEN` | Push sending | from expo.dev | Secrets Manager |
| `SES_REGION`, `SES_FROM` | Outbound email | `ap-south-1`, `alerts@yourdomain.com` | Task definition |
| `SENTRY_DSN` | Error tracking | from sentry.io | Task definition |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Payments (Phase 2) | empty | Secrets Manager |
| `NEXT_PUBLIC_API_URL` | Web client API base | `https://app.yourdomain.com/api/v1` | Build argument |
| `EXPO_PUBLIC_API_URL` | Mobile client API base | same | EAS environment |

**Application settings in the database** (changed from the admin page without a redeploy): sender allow-list, parser versions in use, default thresholds and weights, plan limits, prompt versions.

## Setup steps

Phase 1 takes about half a day to set up the first time, most of it waiting for DNS and the SES approval. Everything below is one-time work, except the release step at the end.

**Accounts you need**

| Service | Used for | Cost |
| --- | --- | --- |
| AWS | Lightsail server, S3 backup bucket, SES outbound email | Pay as you go |
| Cloudflare | DNS, Email Routing, Email Worker | Free plan |
| Domain registrar | Your domain (Cloudflare Registrar sells at cost) | \~US$10–12 a year |
| Claude Console | Anthropic API key | Pay as you go |
| Voyage AI | Embeddings API key | Free allowance |
| Expo | Push notifications and mobile builds | Free plan |
| GitHub | Code, Actions, container registry | Free for private repos within limits |
| Sentry, UptimeRobot | Errors and uptime | Free plans |
| Apple Developer, Google Play | Installing the app on phones beyond development | US$99 a year; US$25 once |

**Phase 1: first deployment**

1. **Domain and DNS.** Add the domain to Cloudflare and switch the registrar's name servers to Cloudflare's. Create an `A` record `app` pointing to the server's static IP, set to DNS only (grey cloud) so Caddy can obtain its certificate.
2. **Server.** In Lightsail (Mumbai), create an Ubuntu 24.04 instance on the 4 GB plan.
   1. Attach a static IP.
   2. Open ports 80 and 443 to all, and port 22 to your IP only.
   3. Turn on automatic snapshots.
   4. Install Docker Engine with the Compose plugin, `unattended-upgrades` and `fail2ban`.
   5. Create a `deploy` user with your SSH key.
3. **Alert email receiving.** In Cloudflare, enable Email Routing for the subdomain `in.yourdomain.com`, and accept the MX and TXT records it adds.
   1. Deploy the Email Worker from the repo (`infra/cloudflare/email-worker`) with `npx wrangler deploy`.
   2. Set its secrets: `API_URL` and `INBOUND_SHARED_SECRET`.
   3. Add a catch-all rule that sends every address at `in.yourdomain.com` to the Worker.
4. **Outbound email.** In Amazon SES (ap-south-1), verify the domain and add its DKIM CNAME records in Cloudflare. Request production access, which takes up to a day. Create an IAM user that can only send email.
5. **Backups.** Create a private S3 bucket for database dumps with a 30-day expiry rule, and an IAM user that can only write to it.
6. **Keys.** Create the Anthropic API key in the Claude Console, a Voyage API key, an Expo access token and a Sentry DSN. Generate the JWT key pair and the inbound secret with the script `scripts/gen-secrets.sh`.
7. **Deploy.** On the server:
   1. Clone the repo.
   2. Copy `.env.example` to `.env` and fill in the values from the configuration section.
   3. Run `docker compose pull && docker compose up -d`.
   4. Apply the database schema with `docker compose exec api alembic upgrade head`.
   5. Create your account with `docker compose exec api python -m app.cli create-user --admin --email you@…`.
8. **Check it end to end.**
   1. Open `https://app.yourdomain.com` and sign in. Copy your forwarding address from Mail and portals.
   2. Add it as a Gmail forwarding address. The confirmation code appears in the app; paste it into Gmail.
   3. Create the Gmail filter, then forward one LinkedIn alert.
   4. Confirm the jobs appear and a push arrives on your phone.
9. **Mobile app.** Set `EXPO_PUBLIC_API_URL`. Build an Android APK for direct install with `eas build -p android --profile preview`, and an iOS build for TestFlight with `eas build -p ios`.
10. **Monitoring.** Add an UptimeRobot check on `https://app.yourdomain.com/api/v1/healthz`. Confirm the first nightly backup appears in S3, then do a test restore into a scratch database.

**Releasing an update (every time).** Tag a release on GitHub. GitHub Actions runs the tests, builds the images, pushes them to the GitHub container registry, then connects to the server to pull the images, apply migrations and restart. Mobile fixes that don't change native code ship with `eas update`.

**Phase 2: moving to managed AWS**

1. Run `terraform apply` in `infra/terraform/envs/prod`. This creates the VPC, RDS, ElastiCache, ECS cluster and services, load balancer, CloudFront, WAF, S3 buckets, the SES receipt rule (store to S3, notify SNS), Cognito and Secrets Manager entries.
2. Point the `in.yourdomain.com` MX record at `inbound-smtp.ap-south-1.amazonaws.com`, and set `INBOUND_ADAPTER=ses`.
3. Copy the data: `pg_dump` from the Phase 1 server and restore into RDS. Then copy the files from MinIO to S3 with `rclone`.
4. Optional, only if Cognito is adopted for MFA: import the existing users into Cognito, with a password reset on first sign-in, then set `AUTH_PROVIDER=cognito`.
5. Set up Razorpay: create the plans, add the webhook URL and its secret, and turn billing on in the admin page.
6. Switch the `app` DNS record to CloudFront. Keep the Phase 1 server read-only for a week, then retire it.

## Milestones 5 to 12: design and status (2 November 2026)

Milestones 5 and 7 are built (commits b37a0f9 and 4643b8e). Milestone 9 is next, then 6, 10 and 11, then 8 and 12. India is the first market. The sections below record what was built or decided; they take precedence over earlier sections of this document where the two differ.

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Foundation | Done |
| 2 | Ingestion | Done, except the Cloudflare email worker (needs a domain) |
| 3 | Resumes and matching | Done with rules and Voyage; Claude scoring waits for the Anthropic key |
| 4 | Readiness, answer bank, packs | Readiness and answer bank done; resume edits, packs, claim check wait for the Anthropic key; Google and Microsoft sign-in wait for a domain |
| 5 | Applications tracker and feedback | Done (b37a0f9) |
| 6 | Notifications, WhatsApp, optional Teams | In progress: WhatsApp alerts and the in-app bell built; sending waits for the one-time Meta setup |
| 7 | Networking | Done (4643b8e); decisions under review |
| 8 | Release: Lightsail, backups, monitoring, security | Not started |
| 9 | More sources and duplicates (India first) | In progress: company boards and job APIs in the Job Search Service, duplicates built |
| 10 | Marketing home page | Built (2026-11-03); plans shown since 2026-11-17 |
| 11 | Subscriptions (India first, Razorpay) | In progress: roles, plans, paywall, invites built 2026-11-17; Razorpay later |
| 12 | US market | Later |
| 13 | Ask BrewMyJob | Part A built (Not for me with reasons, learned preferences); B to E wait for the Anthropic key |
| 14 | Fill application forms | Apply kit and browser extension built (download from Settings); Add from Google results as a proof of concept |

### Milestone 5: applications tracker and job queues (built)

Build order: super admin and settings → applications → Applied and Expired queues with the daily expiry check → contacts → amber to-dos → missing skills and points lost → Applications page → tests and e2e.

- **Super admin and app settings.** The existing `admin` role is the super admin. It is granted only by `make admin EMAIL=…`, never through the API. A shared `app_settings` table (key, JSON value, updated\_by, updated\_at; no `user_id`) is readable by every signed-in user and writable only by admins on an admin settings page; every change writes an `audit_events` row with the old and new values. Settings: `job_expiry_warn_days` (proposed 30) and `job_expiry_move_days` (proposed 45).
- **Applications.** Statuses applied → interviewing → offer → accepted, or rejected, withdrawn or no\_response at any point. Each application keeps the date applied, the resume and cover letter used, notes and follow-up dates; every change is an `application_events` row. Undo of Mark as Applied removes the application.
- **Job queues.** `GET /jobs?tab=top|other|unscored|applied|expired|ignored`. Applied jobs leave Top matches and Other jobs. A job is in exactly one tab.
- **Expiry.** A daily worker task flags jobs older than the warning period with "May have expired" and moves jobs older than the move period to Expired, counted from when the alert arrived. Jobs with an application are never expired automatically. Mark as expired and Move back are user actions.
- **Contacts.** A private, per-user contacts table linked to user jobs: name, LinkedIn URL, email, source (`email` when a Naukri recruiter invite names a recruiter, `user` when pasted). FitFirst never opens job pages and never messages anyone. Networking (milestone 7) reuses these rows. Contacts are included in data export and account deletion.
- **To-dos.** Computed per user job from readiness blockers, missing profile facts (notice period, CTC), a required cover letter, follow-up dates and expiry; returned as a list with an action for each, and as a count on job cards.
- **Match explanation.** The job page lists skills matched and missing and the points lost per factor (weight × shortfall, rounded). "I have this skill" adds the skill to the candidate profile and re-scores that job.

### Milestone 7: networking (built)

FitFirst never logs in to LinkedIn, never sends invitations or messages, and never scrapes.

- **Import.** The user uploads the Connections file from LinkedIn's data export (Settings → Data privacy → Get a copy of your data), as ZIP or CSV. Re-importing updates the list. Emails are dropped unless the user chooses to keep them. The uploaded file is not stored.
- **Company matching.** Names are normalised: lower case, legal suffixes such as Pvt Ltd, Inc and India removed. Two names match when they are equal; when one is the other plus whole words, with the shorter at least 6 characters ("Commonwealth Bank" = "Commonwealth Bank of Australia"); or when a name Naukri cut short is the start of the other, at least 8 characters.
- **Warm paths.** Connections at the companies of Top matches and applied jobs, recruiters first, then leaders. Shown on each job page as "People you know at …".
- **Today's suggestions.** Up to 5 a day (the cap in notification settings): follow-ups first (no reply after 7 days); then warm suggestions, one person per company, nobody repeated within 14 days; then target suggestions, giving the role to look for and a LinkedIn people-search link the user opens. Target roles: CEO for C-level jobs; CTO or Chief Product Officer for senior tech or product jobs; otherwise Talent Acquisition. Template notes stay under 300 characters. At the weekly limit (100), only follow-ups are suggested.
- **Outreach tracker.** sent → accepted → conversation → referral → closed, with an event history.
- **Under review:** the note wording, the target-role choices and the company-matching rules.

### Milestone 6: notifications (planned)

- **Common part.** An outbox with retries; rules per event and channel (strong match, needs input, follow-up due, networking, daily digest); quiet hours (default 22:00–07:00); a daily cap; one message per job; an in-app bell; a settings page with "Send a test".
- **WhatsApp.** Meta WhatsApp Business (Cloud) API only; no unofficial WhatsApp Web automation, which breaks WhatsApp's terms. The user's number is verified with a one-time code. Meta's free test number reaches up to 5 numbers; after that Meta charges per message, and messages FitFirst starts must use Meta-approved templates. Reply buttons need a public webhook and wait for the domain.
- **Teams (optional).** The user pastes a Teams Workflows webhook link, stored encrypted. Works with work or school accounts; personal Teams is uncertain.
- **Email digest.** Written to the log until there is a domain.
- **Open questions:** a message for every job, or only strong matches with the rest in an evening summary; Meta directly or Twilio; whether the user's Teams account is work or personal; whether to move the Expo app and push to a milestone 6b.

### Milestone 9: more sources and duplicates (next)

- **Company feeds** (free, no key): Greenhouse, Lever, Ashby and SmartRecruiters public job boards for companies the user lists, checked daily.
- **Adzuna India API:** free key with a daily limit, kept in `.env`. Commercial use must be confirmed with Adzuna before users are charged; the same applies to Jooble and Careerjet.
- **More alert-email parsers:** iimjobs, hirist, Indeed, Foundit, Instahyre and Glassdoor. Each needs 2–3 real alert emails from the user, sanitised before they are used as test fixtures.
- **No API available to FitFirst** (alert emails only): LinkedIn, Naukri, Indeed, Glassdoor, Foundit, iimjobs, hirist, Instahyre, Wellfound.
- **Duplicates, already in place:** a job repeated in a later alert is not added again and keeps its status; jobs merge by listing, URL, or exact company + title + location.
- **Clear duplicate:** the same listing or URL; or the same company (using the networking company matching) plus the same normalised title ("VP" = "Vice President") and city; or near-identical descriptions. It is merged into the existing job ("Also on …") and not added. If that job is already applied, it stays in Applied and nothing new appears.
- **Potential duplicate:** the same company with a similar title, a different city, or very similar descriptions. It is added with an amber "Possible duplicate of …" note and Same job / Different job buttons; the user's choice is remembered.
- **Needed from the user:** an Adzuna key, a list of target companies, and sample alert emails.

## Roles, plans, shared job sources and Find on Google (17 November 2026)

This section takes precedence over earlier ones where they differ. Decisions and reasons:
`docs/plan-roles-and-plans.md`, `docs/plan-jobsearch-build.md`, `docs/plan-m14.md`.

**Roles and access**

| Item | Design |
| --- | --- |
| Roles | `users.role`: `job_seeker` (default), `admin`, `super_admin` (check constraint, migration 0032). `make admin EMAIL=…` makes a super admin. |
| Access period | `users.access_until` (latest end) and `subscriptions` (private, RLS FORCE: `kind` coupon or payment, `plan` 1m/3m/6m/12m, `months`, `starts_at`, `ends_at`, `invite_id`). A new period starts when the running one ends. |
| Token | The access JWT carries `role` and `acc` (the period's end, epoch seconds). |
| Checks | `require_access` (job seekers need a running period; admins never do) on every feature router, included in `app/main.py`; `require_admin` (admin or super admin) on Job sources; `require_super_admin` on Admin settings, waitlist, contact messages and invites. A missing period is `402 subscription_required`. |
| Free access | `FREE_ACCESS_EMAILS` (a pattern): accounts that need no plan. Local stack: `e2e-…@example.com` and `demo@example.com`; production: empty. |
| Invites | `invites` (no RLS; only the super admin's routes and the link holder by its token read it): `email`, `role` (job_seeker or admin), `free_months` (0, 1, 3), `token_hash` (sha256), `expires_at` (14 days), `accepted_at`/`accepted_by`, `revoked_at`. |

**Endpoints added**

| Method and path | Who | What |
| --- | --- | --- |
| `GET /plans` | signed in | The four plans (₹199 / 500 / 750 / 1,200) and your access; `payments_open` is false until Razorpay |
| `GET /invites/view?token=` | anyone with the link | The invite's email, role, free months, and whether that email has an account |
| `POST /invites/accept` | signed in, the invited email | Applies the role and the coupon; refresh the session afterwards |
| `POST /auth/signup` (`invite` field) | anyone with the link | Sign-up with an invite: the email must be the invite's |
| `GET/POST /admin/invites`, `DELETE /admin/invites/{id}` | super admin | List, make (the link is returned once), withdraw |
| `GET /sources/jobs`, `POST /sources/jobs/{job_id}` | signed in | Jobs → From sources: every open job the sources brought you (latest verdict per job from your `source_runs.jobs`, closed jobs left out, the last run's flagged `new`), and adding one that was left out |
| `GET /sources/companies/{id}/jobs`, `POST …/jobs/{job_id}` | admin | A company's open jobs, the last check's first, and adding one |
| `POST /extension/google-result` | extension token | Adds a job from a Google result (link, title, snippet); it waits in Jobs → From Google (`user_jobs.status = 'review'`, migration 0031) |
| `GET /jobs/google-searches` | signed in | Now uses the roles set on Find on Google (`candidate_profiles.alert_roles`, shared with Google Alerts), else the target roles |

**Shared job sources**

`platform_companies` (shared like the job catalog: `employer_id`, `name`, `added_by`; migration 0033 copied the old
per-user follows) replaces `watched_companies` (no longer read). The event-feed pull reads it for every active
user; each user's relevance check decides what reaches their list, and every verdict is kept on that user's
`source_runs.jobs` for From sources. Adding a company catches its open jobs up for every user with a search
profile; a job seeker's first Skill Match profile queues `sources.catch_up_user` for every company on the list.



I'll generate the code as one monorepo in milestones, each with tests and a working demo, matching the module design. You run it locally with Docker and VS Code. You change and extend it by working with Claude Code inside the repo, which reads the project rules from a `CLAUDE.md` file at the root. The exact commands come with the generated code; this section sets the approach.

**Repository layout**

```text
job-assistant/
├─ CLAUDE.md                  # project rules for Claude Code: stack, conventions, commands, do-nots
├─ docker-compose.yml         # Phase 1 production stack
├─ docker-compose.dev.yml     # local development (hot reload, sample data, Mailpit)
├─ Makefile                   # make dev | test | lint | migrate | seed | api-client
├─ .env.example
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # FastAPI app, routers, middleware (auth, RLS, rate limits)
│  │  ├─ core/                # config, db session, security, errors, events/outbox
│  │  ├─ modules/             # one package per module: identity, profiles, resumes, answers,
│  │  │                        #   ingestion, catalog, matching, recommender, readiness, documents,
│  │  │                        #   applications, networking, notifications, admin, billing, llm
│  │  │     └─ <module>/{router.py, service.py, models.py, schemas.py, tasks.py, tests/}
│  │  └─ worker.py            # Procrastinate app and cron schedule
│  ├─ migrations/              # Alembic
│  ├─ prompts/                 # versioned prompt files with their output schemas
│  └─ tests/fixtures/          # golden alert emails, sample resumes (from the POC), connections CSV
├─ apps/
│  ├─ web/                     # Next.js
│  └─ mobile/                  # Expo
├─ packages/
│  ├─ api/                     # generated TypeScript client from OpenAPI
│  ├─ schemas/                 # zod validators
│  └─ ui-tokens/               # colours, type, spacing shared by web and mobile
├─ infra/
│  ├─ cloudflare/email-worker/  # Phase 1 inbound email
│  ├─ caddy/Caddyfile
│  └─ terraform/               # Phase 2
└─ .github/workflows/           # test, build, deploy
```

**Build order (milestones).** Each milestone ends with passing tests and something you can click through.

1. Foundation: repo, Docker dev stack, database schema and migrations, accounts, profiles, OpenAPI client generation, web sign-in. (Done)
2. Ingestion and catalog: inbound endpoint, Cloudflare Worker, LinkedIn and Naukri parsers with golden tests, deduplication, jobs list. (Done except the worker)
3. Resume and cover-letter library and matching: uploads, profile from resume, rules and Voyage similarity, Top matches tabs. (Done; Claude scoring waits for the key)
4. Readiness, answer bank, resume edit suggestions, tailored packs in Word and PDF, claim check, sign-up changes, Google and Microsoft sign-in. (Partly done)
5. Applications tracker and feedback: Applied and Expired queues, to-dos, match explanation, contacts, super admin settings. (Done)
6. Notifications: outbox, rules, quiet hours, in-app bell, WhatsApp, optional Teams; Expo app possibly in 6b. (Planned)
7. Networking: connections import, warm paths, daily suggestions, outreach tracker. (Done)
8. Release: Lightsail deploy, backups, monitoring, rate limits, security pass. (Not started)
9. More sources and duplicates, India first. (Next)
10. Marketing home page. (Planned)
11. Subscriptions, India first, Razorpay. (Planned)
12. US market. (Later)

Working order from 2 November 2026: 9 → 6 → 10 → 11, then 8 and 12.

**On your laptop**

| Tool | Why |
| --- | --- |
| Docker Desktop (or Docker Engine on Linux) | Runs PostgreSQL, MinIO, Mailpit, API, worker and web locally |
| VS Code with the Claude Code, Python, Pylance, ESLint, Prettier, Docker and Expo Tools extensions | Editing, debugging and Claude Code inside the editor |
| Claude Code | Generating and changing code in the repo. Install with `curl -fsSL https://claude.ai/install.sh \| bash` (macOS, Linux, WSL) or `irm https://claude.ai/install.ps1 \| iex` (Windows PowerShell); it needs a Claude Pro, Max, Team, Enterprise or Console account |
| Node.js 22, pnpm, Python 3.12, uv | Running web and backend outside Docker when debugging |
| Expo Go app on your phone | Trying the mobile app during development |

**Running it locally (the expected commands).**

1. Clone the repo, copy `.env.example` to `.env`, and add your Anthropic and Voyage keys. Leave them empty to use the rule-based fallback from the POC.
2. Run `make dev`. This starts the database, storage, Mailpit, API with hot reload, the worker and the web app at `http://localhost:3000`.
3. Run `make seed` to load the POC's sample account, resumes, alerts and connections.
4. Run `make inbound FILE=backend/tests/fixtures/linkedin_alert.eml` to simulate an alert arriving by email.
5. Run `pnpm --filter mobile start` and scan the QR code with Expo Go.
6. Run `make test` for the backend, web and contract tests.

**Working with Claude Code on the repo.**

- Open the repo folder in VS Code and start Claude Code from the extension panel, or run `claude` in the terminal at the repo root.
- `CLAUDE.md` tells it the stack, folder conventions, the rule that every change needs tests, and the commands to run (`make test`, `make lint`, `make api-client`).
- For larger changes, ask it to plan first, review the plan, then let it implement and run the tests. Typical asks: "add Indeed as a source", or "change the strong-match rule".
- Keep secrets out of prompts and commits. `.env` is git-ignored, and `CLAUDE.md` says never to print or commit it.
- Review every diff before committing. CI runs the same tests on every pull request.

**Detailed setup instructions** (exact versions, screenshots of each console step, troubleshooting) will come as a `SETUP.md` in the repo, written against the generated code.

## Open decisions and sources

- [ ] Domain name for the app and the alert addresses (needed before step 1 of setup)
- [ ] Phase 1 hosting: Lightsail Mumbai (recommended) or a home server with Cloudflare Tunnel
- [ ] iPhone app in Phase 1 (adds the US$99 Apple fee) or Android and web only
- [ ] GitHub organisation or personal account to host the repo and CI
- [ ] Phase 2: Fargate with Multi-AZ RDS (about US$500 infrastructure) or the cheaper EC2 option (about US$250)
- [ ] Phase 2 pricing for the Free and Pro plans, so plan limits can cap AI cost per user

Prices were checked on 15 Oct 2026 and change often. Figures marked approximate, including the Fargate and some Mumbai rates, should be confirmed in the AWS Pricing Calculator before committing.

**Sources**

- [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing) (Haiku 5.5, Sonnet 5.5, Batch API, prompt caching)
- [Amazon SES pricing](https://aws.amazon.com/ses/pricing/) (receiving and sending)
- [Amazon SES endpoints](https://docs.aws.amazon.com/general/latest/gr/ses.html) (email receiving available in Mumbai, ap-south-1)
- [Cloudflare Email Service pricing](https://developers.cloudflare.com/email-service/platform/pricing/) (Email Routing free on all plans)
- [AWS Lightsail pricing summary](https://onedollarvps.com/pricing/aws-lightsail-pricing) (bundle prices; Mumbai transfer halved)
- [db.t4g.medium RDS pricing](https://www.bytebase.com/dbcost/rds/instance/db.t4g.medium.md) (US$61 a month on demand in Mumbai)
- [Voyage AI pricing](https://docs.voyageai.com/pricing) (`voyage-4-lite` US$0.02 per million tokens, 200 million free)
- [Claude Code setup](https://code.claude.com/docs/en/setup) (install commands and requirements)
