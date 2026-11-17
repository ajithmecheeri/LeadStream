# Milestone 7 plan: networking (built 2026-11-02, waiting for the user's review)

Goal: use the people the user already knows. Import their LinkedIn connections, show who they know at the
companies with matching jobs (warm paths), suggest a few people to contact each day with a short note, and
track the outreach. **FitFirst never logs in to LinkedIn, never sends invitations or messages, and never
scrapes.** Every link opens LinkedIn in the user's own browser; the user sends everything themselves.

Started 2026-11-02 while the user was away ("Do you want to start with other milestones?"). Built from the
LLD (module M12, tables, `GET /network/daily` example). The decisions below were made without the user; each
is easy to change.

## How the connections arrive

LinkedIn → Settings → Data privacy → **Get a copy of your data** → Connections. LinkedIn emails a link to a
ZIP (or a `Connections.csv`) within minutes. The user uploads it on the Networking page. The file starts with a
few lines of notes, then `First Name, Last Name, URL, Email Address, Company, Position, Connected On`.

## Modules

| # | Module | Status |
|---|---|---|
| 1 | Import: `POST /network/imports` (CSV or the LinkedIn ZIP, base64 JSON like resumes; 10 MB, 30,000 rows); re-import updates by profile URL, adds new people, never deletes; emails dropped unless the user ticks "keep emails"; `connection_imports` records counts; `DELETE /network/connections` removes every connection and import. The file itself is not kept | **done** (2026-11-02) |
| 2 | Warm paths: connections whose company matches the company of the user's active Top matches; `GET /network/warm-paths`; "People you know at {company}" on the job page (`GET /jobs/{id}/people`) | **done** (2026-11-02) |
| 3 | Today: `GET /network/daily?date=` builds the day's list on first open (in the user's time zone): **warm** (a connection at a Top-match company), **target** (no connection there: the role to look for, with a LinkedIn people-search link) and **follow-up** (outreach sent a week ago with no reply). Daily cap and weekly limit from notification settings (5 and 100). Each has a note from a template (`regenerate=true` rebuilds the day's open ones; past days are only read) | **done** (2026-11-02) |
| 4 | Mark: `POST /network/suggestions/{id}/mark` `sent` (records an outreach) or `skipped`; a target can carry the person the user found (name, profile link) | **done** (2026-11-02) |
| 5 | Outreach tracker: `GET/POST /network/outreach`, `PATCH /network/outreach/{id}`; stages **sent → accepted → conversation → referral → closed**; `outreach_events` logs each change; `POST` records someone contacted outside the suggestions | **done** (2026-11-02) |
| 6 | Web: `/networking` with Today, Warm paths, Outreach and Connections tabs; nav link; job page section. The page opens on Connections until there are some | **done** (2026-11-02) |
| 7 | Tests: parser (no database), every endpoint happy + error path, isolation for the five new tables, e2e: import → warm path on a job → today's list → mark sent → move stage | **done** (2026-11-02): 237 backend tests, 27 web unit tests, 5 e2e journeys |

## Decisions

- **Matching people to jobs by company name.** Both sides are normalised to a `company_key`: lower case,
  punctuation and legal suffixes removed ("Pvt Ltd", "Limited", "Inc", "LLC", "Private", "India", "Group"…).
  Two keys match when they are equal, or when one is the other plus whole words ("Commonwealth Bank" and
  "Commonwealth Bank of Australia") and the shorter has at least 6 characters (so "Bank" never matches). Naukri
  shortens long names ("Crescendo Global Le..."); a truncated job company matches a key that starts with it when
  at least 8 characters are left. Words from the middle of a name never match.
- **Who is suggested at a company:** recruiters and talent partners first, then leaders (head, director, VP,
  chief…), then anyone; one person per company per day. Jobs considered: active Top matches and applied jobs
  (a referral still helps after applying). Target suggestions are only for active Top matches.
- **Notes are templates, not AI** (LLD). They use only the job title, the company and the user's profile
  headline, so they can't claim anything the profile doesn't support. Invitation notes are kept under LinkedIn's
  300-character limit.
- **Target suggestions link to a LinkedIn people search** (`linkedin.com/search/results/people/?keywords=…`)
  that the user opens. FitFirst doesn't run the search or read the results.
- **The day's list is built on demand**, the first time it's opened that day, not by a 07:30 job: nothing
  needs it earlier until push notifications (milestone 6). A suggestion is never repeated for the same person
  within 14 days, and no one with an open outreach is suggested.
- **Weekly limit** counts outreach marked sent in the last 7 days; at the limit, only follow-ups are suggested.
- **Follow-ups:** an outreach still at "sent" a week after it was sent (or last followed up) is suggested again
  as a follow-up, before anyone new. Marking it sent records "followed up" on the same outreach.
- **Removing connections** deletes every connection and import; outreach records stay (they're the user's own
  history, not LinkedIn data).

## For the user to check

- The note wording (`app/modules/networking/notes.py`). Easy to change; tell me the tone you want.
- Who to look for at a company with no connection (`target_role`): the CEO for a C-level role, the CTO or
  Chief Product Officer for senior tech or product roles, otherwise Talent Acquisition.

## Companies you applied to (user feedback 2026-11-15)

Networking → Today now has a **Companies you applied to** section (`GET /network/applied`): applications from the
last 60 days that aren't rejected or withdrawn, newest first, one card per company, at most 10. Each card has:

- **LinkedIn people searches** the user opens in their own browser: *HR & recruiters*
  (`(recruiter OR "talent acquisition" OR HR) "Company"`), *Leaders* (`(director OR head OR VP OR chief)`, plus the
  job's function, engineering/technology or product, when the title shows it) and the likely hiring manager
  (`notes.target_role`, e.g. CTO) when it isn't just Talent Acquisition. BrewMyJob never runs or reads the searches.
- The company name as people write it on LinkedIn (`companies.search_name`: legal suffixes and "India" dropped, a
  truncated last word removed).
- A note after applying (at most 300 characters, templates only, so the claim check holds), people the user already
  knows there, and **I wrote to someone**, which records a manual outreach linked to the job ("N contacted").

Decisions to review: the 60-day window and 10-company cap; "India" is dropped from company names for the search;
these cards aren't counted in the daily cap (they're a list to work through, not daily suggestions).
