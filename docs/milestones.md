# Milestone log

## Milestone 1 — Foundation (done)

**What works**

- Sign up, sign in, sign out, silent session refresh (web cookie, mobile body token).
- Rotating refresh tokens; replaying an old one revokes the whole session family.
- Login throttling: 10 failed attempts per email per 15 minutes.
- Personal alert-forwarding address per user (`alerts-<token>@<INBOUND_DOMAIN>`), shown on the dashboard.
  Mail isn't processed yet (milestone 2).
- Candidate profile with optimistic concurrency and a completeness meter.
- Search profiles: up to 5, weights that always total 100, threshold, seniority, exclusions.
- Notification settings (stored now, used from milestone 6).
- Row-level security on all private tables; the API role can't bypass it.
- Consent record and audit events at sign-up and sign-in.
- Demo data: the fictional Kavya Iyer profile from the POC.

**API**

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/auth/signup` | `{email, name, password, accept_terms}` → tokens; creates profile, settings, consent |
| POST | `/api/v1/auth/login` | `{email, password}`; `X-Client: mobile` returns the refresh token in the body |
| POST | `/api/v1/auth/refresh` | cookie (web) or `{refresh_token}` (mobile) |
| POST | `/api/v1/auth/logout` | revokes the session family |
| GET/PATCH | `/api/v1/me` | name, time zone, forwarding address |
| GET/PUT | `/api/v1/candidate` | PUT needs `version` |
| GET | `/api/v1/profiles/meta` | factors, default weights, seniority scale, limits |
| GET/POST | `/api/v1/profiles` | |
| GET/PATCH/DELETE | `/api/v1/profiles/{id}` | PATCH needs `version` |
| GET/PUT | `/api/v1/settings/notifications` | |
| GET | `/healthz` | |

**Tests**: 24 backend tests (auth, profiles, cross-user isolation including raw SQL as the app role),
4 web unit tests (weight rebalancing), 1 browser end-to-end journey.

**Known gaps, by design**

- No email verification or password reset yet (needs outbound email, milestone 6).
- The login throttle is per API process; Phase 2 moves it to Redis.
- Local JWT keys are generated at start-up; set `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` in prod (`make keys`).

## Milestone 5 — Applications tracker and job-list feedback (done, 2026-11-02)

Plan, decisions and module status: `docs/plan-m5.md`.

**What works**

- **Applied**: a button on each job card and on the job page. The job moves to the Applied tab and an
  application is recorded with the date and the suggested resume and cover letter. Undo works until the
  application has updates.
- **Applications page**: status Applied → Interviewing → Offer → Accepted, or Rejected / Withdrawn / No response;
  a timeline of every change and note; follow-up dates (due ones first, in amber, and on the dashboard);
  filters by status and by the day, month or year applied.
- **Expired**: mark a job expired, or it moves there by itself when no alert has shown it for the super admin's
  number of days (default 45). From 30 days (also set by the admin) it shows an amber "May have expired" with
  "It's still open". Applied jobs never expire; a new alert brings back an automatic expiry.
- **Jobs tabs**: Top matches · Other jobs · Not scored yet · Applied · Expired · Ignored · All, with counts.
- **Amber to-dos**: everything to do on a job in one amber list with the button that fixes it; "N to do" on the
  job card.
- **Why not 100%**: points lost per factor (adding up to 100 − score), skills the job lists that the resume
  has and misses, and "I have this skill", which adds it to the profile and re-scores.
- **Contacts on a job**: the recruiter the email named, plus people the user saves (name, role, LinkedIn profile,
  email, note). FitFirst never contacts them.
- **Super admin**: `make admin EMAIL=…`; an Admin settings page for the expiry days, logged in `audit_events`.

**API (new)**

| Method | Path | Notes |
|---|---|---|
| PATCH | `/api/v1/jobs/{id}` | status now also `applied` and `expired` |
| POST | `/api/v1/jobs/{id}/still-open` | clears "May have expired" |
| POST | `/api/v1/jobs/{id}/skills` | `{skill}`: add to the profile, re-score |
| GET/POST | `/api/v1/jobs/{id}/contacts` | |
| PUT/DELETE | `/api/v1/jobs/{id}/contacts/{contact_id}` | PUT needs `version` |
| GET | `/api/v1/applications` | `status`, `from`, `to`, `due`; counts per status, follow-ups due |
| GET/PATCH | `/api/v1/applications/{id}` | PATCH needs `version` |
| POST | `/api/v1/applications/{id}/notes` | |
| GET | `/api/v1/app-settings` | any signed-in user |
| GET/PUT | `/api/v1/admin/settings` | super admin only (403 otherwise) |

**Tests**: 219 backend tests (21 new, including isolation for `applications`, `application_events` and
`job_contacts`, and the app role's limits on `app_settings`), 24 web unit tests, 4 browser journeys.

**Known gaps**

- Jobs scored before migration 0007 show the breakdown after their next re-score (the live database was
  re-scored once on 2026-11-02).
- The admin page has one section (old jobs). The rest of the admin console (parser health, usage) is Phase 2.

## Milestone 7 — Networking (done, 2026-11-02; waiting for the user's review)

Plan and decisions: `docs/plan-m7.md`. FitFirst never logs in to LinkedIn, sends invitations or messages, or
scrapes: the user imports their own data export and sends everything themselves.

**What works**

- **Import**: LinkedIn's Connections export (the ZIP LinkedIn emails, or the CSV in it). Re-importing updates and
  adds; emails are dropped unless the user keeps them; the file isn't stored. "Remove all" deletes them.
- **Warm paths**: the people you know at the companies of your Top matches and applied jobs, recruiters first,
  on the Networking page and on each job page.
- **Today**: up to 5 a day (the networking cap in notification settings): follow-ups first, then someone you know
  at a matching company, then who to look for where you know no one (with a LinkedIn people-search link). Each
  has a note to copy (templates; invitation notes under 300 characters). "I sent it" or "Skip". At the weekly
  limit (100) only follow-ups are suggested.
- **Outreach**: sent → accepted → in conversation → referred you → closed, with the history of each.

**API (new)**

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/network/imports` | `{file_name, content_base64, keep_email}`; CSV or ZIP, 10 MB |
| GET | `/api/v1/network/summary` | connections, companies, last import, matching jobs where you know someone |
| GET/DELETE | `/api/v1/network/connections` | `q`, `limit`, `offset`; DELETE removes all |
| GET | `/api/v1/network/warm-paths` | |
| GET | `/api/v1/jobs/{id}/people` | your connections at the job's company |
| GET | `/api/v1/network/daily` | `date`, `regenerate`; built the first time each day |
| POST | `/api/v1/network/suggestions/{id}/mark` | `{action: sent\|skipped, person?, note?}` |
| GET/POST | `/api/v1/network/outreach` | `stage` filter; POST records one by hand |
| GET/PATCH | `/api/v1/network/outreach/{id}` | PATCH needs `version` |

