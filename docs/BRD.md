# AI Job Search & Application Assistant — BRD and Technical Design

Oct 9, 2026 · @Ajith Mecheri

## Summary and document control

The system is a multi-user SaaS product that any job seeker can sign up for, and the author is its first pilot user. For each user, it automates job discovery, matching, readiness checks and application preparation across LinkedIn and Naukri. It pushes every decision point to a web dashboard and a mobile app. Final submission stays human-approved: a manual click in the MVP, and one-tap approval for supported channels in Phase 2.

This version merges BRD v1.0 (08 Oct 2026) with the design discussion that followed. Version 1.0 contributes the email-alert ingestion strategy, matching factors and weights, deduplication, AI guardrails, data model, AWS deployment and MVP plan. The discussion adds a native mobile app with push notifications, real-time updates to the web client, an application-readiness check that tells you why a job cannot be applied for automatically, and a defined path to assisted one-tap apply.

| Item | Value |
| --- | --- |
| Document | AI Job Search & Application Assistant: BRD and Technical Design |
| Version | 2.1: multi-user product (supersedes 1.0 of 08 Oct 2026) |
| Primary objective | Automate discovery, matching, readiness checks and application preparation for every user; notify each user on web and mobile wherever a decision or input is needed |
| Users | Any job seeker, through self-service sign-up; the author is the first pilot user |
| Product model | Multi-tenant SaaS (B2C); each user can hold several search profiles |
| Pilot focus | Senior technology leadership roles (VP/SVP Engineering, VP Product Development, Head of Engineering, CTO-track); roles, locations and weights are configurable per user, so any profession works |
| Initial sources | LinkedIn and Naukri (via job-alert emails); Greenhouse and Lever public boards as optional sources |
| Clients | Next.js (React) web app; React Native (Expo) mobile app for iOS and Android; shared TypeScript code in one monorepo |
| Technology baseline | FastAPI (Python 3.12) for the API and workers, Next.js and React Native (TypeScript) for clients, PostgreSQL with pgvector, AWS, LLM services |
| Application principle | Automate everything up to submission; submission requires explicit user approval |

**What changed from v1.0**

| Area | v1.0 | v2.1 |
| --- | --- | --- |
| Users | Single user | Any job seeker: self-service sign-up, several search profiles per user, plans and usage quotas |
| Resumes | One master resume | One resume library per user: a primary resume and up to 3 variations (for example AI, cloud, leadership), plus a cover-letter library; the system recommends the best resume for each job and lists the changes it needs |
| Technology | Superseded | FastAPI (Python) API and workers; Next.js web and React Native (Expo) mobile sharing TypeScript code in one monorepo |
| Alert ingestion | Gmail/Outlook API | A personal forwarding address per user by default; Gmail/Outlook OAuth optional |
| Clients | Web dashboard; email notifications | Web plus native mobile app; push, in-app and email notifications |
| Notifications | Score-based alerts and digests | Score alerts plus action-required alerts naming the specific blocker (screening questions, profile gap, cover letter, assessment) |
| Apply flow | Open the original URL; user submits manually | Readiness classification into Ready, Needs input or Manual only; one-tap assisted submit in Phase 2 for permitted channels |
| JD enrichment | Alert-email content only | Alert email plus a browser-extension capture of the full job description from the page the user is viewing |
| Matching | Weighted 0–100 score | Same weights, plus hard filters, embedding similarity and a defined "strong match" rule |
| Eventing | Queue for ingestion | Queue plus domain events that drive notifications and real-time UI updates |

## Business requirements

The product must cut manual job searching to a few minutes a day. You should only need to act when a strong match appears or an application is blocked on your input.

**Objectives**

- Offer the product to any job seeker through self-service sign-up, with each user's data fully isolated.
- Consolidate LinkedIn, Naukri and later sources into one deduplicated job pipeline per user.
- Rank jobs with explainable AI matching instead of keyword filters.
- Tell each user, on phone and web, exactly which jobs are worth applying for and what is blocking each one.
- Prepare tailored application material that never departs from the user's own profile facts.
- Keep a complete history of what was applied for, when, and with which resume version.
- Keep final submission under user control to avoid account bans, compliance problems and accidental applications.
- Keep the per-user running cost low enough to support a free tier.

**Scope**

| In scope: MVP | In scope: Phase 2 | Out of scope |
| --- | --- | --- |
| Self-service sign-up, login, onboarding wizard | Browser extension: JD capture and form autofill | Unattended bulk auto-apply |
| Multi-tenant data isolation; several search profiles per user | One-tap assisted submit for Greenhouse and Lever | Automated submission on LinkedIn or Naukri from the hosted service |
| Personal forwarding address for alerts; optional Gmail/Outlook OAuth | Paid plans and billing (free plan only during beta) | CAPTCHA solving or anti-bot evasion |
| LinkedIn and Naukri alert-email parsers | Outcome-based ranking feedback | Storing job-portal passwords |
| Extraction, normalization, deduplication | Interview preparation | Recruiter or agency accounts applying for other people |
| Hard filters plus 0–100 explainable score | Calendar integration for interviews and follow-ups | Inventing salary or role data the source does not give |
| Readiness classification and blocker detection | Additional sources and regions |  |
| Resume tailoring, cover letters, screening-answer drafts |  |  |
| Web dashboard and mobile app with push notifications |  |  |
| Application tracker and audit trail |  |  |
| Consent, data export and account deletion |  |  |
| Admin console, usage quotas, support tooling |  |  |

**Personas**

| Persona | Needs | System capability |
| --- | --- | --- |
| Job seeker (mobile) | Know immediately when a strong match or a blocker appears; approve or dismiss on the go | Push notifications, match card, approve/ignore/snooze actions, quick answers to blockers |
| Job seeker (web) | Set up profiles, review fit, edit tailored documents, answer screening questions, track applications | Onboarding, dashboard, job detail, application workspace, tracker |
| New user | Get from sign-up to first matched jobs in under 15 minutes | Onboarding wizard: resume upload and parsing, profile review, alert setup guide, forwarding test |
| Platform administrator | Keep sources, parsers and costs healthy across all users; handle support and data requests | Admin console: parser health, per-user usage, quotas, reprocessing, support view without resume content, deletion requests |

**Functional requirements**

