# Roles, invites, plans and shared job sources (user, 2026-11-17)

The user's feedback of 2026-11-17, and how it is built. Part of milestone 11 (subscriptions) without the payment
gateway, which goes to the backlog.

## What the user asked

1. Job sources only for admins. The user is the super admin and invites other admins.
2. People who subscribe are **job seekers**. They don't see Job sources. They see every job from the sources in
   Jobs → **From sources** (the last run's and older ones). Jobs that fit their profile still go to their Jobs
   (Top matches / Other jobs) automatically; the rest stay in From sources, where they add any by hand.
3. Plans: 1 month ₹199, 3 months ₹500, 6 months ₹750, 1 year ₹1,200. The super admin creates **1- or 3-month
   coupons**: whoever receives the invite email uses the app without paying. Payment gateway: backlog.
4. (Answers to questions, same day) Without a coupon: **sign up, then a paywall** (the plans, "payments coming
   soon"). Sources: **one shared list** of companies, kept by the admins. Google Alerts setup (with its roles) goes
   to **Find on Google**, which becomes a menu item for job seekers (the button on Jobs stays). The browser
   extension can be **downloaded from Settings**.

## Decisions

| # | Decision |
|---|---|
| 1 | Roles: `job_seeker` (everyone who signs up), `admin`, `super_admin`. The old `user` becomes `job_seeker`, the old `admin` becomes `super_admin` (migration 0032). `make admin EMAIL=…` makes a super admin, as before. |
| 2 | Admins (and the super admin) manage Job sources. Admin settings (expiry days, waitlist, feedback, invites) stay super admin only. |
| 3 | **Invites** are made by the super admin on Admin settings: an email, a role (job seeker or admin) and free months (none, 1 or 3) for a job seeker. **No email is sent yet**: the app has no email provider (it needs the domain and its DNS records), so the invite shows a link to copy and send. Sending it by email is in the backlog. A link works once, for that email only, for 14 days, and can be revoked. |
| 4 | Signing up with an invite link: the email is fixed to the invite's; the role and the free months apply at once. Someone who already has an account opens the link, signs in with that email and accepts. |
| 5 | **Access**: a job seeker uses the app while they have a paid or coupon period (`subscriptions`, private, RLS). Without one they see **Choose a plan** (the four prices, "payments coming soon", "have an invite? use its link"). The API answers `402 subscription_required` on every feature route; sign-in, the account, the plans and accepting an invite stay open. Admins and the super admin never need a plan. Coupon months add to a running period. |
| 6 | Test accounts: `FREE_ACCESS_EMAILS` (a pattern) gives access without a plan. Local `make up` sets it to `e2e-…@example.com` and `demo@example.com` so the e2e tests and the demo keep working; production leaves it empty. |
| 7 | **One shared list of companies** (`platform_companies`, shared like the job catalog, no user data): what the admins follow on Job sources. Every active user is matched against every company on it. The companies each user followed before are copied into it (migration 0033). |
| 8 | When an admin follows a company, its open jobs that fit are caught up for every user. When a job seeker's Skill Match profile is first made from their resume, every company's open jobs are caught up for them. Each catch-up records its jobs and verdicts, like a run. |
| 9 | **Jobs → From sources** (job seekers and admins): every open job the sources brought for you, from the last run and older ones, newest run first: "Found at the last run" first, then the rest; each in your list (with its score) or left out (with the reason) and **Add to my jobs**. Closed jobs drop out. |
| 10 | **Find on Google** becomes a sidebar item (Workspace group) and keeps its button on Jobs. Its page gets the Google Alerts card (suggested alerts, roles, feeds) that was on Job sources. |
| 11 | **Settings → Browser extension → Download** gives a zip of `apps/extension`, built into the web image (`/downloads/brewmyjob-extension.zip`), with the install steps. |

## Backlog

- Payment gateway (Razorpay; milestone 11), invoices, renewals.
- Sending invite emails (needs an email provider and the domain).
- A reminder before a period ends.

## Built (2026-11-17)

- Backend: migrations 0032 (roles, `users.access_until`, `invites`, `subscriptions`) and 0033 (`platform_companies`,
  the old follows copied in: 20 companies on the local stack). `app/modules/access` (plans, invites, coupons),
  `require_access` on the feature routers, admin-only Job sources, `GET/POST /sources/jobs` (From sources), catch-up
  for every job seeker with a profile when a company is added and for a new job seeker when their first Skill Match
  profile is made.
- Web: Choose a plan (`/plans`), the invite link (`/invite`), sign-up with an invite, Invites on Admin settings,
  Jobs → From sources on every job the sources brought, Find on Google in the menu with Google Alerts, Settings →
  Browser extension → Download (`/downloads/brewmyjob-extension.zip`, built into the web image).
- Tests: `tests/test_access.py`, From sources and catch-up in `tests/test_sources.py`, subscriptions in
  `tests/test_isolation.py`; e2e `sources.spec.ts` (admin reads Job sources without changing the shared list; job
  seeker; the paywall).

**To review**

- The user's account was a normal user before (no one was admin), so it was made super admin with `make admin`.
- A local-only admin account for the e2e tests is seeded on `make up` (`e2e-admin@example.com`, `backend/app/seed.py`;
  only when `ENV=local`).
- The extension's routes (pairing, filling, Add from Google) work with the extension's own token and are not behind
  the plan check; pairing itself needs the web app, which is.
- The access period is in the access token (15 minutes), so a period that ends closes the app within 15 minutes.
- `watched_companies` is no longer read; it stays until a clean-up migration.
- Admins get jobs from the sources like job seekers (the admin's own list); Job sources shows the admin's own run
  lines.


## Feedback of 2026-11-17 (later the same day), built

1. **Apply on jobs from Google:** a job waiting in Jobs → From Google now has the Apply button at the top of its
   page (with Keep, Mark as applied and Ignore) and in the From Google list.
2. **Documentation:** BRD (roles and plans), LLD (a section for roles, plans, shared job sources and Find on
   Google, and the status table), `docs/README.md` (the plan documents, the differences), `docs/milestones.md`
   (milestone 11, Job sources and Jobs) and `CLAUDE.md`.
3. **Roles on top of Find on Google:** one card, **Roles to look for**, at the top of the page; the Google searches
   and the Google Alerts both use it (up to 5 of the user's own, saved in Google's syntax; else the Skill Match
   profiles' target roles). A role that names its city gets one search and one alert, as written.
4. **Home page pricing:** one plan with the four periods (1 month ₹199, 3 months ₹500, 6 months ₹750, 1 year
   ₹1,200; "Best value" on the year), what every plan includes, and, truthfully, that payment isn't open yet:
   join the waitlist for an invite.
