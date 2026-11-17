# Milestone 4 plan: job detail, packs and sign-up improvements (in progress)

Goal: for a matched job, show what stands between the user and applying (readiness and blockers), and produce
a tailored resume and cover letter as Word and PDF that pass the claim check. The user always applies
themselves. Also: the sign-up changes the user asked for on 2026-11-01.

## Modules

| # | Module | Status |
|---|---|---|
| A | **Sign-up and sign-in** (requested 2026-11-01): "Re-enter password" on Create account (must match, checked in the browser and by the API); a show/hide password button on every password field; **Sign in with Google** and **Sign in with Microsoft** (see below) | **done** (password part, 2026-11-01); Google/Microsoft deferred |
| 1 | Readiness: Ready / Needs input / Manual only per strong or good match, with each blocker (screening question, missing profile fact such as notice period, required cover letter, assessment, partial description) | **done** (2026-11-01) |
| 2 | Answer bank: reusable answers to screening questions, per-profile overrides, flagged when older than 30 days; drafts for new questions | **done** (2026-11-01; per-profile overrides later) |
| 3 | Resume edit suggestions (`resume_rank`, Sonnet): for the suggested resume, the changes that would improve it for this job, each citing the profile fact it draws on; gaps the profile can't support are listed, never added | |
| 4 | Pack: tailored resume and cover letter from the accepted suggestions (`pack_write`, Sonnet), rendered as Word and PDF; claim check maps every claim back to the user's resumes and profile and blocks anything it can't map | |
| 5 | Web: readiness panel and blockers on the job page, answer bank page, pack workspace (tick or skip suggestions, preview, download) | readiness panel, blockers and answer bank page **done**; pack workspace with module 4 |
| 6 | Tests and e2e: sign-up with confirmation, pack generation with a fake model, claim-check failures | sign-up and readiness tests **done**; pack tests with module 4 |

## Google and Microsoft sign-in

**Deferred (2026-11-01):** the user will create the Google and Microsoft registrations once there is a domain.
Milestone 4 builds only the password changes of module A; the provider sign-in is built and tested together
with the registrations (likely alongside the Cloudflare worker, which needs the same domain), so no code ships
that can't be tried.

- **Sign-in only:** OpenID Connect with the scopes `openid email profile`. FitFirst never asks for access to
  Gmail or Outlook mail, so no Google security review is needed (reading mail stays a Phase 2 option).
- **Accounts:** the first Google or Microsoft sign-in creates the account (name and email from the provider,
  terms accepted on a short confirmation step). Signing in with a provider whose verified email matches an
  existing account links it to that account; the password keeps working.
- **No passwords stored from providers**; FitFirst keeps only the provider's user id and email.
- **Difference from the LLD:** the LLD puts Google and Microsoft sign-in in Phase 2 via Amazon Cognito. Here it
  is built into the existing auth (same `/auth` contract), so it works locally and on Lightsail without Cognito.

**Needed from the user before module A's provider part:**

- Google: a Google Cloud project with an OAuth client (Web application) → `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET` in `.env`.
- Microsoft: an app registration in Microsoft Entra (any organisation + personal accounts) →
  `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` in `.env`.
- Redirect URIs registered with both (decided 2026-11-01, so the user can register them before the code exists):
  `http://localhost:8080/api/v1/auth/oauth/<provider>/callback` (`make up`) and
  `http://localhost:8000/api/v1/auth/oauth/<provider>/callback` (`make dev`); the production domain is added at
  deploy (milestone 8).
- Step-by-step instructions will be in SETUP.md. Without these keys the buttons are hidden.

## Decisions (2026-11-01)

- **Re-enter password** is checked in the browser (the mismatch message clears as you retype) and by the API:
  `POST /auth/signup` requires `password_confirm`. Every password field has a Show/Hide button.
- **Readiness is worked out on every read**, from the match, the answer bank, the candidate profile, the
  cover-letter library and the description, instead of the LLD's `readiness` and `blockers` tables. It can't go
  stale, and nothing has to re-run when an answer or the profile changes. Only Top matches (strong + good) have
  a readiness.
- **Blockers detected now:** the four questions forms ask most (notice period, current CTC, expected CTC, total
  experience) when neither the answer bank nor the profile answers them; relocation when the job is in another
  city; a missing full description; no cover letter; factor gaps under 45 (the user can accept a gap per job,
  stored in `user_jobs.acknowledged`).
- **Not detected yet:** the portals' own screening questions and "Manual only" (assessments, login walls,
  unsupported application systems). Both need to see the application form, which arrives with the browser
  extension (BRD FR-09, Phase 2).
- **Answer bank:** seven common questions (four of them required for readiness) plus up to 50 of the user's own;
  the profile answers a common question until the user saves their own answer; answers older than 30 days are
  flagged. Migration `0005`. Per-profile overrides (`search_profile_id`) exist in the table but not yet in the API.
- **API:** `GET/POST /answers`, `PUT/DELETE /answers/{key}`, `GET /jobs/{id}/readiness`,
  `POST /jobs/{id}/blockers/{key}/resolve`; `GET /jobs?readiness=ready|needs_input`; jobs and the job detail
  carry `readiness`; `/jobs/stats` adds `ready` and `needs_input`.

Verified 2026-11-01: 196 backend tests, 20 web unit tests, 3 e2e tests, lint clean.
- **First, middle and last name** (requested 2026-11-01, migration `0006`): Create account and Settings have
  First name (required), Middle name (optional) and Last name (required). `users.name` stays as the display name,
  always built from the parts; existing accounts were split at the first space. `POST /auth/signup` takes
  `first_name`, `middle_name`, `last_name` instead of `name`; `PATCH /me` changes them (middle name `null`
  removes it); `/me` returns all four.

## Answer bank moved into Profile (user, 2026-11-16)

The answer bank is now a tab on Profile (**Profile → Answer bank**, `components/AnswerBank.tsx`); `/answers`
redirects there and the sidebar item is gone. Nothing changed in how answers are used: the Apply kit and the
browser extension fill a form's question from the answer with the same key, or whose question shares at least 60%
of its words (`apps/extension/src/match.js`, `answerFor`).