| ID | Area | Requirement | Phase |
| --- | --- | --- | --- |
| FR-01 | Accounts | Self-service sign-up and login with email and password: sign-up asks for the password twice (both must match) and every password field has a show/hide button; email verification; MFA optional. Google and Microsoft sign-in are in the MVP (milestone 4): sign-in only (OpenID Connect, scopes openid, email and profile), never mailbox access. A provider sign-in whose verified email matches an existing account is linked to it, and the password keeps working | MVP |
| FR-02 | Onboarding | Guided setup: upload resume, review the parsed profile, create LinkedIn/Naukri alerts, set up forwarding, confirm the first alert arrived | MVP |
| FR-03 | Search profiles | Each user can create several search profiles (for example, VP Engineering and CTO-track), each with its own constraints, weights, target roles and strong-match threshold; a profile can name a preferred resume from the user's library (the library is no longer per profile) | MVP |
| FR-04 | Profile | Structured profile: experience, skills, domains, leadership scope, target roles, locations, CTC, notice period, work authorization, dealbreakers. Built either by uploading a resume (the extracted facts are shown for review and editing before saving) or by manual entry | MVP |
| FR-05 | Resume | One resume library per user, in the profile section: one primary resume and up to 3 variations, each labelled with its focus (for example AI/GenAI, cloud and architecture, leadership and delivery) and parsed into structured data; the user can change which resume is primary | MVP |
| FR-06 | Answer bank | Reusable answers to common screening questions, shared across a user's profiles with per-profile overrides | MVP |
| FR-07 | Ingestion | Receive alerts at a personal forwarding address (default), or read them from Gmail/Outlook with OAuth (optional) | MVP |
| FR-08 | Parsing | Recognize LinkedIn and Naukri alert emails; extract title, company, location, experience, salary, job URL and source job ID | MVP |
| FR-09 | JD enrichment | Obtain the full job description through the browser extension, a public ATS posting, or manual paste; flag jobs scored on partial data | MVP (manual), Phase 2 (extension) |
| FR-10 | Normalization | Normalize titles, skills, locations, company names and employment attributes to a controlled taxonomy | MVP |
| FR-11 | Deduplication | Merge the same or near-same job across sources within a user's pipeline, keeping every source link. A clear duplicate (same listing or URL; same company, same normalised title and same city; or near-identical description) is merged into the existing job as "Also on …" and keeps its status. A potential duplicate (same company with a similar title, a different city, or a very similar description) is added with an amber "Possible duplicate of …" note and Same job / Different job buttons; the choice is remembered | MVP |
| FR-12 | Hard filters | Reject jobs that fail any hard constraint of a profile before AI scoring | MVP |
| FR-13 | Matching | Produce a 0–100 fit score per profile with factor scores, must-have gaps and a written rationale | MVP |
| FR-14 | Strong match | Classify a job as a strong match when it passes all hard filters, scores at or above the profile's threshold (default 85) and has no must-have gap | MVP |
| FR-15 | Readiness | Classify each strong match as Ready, Needs input or Manual only, and record each blocker | MVP |
| FR-16 | Notifications | Push, in-app and email notifications for strong matches, blockers, digests, follow-ups and failures, with per-channel and quiet-hour settings; one notification per job even when several profiles match | MVP |
| FR-17 | Tailoring | For each matched job, recommend the best-suited resume and cover letter from the user's libraries with a fit score and reason for every resume, list the specific changes that would improve the recommended one, and generate the tailored variant, cover letter and draft answers once the user accepts; all grounded only in the user's profile facts | MVP |
| FR-18 | Apply | Open the application destination with an application pack; record the user's submission | MVP |
| FR-19 | Assisted submit | Submit on the user's one-tap approval for permitted ATS channels, with daily caps and a full audit record | Phase 2 |
| FR-20 | Tracker | Track status from Saved through Applied, Interview and Offer to Rejected/Closed, with the exact document versions used | MVP |
| FR-21 | Search | Filter by profile, score, role, source, location, company, date, readiness and status | MVP |
| FR-22 | Feedback | Capture Interested, Ignore, Applied and Not a fit, with a reason; feed into ranking | MVP |
| FR-23 | Plans and quotas | Plans limit profiles, scored jobs per month and generated packs; usage shown to the user; free plan during beta | MVP (quotas), Phase 2 (billing) |
| FR-24 | Consent and data rights | Capture consent at sign-up; let users export all their data and delete their account, with deletion completed within 30 days | MVP |
| FR-25 | Admin console | Parser health, per-user usage and cost, quota overrides, reprocessing, support view that hides resume content | MVP |
| FR-26 | Audit | Record source, processing status, model and prompt versions, score and generated artifacts per user | MVP |
| FR-27 | Cover letters | A cover-letter library per user: up to 5 letters, one marked as default; each uploaded or written in the app | MVP |
| FR-28 | Jobs by match | The Jobs list opens on "Top matches" (Strong and Good, highest score first). Low and filtered jobs go to an "Other jobs" tab with the reason; jobs not yet scored have their own tab. Every scored job shows the primary resume's match %, plus the best resume's % when a different resume fits better | MVP |
| FR-29 | Model provider | Use the Claude API at launch through one model gateway; any task can be moved to a self-hosted model later. Compare quality and cost on logged calls before switching a task | MVP (gateway), Phase 2 (self-hosted) |
| FR-30 | Job queues | Jobs page tabs: Top matches, Other jobs, Not scored yet, Applied, Expired, Ignored. Mark as Applied (next to Ignore, on the job card and job page) moves a job to Applied with the date; it can be undone. Mark as expired moves a job to Expired. A job shows an amber "May have expired" after N days and moves to Expired after M days, counted from the alert; the super admin sets N and M (proposed 30 and 45). Applied jobs never expire automatically; an expired job can be moved back | MVP (milestone 5) |
| FR-31 | To-dos | Everything the user must do on a job is shown in amber with a button that fixes it: description missing, screening questions unanswered, missing profile facts (notice period, CTC), a required cover letter, a follow-up due, may have expired. Job cards show "N to do" | MVP (milestone 5) |
| FR-32 | Match explanation | The job page lists skills the user has and skills missing, and the points lost per factor (for example "Skills −8 · Location −3 · Experience −2"). "I have this skill" adds the skill to the profile and re-scores; it is for skills the user really has, because tailored resumes may claim only what the profile supports | MVP (milestone 5) |
| FR-33 | Job contacts | The job page shows the recruiter name when the email has one (Naukri recruiter invites; LinkedIn alerts never name a person) and a Contact box where the user pastes a name, LinkedIn profile link or email they found themselves. FitFirst saves it, never opens job pages and never messages anyone. Networking reuses these contacts | MVP (milestone 5) |
| FR-34 | Admin settings | Shared app settings (such as the two expiry periods) are readable by every user and changeable only by the super admin on an admin settings page, without a redeploy; every change is logged. An account becomes super admin only through the command make admin EMAIL=…, never from inside the app | MVP (milestone 5) |
| FR-35 | Networking | Import the user's own LinkedIn connections export (ZIP or CSV); show warm paths at the companies of Top matches and applied jobs ("People you know at …"); up to 5 suggestions a day (follow-ups, then warm, then target roles with a people-search link the user opens); template notes under 300 characters; respect a 100-a-week invitation limit; outreach tracker from sent to referral. FitFirst never logs in to LinkedIn, sends invitations or scrapes | MVP (milestone 7) |
| FR-36 | WhatsApp and Teams | Notifications by WhatsApp through Meta's official WhatsApp Business (Cloud) API only, to a number verified with a one-time code; optional Microsoft Teams through a Workflows webhook link the user pastes (stored encrypted). Same rules, quiet hours and caps as other channels | MVP (milestone 6) |
| FR-37 | More sources | Company job feeds (Greenhouse, Lever, Ashby, SmartRecruiters) for companies the user lists, checked daily; the Adzuna India API; alert-email parsers for iimjobs, hirist, Indeed, Foundit, Instahyre and Glassdoor. India first | Milestone 9 |
| FR-38 | Marketing and subscriptions | A public marketing home page; paid plans for India with Razorpay; the US market later | Milestones 10, 11, 12 |

**Non-functional requirements**

| NFR | Requirement |
| --- | --- |
| Latency | A new alert email is scored and, if it is a strong match, notified within 5 minutes; a push notification is delivered within 30 seconds of the event |
| Availability | 99.5% monthly for the MVP |
| Scalability | 10,000 registered users and 500,000 alert emails a month without redesign; workers scale horizontally and are partitioned by user |
| Tenant isolation | No query can return another user's data: row-level security in PostgreSQL keyed on user\_id, plus authorization checks in the API |
| Security | TLS in transit; encryption at rest; OAuth tokens in AWS Secrets Manager; no portal passwords |
| Privacy | Compliance with India's Digital Personal Data Protection Act 2023 and its Rules: consent, purpose limitation, export and deletion; store only parsed job data from emails, not whole mailboxes |
| Fairness | One user's load cannot slow another's: per-user rate limits and fair queueing in workers |
| Explainability | Every score shows factor scores, gaps and rationale |
| Reliability | Idempotent ingestion; retries with backoff; dead-letter queue; manual reprocessing |
| Observability | Centralized logs, metrics, traces, parser-health and per-user LLM-cost dashboards |
| Maintainability | Each source adapter and parser is versioned and independently replaceable |
| Compliance | Respect source terms and mailbox scopes; no automation of a job portal from the hosted service |
| Cost | LLM spend tracked per user, per job and per day, with per-plan quotas and a platform-wide monthly ceiling |

