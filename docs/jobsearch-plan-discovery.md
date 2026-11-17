# BrewMyJob Job Search Service — design and plan

Version 1.1 · 13 November 2026 · Status: agreed design, not built yet

This document is self-contained: it describes the product, what exists today, the decisions taken, and the
design of a separate **Job Search Service** that finds jobs for BrewMyJob. It replaces the earlier
"plan-discovery" notes and reviews `docs/Job_Discovery_and_Aggregation_API_Technical_Design.docx` (a design
the product owner obtained from ChatGPT on 2026-11-13).

---

## 1. Context

**BrewMyJob** (repository name FitFirst) helps senior technology leaders in India find the few jobs worth
applying to. Today:

- Users **forward the job-alert emails** they already receive (LinkedIn, Naukri, and job lists from an AI
  assistant such as ChatGPT) to a personal BrewMyJob address. Each email is split into jobs.
- BrewMyJob also reads **company career feeds** (Greenhouse, Lever, Ashby, SmartRecruiters) for companies a
  user follows, and has an **Adzuna** job-API integration waiting for its key.
- Every job goes into a **shared job catalog** (one record per real job, linked to every source that listed it,
  duplicates detected), then is matched to each user, **scored against each of their resumes** (each resume has
  its own "Skill Match profile"), and shown as Top matches with an Apply kit, warm paths and alerts.
- **The user always applies themselves.** BrewMyJob never applies, never logs in to job portals, never stores
  portal or email passwords.

Stack: Python 3.12, FastAPI, SQLAlchemy 2 (async), PostgreSQL with row-level security for private data,
Procrastinate (Postgres-backed job queue) for background work, Next.js web app, Docker Compose.

**Why this service:** the product owner's ChatGPT task finds many relevant public jobs on employer career sites
every day. BrewMyJob should find them itself, reliably, with history and duplicate handling, and as a
**separate microservice** that can scale and be deployed independently of the main app (decision 7).

---

## 2. Rules the service must follow (non-negotiable)

1. **No automation on job portals.** LinkedIn, Naukri, Foundit, Indeed and similar portals are never scraped,
   crawled, logged in to or automated (no Playwright, no undocumented portal endpoints).
2. **Portal jobs only through allowed channels** (decision 1): email alerts the user forwards (main app), or a
   Google or free job API that returns them (Adzuna, Jooble, Careerjet…). From an API, only the fields the API
   returns are used (title, company, place, snippet, link); the portal page itself is never fetched. The same job
   is then looked for on the employer's own site, so Apply goes there when possible.
3. **Employer career sites are the main source.** Their public job boards and public career-site listings are
   read politely: identified user agent, rate limits per host, few pages, details only for jobs not seen before,
   robots rules respected.
4. **No user data in the service.** It never receives user ids, names, emails, resumes, scores or answers. It
   only receives aggregated demand (locations, kinds of role) and employer lists (section 6).
5. **AI calls** go through an LLM gateway with a versioned prompt, validated (Pydantic) output, a logged row per
   call, a daily budget, and a rule-based fallback where one makes sense.
6. **Nothing is invented.** A lead found by AI search never becomes a job by itself; a job exists only once a
   connector has read it from the employer's site or an allowed API.

---

## 3. Decisions (product owner, 2026-11-13)

