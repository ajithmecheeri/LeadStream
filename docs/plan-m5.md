# Milestone 5 plan: applications tracker and job-list feedback (built 2026-11-02)

Goal: track every job from "found" to "applied" and beyond, keep the active list to jobs still worth acting
on, and make clear what the user has to do and why a match isn't 100%. The user always applies themselves:
FitFirst records that they did, it never applies or contacts anyone.

## Feedback (2026-11-02)

| # | Request | Proposal |
|---|---|---|
| 1 | Mark a job as **Applied**, from the job list and the job page, like Ignore; applied jobs go to their own queue | An Applied button next to Ignore on each job card and on the job page. Applied jobs leave Top matches / Other jobs and appear in an **Applied** tab with the date applied. Undo works like Ignore. The tracker statuses (see below) start from here |
| 2 | Show who posted the job (profile or email) so the user can contact them | Alert emails rarely name a person: LinkedIn alerts never do; Naukri recruiter invites give a recruiter name (often generic) and never an email. FitFirst doesn't open job pages (no scraping). So: show the recruiter name when the email has one, and a **Contact** box on the job page where the user pastes a name, LinkedIn profile link or email they found. Saved only; FitFirst never messages anyone. Milestone 7 reuses these contacts |
| 3 | Anything the user has to do is highlighted in **amber** (e.g. job description missing) | One amber "to do" style for every action item: description missing, screening questions unanswered, profile facts missing (notice period, CTC), a cover letter the job requires, a follow-up that is due. Each has a button that fixes it. Job cards show a small amber "2 to do" marker |
| 4 | Say clearly which missing skills keep the match below 100% | On the job page: **Skills you have / Skills missing** from the job's skill list, and the **points lost per factor** (e.g. "Skills −8 · Location −3 · Experience −2"), since skills aren't always the cause. Each missing skill has "I have this skill", which adds it to the profile and re-scores (only for skills the user really has: packs may claim only what the profile supports) |
| 5 | Expired jobs: show that a job has probably expired, or let the user mark it, so it leaves the active queue | A **Mark as expired** button (moves the job to an **Expired** tab). Alerts don't say when a job closes, so age is the signal: an amber **"May have expired"** warning after N days, and the job moves to Expired by itself after M days. Days are counted from the last alert that showed the job (see decisions). N and M are set by the admin |

Resulting queues on the Jobs page: **Top matches · Other jobs · Not scored yet · Applied · Expired · Ignored**.

## Decisions

- **Expiry days are set by the admin (2026-11-02).** The user wants both the warning and the automatic move,
  with the number of days configurable by the super admin. Proposed defaults: warning after 30 days, moved
  to Expired after 45. The values live in a shared `app_settings` table (no `user_id`, readable by every
  user, writable only with the existing `admin` role through `require_admin`), changed on a small admin
  settings page without a redeploy (LLD: "application settings in the database"). A job the user has
  applied to never expires automatically. An automatically expired job can be moved back to active.
- **The expiry clock (2026-11-02, built).** Days count from the last sign the job is open: the latest alert
  that showed it (`last_seen_at`) or the user's "It's still open" (`confirmed_open_at`), whichever is later.
  A job that keeps appearing in alerts is evidently still open, so counting from the first alert would expire
  live jobs. A new alert also brings back a job that expired automatically; one the user marked Expired stays.
  The daily task runs at 02:30 (worker time zone, UTC in Docker).

- **All five feedback points are in milestone 5 (2026-11-02)**, together with the original scope: tracker
  statuses after Applied, events, follow-up dates and date/month/year filters.
- **Super admin (2026-11-02).** "Super admin" is the existing `admin` role (`users.role`, checked by
  `require_admin`). An account becomes super admin with `make admin EMAIL=…`, a CLI command run as the
  database; there is no way to become admin from the app. Every settings change is written to
  `audit_events`. The role travels in the access token, so the account signs out and in again (or waits for
  the next refresh) to see the admin page.
- **Contacts are `job_contacts` (2026-11-02, built)**, one row per person per job. Milestone 7's connections
  import can link to them rather than share a table, since an imported connection isn't tied to a job.