## Multi-user product model

Every user is an isolated tenant with their own account, search profiles, alert inbox and application history. The only shared data is the public job catalog, where each posting is extracted once and reused for every user who receives it. That keeps the per-user LLM cost low enough for a free plan.

**Account structure**

| Level | Holds | Shared or private |
| --- | --- | --- |
| User account | Login, plan, consent record, devices, answer bank, resume library (primary + up to 3 variations), cover-letter library (up to 5), forwarding address, notification settings | Private |
| Search profile (one or more per user) | Hard constraints, weights, target roles, strong-match threshold, preferred resume | Private |
| Job catalog | Public posting data, extracted JD structure, embedding, source links | Shared: extracted once per job |
| User pipeline | Which jobs reached this user, scores per profile, readiness, blockers, applications, feedback | Private |

**Roles and plans (added 17 November 2026)**

| Role | Who | Can do |
| --- | --- | --- |
| Job seeker | Everyone who signs up | Uses the app while a plan or coupon period runs; sees every job from the shared job sources in Jobs → From sources |
| Admin | Invited by the super admin | Manages Job sources (the shared list of companies BrewMyJob reads); never needs a plan |
| Super admin | The product owner | Everything an admin can, plus Admin settings and invites |

One plan with four periods: 1 month ₹199, 3 months ₹500, 6 months ₹750, 1 year ₹1,200. The super admin invites
people by email; a job seeker's invite can carry a coupon of 1 or 3 free months. Without a period a job seeker
sees only the plans. Online payment (Razorpay) comes later. Design: `docs/plan-roles-and-plans.md`.

**How each user's alerts get in**

| Option | How it works | Trade-off |
| --- | --- | --- |
| Personal forwarding address (default) | Each user gets a private inbound address (for example alerts-7f3k@in.yourdomain). A mail filter forwards only LinkedIn and Naukri alert emails to it. The system spots the mailbox's forwarding-confirmation email and shows the code in onboarding | No mailbox access and no Google verification; the user spends about 2 minutes setting up a filter |
| Gmail OAuth (optional) | Read-only, limited to one label | Gmail read scopes are restricted: a public app needs Google verification and an annual third-party security assessment (as of mid-2026; confirm). Offer only after passing it |
| Outlook OAuth (optional) | Microsoft Graph Mail.Read | Needs Microsoft publisher verification; a lighter process than Google's |

Inbound mail is accepted only when SPF and DKIM pass for the LinkedIn and Naukri sender domains, plus the one-time forwarding-confirmation message. Anything else is dropped.

**Onboarding flow** (target: first scored job within 24 hours of sign-up, since alerts arrive daily)

1. Sign up with email, Google or Microsoft, and accept the consent notice.
2. Upload a resume. The system parses it into a draft profile.
3. Review the profile and set hard constraints. This creates the first search profile.
4. Create LinkedIn and Naukri alerts, using an in-app guide that suggests keywords from the profile.
5. Set up forwarding, and send a test alert to confirm it arrives.
6. Install the mobile app and allow push notifications.

**Plans and quotas (proposed)**

| Plan | Search profiles | LLM-scored jobs per month | Application packs per month | Apply |
| --- | --- | --- | --- | --- |
| Free | 1 | 300 | 10 | Assisted manual |
| Pro | 3 | 2,000 | 60 | Assisted manual; one-tap submit for Greenhouse/Lever (Phase 2) |

Hard filters and the embedding pre-screen cost no LLM calls, so only jobs that reach LLM scoring count against the quota. Prices are open: everyone is on the free plan during the beta, and billing (Razorpay for India) arrives in Phase 2.

**Apply automation in a multi-user product.** The hosted service will not automate submission on LinkedIn or Naukri for any user. Running a bot across many members' accounts would breach both portals' terms at scale and expose the business, not just individual accounts. The opt-in assisted mode from the single-user design is withdrawn. Users get the browser extension's autofill instead, which runs in their own browser and submits only when they click. One-tap submit remains for ATS channels that permit it.

**Compliance and trust**

- **DPDP Act 2023 and its Rules:**
  - A consent notice at sign-up that lists each purpose.
  - Data export (JSON and PDF) and account deletion.
  - A grievance contact and a breach-notification procedure.
- **Data residency:** host in AWS Mumbai (ap-south-1).
- **LLM provider:** the Claude API directly at launch, through one gateway so any task can move to a self-hosted model later. The provider must not train on user data. Re-check data residency before public launch.
- **Terms of service:** users are responsible for what they submit. The system never submits without their action.
- **Admin access:** support staff see metadata, never resume content or answers. Viewing as a user requires that user's consent and is audited.

## Application screens

Eight screens cover the journey from sign-up to tracking applications: seven on the web and three views in the mobile app. These are design mockups, since the application is not built yet. Companies, jobs, scores and resume lines are illustrative sample data, and the requirement IDs map to the functional requirements above.

**1. Sign-up and onboarding** (FR-01, FR-02, FR-07)

&#91;image: Onboarding: setup steps, private forwarding address with Gmail filter instructions, live check of incoming alerts\]

A new user works through six steps:

1. Create an account.
2. Upload a resume.
3. Review the parsed profile.
4. Create job alerts.
5. Forward the alerts.
6. Install the mobile app.

The forwarding step gives each user a private address and the exact mail filter to create. The live-check panel catches Gmail's confirmation code and confirms when the first test alert arrives. This screen is what makes the product usable by anyone without mailbox access.

**2. Dashboard** (FR-12, FR-15, FR-16, FR-20)

&#91;image: Dashboard: KPIs, action required, ready to apply, pipeline, follow-ups\]

The landing page answers one question: what needs me today? Blocked strong matches come first, each with its blockers listed. Ready jobs come next, followed by today's pipeline counts from alerts received to strong matches, follow-ups due and a preview of the evening digest.

**3. Job detail** (FR-09, FR-11, FR-13, FR-15, FR-17, FR-28)

&#91;image: Job detail: score breakdown, strengths and gaps, readiness blockers, captured JD\]

The top of the screen shows the suggested resume and cover letter, each with its match %. Below that, the screen shows how a job's score breaks down by factor and weight, with the model, prompt and profile versions behind it. It also lists strengths and gaps, and shows LinkedIn and Naukri postings merged into one job. The readiness panel holds each blocker with a drafted answer that can be accepted, edited or saved to the answer bank.

**4. Application workspace** (FR-05, FR-17, FR-18)

&#91;image: Application workspace: ranked resumes with coverage, suggested changes with sources, a gap that is not added, screening answers, claim check\]

The application pack for one job. The system ranks every resume in the user's library against the job's themes and recommends one: here the AI & GenAI version covers 94% against 81% and 72%. Below the ranking, it lists suggested changes, each citing the profile fact or library resume it draws on, for the user to tick or skip. Requirements the profile cannot support are shown as gaps and never added. A claim check must pass before the user opens the portal with autofill or marks the job applied.

**5. Profile and preferences** (FR-03, FR-04, FR-05, FR-06, FR-12, FR-27)

&#91;image: Profile: search-profile switcher, hard constraints, scoring weights, resume library with usage and interview counts, answer bank\]

