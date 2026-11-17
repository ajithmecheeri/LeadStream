# Job Search Service: build of steps 0 and 1

Started 2026-11-14 at the user's request ("Please start the Step 0 and Step 1"). The design is
`docs/jobsearch-plan-discovery.md`; this file records how steps 0 and 1 were built and the decisions taken on the
way, for the user to review. Backup taken first: `~/code/FitFirst-backups/before-jobsearch-2026-11-14/`
(`code.tgz` and `fitfirst.dump`).

## Decisions taken while building (to review)

1. **Role families (open question 1): the app's own job families, mapped automatically.** A search area's role
   family is the family of each target role (`taxonomy.title_families`: technology, product, data…), so no new
   list to maintain. A role with no family is sent as `other`.
2. **Countries (open question 4): India only for now.** Every connector keeps India jobs (as today's feeds do);
   the service has a `COUNTRY` setting so other countries can follow (milestone 12).
3. **Event ordering.** Every transaction that writes events takes one advisory lock, so event ids are committed
   in order and the app's cursor never skips an event that commits late.
4. **Workday reads India through the board's own location filter** (the "India" value of its country facet).
   When a board has no such filter, the service pages through the whole board (at most 2,000 postings) and keeps
   the India ones. Details (the description) are fetched only for postings not seen before, at most 150 a run
   per board, three at a time; the rest follow on the next run. A posting is announced (NEW) once its details
   are in, so the app never scores a Workday job on its title alone.
5. **Workday boards are added by link only** (a `…myworkdayjobs.com/…` or `…myworkdaysite.com/recruiting/…`
   careers link). Guessing a Workday board from a company name would mean probing many hosts; not done.
6. **Closing.** A listing missing from its board on two complete checks in a row is CLOSED. The app marks the
   catalog job (`details.closed_on_site`) and leaves users' rows alone: what to do with closed jobs in the lists
   (an Expired-style queue) is a later decision.
7. **"Check now" checks followed companies only.** Job APIs (Adzuna) run on the service's shared schedule
   (every 6 hours, within the daily quota) for the search areas, not per user.
8. **Today's company feeds keep their ids.** The app exports each `company_feeds` row to the service with the
   same id (`POST /v1/employers` with `id`), so `watched_companies.employer_id` needs no remapping. The export
   runs automatically before the app's first pull; `company_feeds` is then emptied (the table is dropped in a
   later migration, once the switch is confirmed).
9. **Per-user run summaries** (`source_runs`) are now written when the app pulls events: for each user and
   employer, how many listings arrived, how many reached the user, how many the relevance check left out.
10. **Job locations at sign-up** go in `candidate_profiles.job_locations` (1 to 10 places). New match profiles
    start with them. Existing users without any are asked once on the Dashboard.
11. **Not built in steps 0–1** (in the design, later steps): discovery and leads (step 3, needs the Anthropic
    key), `llm_calls`, Jooble and Careerjet, careers-page reader, Oracle, SuccessFactors.

## What was built

**The service (`services/jobsearch/`)**: its own package, Dockerfile, Alembic migrations, tests and database.

