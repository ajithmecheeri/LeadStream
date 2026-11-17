# Milestone 14 — Fill application forms (plan and status)

Scope, Workday detail and dependencies: `docs/milestones.md` (Milestone 14). The user approved the non-negotiable
change on 2026-11-09 ("Just filling in local browser is fine") and asked for 14 to be built with 6.2, 13 A, 9.3 and
the 10 leftovers while they were away. Decisions below are for review.

## Status

| Part | What | Status |
|------|------|--------|
| 14.0 | Non-negotiable change in CLAUDE.md | **done** 2026-11-09 |
| 14.1 | Apply profile: phone, address, websites, languages, work history, education; "Fill from a resume" | **built** 2026-11-09 |
| 14.2 | Apply kit on the job page: every field with Copy, in Workday's order; resume and cover letter downloads | **built** 2026-11-09 |
| 14.3 | Extension shell (Chrome/Edge MV3), pairing code on Settings, read-only revocable token, portal block list | **built** 2026-11-09 |
| 14.4 | Greenhouse, Lever, Ashby, SmartRecruiters and other forms, by label | **built** 2026-11-09 (tested on a Greenhouse-shaped page) |
| 14.5 | Workday: field ids, dropdowns, work history and education with Add, dates | **built, needs real pages** (tested on a hand-made Workday-shaped page) |
| 14.6 | Unknown questions: answer bank by meaning (built); Claude for the rest | answer bank built; Claude waits for the key |
| 14.7 | Free-text drafts with the claim check; tailored resume | waits for milestone 4 packs (Anthropic key) |
| 14.8 | Chrome Web Store | waits for milestone 8 (deploy), privacy page (built as a draft), developer account |

## What was built

- **Profile → For application forms** (`components/ApplyProfileForm.tsx`): phone, address, websites, languages, work
  history (most recent first, "I currently work here"), education. "Fill from a resume" reads phone, city, roles with
  month dates and education (degree and school lines joined) with rules; nothing is saved until Save.
- **Job page → Apply kit** (`components/ApplyKit.tsx`): My information, My experience, Application questions, each
  value with Copy; downloads of the suggested resume and cover letter; what's missing, with a link to Profile.
- **Settings → Browser extension** (`components/BrowserExtension.tsx`): Pair a browser (one-time code, 10 minutes),
  paired browsers with last use, Unpair.
- **Extension** (`apps/extension`, see its README): popup (pair, Fill this page, unpair), background worker (API calls,
  injection on click), `match.js` (rules), `fill.js` (filling). Green = filled, amber = needs you, a toast summary.
- **API**: `GET/PUT /apply-profile`, `POST /apply-profile/from-resume`, `GET /jobs/{id}/apply-kit`;
  `POST /extension/pairing-code`, `GET /extension/devices`, `DELETE /extension/devices/{id}`, `POST /extension/pair`,
  `GET /extension/fill-data?url=`, `GET /extension/resumes/{id}/file`, `GET /extension/cover-letters/{id}/file`.
- **Data** (private, RLS FORCE, isolation tests): `apply_profiles` (migration 0020), `extension_tokens` (0021).
- **Tests**: `test_apply.py`, `test_extension.py`, isolation tests; `lib/extension-match.test.ts`;
  e2e `extension-fill.spec.ts` (Greenhouse-shaped, Workday-shaped, portal refused).

## Decisions to review

1. **Apply profile as one row** with work history, education and languages as validated JSON lists, saved as one form
   with a version (like the candidate profile), rather than three tables. Simpler to edit and to export.
2. **Name and email come from the account**, not the apply profile.
3. **Pairing code carries the user id** (`bmjpair.<id>.<secret>`; tokens `bmjx.<id>.<secret>`), so the code and token
   are checked inside the user's own RLS scope; only sha256 hashes are stored. Codes last 10 minutes, once; tokens
   until unpaired. The token can only read: fill data, resume and cover-letter files.
4. **The block list is enforced twice**: the extension won't inject on a portal, and the API answers 403 for a portal
   page's fill data.