A switcher at the top selects the search profile being edited, and new profiles can be added within the plan's limit. Hard constraints decide which jobs are discarded before any AI cost is incurred. Weight sliders must total 100%. The resume library holds one primary resume and up to 3 variations, each with its focus, how often it was sent and how many interviews it led to; the user can change which one is primary. The cover-letter library holds up to 5 letters, one of them the default. "Fill from resume" builds the candidate profile from an uploaded resume, for review before saving. The answer bank is shared across profiles and flags answers older than 30 days. Saving a profile creates a new version and re-scores open jobs.

**6. Application tracker** (FR-20)

&#91;image: Application tracker: kanban from Interested to Offer/Closed\]

The tracker is a board running from Interested through Needs input, Ready, Applied and Interview to Offer/Closed. Each card keeps the exact resume, cover letter and answers used, and shows the next action.

**7. Sources, notifications and apply modes** (FR-07, FR-16, FR-19)

&#91;image: Settings: alert inbox, job sources with parser health, apply modes, notification rules, limits and plan usage\]

This screen covers the user's private forwarding address (which can be rotated) and per-source parser health. It holds the apply modes: one-tap submit for ATS channels, and extension autofill for LinkedIn and Naukri, where the user always clicks Submit. It also holds the event-by-channel notification matrix, quiet hours, push cap, and plan usage against quota.

**8. Mobile app** (FR-15, FR-16, FR-19)

&#91;image: Mobile: push notifications, match card, answering a blocker\]

The mobile app has three views:

- **Push notifications:** one for each strong match, blocker and follow-up.
- **Match card:** the job with reasons it fits, plus Approve, Ignore and Snooze.
- **Blocker flow:** the user answers with a draft or a single tap and the job is re-checked.

In the MVP, Approve opens the pack on the laptop. In Phase 2 it submits through permitted channels.

## Platform constraints, apply policy and risks

Neither LinkedIn nor Naukri offers a candidate-side API for job search or applying, and both prohibit automated access in their terms. Job-alert emails are therefore the primary, sanctioned ingestion channel for every user. The hosted service does not automate submission on either portal. This reflects the platforms' terms as understood in mid-2026 and must be re-checked before launch.

| Source | Discovery | Full JD | Submission |
| --- | --- | --- | --- |
| LinkedIn | Job-alert emails (title, company, location, link) | Browser-extension capture from the page the user opens, or manual paste | User submits; optional extension autofill in the user's own browser |
| Naukri | Job-alert emails (title, company, experience, CTC band, location, link) | Browser-extension capture or manual paste | User submits; optional extension autofill in the user's own browser |
| Greenhouse | Public job-board API per company | Included, with the application's custom questions | Phase 2 candidate for one-tap assisted submit, subject to each employer's board settings |
| Lever | Public postings API per company | Included | Phase 2 candidate for one-tap assisted submit |
| Company career sites | Future adapters | Varies | User submits |
| Mailbox | Personal forwarding address (default); Gmail or Outlook OAuth optional after verification | n/a | n/a |

**Apply modes**

| Mode | What the system does | What the user does | Phase |
| --- | --- | --- | --- |
| Assisted manual | Builds the application pack, opens the job URL, autofills via the extension where the form allows | Reviews and clicks Submit; marks Applied (the extension can confirm automatically) | MVP |
| One-tap assisted | Prepares and validates every field, sends a push card; submits through the official ATS channel after approval | Taps Approve on phone or web | Phase 2 (Greenhouse, Lever) |
| Automated submit on LinkedIn/Naukri | Not offered by the hosted service | n/a | Never |
| Unattended bulk apply | Not supported | n/a | Never |

The original goal, to apply automatically when a job matches exactly, is met in two ways. On ATS channels it becomes one-tap approval. On LinkedIn and Naukri it becomes extension autofill, where the system fills the form and the user clicks Submit. Either way the user spends seconds per application, no account is put at risk, and the business does not operate a bot on those portals.

**Risks and mitigations**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| LinkedIn/Naukri treat the product as automation | High | No portal automation from the service; ingestion only from emails users forward; autofill runs in the user's own browser on their click |
| Gmail OAuth verification delays or fails | Medium | Forwarding address is the default and needs no mailbox access; offer Gmail OAuth only after verification passes |
| Alert emails lack the full JD, weakening matching | High | Score provisionally on email data and flag it; enrich via extension, ATS posting or paste before a strong-match notification |
| Alert-email format changes break parsers for all users at once | High | Versioned parsers, golden-sample tests, parser-health alerts, LLM fallback extraction, bulk reprocessing |
| Cross-tenant data leak | High | Row-level security, per-user encryption context, automated isolation tests in CI, penetration test before public launch |
| AI invents experience in tailored documents | High | Grounding only in profile facts; claim-to-source check; mandatory user review |
| LLM cost grows faster than users pay | High | Shared job catalog (extract once), hard filters and embeddings before LLM calls, model routing, per-plan quotas |
| Abuse: spam sign-ups or inbound-address misuse | Medium | Email verification, rate limits, SPF/DKIM checks on inbound mail, sender allow-list |
| Personal data regulation (DPDP) | High | Consent capture, export and deletion, India data residency, grievance and breach procedures |
| Duplicate jobs across sources | Medium | Layered exact, fuzzy and semantic deduplication |
| Notification fatigue | Medium | Only strong matches and blockers push immediately; everything else goes into a daily digest; quiet hours |

## Solution architecture

The backend is a set of FastAPI (Python) services and queue-driven workers on AWS. Each pipeline stage publishes a domain event, and a single notification service turns those events into push, real-time web and email messages. The web app, mobile app and browser extension all talk to one API.

&#91;embedded content: system architecture · 5 workers, 3 clients\]

Alerts enter at the top-left and pass through five workers. Each worker publishes to the event bus, and the notification service is the only component that contacts the user unprompted.

| Component | Responsibility | Technology |
| --- | --- | --- |
| Web app | Public site, sign-up, onboarding, dashboard, job detail, application workspace, profiles and resume library, tracker, settings | Next.js (React, TypeScript), WebSocket client |
| Mobile app | Match cards, blocker prompts, resume recommendation review, approve/ignore/snooze, quick answers, tracker | React Native with Expo (iOS and Android), Expo Push |
| Shared client packages | API client and types generated from the FastAPI OpenAPI schema, validation, data hooks, design tokens | TypeScript monorepo (Turborepo + pnpm), TanStack Query, zod |
| Browser extension | Capture the full JD from the open job page; autofill application forms from the application pack; confirm submission | Chrome/Edge Manifest V3, TypeScript, shared API client |
| Identity and accounts | Sign-up, login (email and password; Google and Microsoft sign-in from milestone 4), MFA, sessions, consent records, account deletion | Built-in accounts in FastAPI (Argon2id, JWT), with Google and Microsoft through OpenID Connect; Amazon Cognito optional later for MFA at scale |
| API | Business APIs, per-user authorization, quotas, real-time WebSocket feed | FastAPI (Python 3.12), Pydantic v2, SQLAlchemy 2.0 (async) |
| Inbound email | Receive forwarded alerts at each user's private address; verify SPF/DKIM; map address to user; store raw message briefly in S3 | Amazon SES receiving, S3, Lambda (Python) trigger |
| Ingestion worker | Turn inbound messages (or OAuth mailbox changes) into idempotent AlertReceived events, tagged with user\_id | Python worker on SQS; Gmail API watch and Graph delta queries for OAuth users |
| Job processing worker | Parse alerts; look up or create the shared catalog job; extract JD structure once; link the job to the user's pipeline | Python worker, versioned parser per source |
| Matching service | Per profile: hard filters, embeddings pre-screen, LLM scoring with rationale and gaps; quota checks before LLM calls | Python worker, pgvector, LLM SDK with structured output |
| Resume recommender | Score every resume in the profile's library against the JD's themes; recommend one; list suggested changes and gaps | Python worker, pgvector, LLM |
| Readiness service | Classify strong matches as Ready, Needs input or Manual only; detect blockers | Python worker, ATS question APIs, profile and answer-bank checks |
| Document service | Resume parsing; tailored resume, cover letter, screening-answer drafts, application pack | Python worker; pdfplumber and python-docx to parse; docxtpl and WeasyPrint to render |
| Apply worker (Phase 2) | Submit approved applications through permitted ATS channels only | Greenhouse and Lever APIs |
| Notification service | Subscribe to domain events; apply each user's rules, quiet hours, digests; fan out to channels | Python worker, Expo Push (FCM/APNs), WebSocket via Redis pub/sub, Amazon SES |
| Plans, quotas and billing | Plan limits, usage metering per user, quota enforcement; billing in Phase 2 | PostgreSQL usage tables, Redis counters; Razorpay (Phase 2) |
| Admin console | Parser health, per-user usage and cost, reprocessing, support view without resume content, data-rights requests | Next.js admin app, role-based access |
| Event and queue layer | Work queues with retries, dead-letter queues and per-user fair queueing; domain event bus | Amazon SQS (message group per user) + SNS |
| Data stores | Relational data with row-level security, vectors, cache, documents, secrets | RDS PostgreSQL + pgvector, ElastiCache Redis, S3, Secrets Manager, KMS |
| Observability | Logs, metrics, traces, parser health, LLM cost per user, client crashes | CloudWatch, OpenTelemetry, X-Ray, Sentry |