| Part | Where |
|---|---|
| Settings (prefix `JOBSEARCH_`; reads the app's `ADZUNA_*` keys too) | `jobsearch/config.py` |
| Tables: employers, employer_boards, search_areas, listings, listing_sources, listing_versions, events, connector_runs, api_quota (+ Procrastinate) | `jobsearch/models.py`, `migrations/versions/0001_initial.py` |
| Connectors: Greenhouse, Lever, Ashby, SmartRecruiters (moved from the app), **Workday** (new), Adzuna (moved; per search area, daily quota) | `jobsearch/connectors/` |
| Finding a board from a link or name; suggested employers (NVIDIA on Workday added) | `jobsearch/resolver.py` |
| Listings store: NEW / UPDATED / REPOSTED / CLOSED, versions, Workday's pending postings | `jobsearch/store.py` |
| Checking boards and job APIs, registering employers | `jobsearch/service.py` |
| Internal API v1 (token): employers, lookup, suggested, check, demand, events, listings, sources, runs, check-all | `jobsearch/api.py` |
| Schedules: every board every 3 hours (one task each), job APIs every 6 hours | `jobsearch/worker.py` |
| Tests: 58 (connectors with saved samples incl. real Workday responses, store rules, API) | `tests/` |

**The app (`backend/`)**

- `app/modules/sources/`: `client.py` (the service's API), `sync.py` (pull events → catalog → users the jobs
  fit → scoring; demand; check now; export of the old feeds), `tasks.py` (pull every 5 minutes; check on
  request), `router.py` (same endpoints as before, through the service; works with the service down).
  `feeds.py`, `discover.py`, `adzuna.py` and `service.py` moved to the service.
- Migration `0025_jobsearch_service.py`: `employer_id` in `watched_companies` / `source_runs`,
  `jobsearch_sync`, `workday` source, `candidate_profiles.job_locations`.
- Job locations: required at sign-up (`SignupIn.job_locations`), `PUT /candidate/job-locations` (the one-time
  question), on `PUT /candidate`, default places for new match profiles.
- Tests: `test_sources.py` rewritten against a fake service (22 tests), `test_job_locations.py`,
  `test_source_relevance.py` (the relevance rules that stay in the app).

**Web**: sign-up asks "Where do you want to work?"; the Dashboard asks older accounts once; Profile tab edits it;
Job sources page: Workday by careers link, "every 3 hours" schedule, a notice when the service can't be reached,
and a "Hiring systems" health list. e2e: every sign-up fills the new field; the sources test checks the Workday
suggestion and the new schedule text.

**Infra**: `infra/postgres/init/02-jobsearch.sh` (roles and databases, safe to re-run), Compose services
`jobsearch-db` (one-shot), `jobsearch-api` (:8100) and `jobsearch-worker`; Makefile `dev-jobsearch-api`,
`dev-jobsearch-worker`, and the service's tests in `make test` / `make test-local` / `make lint`.

## Step 2: careers pages, Oracle, SuccessFactors, iCIMS, Eightfold (started 2026-11-14)

The user committed steps 0–1 and asked for step 2. Each system's public listings were checked on live sites first
(2026-11-14):

| System | Live check | How it is read |
|---|---|---|
| Oracle Recruiting Cloud | Works (JPMorgan Chase, `jpmc.fa.oraclecloud.com`, site CX_1001: 288 India jobs) | The career site's own search (`hcmRestApi/.../recruitingCEJobRequisitions`), India through its location facet; details (`recruitingCEJobRequisitionDetails`) for new jobs only |
| Eightfold | Works (Netflix, `explore.jobs.netflix.net`; robots.txt allows `/api/apply`) | `/api/apply/v2/jobs?domain=…&location=India`, details per new job |
| Careers pages (any company site) | Works (Arm on Radancy; SAP's own site) | robots.txt, then the sitemap's job pages, then the schema.org `JobPosting` on each page (JSON-LD, or microdata) |
| SuccessFactors (Career Site Builder) | Not checked: Cargill's and Capgemini's sites showed "Site Maintenance" (weekend) | Through the careers-page reader (sitemap + job pages with microdata) |
| iCIMS | No live India tenant found to check | Through the careers-page reader when its job pages carry `JobPosting`; no dedicated connector |

Decisions (to review):

12. **One generic careers-page reader instead of separate SuccessFactors and iCIMS connectors.** Both publish
    standard job pages; a separate connector is added only if a real site needs one.
13. **The careers-page reader is polite:** it follows robots.txt (never a disallowed path, e.g. search pages),
    reads only sitemaps and job pages, at most 60 new pages a run, two at a time. Pages whose address names an
    Indian city are read first; a page found to be outside India is remembered for 30 days and not read again.
14. **Job portals are refused** as careers pages (LinkedIn, Naukri, Indeed, Foundit, Glassdoor, Monster, Shine,
    iimjobs, hirist, Instahyre, Cutshort, Wellfound…): non-negotiable rule 1.
15. **From Oracle, only the job's own text is kept**: the recruiter's name and email in its details are never
    stored.
16. **A careers page without a sitemap** is read from the links on its page only, and nothing is closed from it
    (it can't be known complete).
17. **Job counts on a careers site** cover only the pages robots.txt lets us read.
18. **Suggested companies** gain the three sites checked live: JPMorgan Chase (Oracle), Netflix (Eightfold), Arm
    (careers site).

What was built in step 2:

| Part | Where |
|---|---|
| Oracle Recruiting Cloud connector | `services/jobsearch/jobsearch/connectors/oracle.py` |
| Eightfold connector (finds the company domain on the careers page when the link lacks it) | `connectors/eightfold.py` |
| Careers-page reader: robots.txt, sitemaps (indexes, gzip), JSON-LD and microdata `JobPosting`, India-first order, out-of-India pages remembered, job portals refused | `connectors/careers.py` |
| Links resolved to Oracle / Eightfold / careers sites; portal links refused with `job_portal` | `resolver.py`, `api.py` |
| Service migration `0002_more_systems.py`: the three systems, `board_pages` | `services/jobsearch/migrations/` |
| App migration `0026_more_job_sources.py`: `oracle`, `eightfold`, `careers_page` in `job_sources` | `backend/migrations/` |
| One list of company-site sources (`COMPANY_SITES`) for the Jobs "company" filter and the duplicates rule (Workday had been missing from both since step 1) | `catalog/parsers/base.py` |
| Web: the new systems' labels, "paste the careers-site link" wording, company names from links | `apps/web/app/(app)/sources/page.tsx`, `lib/jobs.ts` |
| Tests: 22 new service tests on trimmed real responses (Oracle, Eightfold, Arm) and a fake careers site; app tests for portal refusal and the shared list | `services/jobsearch/tests/test_step2_connectors.py`, `test_api.py`, `backend/tests/test_sources.py` |

Live reads on 2026-11-14: JPMorgan Chase (Oracle) 288 India jobs, 150 read in full in 31 s (the rest on the next
run); Netflix (Eightfold) 11 in 4 s; Arm (careers site) 469 job pages, the 60 India ones read first in 23 s.
SuccessFactors and Workday sites were in weekend maintenance; both are read again every 3 hours.

## Find on Google (route 1, 2026-11-14)

The user asked why a LinkedIn-only job (Woolworths Group, recruited through an agency, not on the company's own
site) wasn't found, then chose the free route: Google searches the user runs in their own browser, and adding the
jobs they find by hand. Paid search APIs go to the backlog until there is revenue (discovery plan, decisions 8–9).

| Part | Where |
|---|---|
| Searches: one per target role × job location (at most 8 × 4), a Google query per portal; Bengaluru/Bangalore and Gurugram/Gurgaon searched both ways | `backend/app/modules/jobs/found.py`, `GET /jobs/google-searches` |
| Add a job you found: LinkedIn, Naukri or Foundit job link (job id read from the link only), title, company, place, optional description (kept as the user's own, like a pasted one); unverified, so it never changes a catalog job; the same job added twice, or brought later by an alert, is one job | `POST /jobs/found` |
| `foundit` source | migration `0027_foundit_source.py`, `catalog/parsers/base.py` |
| Web: "Find on Google" on the Jobs page → `/jobs/find` (period: past 24 hours / week / month); a LinkedIn link fills the title and company it spells out; Foundit in the source filter | `apps/web/app/(app)/jobs/find/page.tsx`, `lib/found.ts` |
| Tests | `backend/tests/test_found_jobs.py`, `apps/web/lib/found.test.ts`, `apps/web/e2e/find-on-google.spec.ts` |

## Google Alerts by RSS (2026-11-15)

The user uploaded a design for an agent that reads Google Alerts from Gmail through the Gmail API and asked that, in
the end, users do nothing but configure alerts. Built with the alerts' RSS feeds instead of Gmail (discovery plan,
decision 10). Also asked the same day: a coffee mug before the BrewMyJob name (top left), and Job sources showing what
the last run pulled and how much of it fits the user's profile.

| Part | Where |
|---|---|
| `alert_feeds` (private, RLS): the feed link, the alert's query, last read, last error, what the last read found / added / skipped, the jobs it added (for the Top matches count) | migration `0028_alert_feeds.py`, `app/modules/alerts/models.py` |
| Feed reading: only `https://www.google.com/alerts/feeds/<digits>/<digits>` is fetched (no other host, no redirects elsewhere); Atom parsed with the standard library; each entry's real link taken from Google's `/url?url=` redirect; LinkedIn, Naukri and Foundit job links become jobs by `jobs/found.portal_job`; title and company from Google's title ("Acme hiring VP Engineering in Bengaluru … \| LinkedIn") or else the link; the snippet is kept as a short description | `app/modules/alerts/feed.py` |
| Reading and linking: unverified cards into the catalog, linked to the user, scored; a run line in `source_runs` (source `google_alert`) | `app/modules/alerts/service.py` |
| Schedule: 02:30, 08:30 and 14:30 UTC (08:00, 14:00, 20:00 IST); a feed is read at once when added | `app/modules/alerts/tasks.py` |
| Endpoints: `GET /alerts` (suggested alerts from the user's roles and places, with a Google Alerts link; the feeds and their last read), `POST /alerts` (a feed link), `DELETE /alerts/{id}` | `app/modules/alerts/router.py` |
| Last run on Job sources: each pull of the service's feed is recorded (jobs, new, updated); the page shows what it pulled, how many fit your profile and how many of the new ones are Top matches | `jobsearch_sync` columns (migration 0028), `sources/router.py` |
| Web: Google Alerts section on Job sources; coffee mug in the sidebar brand | `apps/web/app/(app)/sources/page.tsx`, `components/` |

Decisions to review:
- One alert per role and place covering the three portals: `"VP Engineering" Bengaluru (site:linkedin.com/jobs/view OR site:naukri.com/job-listings OR site:foundit.in/job)`, so the user creates fewer alerts. If Google Alerts ignores the OR, split it per portal.
- Jobs from alerts are linked whatever their fit; scoring sorts them into Top matches or Other jobs, since the user chose the query.
- Links to other sites (a company's careers page) are counted and skipped; handing them to the Job Search Service comes later.

## Left for later

- Paid search API for portal listings (backlog, after revenue; discovery plan decision 9).

- Drop `company_feeds` once the switch is confirmed on the real data (a later migration).
- Jobs that close on the employer's site: shown how in the lists (decision 6).
- Workday descriptions are read once; later edits to a Workday posting are seen only through its title or
  requisition (a periodic re-read of a sample could follow).
- Step 2 (careers pages, Oracle, SuccessFactors) and step 3 (discovery, Jooble, Careerjet).
- Speed of the app's pull: the first pull after the switch (1,048 events, 254 accounts, mostly test accounts)
  took about 9 minutes, because each user's audience is read from their resume. Fine now; with many real users,
  keep the audiences cached between pulls.
- The live Workday read (NVIDIA) on 2026-11-14 hit Workday's weekend maintenance (HTTP 521 for everyone); the
  service recorded it and reads the board again every 3 hours. The response format was confirmed on the live site
  earlier that day.

## Every job of the last run, kept or left out (user, 2026-11-16)

"Can I see last run jobs even if not matching my skills?" Jobs the relevance check leaves out (below the user's
level, another field, not one of their locations) were only counted; they never reached the user's list. Now each
run line keeps its jobs and the verdict (`source_runs.jobs`, migration 0030, at most 300 per line;
`relevance.why_not` gives the reason). Job sources → Last run → **See every job from this run** lists them (All /
In your list / Left out), each left-out one with its reason and **Add to my jobs** (`POST
/sources/last-run/jobs/{job_id}`; scored like any other). Runs before 16 Nov have no list.

Feedback the same day, built:

- **Jobs → From sources** (new tab, `?tab=sources`): the same list of the last run's jobs, kept or left out, on
  the Jobs page. The list is one component (`components/PulledJobs.tsx`) used there, on the Last run card and
  per company.
- **A followed company's jobs**: "when I click on 22 jobs, it does not say which are those jobs". The "N jobs"
  badge (it counted the jobs ever added from the company and opened the whole Jobs list) is replaced by **See the
  N jobs** on each company: every open India job at the company (service: `GET /v1/employers/{id}/listings`,
  newest first, no descriptions, at most 500, with the board's last run), each in your list with its score or
  left out with the reason, a **New** mark on the ones the company's last check found (first seen at or after
  that run started), and **Add to my jobs** (`GET /sources/companies/{employer_id}/jobs`, `POST
  …/jobs/{job_id}`). The company line now reads "N open in India · N in your list · N added at the last check".
- **Bug found while checking (decision to review):** jobs a company already had open when the user followed it
  never reached them: the event feed only carries changes, and the pull delivers only what arrives. On the
  user's data, Arm, JPMorgan Chase and others had Director/VP jobs that fit and were not in the list. Now every
  check of a user's companies (following one, Check now) ends with a **catch-up** (`sync.catch_up`): the
  company's open jobs that pass the relevance check and aren't in the list yet are added and scored. Jobs already
  in the list keep their status (ignored stays ignored). The company's check line then says open jobs, added
  and left out; the page adds up a company's lines of one check (5 minutes) for "added". Ran once for every
  account that follows companies on 2026-11-16.

**Last-check jobs in their own section (user, 2026-11-16).** A followed company's job list now shows the jobs its
last check found first, under "Found at the last check (N)" (or "The last check found no new jobs."), and the other
open jobs below under "Other open jobs (N)", with the All / In your list / Left out filters over those. The
"Found in the last check" filter is gone, since that section replaces it (`apps/web/components/PulledJobs.tsx`).