**Tests**: 237 backend tests (18 new, including isolation for the five new tables), 27 web unit tests,
5 browser journeys. Fictional connections in `backend/tests/fixtures/connections/Connections.csv`.

## Planned milestones (agreed 2026-11-02)

Working order: 9 → 6 → 10 → 11, then 8 (release) and 12 (US). India is the first market; the US comes later.

### Milestone 6 — Notifications (in progress; decided 2026-11-03)

Started 2026-11-05: WhatsApp alerts for strong matches are built and wait for the Meta setup. Progress,
decisions and the setup steps: `docs/plan-m6.md`. User, 2026-11-05: alerts are for **high (strong) matches**,
not every new job (this replaces decision 1 below).

User decisions of 2026-11-03:
1. **A WhatsApp message for every new job, but never for a duplicate** (a clear duplicate from M9, a job repeated
   in a later alert email, or one already applied). Strong jobs are already at the top in Top matches.
2. **Meta or Twilio:** the user asked for a free option for now. Plan: start on Meta's free test number (see below);
   decide on paid sending before launch.
3. **Teams:** later, not in M6.
4. **Expo app and push move to 6b**, built once the web app is stable.

The common part, built once for every channel:
- an outbox with delivery status and retries;
- per event and channel rules: new job, needs input, follow-up due, networking suggestions, daily digest;
- quiet hours (messages held until morning), a daily cap, one message per job, none for duplicates;
- an in-app bell and a settings page with "send a test".