**Domain events**

| Event | Published by | Consumed by |
| --- | --- | --- |
| AlertReceived | Ingestion worker | Job processing worker |
| JobCreated / JobMerged | Job processing worker | Matching service, web real-time feed |
| JobScored | Matching service | Readiness service (strong matches), notification service (digest) |
| StrongMatchReady | Readiness service | Notification service (push), document service (pre-generate pack) |
| ActionRequired | Readiness service, apply worker | Notification service (push with blocker detail) |
| ApplicationPackReady | Document service | Notification service, web/mobile |
| ApplicationSubmitted / SubmissionFailed | Apply worker or extension confirmation | Tracker, notification service |
| ProcessingFailed | Any worker | Admin alert |

## Matching, readiness and notifications

A job reaches the user's phone only if it passes the hard filters, scores at least 85 and has no must-have gap. Even then, it arrives either as "ready to apply" or with a named blocker. "Exact match" is defined as this rule, not literal text equality, which almost no job would meet.

&#91;embedded content: match-to-notification flow · 3 gates, 3 readiness outcomes\]

Once a blocker is answered, the job goes back through the readiness check and, if nothing else is missing, moves to Ready.

**Matching pipeline**

1. Hard filters (deterministic, no LLM cost): location and work model, seniority floor, minimum CTC where stated, excluded companies and industries, job age, already applied.
2. Embedding pre-screen: cosine similarity between the job embedding and the profile embedding; jobs below a floor (initially 0.55, tuned in the pilot) are scored "low" without an LLM call.
3. LLM extraction: the JD is converted into a structured schema covering must-have skills, preferred skills, years required, leadership scope, domain, work model and CTC.
4. LLM scoring: factor scores against the weights below, must-have gaps, transferable strengths and a short rationale, as structured JSON.
5. Classification: Strong match (85 or more, no must-have gap), Good (70–84), Low (below 70). The thresholds are configurable.
6. Scoring on email data alone is marked provisional. It is re-scored when the full JD arrives, and a strong-match push waits for the full JD.

| Factor | Default weight |
| --- | --- |
| Role and seniority | 20% |
| Experience and leadership scope | 15% |
| Core product/engineering skills | 15% |
| Cloud and architecture | 10% |
| AI/GenAI | 10% |
| Industry/domain | 10% |
| Location/work model | 10% |
| Required/preferred skills | 5% |
| Compensation and other preferences | 5% |

Weights are configurable per profile. User feedback (Ignore, Not a fit with a reason) is logged against factor scores. Weights are re-tuned against the top-20 precision measured in the pilot, not adjusted automatically.

**Resume recommendation**

The match score rates the person against the job, and the resume choice decides how to present them. The two are kept separate, so a strong candidate is never marked down for sending the wrong resume. For every strong or good match:

1. The JD is broken into themes and their weight. For example, a role might be 50% AI/GenAI, 30% cloud platform and 20% leadership, with its must-haves listed.
2. Each resume in the profile's library is scored for coverage of those themes and must-haves, using embedding similarity plus an LLM check of which requirements each resume actually evidences.
3. The resumes are ranked. The best one is recommended with a one-line reason, such as "AI-focused version covers 9 of 10 must-haves; the cloud version covers 7."
4. The system lists suggested changes to the recommended resume, each tied to a fact in the profile:
   - bullets to move up
   - skills or achievements to surface from another version
   - JD keywords the profile supports
   - lines to cut for length
5. Requirements the profile cannot support are shown as gaps and are never added to a resume.
6. If no resume covers the job's main theme well (below 70% coverage), the system suggests a new resume version for that theme. This also appears in the weekly profile-gap digest when several jobs share the theme.

The user can accept all suggested changes, pick some of them, or switch to another resume. Accepted changes produce the tailored variant for that job. A tailored variant can also be saved back to the library as a new version. The system tracks which resume version was sent with each application, and later which ones led to interviews, to improve future recommendations.

**Readiness classification**

| Status | Condition | Examples of blockers recorded |
| --- | --- | --- |
| Ready | Every required field is answerable from the profile and answer bank; documents generated; channel supports assisted or manual apply | None |
| Needs input | One or more items need the user's answer or decision | Unanswered screening question; profile field missing (notice period, certification, work authorization); cover letter required and the draft needs review; expected-CTC question; must-have skill the profile does not show; JD still partial |
| Manual only | The application cannot be prepared or submitted by the system | Online assessment; redirect to an unsupported ATS; login or CAPTCHA wall; employer email-only application |

Where screening questions come from:

- Greenhouse publishes each job's custom questions through its job-board API, so readiness is known before the user opens the job.
- On LinkedIn and Naukri, questions are visible only inside the application form. The browser extension reports them when the user opens the form. Until then, readiness is shown as "questions unknown".
- Profile gaps are detected from the JD itself, for example a required certification or a stated notice-period limit.
- When the same gap appears in several strong matches, the system suggests a profile update rather than raising each case separately.

**Notification rules**

| Trigger | Channel | Content and actions |
| --- | --- | --- |
| Strong match, Ready | Immediate push + web | Score, title, company, top 3 reasons; Review pack, Approve (Phase 2), Ignore |
| Strong match, Needs input | Immediate push + web | Each blocker with a drafted answer; Answer now, Snooze, Ignore |
| Strong match, Manual only | Immediate push + web | Reason (for example, assessment required); Open job, Ignore |
| Good match (70–84) | Daily digest (push summary + email) | List with scores; open in app |
| Recurring profile gap | Weekly | "5 strong matches ask for X; add it to your profile?" |
| Application follow-up due | Push | Company, days since applied; Mark status |
| Submission failed (Phase 2) | Immediate push | Error and fallback link to apply manually |
| Parser or ingestion failure | Admin alert | Source, error rate, sample message ID |

Notification settings cover per-channel on/off, quiet hours (default 22:00–07:00 IST), a maximum of 10 immediate pushes a day, and digest time.

**Job and application states**

Job processing: Received → Parsed → Normalized → Scored → Readiness checked → Notified.

Application: Saved → Interested → Preparing → Needs input → Ready → Approved → Applied → Interview → Offer, ending at Rejected/Closed or Withdrawn.