- **Why not 100% is stored at scoring time (2026-11-02, built)** in `job_matches.explain`: points lost per
  factor, "similarity" (resume wording, when Voyage is on) and "clash" (the cap for another line of work),
  adding up to 100 − score, plus the job's listed skills the best resume has and misses. LinkedIn alerts list
  no skills, so the skills part shows only for Naukri jobs until a description with skills is pasted.
- **To-dos are worked out on read** (like readiness): Top-match blockers, "may have expired", and a follow-up
  that's due. Readiness blockers count only while the job is active (not after Applied).

## Modules

| # | Module | Status |
|---|---|---|
| 1 | Super admin and app settings: `make admin EMAIL=…`; shared `app_settings` table (key, value, updated_by, updated_at; no RLS; the app role can't insert or delete rows); `GET /app-settings` (any user, read), `GET /admin/settings`, `PUT /admin/settings` (admin); keys `job_expiry_warn_days` (30) and `job_expiry_auto_days` (45), auto ≥ warn, 1–365; web `/admin/settings`, linked in the nav only for admins | **done** (2026-11-02) |
| 2 | Applications: `applications` table (private, RLS) created when a job is marked Applied: status **Applied → Interviewing → Offer → Accepted**, or **Rejected / Withdrawn / No response** at any point; applied date, the resume and cover letter used, notes, follow-up date, `version`. `application_events` (private) logs every status change and note with its date. Undo Applied removes the application if nothing else was recorded (else 409 `application_has_history`). API: `GET /applications` (status, from/to, due), `GET/PATCH /applications/{id}`, `POST /applications/{id}/notes` | **done** (2026-11-02) |
| 3 | Job queues: Applied and Expired join New/Seen/Ignored. `user_jobs` gains `expired_at` and `expired_by` (user / auto). Mark as expired and undo; `POST /jobs/{id}/still-open`; a daily worker task (`jobs.expire_old`) moves jobs with no sign of life for `job_expiry_auto_days` to Expired, never applied ones; "May have expired" flag after `job_expiry_warn_days`. Jobs tabs: Top matches · Other jobs · Not scored yet · Applied · Expired · Ignored, with counts. Applied / Ignore / Expired buttons on each job card and on the job page | **done** (2026-11-02) |
| 4 | Contacts on a job: the recruiter name from the email when there is one; a Contact box (name, role, LinkedIn profile URL, email, note) per job, private, several per job. Saved only; FitFirst never sends anything. API `GET/POST /jobs/{id}/contacts`, `PUT/DELETE /jobs/{id}/contacts/{contact_id}`; LinkedIn links only for the profile URL | **done** (2026-11-02) |
| 5 | Amber "to do": one style and one list per job of everything the user must do (description missing, unanswered screening questions, missing profile facts, required cover letter, follow-up due, may have expired), each with the button that fixes it; "N to do" marker on job cards; built on the readiness blockers (`todos` on the job detail, `todo` count on each job) | **done** (2026-11-02) |
| 6 | Why not 100%: skills matched / missing per job (from the job's skill list against the suggested resume and profile skills); points lost per factor from the weights; "I have this skill" (`POST /jobs/{id}/skills`) adds it to the profile skills, re-scores this job at once and the rest in the background | **done** (2026-11-02) |
| 7 | Applications page `/applications`: list by status with counts, filters by status and by date / month / year applied, follow-ups due first; application detail with the status timeline, notes and follow-up date; dashboard shows follow-ups due | **done** (2026-11-02) |
| 8 | Tests: happy and error path for every endpoint, isolation for the new private tables, admin-only checks (403 for a normal user), expiry task with frozen dates; web unit tests; e2e: mark applied → Applied tab → move to Interviewing, note, follow-up due on the dashboard and as a to-do, mark expired and restore, save a contact. The admin page isn't in the e2e (making an admin needs the command line); the backend tests cover it | **done** (2026-11-02): 219 backend tests, 24 web unit tests, 4 e2e journeys |
