# LeadStream (Sunstream lead generation app): requirements and decisions

Internal application for Sunstream Global's presales team, started as a copy of FitFirst/BrewMyJob
(copied 2026-11-17). The source document is `SunStreamPresalesApp.docx`. Where this file and the copied
FitFirst docs disagree, this file wins for Sunstream.

## What it does

Job alerts from US job sources arrive by forwarded email. Each job is matched to the profiles the team
configured. Jobs are listed with match details. For each job the app pulls employer details (ZoomInfo) and
shows them in a Company tab, and tries to find contact information on the company's website. The jobs are
sales leads for Sunstream; they are not applications.

Focus roles: engineering design, mechanical design, electronics design, PCB design, embedded programming, IoT.

## Requirements (from the document)

1. Configure profiles for the US job market and get alerts on new postings; a job is matched to the stored profiles.
2. Focus roles: engineering design, mechanical design, electronics design, PCB design, embedded programming, IoT.
3. Many profiles; all alerts aggregate into this one application.
4. Job listing as in BrewMyJob.
5. Match details of each job against the profiles.
6. Alerts from Indeed.us, LinkedIn, Google Jobs, Dice.com, Engineering.com, EngineeringCentral.com
   (alert formats will be trained from sample emails).
7. No marketing page (internal application).
8. No Job sources page; no career-page or hiring-system integrations for now.
9. No autofill information and no browser extension.
10. Must be able to crawl in future.
11. Mail can be forwarded from different email addresses to the application.
12. For each job, find the employer in ZoomInfo (or similar) and show the company profile in another tab.
13. Try to pull contact information from the company's website.

## Decisions (user, 2026-11-17)

- **Profile = basic search criteria** (titles, skills, locations, seniority): the "Match Profile". No resumes.
- **Shared by the presales team:** everyone on the team sees all jobs and company information.
- **Several admins** add and manage users. Analytics for admins come later.
- **Company details come from the ZoomInfo API first.**
- **Setup:** a new separate repo copied from FitFirst; BrewMyJob stays untouched.
- **App name: LeadStream.** User-facing text should say LeadStream (not FitFirst or BrewMyJob).

## Keep, change, remove (proposed; confirm)

| Area | Plan |
|---|---|
| Email ingestion, parsers, catalog, duplicates, worker | Keep; add parsers for the six sources from sample emails |
| Matching engine and match details | Keep; change to criteria-only profiles with no resume |
| Jobs list | Keep; add a Company tab on the job page |
| Auth and row-level security | Change: team-shared data (no per-user rows for jobs/profiles); admin role to manage users |
| Marketing home page, waitlist, plans, coupons, payments | Remove |
| Job sources, Job Search Service, Find on Google | Remove (keep the code path for crawling later) |
| Extension, autofill, apply kit, answer bank | Remove |
| Resumes, packs, applications tracker, networking, WhatsApp, Ask BrewMyJob | Remove unless confirmed |
| India-specific parts (rupee plans, India locations) | Replace with US (states, remote, USD) |

## Open questions

1. Sample alert emails (2 to 3 sanitised each) for Indeed, LinkedIn, Dice, Engineering.com, EngineeringCentral;
   and how Google Jobs alerts are received today.
2. Forwarding: allow-list of sender addresses, or one address per person or profile?
3. Sign-in method (Google Workspace, Microsoft, or email and password with invites) and the number of users.
4. Notification channel for new matches (email, Slack or Teams, in-app).
5. Lead status and CRM export (HubSpot, Salesforce, Zoho)?
6. Crawling: portals stay on alert emails only; crawl company websites and permitting sources later (to confirm).
7. Repo name (suggested: `leadstream`) and hosting. The app name is decided: LeadStream.
8. ZoomInfo: API access, credentials and licence terms; how it may be used for outreach.
9. Contact information from websites: public business contacts only, honouring robots.txt (to confirm), and any
   outreach compliance rules Sunstream follows.

## Proposed build order

1. New repo, rename, strip removed features, US locale. Tests pass.
2. Team-shared data model, admin and user management.
3. Criteria-only Match Profiles with starter profiles for the six role areas.
4. Parsers for the six sources (needs the sample emails) and multi-address forwarding.
5. ZoomInfo company enrichment and the Company tab.
6. Website contact discovery.
7. Notifications and admin analytics.