## Data model, APIs, technology and security

One PostgreSQL database holds all relational data and the embeddings (pgvector). Every private table carries user\_id and is protected by row-level security. Only the job catalog (Job, JobSourceLink) is shared, because it holds public posting data. Documents live in S3 under per-user prefixes, and secrets live in Secrets Manager.

**Data model**

| Entity | Key fields | Scope |
| --- | --- | --- |
| User | id, email, name, timezone, status, plan\_id, inbound\_address, created\_at | Private |
| Consent | user\_id, notice\_version, purposes, granted\_at, withdrawn\_at | Private |
| CandidateProfile | user\_id, version, summary, years\_experience, experience, skills, domains, leadership\_scope, ctc\_current, ctc\_expected, notice\_period\_days, work\_authorization | Private: the user's facts, shared by their search profiles |
| SearchProfile | id, user\_id, name, version, target\_roles, locations, work\_model, constraints, dealbreakers, weights, threshold, default\_resume\_id, embedding, is\_active | Private |
| AnswerBank | user\_id, search\_profile\_id (null = all profiles), question\_key, question\_text, answer, last\_confirmed\_at | Private |
| Resume | id, user\_id, search\_profile\_id (optional), label, focus\_tags (for example ai, cloud, leadership), file\_uri, parsed\_json, theme\_coverage, embedding, version, is\_primary (one per user; up to 3 variations), source (uploaded or saved from a tailored variant), created\_at | Private: the resume library |
| CoverLetter | id, user\_id, label, text, file\_uri, file\_name, file\_kind, is\_default (one per user; up to 5 letters), version, created\_at | Private: the cover-letter library |
| ResumeRecommendation | user\_job\_id, search\_profile\_id, resume\_id, rank, coverage\_score, must\_haves\_covered, reason, suggested\_changes (type, text, profile\_source), primary\_resume\_score, recommended\_cover\_letter\_id, gaps, model\_version, created\_at | Private |
| MailboxConnection | user\_id, provider, scope, token\_secret\_ref, watch\_expiry, last\_sync\_cursor | Private (OAuth users only) |
| SourceMessage | id, user\_id, channel (forward or OAuth), external\_message\_id (unique per user), source, parser\_version, received\_at, processing\_status | Private |
| Job | id, canonical\_url, title, company, location, work\_model, description, jd\_completeness, salary, experience, posted\_at, structured\_json, themes, embedding, fingerprint | Shared catalog |
| JobSourceLink | job\_id, source, source\_job\_id, source\_url, first\_seen\_at | Shared catalog |
| UserJob | user\_id, job\_id, source\_message\_id, first\_seen\_at, status | Private: which jobs reached this user |
| JobScore | user\_job\_id, search\_profile\_id, profile\_version, model\_version, prompt\_version, overall\_score, factor\_scores, must\_have\_gaps, rationale, is\_provisional, band | Private |
| Readiness | user\_job\_id, status, blockers (type, question, draft\_answer, resolved), checked\_at | Private |
| Application | id, user\_id, job\_id, search\_profile\_id, status, mode, approved\_at, applied\_at, base\_resume\_id, tailored\_document\_id, accepted\_changes, cover\_letter\_id, answers\_snapshot, notes | Private |
| GeneratedDocument | id, user\_id, job\_id, type, base\_resume\_id, content\_uri, model\_version, prompt\_version, created\_at | Private |
| Notification | id, user\_id, event\_type, job\_id, channel, sent\_at, opened\_at, action\_taken | Private |
| DeviceRegistration | user\_id, platform, expo\_push\_token, last\_seen\_at | Private |
| UserFeedback | user\_id, job\_id, action, reason, created\_at | Private |
| Plan | id, name, max\_profiles, max\_resumes\_per\_profile, max\_scored\_jobs, max\_packs, features | Platform |
| UsageCounter | user\_id, period, scored\_jobs, packs, llm\_tokens, llm\_cost | Private |
| DataRequest | user\_id, type (export or delete), status, requested\_at, completed\_at | Private |
| AuditEvent | user\_id, actor, event\_type, entity\_id, timestamp, metadata | Private |

**Deduplication.** Duplicates are matched in order of confidence: canonical URL, source job ID, normalized company + title + location, description fingerprint, then semantic similarity (cosine 0.92 or more, tuned in the pilot). The richest and freshest record is kept as the master, and every source link is retained.

**AI guardrails.**

- Generated content may use only profile, resume and JD facts.
- A post-generation check maps each claim in a tailored resume or cover letter back to a profile source and blocks any claim it cannot map.
- Gaps are shown, not hidden.
- Model and prompt versions are stored with every score and document.
- No submission happens without explicit approval.
- The LLM is called with structured-output (JSON schema) mode for extraction and scoring.

**APIs (illustrative)**

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | /api/auth/signup, /api/auth/login | Account creation and login (email and password; Google and Microsoft sign-in through /api/auth/oidc/{provider}) |
| GET / PUT | /api/me | Account, plan, usage, inbound forwarding address |
| POST | /api/me/consent | Record or withdraw consent |
| POST | /api/me/data-requests | Request data export or account deletion |
| GET / POST / PUT / DELETE | /api/profiles | Manage search profiles |
| GET / PUT | /api/candidate | Read or update the user's candidate facts |
| GET / PUT | /api/answer-bank | Read or update reusable screening answers |
| GET / POST / PATCH / DELETE | /api/profiles/{id}/resumes | Manage the resume library: upload, label, set focus tags, set default |
| GET | /api/jobs/{id}/resume-recommendations | Ranked resumes for this job with coverage, reason, suggested changes and gaps |
| POST | /api/jobs/{id}/resume-recommendations/apply | Apply chosen changes to a chosen resume; optionally save the result to the library |
| GET | /api/jobs | Search and filter by profile, score, band, readiness, source, status |
| GET | /api/jobs/{id} | Job detail, scores per profile, rationale, readiness and blockers |
| POST | /api/jobs/{id}/feedback | Interested, Ignore, Not a fit (with reason) |
| POST | /api/jobs/{id}/jd | Submit a captured or pasted full JD (extension or manual) |
| POST | /api/jobs/{id}/application-pack | Generate the tailored resume, cover letter and answers |
| POST | /api/jobs/{id}/blockers/{blockerId}/resolve | Answer a blocker (optionally save it to the answer bank) |
| POST | /api/applications/{id}/approve | One-tap approval (Phase 2) |
| GET / POST / PATCH | /api/applications | Tracker: list, create, update status |
| GET / PUT | /api/notifications/settings | Channels, quiet hours, caps, digest time |
| POST | /api/devices | Register an Expo push token |
| POST | /api/integrations/mailbox/connect | Start optional Gmail/Outlook OAuth |
| POST | /api/onboarding/forwarding-test | Check that a test alert reached the user's address |
| GET | /api/admin/... | Admin console: parser health, usage, reprocessing, data requests (admin role only) |
| WS | /ws/events | Real-time feed over WebSocket, scoped to the signed-in user |

FastAPI publishes the OpenAPI schema for these endpoints. The web app, mobile app and extension all use a TypeScript client generated from that schema, so a change to the API shows up as a type error in every client before release.

**Technology stack**