Channels:
- **WhatsApp:** Meta WhatsApp Business (Cloud) API; the user's number is verified with a one-time code. Messages
  BrewMyJob starts use templates Meta approves. Unofficial WhatsApp Web automation is not used.
  - **Free for now:** Meta's test business number costs nothing and can message up to 5 verified numbers — enough
    for the user and testers. Replies inside 24 hours of the user's last message to the business are also free.
  - **Paid later:** job alerts sent outside that window are "utility" template messages, charged per message by
    Meta (roughly ₹0.1–0.15 each in India; check Meta's current rate card). Twilio adds its own fee on top, so
    Meta directly is the default.
- **Teams:** later, not in M6 (a Teams Workflows webhook link that the user pastes, stored encrypted).
- **Email digest:** sent through the domain (brewmyjob.com) once outbound email is set up; logged to the console
  until then.

Reply buttons (Applied / Ignore inside WhatsApp) need a public webhook: `inbound.brewmyjob.com` (the M2 tunnel)
can carry it.

### Milestone 6b — Mobile app (later, once the web app is stable)

Expo app for iOS and Android sharing `packages/api`, with push notifications.

### Milestone 9 — More sources and duplicates (India first; in progress)

Started 2026-11-03. Company career feeds and Adzuna are built (Adzuna waits for its key); duplicates were built on
2026-11-07 (rules and thresholds in `docs/plan-m9.md`, decision 12).
Progress, decisions and the relevance rules: `docs/plan-m9.md`.

- **Company feeds (free, no key):** Greenhouse, Lever, Ashby and SmartRecruiters public job feeds for a list of
  companies the user chooses, checked once a day.
- **Adzuna India API:** a free key; searched with the user's search profiles. Commercial use must be confirmed
  with Adzuna before charging users (likewise Jooble and Careerjet if added).
- **More alert-email parsers:** iimjobs, hirist, Indeed, Foundit, Instahyre, Glassdoor. Each needs 2–3 real alert
  emails from the user, sanitised before they become fixtures. Also (built 2026-11-08): job lists an AI assistant
  (ChatGPT scheduled task, Gemini, Claude…) emails from the user's own address — `docs/assistant-alert-prompt.md`.
- **No API for FitFirst** (alert emails only): LinkedIn, Naukri, Indeed, Glassdoor, Foundit, iimjobs, hirist,
  Instahyre, Wellfound.
- **Duplicates:**
  - Already in place: one row per user and job, so a job repeated in a later alert email is not added again and
    keeps its status. The catalog also merges by listing, URL or exact fingerprint.
  - **Clear duplicate:** same listing or URL; or the same company (the networking `company_key` matching) plus the
    same normalised title ("VP" = "Vice President") and city; or near-identical descriptions. It is merged into the
    existing job ("Also on …") and not added. If that job is already applied, it stays in Applied and nothing new
    appears.
  - **Potential duplicate:** same company with a similar title, a different city, or very similar descriptions. It
    is added with an amber "Possible duplicate of …" note and **Same job** / **Different job** buttons. The
    choice is remembered.
  - Thresholds go in the milestone plan for the user's review.

### Job sources and Jobs (feedback of 2026-11-16 and 2026-11-17)

- **Jobs tabs:** Top matches, Other jobs, Applied, Expired, Ignored, All, **From sources** (every job the job
  sources brought you, the last run's first, with Add to my jobs for the ones left out) and **From Google** (jobs
  added from Google results with the browser extension, waiting for Keep or Ignore; shown while one waits).
- **Job sources (admins):** each company's open jobs, with the ones its last check found in their own section;
  last-run and last-check figures. Jobs open before a company was added, or before a job seeker joined, are caught
  up for them.
- **Find on Google** (a menu item for job seekers): one set of roles on top, used by the Google searches and the
  Google Alerts on the same page; Google Alerts setup moved here from Job sources.
- **Browser extension:** downloadable from Settings → Browser extension; on Google's results it adds an **Add to
  BrewMyJob** button for LinkedIn, Naukri and Foundit jobs (proof of concept, `docs/plan-m14.md`).

### Milestone 10 — Marketing home page (planned)

- A public landing site, separate from the app, built from a template the user provides (it must be licensed
  for commercial use).
- Search-friendly page setup, social preview images, analytics (GA4 or Plausible), cookie consent, a fast static
  build, and a pricing section linking to milestone 11.
- Content stays truthful: no invented testimonials, user counts or logos, and no auto-apply claims.

### Milestone 11 — Subscriptions (India first; in progress)

**Built 2026-11-17** (`docs/plan-roles-and-plans.md`), everything except taking payment:

- **Roles:** job seeker (everyone who signs up), admin (manages Job sources), super admin (Admin settings and
  invites; made with `make admin`).
- **Plans:** one plan, four periods: 1 month ₹199, 3 months ₹500, 6 months ₹750, 1 year ₹1,200. Shown on the
  home page and on the app's **Choose a plan** page.
- **Paywall:** a job seeker without a running period sees only Choose a plan; the API answers
  `402 subscription_required` on every feature route. Admins never need a plan.
- **Invites and coupons:** the super admin invites a job seeker (with a 1- or 3-month coupon, or none) or an admin
  on Admin settings → Invites. The link works once, for that email, for 14 days. No email is sent yet (no email
  provider until the domain): the super admin copies the link and sends it.
- **Job sources for admins:** one shared list of companies; every user gets the jobs that fit, and sees all of
  them in Jobs → From sources.

Still to build:

- Razorpay hosted checkout (UPI auto-pay and cards), so FitFirst never handles card data.
- Pricing on the home page → sign up → checkout → a webhook turns the plan on.
- Plan limits enforced (for example jobs scored a month, packs a month), a billing page (upgrade, cancel,
  invoices), and a free tier or trial.
- Built in Razorpay test mode first. Going live needs the user's Razorpay business account (KYC), plans and
  prices, and the domain.

### Milestone 12 — US market (later)

- **Alert emails:** LinkedIn US, Indeed, Glassdoor, ZipRecruiter, Dice, Built In, Ladders, Wellfound.
- **APIs:** Adzuna US, Jooble, USAJobs, The Muse, and company feeds (far more common in the US).
- **Profile changes:** USD salary, states and remote-US, a work authorization / visa sponsorship filter, and a
  region on each search profile.
- **Billing:** Paddle or Lemon Squeezy as merchant of record, so US and EU sales tax is handled for the business.

### Milestone 13 — Ask BrewMyJob: an assistant that learns from feedback (backlog, added 2026-11-03)

The user's request: let users ask questions such as "Why is Director, Product Design a top match for me?" and let
the answers and the feedback improve BrewMyJob over time. Order in the plan not decided yet; part A needs no AI key
and could come early.

**What users can do**
- **Ask** from any page, or from a job ("Why is this a top match?", "What's missing for this one?", "Why didn't
  I get jobs from Okta today?", "How do I set up Naukri alerts?"). Answers come from the user's own data and
  explain the actual score, filters and sources, not guesses.
- **Say "Not for me"** on any job, with a reason: wrong field, wrong level, location, company, salary, already
  applied elsewhere, duplicate, other (free text). Also available as a reply in the assistant ("this isn't my field").
- **Let it change things, with confirmation**: ignore a job, exclude a company, raise the seniority floor, add a city,
  adjust a search profile's weights. The assistant proposes; the user presses Confirm. Every change is undoable.

**How it improves (three loops, each with a person in charge)**
1. **For the user, right away:** "Not for me" reasons turn into that user's own preferences (excluded companies,
   fields they don't want, a higher level), shown on the profile so they can see and undo them. Their jobs are
   re-scored.
2. **For everyone, reviewed:** feedback is grouped (for example "8 users: design titles scored as product") into a
   review queue on Admin settings. A fix is a reviewed change to the matching rules, like the 2026-11-03 Product
   Design fix, and each confirmed case becomes a test, so it never comes back. Nothing changes the rules for everyone
   automatically.
3. **For the AI parts, measured:** once Claude scoring and packs are on, confirmed feedback becomes an evaluation set.
   A new prompt version must do better on it before it replaces the old one (prompts are versioned in `backend/prompts/`).

**Rules (from CLAUDE.md, applied to the assistant)**
- Only through the LLM gateway: a versioned prompt, validated output, a rule-based fallback, a row in `llm_calls`.
  Models: `claude-sonnet-5-5` for answers, `claude-haiku-5-5` to sort feedback into reasons.
- **Read tools** see only the signed-in user's data (they run in `user_scope`, so RLS applies): their jobs and match
  breakdowns, profile, search profiles, sources, inbox, applications. **No tool** reaches another user's data, a job
  portal, email or messaging. The assistant never applies, never contacts anyone, never logs in anywhere.
- Job descriptions and emails are untrusted text: they are passed to the model as data, never as instructions
  (a posting saying "ignore your rules" changes nothing).
- Anything the assistant writes for the user (a note, a summary) passes the claim check.
- Limits: questions per user per day and a monthly cost cap (ties in with milestone 11 plans and milestone 8 rate
  limits).
- Privacy (DPDP): conversations are private (RLS), kept 90 days, deletable by the user, and included in the data
  export. The review queue shows feedback without names or emails.

**Data (all private, RLS FORCE, own_rows policy)**: `assistant_conversations`, `assistant_messages`,
`job_feedback` (user job, reason, free text, what changed), `learned_preferences`. Shared, admin only:
`feedback_groups` (grouped and anonymised).

**Parts**
- **A. "Not for me" with reasons + per-user learning** (loop 1). No AI needed.
- **B. Ask panel** with read tools: explain a score, a filter, a source; setup help.
- **C. Admin review queue + regression cases** (loop 2).
- **D. Changes with confirmation** from the assistant.
- **E. Evaluation set and prompt versions** (loop 3), after Claude scoring is switched on.

Needs: the Anthropic API key (B, D, E); milestone 8 rate limits before public use.

### Milestone 14 — Fill application forms (optional; build last, added 2026-11-04)

The user's question: can BrewMyJob fill in the application form on a company's site? Agreed as an optional item,
built after everything else. Nothing built yet.

- **A. Apply kit on the job page (no extension).** Everything a form asks for, each with a Copy button: name, email,
  phone, LinkedIn URL, location, answers from the answer bank (notice period, current and expected CTC…), and the
  suggested resume and cover letter to download. Works on every site, including LinkedIn and Naukri, and on a phone.
- **B. Browser extension (Chrome and Edge) for company application forms.** The user clicks "Fill with BrewMyJob" on
  the apply page. The extension reads the field labels, gets the answers from the API, fills the fields and attaches
  the resume, and marks in amber what it couldn't answer. **It never clicks Submit.** Afterwards it offers
  "Mark as applied?" for the tracker, and offers to save new answers to the answer bank (the user confirms).
  - Permissions: `activeTab` + `scripting` only, so it sees a page only when the user clicks its button.
  - Sites: Greenhouse, Lever, Ashby and SmartRecruiters first (stable field names, matched by rules); then Workday,
    SuccessFactors, iCIMS and Taleo, one step at a time.
  - **Hard-blocked in code:** linkedin.com, naukri.com, indeed.com and other job portals. LinkedIn's user agreement
    prohibits extensions that automate activity, and users' accounts get restricted for it; the Apply kit covers
    those sites instead.
  - Labels to answers: rules first, then match by meaning against the answer bank. For odd questions, Claude Haiku
    through the LLM gateway, which sees only the field labels.
  - Free-text answers ("Why do you want to join us?") are drafts that pass the claim check and wait for the user.
  - Sign-in: pair once with a code from Settings; a short-lived, revocable token that can only read the profile,
    answers and resumes. Pairings in a new private table (RLS FORCE, own_rows, isolation test).
- **C. Tailored packs.** Once milestone 4 packs exist, attach the resume tailored for the job.

**14.0 decided 2026-11-09:** the user approved the non-negotiable change ("just filling in the local browser is fine"); CLAUDE.md now carries it.
Needs before B (as first written): the user's change to the CLAUDE.md non-negotiable (proposed wording: "No automation on job portals
(LinkedIn, Naukri, Indeed…). On company application forms, the extension fills fields only when the user clicks,
and never submits."), a Chrome Web Store developer account and the privacy policy page (milestone 10 leftover).
Until then it can be loaded unpacked for the user's own use.

#### Detail added 2026-11-09 (user: "the plugin which will help me fill the data faster in Workday etc.")

**What a Workday application asks for**, compared with what BrewMyJob stores today:

| Workday page | Fields | Stored now? |
|---|---|---|
| My Information | name, email, **phone**, **address** (street, city, postcode, country), "how did you hear about us", previously worked here? | name, email; **no phone or address** |
| My Experience | **work history** (title, company, location, from–to, description) with "Add another"; **education** (school, degree, field, dates); **languages**; skills; **websites**; resume upload | skills, LinkedIn URL and resume files; **no structured work history, education or languages** (only resume text) |
| Application Questions | employer's own questions: notice period, CTC, relocation, work authorisation, sponsorship… | answer bank (milestone 4) and candidate profile: yes |
| Voluntary Disclosures / Self Identify | gender, ethnicity, disability, veteran status (mostly US) | **never stored or filled**: sensitive; the user answers these |
| Review | the whole application | the user reviews and clicks Submit themselves |

**How Workday is different from Greenhouse or Lever:**
- **One account per employer.** Each company's Workday site (`<company>.wd1.myworkdayjobs.com`) needs its own sign-up.
  The user creates the account and signs in; the extension never creates accounts or handles passwords
  (non-negotiable: no stored passwords).
- **A multi-page wizard.** "Fill this page" works on the page in view; the user clicks Next. No click-through.
- **Custom controls.** Workday's dropdowns are listboxes (click, type, pick), dates are month and year boxes, and work
  history and education are repeated "Add" sections. Fields are found by Workday's `data-automation-id` attributes,
  with the visible label as a fallback.
- **Workday's own "Autofill with resume"** parses the uploaded resume first. The extension then corrects and completes
  what it got wrong (titles, dates, missing jobs).
- **Workday changes its pages.** Selectors are versioned rules, tested against saved, sanitised copies of real
  application pages. A field the rules don't recognise is left blank and marked amber; nothing is guessed.

**Plan, in order:**

| Part | What | Depends on |
|---|---|---|
| 14.0 | The user's change to the non-negotiable (wording above) | **decided 2026-11-09**: in CLAUDE.md |
| 14.1 | **Apply profile**: phone, address, work history, education, languages and links as structured data. Proposed from the resumes (rules now, Claude later) and confirmed by the user; editable on Profile. Private tables with RLS and isolation tests | nothing: can start now |
| 14.2 | **Apply kit** on the job page: every field with a Copy button, work history in Workday's order, the resume to download. Works on Workday, LinkedIn, Naukri and phones | 14.1 |
| 14.3 | **Extension shell** (Chrome, Edge; Manifest V3, `activeTab` + `scripting`), pairing with a code from Settings, a read-only revocable token (new private table), portal hard-block list | 14.0, 14.1 |
| 14.4 | Greenhouse, Lever, Ashby, SmartRecruiters: one-page forms with stable field names | 14.3 |
| 14.5 | **Workday**: fill the page in view, listboxes, month/year dates, "Add" sections, resume upload; voluntary disclosures skipped; tests on saved pages | 14.3; **2–3 saved Workday application pages** from the user (browser "Save page as", sanitised before they become fixtures) |
| 14.6 | Unknown questions: match against the answer bank by meaning; Claude Haiku for labels the rules don't know; new answers saved only when the user confirms | rules work without a key; Claude needs the **Anthropic key** |
| 14.7 | Free-text answers ("Why this company?") as drafts that pass the claim check; the tailored resume attached | milestone 4 packs and claim check (**Anthropic key**) |
| 14.8 | Publish for other users: Chrome Web Store listing and its privacy disclosure | **milestone 8** (public HTTPS API), **privacy policy page** (milestone 10), **Chrome Web Store developer account** (one-time fee). Before that, the user loads it unpacked against their own API |
| later | SuccessFactors, iCIMS, Taleo, Oracle Recruiting (seen in the ChatGPT lists: JPMorganChase) | 14.5 approach, one system at a time |

Not in scope: clicking Submit, creating Workday accounts, storing Workday passwords, filling self-identification
answers, and anything on LinkedIn, Naukri, Indeed or other job portals (hard-blocked).

## Milestone 10 — Marketing home page (built 2026-11-03, waiting for the user's review)

Built from the user's design export "Home page — light" (`TestFiles/raw/`, not committed), rebuilt in the web
app's own code: `app/page.tsx`, `app/_home/` (styles, waitlist form, nav). The design's colours, fonts
(Bricolage Grotesque, Geist, Geist Mono), sizes and layout are kept.

- **`/` is now the public home page** (it used to redirect to sign-in). Signed-in visitors see "Open the app";
  others see "Sign in" and "Join the waitlist".
- **Waitlist:** the form posts to `POST /api/v1/waitlist` (migration 0009, table `waitlist`: email, source, time;
  shared, no RLS; the app role can't update rows). The answer is the same whether the email is new or already
  listed, and a hidden field catches form-filling bots. The super admin sees the list on Admin settings
  (`GET /api/v1/admin/waitlist`).
- **Search and sharing:** page title and description, canonical URL, Open Graph and Twitter tags, a generated
  1200×630 preview image (`app/opengraph-image.tsx`), `robots.txt` (only `/` may be indexed) and `sitemap.xml`.
  The site address comes from `NEXT_PUBLIC_SITE_URL` (default `https://brewmyjob.com`).
- **Honesty changes to the design's copy:** features that aren't built yet carry "COMING SOON":
  - tailored resume and cover letter (step 3 and its feature card);
  - flagging possible duplicates ("Soon: …");
  - data export and account deletion ("Arriving before paid plans launch");
  - the Pro price, shown as "Price coming soon" instead of the `₹[PRICE]` placeholder.

  The footer's Terms and Contact links are left out, because those pages and the address don't exist yet.
  Gmail only in step 1, since Outlook forwarding hasn't been tried.
- **Layout fix:** the last row of feature cards had 2 + 3 + 3 columns (more than the 6-column grid), so it
  wrapped unevenly. The last three cards are now equal (2 + 2 + 2).

**Built 2026-11-09 (user away; for review):** `/privacy`, `/terms` and `/contact` (`app/privacy`, `app/terms`, `app/contact`,
shared layout `app/_legal/`). Privacy and terms describe what the code does today (data kept, the one sign-in
cookie, Cloudflare / Voyage / Meta / Anthropic and what each receives, 90-day raw email deletion, DPDP rights) and
carry a visible **Draft** note (`LEGAL_DRAFT` in `app/_legal/LegalPage.tsx`) until the user (and ideally a lawyer)
has reviewed them. Still to fill in before launch: the hosting provider and data location, a named grievance
contact if DPDP rules require one, self-service export/delete (milestone 8). The contact page is a form (no
mailbox exists yet): messages go to `contact_messages` (migration 0019, shared, the app role can't change or delete
rows) and the super admin reads them on Admin settings; privacy requests are marked. Footer, robots.txt and the
sitemap link the three pages.

**Left for this milestone:** analytics (GA4 or Plausible) with a cookie banner if the choice sets cookies; privacy
policy and terms pages (needed for DPDP before launch); a contact address such as hello@brewmyjob.com (Email
Routing on the root domain).

**Tests:** 4 backend tests (`test_waitlist.py`); e2e `home.spec.ts` (page, FAQ, waitlist, sign-in link, robots and
sitemap). All 241 backend tests, 27 web unit tests, 20 email-worker tests and 7 e2e journeys pass.