5. **Never filled:** sensitive questions (gender, ethnicity, race, veteran, disability, sexual orientation, pronouns,
   caste, religion, date of birth, age, marital status, nationality, passport, Aadhaar, PAN, SSN, criminal record,
   signature, password), fields that already have a value, checkboxes and radio buttons (except Workday's "I currently
   work here").
6. **Answer-bank matching is strict** (60% of the words shared, after dropping filler words): a blank is better than a
   wrong answer. "How large a team have you managed?" matches "How large a team have you managed so far?" but not
   "What size team have you managed?".
7. **Workday "Add"** is clicked to open another work-history or education block (it adds a section to the form; it
   doesn't submit). Next and Submit are never clicked.
8. **One page at a time on Workday**: the user clicks Next and Fill again on each page.
9. **No icons yet**: Chrome shows a letter. Icons come with the store listing.

## What the user should do

- Save 2–3 real Workday application pages (each step: My Information, My Experience, Application Questions) with the
  browser's "Save page as → Webpage, complete" into `TestFiles/raw/` (git-ignored) so the Workday rules can be checked
  against them and turned into sanitised fixtures.

## Company-form Yes/No questions (user, 2026-11-15)

From a GE HealthCare application on Workday: eight questions most company forms ask, added to the answer bank as
standard questions with quick picks (`readiness/questions.py`, `choices`): legally authorised to work, visa
sponsorship, willing to work in the job's location, non-compete / non-solicitation, confidential information
("Yes, I agree"), younger than 18, former government employee, family or business partners employed by a
government. None blocks readiness. They show on Profile → Application Autofill Information (Application questions)
and on the Answer bank page; the extension recognises each by its wording (`apps/extension/src/match.js`, checked
before the address rules, since the questions mention a country or location) and picks the dropdown option that
means the saved answer. Tests: `backend/tests/test_readiness.py`, `apps/web/lib/extension-match.test.ts`,
`apps/web/e2e/extension-fill.spec.ts`.

## Gender, ethnicity and uniformed forces (user, 2026-11-16)

From an Oracle form ("Ethnicity", "Gender", "Have you served in any of the below India Uniformed forces?"), the user
asked for these to be autofilled. Three standard answer-bank questions were added (`readiness/questions.py`):
`uniformed_forces` (Yes/No), `gender` and `ethnicity` (voluntary, quick picks incl. "Prefer not to say"). Decision 5
changes only for gender and ethnicity: the extension fills them **only from the answer saved under that key**, never
by a loose wording match, and only when the label asks nothing else sensitive ("Race/Ethnicity", "Gender and sexual
orientation" stay the user's). Left blank in the bank, they are left blank on the form. Everything else on the list
is still never filled.

## POC: Add from Google results (user, 2026-11-17)

**What.** The user runs a Google search in their own browser (for example one of Find on Google's searches). The
extension puts a **+ Add to BrewMyJob** button under each LinkedIn, Naukri or Foundit job result. One click sends
what Google shows (link, title, snippet) to `POST /api/v1/extension/google-result`, which adds the job like a Google
Alerts job: title, company and place read from Google's title (`alerts/feed.py`), the link read only for the
portal's job id, unverified, scored from title and snippet (below Top until the description is pasted). Clicking
twice doesn't add it twice. The button shows **Added ✓** and an **Open in BrewMyJob** link.

**Why it stays inside the rules.** The portal page is never opened or read; only Google's own result fields are used
(the same rule as Google Alerts and Find on Google). Nothing happens without the user's click. The script runs only
on `google.com/search` and `google.co.in/search` and never on a portal (the portal block list is unchanged).

**Decisions to review.**
- The extension's token could only read until now; this lets it add a job (only through this one route).
- Google's results page markup changes from time to time; the script looks for any result title link (`a` with an
  `h3`) pointing at a portal job page, and the snippet from Google's snippet box or the result's text.
- An iframe was ruled out: Google and the portals refuse to be framed, and a page can't read another site's frame.

**To remove the POC** (all of it is in these places):
`backend/app/modules/extension/google.py`, its two lines in `backend/app/main.py`, `backend/tests/test_extension_google.py`,
`apps/extension/src/google.js`, the `content_scripts` entry (and the last sentence of `description`) in
`apps/extension/manifest.json`, `addGoogleResult` and the `google-result` line in `apps/extension/src/background.js`,
`apps/web/e2e/extension-google.spec.ts`, the README paragraph, then `make api-gen`.

**Review queue (user, 2026-11-17).** A job added from Google now waits in **Jobs → From Google** (new status
`review`, migration 0031) instead of going straight to Top or Other. It is scored meanwhile, but it isn't in the
active lists, alerts, the bell or auto-expiry. Each one has **Keep** (status `seen`: it moves to Top matches or Other
jobs by its score), **Add description** (the job's page: paste it for a full score, which Top needs) and **Ignore**.
A job already in the list stays where it is. A job can't be sent back to review. If a LinkedIn or Naukri alert later
brings the same job, it stays in review until the user decides. The tab shows only while something waits in it.
Removing the POC keeps the status harmlessly (or run the migration's downgrade: review jobs become `new`).

**Bug found on first use:** "Adding…" for ever. An escaping slip in the background script (`/\/$/` written as
`//$/`) made the whole service worker fail to load, so the click never reached the API. Fixed; the button now
gives up after 20 seconds with a message, and a unit test parses every extension script
(`apps/web/lib/extension-match.test.ts`), since no other test loads the background script.