| Area | Choice |
| --- | --- |
| Web | Next.js (React, TypeScript, App Router): public and sign-up pages server-rendered for search engines; the signed-in app as client components |
| Mobile | React Native with Expo (iOS and Android): Expo Router, EAS Build, over-the-air updates, Expo Push |
| Code sharing | Monorepo (Turborepo + pnpm): generated API client and types, zod validation, TanStack Query data hooks, design tokens and copy shared by web, mobile and extension; screens built natively for each platform |
| Admin app | Next.js in the same monorepo, role-restricted |
| Extension | Chrome/Edge Manifest V3, TypeScript, shared API client |
| API | FastAPI (Python 3.12), Pydantic v2, Uvicorn behind Gunicorn; the OpenAPI schema is the contract for every client |
| Workers | Python services consuming SQS (aioboto3); Celery with an SQS broker is an acceptable alternative |
| Data access | SQLAlchemy 2.0 (async) with Alembic migrations; row-level security through a per-request session setting (app.user\_id) |
| Real time | FastAPI WebSockets, with Redis pub/sub to fan out across API instances; Server-Sent Events as fallback |
| Identity | Built-in accounts (Argon2id passwords, JWT) with Google and Microsoft sign-in via OpenID Connect (sign-in scopes only); Amazon Cognito optional later for MFA |
| Database | Amazon RDS PostgreSQL 16 with pgvector and row-level security |
| Cache | Amazon ElastiCache (Redis): rate limits, quota counters, WebSocket fan-out |
| Queues and events | Amazon SQS (FIFO message groups per user for fairness), SNS |
| Inbound email | Amazon SES receiving with a dedicated subdomain |
| AI | LLM through its Python SDK with JSON-schema structured output; embeddings model; model routing (small model for extraction, larger for scoring, resume recommendation and writing) |
| Document processing | pdfplumber and python-docx to parse resumes; docxtpl (DOCX) and WeasyPrint (PDF) to render tailored resumes |
| Mailbox OAuth (optional) | Gmail API with push watch; Microsoft Graph delta queries |
| Push | Expo Push service (delivers through FCM and APNs) |
| Email out | Amazon SES |
| Billing (Phase 2) | Razorpay subscriptions (India); Stripe if international users are added |
| Storage | Amazon S3 with per-user prefixes and signed, expiring URLs |
| Hosting | ECS Fargate for FastAPI, workers and Next.js; CloudFront in front; region ap-south-1 (Mumbai) |
| Observability | CloudWatch, OpenTelemetry (Python and JavaScript), X-Ray; Sentry for web and mobile errors |
| CI/CD | GitHub Actions; EAS for mobile builds and store submission |
| Testing | pytest, Schemathesis contract tests from the OpenAPI schema, golden-sample parser tests, tenant-isolation tests, Playwright (web), Maestro (mobile), Locust load tests |

**Why this stack**

- **FastAPI and Python.** The heaviest work is AI and documents: LLM calls, embeddings, resume parsing and rendering. Python has the strongest libraries for all of it, so the API and workers share one language and one data model (Pydantic).
- **FastAPI's OpenAPI schema** gives typed clients for free, which keeps three front ends in step with the API.
- **Next.js plus React Native, rather than one codebase for both.** The web app needs dense desktop layouts (tracker board, side-by-side resume comparison, document editing) and server-rendered public pages. The phone needs fast native screens and push. Sharing logic, types and data hooks in a monorepo gets most of the reuse without compromising either.
- **Expo** removes native build setup, handles push for both platforms through one service, and ships fixes over the air without a store release.
- **Alternatives considered:**
  - Expo with React Native Web for both platforms: weaker desktop UX and SEO.
  - Flutter: no code sharing with the Next.js web app, and a second language for the team.

**Security**

- Tenant isolation: PostgreSQL row-level security on every private table, with the user id set per request from the verified token. API authorization checks as a second layer. CI tests that try cross-user access on every endpoint.
- Inbound addresses are random and unguessable, and can be rotated by the user. Mail is accepted only from allow-listed senders with passing SPF/DKIM.
- Optional mailbox OAuth uses minimum scopes (read-only, label-limited). Tokens are held in Secrets Manager. No mailbox or portal passwords are stored.
- TLS everywhere. RDS and S3 are encrypted at rest with KMS, and resume documents carry a per-user encryption context.
- Signed, expiring document URLs. Rate limits per user on the API and AI endpoints.
- Logs never contain resume content, answers or tokens.
- Data export and account deletion, completed within 30 days. Source messages are retained for 90 days by default.
- WAF in front of CloudFront and the API. GuardDuty and Security Hub enabled. IAM least privilege per service.
- Admin roles with audited access. Support staff cannot read resume content. Viewing as a user requires that user's consent.
- A third-party penetration test before public launch.

**Resilience.** Every source message carries an idempotency key. Transient errors are retried with exponential backoff, and repeated failures go to a dead-letter queue. Source URLs are kept even when parsing partially fails. Failed messages can be reprocessed from the dashboard.

## Legal and platform compliance (4 November 2026)

This section records how FitFirst / BrewMyJob stays within job-portal terms and Indian law. It is a product position, not legal advice; the items marked for counsel must be reviewed by an Indian lawyer before paid launch.

### Job portals (LinkedIn, Naukri and others)

- **No automated collection.** LinkedIn's User Agreement ("Don'ts") and Naukri's terms prohibit bots, crawlers and scraping of profiles or job data. FitFirst never logs in to a portal, never scrapes, never auto-applies, never auto-connects and never posts on a user's behalf. The practical risk of breaking this is the user's own account being restricted or banned.
- **Indian law.** Extracting data from a computer system without the owner's permission can be a civil wrong under section 43 of the Information Technology Act, 2000, and an offence under section 66 when done dishonestly or fraudulently. Not scraping keeps FitFirst outside both.
- **Content users post.** LinkedIn's India terms state that members who create or share content that breaks Indian law may face penalties under the IT Act, and that LinkedIn may report offences to the authorities. This applies to each user's own posts, invitations and messages. FitFirst only drafts notes; the user edits and sends them, and the claim check keeps drafts to what the user's resumes support.

### How each FitFirst feature stays compliant

| Feature | Source of data | Why it is allowed |
| --- | --- | --- |
| Job alerts | Alert emails the portal sends to the user, forwarded by the user | No access to the portal's systems |
| Networking | The user's own LinkedIn data export (Connections file), uploaded by the user | LinkedIn provides this data to the user; the file is not stored |
| Outreach | Notes drafted by FitFirst, sent by the user from their own account | FitFirst sends nothing |
| Company feeds (M9) | Public job-board APIs of Greenhouse, Lever, Ashby and SmartRecruiters | Published by the hiring systems for this purpose |
| Job-search APIs (M9) | Adzuna, Jooble, Careerjet with an API key | Used within each provider's API terms; commercial use to be confirmed |
| Browser extension (Phase 2) | The job page the user is viewing, captured on the user's click | No automation; reads only the open page |

### Terms of service and privacy

- The BrewMyJob terms of service will state that users are responsible for everything they send or post, including notes and documents drafted by BrewMyJob, and that they submit every application themselves.
- Personal data is handled under the Digital Personal Data Protection Act, 2023: consent at sign-up (already recorded), purpose limitation, data export and account deletion (milestone 8), and per-user isolation through row-level security.

### For review by counsel before paid launch

- [ ] Terms of service and privacy policy, including user responsibility for sent content.
- [ ] DPDP Act 2023 obligations: notice, consent, retention, grievance officer, breach reporting.
- [ ] Commercial use of Adzuna, Jooble and Careerjet data in a paid product.
- [ ] Use of third-party names (LinkedIn, Naukri) on the marketing page.

## Roadmap and status (2 November 2026)