| # | Decision |
|---|---|
| 1 | LinkedIn, Naukri and Foundit stay **email-alerts only**, unless a listing of theirs comes from a Google API or a free job API (then API fields only; rule 2). |
| 2 | Google search APIs are **not a free route**: the Custom Search JSON API closed to new customers in January 2026 and ends for everyone on 1 January 2027; its successor (Vertex AI Search, being renamed Agent Search) searches at most 50 listed sites and is paid beyond a trial. *(From secondary sources; verify on Google's pages before relying on it.)* |
| 3 | Free job APIs next to Adzuna: **Jooble** (free key on request) and **Careerjet** (free partner key with an affiliate id). The product owner applies for the keys. |
| 4 | **Paid job data** (licensed feeds, including licensed LinkedIn data): next phase, **after seeing real users**. |
| 5 | **Build a Workday connector.** Workday career sites list jobs through the public search their own page uses (no login, not officially documented): used politely (rule 3). |
| 6 | **Finding employers: Claude web search, by the users' own job locations** (not Bengaluru only). **Job location becomes required at sign-up.** |
| 7 | **The job search is a separate microservice, including today's Job sources** (company feeds, Adzuna, following companies). |
| 8 | (2026-11-14) **Find on Google, in the user's own browser** ("route 1"): the Jobs page offers ready-made Google searches (`site:linkedin.com/jobs/view`, `site:naukri.com/job-listings`, `site:foundit.in/job`) from the user's target roles and job locations; the user opens them and adds the jobs they like by link, title, company, place and, optionally, the pasted description. The link is read only for the portal's job id; BrewMyJob never opens the page or Google's results. Built in the main app (`jobs/found.py`, `/jobs/find`). |
| 9 | (2026-11-14) **Paid search APIs come later, once there is revenue** (backlog): a search API (Brave, SerpAPI, Tavily or Exa) run by the service on a schedule for the same searches, its fields only (title, link, snippet), never the portal page; check the provider's terms on storing results first. Reading Google's result pages from a server is not allowed (Google's terms) and there is no free Google search API (Custom Search JSON API closed to new customers; it ends on 1 January 2027). |
| 10 | (2026-11-15) **Google Alerts as a free, automatic source, read from their RSS feeds** (the design document `docs/Google_Alerts_Gmail_Job_Discovery_Agent_Technical_Design.docx`, adapted). The user's only work is creating the alerts: Job sources suggests one alert per target role and place (LinkedIn, Naukri and Foundit job pages in one query), opens Google Alerts with the query filled in, and the user picks *Deliver to: RSS feed* and pastes the feed link back. BrewMyJob reads each feed three times a day (08:00, 14:00, 20:00 IST) and as soon as it is added. **Not the Gmail API** of the design document: `gmail.readonly` is a restricted scope (Google verification and a yearly security assessment; refresh tokens expire after 7 days until then), it would give us every email in the inbox, and each user would have to connect Gmail. **Not email forwarding** either: each user would have to add a Gmail filter. Only the feed's fields are used (title, link, snippet). The link is Google's redirect; its target is read for the portal's job id as in Find on Google, and the portal page is never opened. Links to other sites are counted and skipped for now. Jobs are unverified (like a job added by hand) and scored from title and snippet (capped below Top until the description is pasted). Feed links are personal, so they live in the main app (`alert_feeds`, RLS), not in the Job Search Service. Built in `backend/app/modules/alerts`. Risks: Google may drop RSS delivery (fallback: email forwarding and an alert-email parser); Google indexes few LinkedIn job pages, so each feed shows what it brings. |

---

## 4. What the data says (the 83 jobs ChatGPT sent so far, 2026-11-13)

| Where the job's link points | Jobs | Readable by BrewMyJob today |
|---|---|---|
| The company's own careers site | 33 | no → careers-page reader (step 2) |
| A LinkedIn job page | 20 | no, by rule; usually also on the employer's site |
| Workday | 15 | no → Workday connector (step 1) |
| Greenhouse, Ashby, SmartRecruiters | 6 | yes (company feeds) |
| Oracle, SuccessFactors, iCIMS, Eightfold | 8 | no → step 2 |
| no link | 1 | — |

---

## 5. Architecture

```
                         ┌───────────────────────── Job Search Service (new microservice) ─────────────────────────┐
  Main app ──demand────▶ │ ① Demand: search areas (location × role family), followed employers                    │
  (aggregated, no users) │        │                                                                                │
                         │        ▼                                                                                │
                         │ ② Discovery (daily): Claude + web search, job portals blocked → LEADS                   │
                         │        │   (company, title, place, employer job/careers URL)                            │
                         │        ▼                                                                                │
                         │ ③ Resolver: detect the employer's hiring system from the URL → EMPLOYER REGISTRY        │
                         │        │                                                                                │
                         │        ▼                                                                                │
                         │ ④ Connectors (every 3 h, each isolated): Workday · Greenhouse · Lever · Ashby ·          │
                         │        │   SmartRecruiters · careers pages (schema.org JobPosting) · Oracle ·            │
                         │        │   SuccessFactors · job APIs (Adzuna, Jooble, Careerjet)                         │
                         │        ▼                                                                                │
                         │ ⑤ Listings store: normalise → dedupe within the service → versions + events             │
                         │        NEW · UPDATED · REPOSTED · CLOSED  (closed when it leaves the employer's feed)    │
                         │        │                                                                                │
                         │        ▼                                                                                │
                         │ ⑥ Event feed API (cursor) ─────────────────────────────────────────────────────────────┼──▶ Main app
                         └─────────────────────────────────────────────────────────────────────────────────────────┘    pulls events
                                                                                                                         │
  Main app (unchanged role):  email alerts ──▶ shared job catalog ◀── events from the service                            │
                              (dedupe across email and service jobs) ──▶ link to users who fit ──▶ score per resume     ◀┘
                              ──▶ Top matches, Apply kit, warm paths, bell / WhatsApp alerts
```

**Responsibilities**

| Job Search Service owns | Main app keeps |
|---|---|
| Finding employers (Claude web search), the employer registry and each employer's hiring system | Users, accounts, privacy (row-level security) |
| All connectors: company feeds (incl. today's four), Workday, careers pages, Oracle, SuccessFactors, job APIs | Email alerts (they are addressed to one user) |
| Normalising listings, history, NEW / UPDATED / REPOSTED / CLOSED events | The shared job catalog: the one place where email jobs and service jobs are deduplicated |
| Schedules, rate limits, connector health, run history, its own LLM calls and budget | Which jobs reach which user, scoring, Top matches, alerts, applications |
| An internal API (section 7) | The Job sources page (it calls the service API) and each user's followed companies |

**Why pull, not push:** the main app pulls events with a cursor. The service never needs to know the app's
address or retry deliveries; the app can catch up after downtime; a second consumer (another product, analytics)
can read the same feed later.

---

## 6. What crosses the boundary (privacy)

The main app sends the service only:

- **Search areas:** distinct (location, role family) pairs across all active users, e.g. `("Bengaluru",
  "engineering leadership")`, `("Remote India", "product leadership")`. No user ids, no counts per user.
- **Employers to watch:** careers URLs or hiring-system boards that users chose to follow. The service returns an
  employer id; *which* user follows it stays in the main app.
- **"Check now" requests** for an employer id.

The service sends back only public job data (listings and events), employer details, and health information.

---

## 7. Internal API (service, version 1)

Base: `http://jobsearch:8100/v1` (internal network only, not exposed to the internet). Authentication: a
service-to-service bearer token (rotated via environment), later mTLS. Errors use the same envelope as the main
app: `{"error": {"code", "message", "details", "request_id"}}`.

| Method and path | Purpose |
|---|---|
| `PUT /demand/search-areas` | Replace the list of search areas `[{location, role_family, titles[]}]` (the app sends it after users change their locations or profiles, and daily) |
| `POST /employers` | Register an employer by careers URL or name: `{url?, name?}` → `{employer_id, name, system, board, status}` (resolves the hiring system; 202 if resolution runs in the background) |
| `GET /employers/{id}` | Employer details, hiring system, last check, jobs found, last error |
| `POST /employers/{id}/check` | Check one employer now (rate-limited) |
| `GET /employers/suggested?location=` | Employers discovered for a location (to suggest following) |
| `GET /events?after={cursor}&limit=500` | The event feed: `[{event_id (cursor), type: NEW|UPDATED|REPOSTED|CLOSED, occurred_at, listing}]`, oldest first |
| `GET /listings/{id}` | One listing with its sources and version history |
| `GET /sources` | Connectors and their health (last run, success rate, errors) |
| `GET /runs?kind=discovery|connector&since=` | Run history with counts (found, new, updated, reposted, closed, failed) |
| `POST /discovery/run` | Run discovery now for given search areas (admin only; budget still applies) |
| `GET /healthz` | Liveness |

**Listing fields** (the normalised job): `listing_id`, `employer_id`, `company`, `title`, `location`,
`work_model` (Remote / Hybrid / On-site / unknown), `experience` (as stated), `salary` (as stated), `description`
(plain text), `skills` (as listed), `posted_at` (the source's posting date, if any), `first_seen_at`,
`last_seen_at`, `closed_at`, `status` (active / closed / unknown), `sources[]` (`{source, source_job_id, url,
apply_url}`), `requisition_id`, `content_hash`. Unknown values stay empty; nothing is guessed.

---

## 8. Service data model (its own database)

| Table | Holds |
|---|---|
| `employers` | Name, aliases, website, careers URL, country |
| `employer_boards` | Employer × hiring system × board id/URL, last check, last error, jobs total / in scope |
| `search_areas` | Location, role family, titles; last discovery run |
| `leads` | What discovery found: company, title, place, URL, found_at, resolved employer, outcome |
| `listings` | The normalised jobs (fields in section 7) |
| `listing_sources` | Each source's id and URLs for a listing |
| `listing_versions` | Earlier versions when a listing materially changes |
| `events` | NEW / UPDATED / REPOSTED / CLOSED, with a sequential id used as the feed cursor |
| `connector_runs`, `discovery_runs` | When, what, counts, errors, duration |
| `llm_calls` | Every AI call: prompt version, model, tokens, cost, outcome |
| `api_quota` | Calls made per external API per day (Adzuna, Jooble, Careerjet) |

No table holds user data, so the service needs no row-level security.

**Change and repost detection:** a fingerprint of the normalised content (title, employer, description,
location, requisition id). Same requisition or URL with a changed fingerprint → UPDATED (new version kept); a
listing that was closed and comes back, or the same requisition reposted with a new id → REPOSTED; missing from
its employer's feed on two checks in a row → CLOSED.

---

## 9. Connectors

Each connector has the same interface: input = an employer board or a search area; output = listings plus a
run record (found, new, updated, errors). Each runs on its own; one failing never stops the others (retries
with backoff, a circuit breaker per host).

| Connector | How it reads | Notes |
|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters | Their public job-board APIs (built today in the main app; moves to the service) | No key, no login |
| **Workday** | The public career-site search the page itself uses, per employer, filtered to the search areas' locations; details only for unseen jobs | Not officially documented (decision 5); slow and polite |
| Careers pages | schema.org `JobPosting` data on employer job pages (the data Google Jobs uses) | Works across many custom sites |
| Oracle Recruiting Cloud, SuccessFactors | Their public career-site listings | Step 2 |
| iCIMS, Eightfold | If they offer usable public listings | Step 2, to check |
| Adzuna, Jooble, Careerjet | Their job-search APIs, per search area | Keys needed; portal listings: API fields only (rule 2) |

---

## 10. Discovery (Claude web search)

- **Input:** each search area (location × role family, with example titles).
- **How:** Claude (Anthropic API) with its web search tool, through the service's LLM gateway, with job portals
  as blocked domains and a versioned prompt asking for recent openings on employer sites.
- **Output (validated):** leads `{company, title, location, url, posted_hint}`. The resolver finds the employer's
  hiring system from the URL and registers the employer; connectors then read the real jobs.
- **Cost control:** one run per search area per day, shared by every user who wants that area; a daily budget;
  a new search area gets one run straight away.
- **Needs:** the Anthropic API key. Until then, discovery is built and tested with recorded responses but switched
  off.

---

## 11. Schedules

Searches never run per user and never when someone searches in the app (the app only queries its own catalog).

| What | How often | Run for |
|---|---|---|
| Discovery (Claude) | once a day | each search area, once, within the daily budget |
| Employer boards (all hiring systems) | every 3 hours | each employer once, however many users follow it |
| Job APIs (Adzuna, Jooble, Careerjet) | every 3–6 hours | each search area, within each API's daily limits |
| Main app pulls the event feed | every 5 minutes | all new events since its cursor |
| "Check now" | on request | one employer, a few times a day at most |

After the main app pulls events, only new or changed jobs are linked to the users they fit and scored.

---

## 12. Deployment and operations

- **Code:** in the same repository, `services/jobsearch/` (its own `pyproject`, tests, Dockerfile, migrations).
  Same stack as the main app (FastAPI, SQLAlchemy, Procrastinate, PostgreSQL) to keep it boring.
- **Containers:** `jobsearch-api` and `jobsearch-worker` in Docker Compose, on the internal network only.
- **Database:** its own database (`jobsearch`) and roles. Same PostgreSQL server at first; its own server when
  load needs it.
- **Secrets:** API keys (Anthropic, Adzuna, Jooble, Careerjet) and the service token in environment variables
  now; a secrets manager at release (milestone 8).
- **Observability:** structured logs with request and run ids; `/sources` and `/runs` for health; the main app's
  Job sources page and admin page show them. Metrics to watch: jobs found per source and run, new / updated /
  reposted / closed per run, duplicate and false-merge rate, missing-field rate, connector failure rate, AI spend.
- **Scaling:** more workers per queue; connectors and discovery on separate queues; the event feed lets any number
  of consumers read independently.

---

## 13. Migration from today's Job sources (main app)

| Today (main app) | Becomes |
|---|---|
| `company_feeds` (shared boards) | `employers` + `employer_boards` in the service (ids mapped once) |
| `watched_companies` (private, per user) | Stays in the main app, pointing to the service's `employer_id` |
| `source_runs` (per user) | Service `connector_runs` (per employer); the app keeps a per-user summary of what reached the user |
| `sources/feeds.py`, `discover.py`, `adzuna.py`, `tasks.py` | Move to the service |
| `sources/relevance.py` (which jobs reach a user) | Stays in the main app |
| Job sources page and its endpoints (`/sources`, `/sources/lookup`, `/sources/companies`, `/sources/check`) | Same page and endpoints in the app; they call the service API |

The switch happens behind the same page, with no change for users: the service starts reading the same
employers, the app starts pulling events, then the old tasks are switched off.

---

## 14. Build steps and integrations (including earlier milestones)

| Step | What | Status | Waits for the product owner |
|---|---|---|---|
| Built | LinkedIn and Naukri alert emails, Naukri recruiter invites, LinkedIn saved jobs, AI-assistant lists (main app) | working | — |
| Built | Greenhouse, Lever, Ashby, SmartRecruiters company feeds (main app; move in step 0) | working | — |
| Built | LinkedIn connections import; browser extension filling Greenhouse, Lever, Ashby, SmartRecruiters, Workday forms | working | a check on a real Workday page |
| Built | Adzuna (main app; moves in step 0) | built | the Adzuna key |
| Built | Cloudflare email forwarding | built | the one-time Cloudflare setup and a Gmail test |
| Built | WhatsApp alerts | built | the Meta setup (number, templates, token) |
| **0** | Service skeleton (API, worker, database, token auth, event feed); move today's Job sources into it; the app pulls events | **built** 2026-11-14 | — |
| **1** | Workday connector; job locations required at sign-up (and asked once of existing users); version and event tracking; 3-hour schedule; health on the Job sources page | **built** 2026-11-14 | a live Workday read (sites were in maintenance) |
| **2** | Careers-page reader (`JobPosting`); Oracle Recruiting Cloud; SuccessFactors; iCIMS and Eightfold if usable | **built** 2026-11-14 (SuccessFactors and iCIMS through the careers-page reader; see `docs/plan-jobsearch-build.md`) | a live SuccessFactors read (sites were in maintenance) |
| **3** | Discovery: Claude web search → resolver → employer registry | built and tested, switched off | the Anthropic key |
| **3** | Jooble, Careerjet | ~1 day each | their keys |
| **4** | More alert emails in the main app: iimjobs, hirist, Foundit, Indeed, Naukri "Neo early alert" | per site | 2–3 sample emails each |
| Built | Find on Google (decision 8): searches for LinkedIn, Naukri and Foundit the user runs in their browser; Add a job you found | **built** 2026-11-14 | — |
| Built | Google Alerts by RSS (decision 10): suggested alerts on Job sources, feeds read three times a day, jobs scored; Job sources shows what the last run pulled and how many fit | **built** 2026-11-15 | a real feed link to confirm Google's format |
| Backlog | Paid search API for LinkedIn, Naukri and Foundit listings on a schedule (decision 9) | after revenue | provider choice, its terms on storing results, budget |
| Later | Google and Microsoft sign-in | planned | the domain |
| Later | Razorpay billing (milestone 11) | planned | business account, plans and prices |
| Later | Email digest, Teams alerts, phone app with push (milestone 6b) | planned | — |
| Later | Analytics and cookie consent on the home page | planned | the provider choice |
| Later | Paid job data | after real users | budget |
| Later | US market: job sites and APIs, Paddle or Lemon Squeezy (milestone 12) | later | — |

Rough effort: step 0 about 4–6 days, step 1 about 5–7 days, step 2 about 3–4 days, step 3 about 4–6 days.

---

## 15. Open questions

1. **Role families for search areas:** derive them from users' Skill Match profiles (target roles) automatically,
   or a fixed list (engineering, product, AI, architecture, delivery, transformation leadership) that profiles
   map to? Proposed: a fixed list, mapped automatically.
2. **Model for discovery:** a smaller, cheaper Claude model for searching versus a larger one for better leads.
   Proposed: start with the smaller one and compare on a week of searches.
3. **Leads not confirmed on an employer site** (e.g. only a LinkedIn link found): drop them, or show them as
   "unconfirmed" with no Apply link? Proposed: drop, and count them in run history.
4. **Countries:** India first; the design allows any country once users choose locations elsewhere
   (milestone 12 for the US).