Milestones 1, 5 and 7 are complete; 2, 3 and 4 are complete except the parts that wait for a domain or the Anthropic API key. The agreed order from here is 9 → 6 → 10 → 11, then 8 and 12. India is the first market; the US comes later.

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Foundation | Done |
| 2 | Ingestion (LinkedIn and Naukri alert emails) | Done, except the Cloudflare email worker (needs a domain) |
| 3 | Resumes and matching | Done with rules and Voyage similarity; Claude scoring waits for the Anthropic key |
| 4 | Readiness, answer bank, packs | Readiness and answer bank done; resume edits, packs and claim check wait for the Anthropic key; Google and Microsoft sign-in wait for a domain |
| 5 | Applications tracker and feedback: Applied and Expired queues, amber to-dos, match explanation, contacts, super admin settings (FR-30 to FR-34) | Done |
| 6 | Notifications, plus WhatsApp and optional Teams (FR-16, FR-36) | In progress: WhatsApp alerts and the in-app bell built; sending waits for the one-time Meta setup |
| 7 | Networking (FR-35) | Done; decisions under review |
| 8 | Release: Lightsail, backups, monitoring, security | Not started |
| 9 | More sources and duplicates, India first (FR-11, FR-37) | In progress: company boards and job APIs in the Job Search Service; duplicates built; Job sources for admins, one shared list (17 November) |
| 10 | Marketing home page (FR-38) | Built 3 November; legal and contact pages 9 November; the four plans 17 November; analytics and cookie consent left |
| 11 | Subscriptions, India first, Razorpay (FR-23, FR-38) | In progress: roles, plans, paywall and invite coupons built 17 November 2026; Razorpay later |
| 12 | US market | Later |
| 13 | Ask BrewMyJob: assistant, Not for me feedback, per-user learning | Part A built; B to E wait for the Anthropic key |
| 14 | Fill application forms: Apply kit, then a browser extension | Built; Add from Google results as a proof of concept |

**Milestone 5 — applications tracker.** Statuses Applied → Interviewing → Offer → Accepted, or Rejected, Withdrawn or No response at any point; the date applied, the resume and cover letter used, notes, follow-up dates and a history of every change; an Applications page with status and date, month or year filters and follow-ups due first. The dashboard step "Create a search profile" explains what a search profile does and that, without one, jobs are scored on the resume alone.

**Milestone 7 — networking, open for review:** the wording of the template notes, the target-role choices (CEO for C-level jobs, CTO or Chief Product Officer for senior tech or product jobs, otherwise Talent Acquisition) and the company-matching rules.

**Milestone 6 — open questions**

- [ ] A message for every job, or only strong matches, with the rest in an evening summary?
- [ ] WhatsApp through Meta directly, or through Twilio?
- [ ] Is the Teams account a work or personal one? (Teams Workflows webhooks are certain only for work or school accounts.)
- [ ] Move the Expo mobile app and push notifications to a milestone 6b?

WhatsApp constraints: Meta's free test number reaches up to 5 numbers; after that Meta charges per message, and messages FitFirst starts must use templates Meta approves. Reply buttons need a public webhook, so they wait for the domain. No unofficial WhatsApp Web automation, because it breaks WhatsApp's terms. Until there is a domain, the email digest is written to the log.

**Milestone 9 — sources.** LinkedIn, Naukri, Indeed, Glassdoor, Foundit, iimjobs, hirist, Instahyre and Wellfound offer no API that FitFirst can use, so they come in only through alert emails. Adzuna's free key has a daily limit, and commercial use must be confirmed with Adzuna (likewise Jooble and Careerjet) before users are charged.

Needed from the product owner for milestone 9: an Adzuna API key, a list of target companies for the company feeds, and 2–3 real alert emails from each new site (sanitised before they are used in tests).

## Delivery plan, acceptance and open questions

The multi-user MVP takes about 16–18 weeks to reach a closed beta. The author pilots it first, then 25–50 invited users join before any public launch. Multi-tenancy is built in from Phase 1, because retrofitting isolation later is the costliest change in this design.

| Phase | Scope | Indicative duration | Exit criterion |
| --- | --- | --- | --- |
| 1. Foundation | Architecture, monorepo and generated API client, FastAPI skeleton, multi-tenant database with row-level security, sign-up and login (built-in accounts), consent, candidate and search profiles, answer bank, resume parsing | 2 weeks | Two test users cannot see each other's data; profiles editable on web |
| 2. Ingestion | Per-user SES inbound addresses, forwarding-confirmation handling, LinkedIn and Naukri parsers, idempotent ingestion | 2 weeks | Forwarded alerts from both portals parsed for several users, with golden-sample tests passing |
| 3. Processing | Shared job catalog, normalization, deduplication, manual JD paste, web job list and detail | 2 weeks | The same job received by two users is extracted once and appears in both pipelines |
| 4. Matching | Per-profile hard filters, embeddings, LLM scoring and rationale, usage metering and quotas | 2 weeks | Every job has a score per active profile; quotas enforced |
| 5. Readiness and documents (repository milestone 4) | Readiness classification and blockers, answer bank, resume edit suggestions, tailored resume and cover letter in Word and PDF, claim check; sign-up changes (password confirmation, show/hide) and Google and Microsoft sign-in. The resume library and per-job resume recommendation were delivered in milestone 3 | 2 weeks | Strong matches classified with blockers; packs generated and reviewed |
| 6. Notifications and mobile | Notification service, WebSocket feed, React Native (Expo) app, push, digests, tracker | 2–3 weeks | Strong-match and blocker pushes arrive on phone within 30 seconds of the event |
| 7. Onboarding and operations | Onboarding wizard, admin console, data export and deletion, support tooling | 2 weeks | A new user reaches a working setup in under 15 minutes without help |
| 8. Pilot and closed beta | Security hardening, deployment in ap-south-1, author pilot, then 25–50 invited users | 2 weeks plus beta period | Top-20 precision measured per user; no isolation defects; onboarding completion rate measured |
| Public launch | Penetration test, privacy policy and terms, DPDP readiness review, app store releases | After beta | All launch prerequisites signed off |
| Phase 2 | Browser extension (JD capture, autofill), one-tap submit for Greenhouse/Lever, Razorpay billing, Gmail OAuth after Google verification, outcome-based ranking | After launch | Decided on beta results |

**MVP acceptance criteria**

- Any person can sign up, verify their email, give consent and complete onboarding without assistance.
- A user can create several search profiles, and each job is scored against each active profile.
- No API call, query or notification can expose one user's data to another; automated isolation tests pass.
- Alerts forwarded to a user's private address are ingested only for that user; mail from other senders is rejected.
- LinkedIn and Naukri alert emails are recognized and parsed into normalized jobs; a job received by many users is extracted once.
- Duplicate jobs across sources are consolidated, with all source links kept.
- Every job receives a 0–100 score with factor-level rationale and must-have gaps.
- Strong matches are classified as Ready, Needs input or Manual only, with each blocker named.
- Strong-match and blocker notifications reach the mobile app and the web app, and respect quiet hours and caps.
- Tailored resumes and cover letters contain no claim that cannot be traced to the user's profile.
- The tracker preserves the exact resume, cover letter and answers used for each application.
- Plan quotas are enforced and usage is visible to the user and to admins.
- A user can export all their data and delete their account; deletion completes within 30 days.
- No application is ever submitted without explicit user action, and the service never automates LinkedIn or Naukri.
- No OAuth token or secret is stored in plaintext.

**Open questions**

- [ ] Product name and domain (needed for the inbound email subdomain and app store listings)?
- [ ] Target market at launch: India only, or international from the start (affects billing, data residency and job sources)?
- [ ] Pricing: free tier limits as proposed, and the Pro price point?
- [ ] Is Gmail OAuth worth the Google verification and annual assessment, or is the forwarding address enough?
- [x] Strong-match threshold default: decided 85 (Good 70–84), set per search profile.
- [x] LLM provider: decided the Claude API directly at launch, through the model gateway. Re-check data residency before public launch.
- [ ] Legal entity and owner for the privacy policy, terms and grievance contact?
- [ ] Mobile distribution for the beta: TestFlight and Play internal testing, or store release?
