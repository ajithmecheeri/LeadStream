# Milestone 9 — More sources and duplicates (India first)

Started 2026-11-03 at the user's request: alert emails arrive too rarely to test with, so jobs should also come
from sources that allow automated access. Scope and rules are in `docs/milestones.md` (Milestone 9). LinkedIn and
Naukri are never scraped; every source here is an official, public API.

## Status

| Part | What | Status |
|------|------|--------|
| 9.1 | Company career feeds: Greenhouse, Lever, Ashby, SmartRecruiters. Add by name or careers-page link; checked daily; suggested companies | built 2026-11-03 |
| 9.2 | Adzuna India API, searched with the user's search profiles | built 2026-11-03; waits for `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` |
| 9.3 | Duplicates: clear duplicates merged across sources, potential duplicates flagged (Same job / Different job) | built 2026-11-07 (decision 12: rules, thresholds and what was found in the user's jobs) |
| 9.4 | More alert-email parsers (iimjobs, hirist, Indeed, Foundit…) | waits for 2–3 sample emails per site. 2026-11-04: LinkedIn saved-jobs reminders (`linkedin_saved_jobs`) and Naukri recruiter invites without [brackets] in the subject (employer from its rating line) are read; Naukri "Neo Early Alert" is not yet. 2026-11-05: the user is setting up Foundit and iimjobs alerts and will send samples |
| 9.4b | AI assistant job lists (user, 2026-11-08: a scheduled ChatGPT task that searches employer career pages and mails the results from the user's Gmail) | built 2026-11-08 (decision 13) |
| 9.5 | Jooble, Careerjet | later (keys, terms) |

## Decision 13: AI assistant job lists (2026-11-08)

The user set up a scheduled ChatGPT task that searches the web for Bengaluru leadership roles and emails the list
from their own Gmail, then forwarded one to their BrewMyJob address. Any user can do the same with their own
ChatGPT (or Gemini, Claude…) subscription; if OpenAI later offers an API for these tasks, it can replace the email.

- **Parser** `catalog/parsers/assistant.py` (`ai_assistant_alert@1`, source `ai_assistant`, lead `alert`). The
  email comes from the user's own address, so the sender can't identify it: it is tried **only for addresses the
  user listed on Mail setup**, after the portal parsers, and recognised by its layout (numbered entries with
  labelled lines: Employer, Location, Posted, Experience, Role summary, Application…). Wording may vary between
  runs; entries need a title and an employer or a link. Shopping lists and other own mail stay unparsed.
- **Unverified**, like every hand forward: an assistant can be wrong or invent a job, so its cards never change an
  existing catalog job; a portal or feed card for the same job replaces them.
- **The role summary is not the description.** It goes in the job's details (scored as text) and the job still
  asks for the employer's description before it can be Strong (the title-only cap). To revisit if the summaries
  prove reliable.
- **Links**: the employer's page, out of Gmail's `google.com/url?q=` wrapper, tracking parameters removed. Apply
  button: "Apply on <company>'s site".
- **Dates**: "Posted: 04 Nov 2026" and "about 3 days ago" (counted from the alert date) become `posted_at`;
  deadline, reference and the assistant's source go in the details.
- First email (5 jobs): Arm matched a job the user had already applied to via LinkedIn; Capital One and one SAP
  job were merged into earlier LinkedIn listings as the same job (9.3); two new jobs.
- **Second layout (2026-11-09, parser v2)**: `Company — Title` headings that wrap onto a second line, the requisition
  in brackets, "Scope:", "Listing:", `Location: Bengaluru | On-site`, and a section "… DIRECT EMPLOYER ROUTE NOT
  VERIFIED" (those jobs get the detail "employer page: not found by the assistant"). v1 read 7 of its 17 jobs with
  the company inside the title; a one-off script corrected the 11 assistant-only jobs in place (statuses kept) and
  added the 10 missed.
- **Doubts about the posting (user, 2026-11-09)**: "posted yesterday" on one site and "23 days ago" on another.
  Every date on the Posted line is read (dates, "yesterday", "N days/weeks ago", "14+ days"); the oldest becomes
  `posted_at`; dates a week or more apart (or "conflict", "discrepancy") and a deadline go in
  `details.posting`. `jobs/expiry.py: posting_doubt` turns them into the amber to-do and the "May have expired"
  badge: deadline passed ("may have closed") or today ("close today"), dates disagree, or only the assistant has
  shown it and it was posted `job_expiry_warn_days` (30) or more ago. "Still open" clears it; it never expires a
  job by itself.
- **Suggested prompt for users** (keeps the layout stable): see `docs/assistant-alert-prompt.md`.

## What was built (9.1, 9.2)

- **Backend** `app/modules/sources/`: `feeds.py` (the four readers, India filter), `discover.py` (find a board from a
  name or link; the suggested list), `relevance.py` (decision 3), `adzuna.py`, `service.py` (fetch once, store per
  user through the catalog and `jobs/linking.py`, queue scoring), `tasks.py` (06:30 and 18:30 IST, on demand), `router.py`.
- **Migration 0011**: `company_feeds` (shared), `watched_companies` and `source_runs` (private, RLS), new sources and
  leads allowed in `job_sources` and `user_jobs`.
- **API**: `GET /sources`, `POST /sources/lookup`, `POST /sources/companies`, `POST /sources/companies/suggested`,
  `DELETE /sources/companies/{id}`, `POST /sources/check`. Jobs list filters `source=company|adzuna` and the
  `company_feed` / `job_board` leads.
- **Web**: Job sources page (`/sources`, in the menu): find and follow a company, suggestions with "Follow all",
  per-company result ("N in India · N new for you · N not shown"), Adzuna status, Check now. Labels on the Jobs page.
- **Linking** moved from ingestion to `app/modules/jobs/linking.py` so alerts and sources share it.
- **Tests**: `test_source_feeds.py` (readers, links, relevance; no database), `test_sources.py` (endpoints, storage,
  the relevance check end to end, Adzuna, shared fetch), isolation test for the new tables, e2e `sources.spec.ts`.
- **Tried live** (demo account, 2026-11-03): Databricks, Zeta and Freshworks gave 148 India jobs, of which 11 reached
  the user and 137 were left out by the relevance check.

## Decisions (for the user's review)

1. **Feeds are shared, watching is private.** `company_feeds` (shared, no RLS, like the job catalog) holds one row per
   company board; `watched_companies` (private, RLS) says which users follow it. A feed is fetched once however many
   users watch it.
2. **India only.** Feed jobs outside India are dropped (location names an Indian city, "India" or "IND"; for
   SmartRecruiters the API's `country=in`). Remote-India counts. The US comes with milestone 12.
3. **Relevance gate, so a company's 100 junior openings don't flood the list.** A feed or Adzuna job reaches a user
   only when:
   - its title's seniority is at least one level below the user's floor: the lowest `min_seniority` of their active
     search profiles, or without profiles one taken from years of experience (≥ 18 years → 4 Senior manager,
     ≥ 12 → 3 Manager, ≥ 6 → 2 Lead, else 1). Titles with no seniority word pass only when the floor is 2 or less;
   - and its title's job family overlaps the user's (from headline, target roles and resumes), when both are known;
   - and at least one active search profile's hard filters (locations, excluded companies) let it through.

   Jobs that don't pass are counted, not linked to the user: the Job sources page shows "N not shown".
   Email alerts are not gated: the user chose those alerts.

   **All levels (user, 2026-11-03: "eventually we need jobs in all levels as this will go public").** The check is
   per user, so a fresher with an engineer profile gets the junior openings and a VP gets the senior ones. Every India
   job a source lists is stored in the shared catalog whatever its level; only the link to each user is filtered.
   Still to do before launch: an "All levels" switch per user, a suggested-companies list that isn't tilted to
   senior roles, and following companies' feeds (or a curated India list) without any user watching them, so the
   catalog grows on its own.
4. **Schedule.** Feeds and Adzuna run at 06:30 and 18:30 IST (twice a day since 2026-11-04, user request; was 06:30 only), and on "Check now" (at most once every 10 minutes per user). The page shows the last check (sources, India jobs listed, new for you, not shown) and the next one. Since 2026-11-05 (user) these times are shown in the user's time zone (Settings → Time zone), e.g. "08:00 and 20:00 EST".
   Adding a company checks it at once.
5. **A job that leaves its company feed** is not expired automatically yet (feeds are authoritative, so this is
   planned with 9.3).
6. **Leads.** `company_feed` ("Company careers") and `job_board` ("Job board") join alert / recommendation /
   recruiter invite; they rank below an alert when one job arrives several ways.
7. **Adzuna** queries are one per (target role × location) of active search profiles, at most 10 a day per user,
   jobs from the last 7 days, 50 per query. Without a search profile Adzuna is skipped (the page says so). Free keys
   may be non-commercial: confirm with Adzuna before paid launch.
8. **Suggested companies** (checked 2026-11-03 for public feeds with senior roles in India): Databricks, Okta,
   Zscaler, MongoDB, GitLab, Stripe, Rubrik, Twilio, Coinbase (Greenhouse); Meesho, Zeta, Paytm (Lever); Freshworks,
   ServiceNow, Swiggy, Wise (SmartRecruiters). Many large Indian employers (TCS, Infosys, banks) use Workday or
   SuccessFactors, which have no public feed; they stay email-only.
9. **Hand-forwarded alerts** (separate from M9). 2026-11-03: `INBOUND_TEST_SENDERS` in `.env`, testing only.
   2026-11-04 (user: "accept forwarding from the individual users in case they are not able to set up forwarding…
   their choice … from a specific email"): replaced by a per-user list on Mail setup ("Forward alerts by hand", up to
   3 addresses, table `forward_senders`, migration 0012). A forward is accepted only from a listed address, with DKIM
   passing for its domain, to that user's secret address. A hand forward loses the portal's DKIM, so the forwarder
   could edit it: its jobs enter the catalog as `verified = false`, never change an existing job, and the first
   verified sighting (filtered alert, feed, Adzuna) replaces their facts. Remaining risk, accepted: a second user's
   hand forward of the same listing links to the first forwarder's unverified facts until a verified sighting.
10. **Job fields from the title's main function** (user feedback 2026-11-03: "Director, Product Design" was a Top
    match for an engineering/product leader). Matching now reads a title's field from its first part that names one
    (`taxonomy.title_families`): "Director of Recruiting, Engineering & IT" is recruiting, not engineering. "Product
    Design" counts as design. New fields: design, legal, customer support, lending; recruiting, industrial relations,
    learning & development and supply added to existing ones. An unrelated field caps the score at 45 (Other jobs).
    Scores were recalculated for every user.
    2026-11-04 (an HCL "SAP GRC / BR&C Technology Architect" invite scored 81 for an engineering and product
    leader): new field `enterprise_apps` (SAP, S/4HANA, ERP, Oracle EBS/Fusion, Salesforce, Workday, ServiceNow,
    Dynamics 365…). When a title's main part names one, that specialism wins over "technology"
    ("SAP Technology Architect" is SAP work). For this user it now scores 45 (Other jobs), as does
    "Global SAP Consolidations Manager".
11. **Specialist jobs and title-only jobs (user feedback 2026-11-05).**
    - **Specialisms from the description.** "MCCB Product Engineering" (Capgemini, switchgear manufacturing)
      scored 88 for a software leader: its title says "Product Engineering" and its company blurb says software,
      cloud and AI. Now a description naming at least 4 terms of a specialism (`taxonomy.SPECIALISMS`):
      - manufacturing and hardware: APQP, PPAP, NPI, moulding, switchgear, PCB…;
      - SAP / Oracle / Salesforce…, which also needs 2 hands-on terms (ABAP, Fiori, Apex, CPQ…), so a software
        job that only lists integrations ("connectors for Salesforce, Workday") doesn't count.

      When no resume names 2 of its terms, the score is capped at 55 (Other jobs; "A different line of work" in
      points lost). The company's own name is ignored, and a vendor's jobs (SAP Labs, Salesforce…) are never its
      own specialism. Checked on all 1,000 catalog jobs: 11 flagged, all genuinely specialist. For this user the
      MCCB job went from 88 to 55, and Rubrik's "Senior TPM - IT GTM" (Salesforce) from 94 to 55.
      2026-11-06 (user): Oracle's technology stack added (OCI, ADF, BI Publisher, OBIEE, Oracle Data
      Integration, WebLogic, Hyperion…), so PwC's "AES – Oracle Technical Director" went from 95 to 55. A bare
      "Oracle" counts only as a name, so a job migrating "from Oracle and Postgres" isn't flagged. A resume shows
      the specialism only with a hands-on term among the two, not just "Oracle" and "ERP" in passing.
    - **Title-only jobs** (LinkedIn alerts often carry no description):
      - key skills are no longer marked down, since a title can't name six of them;
      - wording similarity is left out, because a title alone always reads as far from a resume (about 27
        points lost on every title-only job);
      - such a job can reach Good (Top matches) but not Strong until its description is in. Points lost then
        show "Only the title is known", and no WhatsApp alert goes out on a title alone.

      "Director of Engineering" (title only) went from 54 to 84.
    - **Industry experience asked for (2026-11-06, user).** Shell Recharge's "Director, Product Management"
      scored 89. The function fits, but its must-haves are EV charging (OCPP/OCPI, CPO/MSP platforms, charging
      networks). `taxonomy.INDUSTRIES` lists industries with their own vocabulary: EV charging, core banking,
      insurance platforms, healthcare IT and telecom. Only sentences that ask for something ("experience",
      "knowledge", "expertise"…) count, so an EV company describing itself doesn't make every one of its jobs
      need EV experience. The thresholds are the same as for specialisms (4 terms, 2 hands-on).
      - When no resume shows the industry, the score is capped at **65**, gentler than another line of work
        (55, or 45 for the title). Points lost read "Asks for industry experience your resumes don't show".
      - Checked on all 1,000 catalog jobs: only this one is flagged. It went from 89 to 65.
    - **Not a fit, from a gap (user, 2026-11-06).** Rules will always miss some cases, so the user can re-rate a job.
      - A gap on a Top match's "Ready to apply?" list names what the job asks for: the industry terms it asks
        experience in ("EV charging, OCPP, OCPI…"), the field ("banking"), or the missing skills.
      - Beside **I'll address it**, a **Not a fit** button (`POST /jobs/{id}/not-a-fit` `{gap}`) caps the job at
        40, moves it to Other jobs, and shows "You marked this job not a fit" in points lost.
      - A notice on the job page offers **Undo** (`DELETE`).
      - The answer is kept in `user_jobs.acknowledged` (`not_a_fit:<gap>`) and survives every re-score.
      - It is per job for now. Learning from these answers (lowering similar jobs on their own) belongs to M13
        part A.
    - **Missing skills cost points (user, 2026-11-06).** NatWest's "Principal Engineer, UCX Platform, VP" showed
      100% with RAG and Solution architecture missing: skills is one of nine factors (15%), so two gaps cost
      under a point. Now each skill the job asks for that no resume or the profile shows costs 3 points, at most 15.
      Points lost names them ("Skills it asks for that your resumes don't show: …"). **I have this skill** adds
      the skill to the profile and the job is re-scored without that penalty.
    - **Hands-on roles for a leader (user, 2026-11-06).** A title whose main part is hands-on (Engineer,
      Developer, Architect, Scientist) for a candidate whose current role leads teams (Head, Director, VP,
      Engineering Manager…):
      - the Role factor is capped at 40, which makes it a role gap on the job ("… is a hands-on (individual
        contributor) role … a bank's “VP” is a grade");
      - the job is at most Good.

      A bank grade after a comma ("…, VP") doesn't make it a leadership role. The other way round (an engineer
      applying to lead) isn't flagged.
    - Effect for this user: 9 of 33 Strong matches became Good (NatWest 100 → 84), and the other Strong matches
      lost 3 points on average.
    - "Digital marketing" is marketing, and "Strategy" / "Operations" beside another function only qualify it.
      Target's "Director, Digital Marketing Strategy & Operations" is 45.
    - **Not done: fetching descriptions from LinkedIn links.** That is automated access to LinkedIn, which the
      non-negotiables rule out even for public pages.

12. **Duplicates: never merge or hide on a guess (design for 9.3, agreed with the user 2026-11-05).** The same
    role often arrives with a slightly different description, or from a recruitment agency under its own name
    ("Leading MNC", "Confidential"), so BrewMyJob merges only when it's certain and otherwise lets the user decide.

    | Case | When | What happens |
    |------|------|--------------|
    | Certain | Same listing or link; or same company + same normalised title ("VP" = "Vice President") + same city | Merged: "Also on Naukri". An applied job stays in Applied |
    | Likely, same company | Same company with a similar title, another city, or a near-identical description | Kept, amber "Possible duplicate of …", Same job / Different job |
    | Possible, an agency | One poster is anonymous ("Leading MNC", "Confidential") or a recruitment agency, and the description, level, city and experience range are very close to a named company's job | Kept, amber "Possibly the same role, posted by an agency" |
    | Two named companies, similar text | Okta and Zscaler both post a standard "Director, Engineering" description | Not flagged: shared job-description templates are normal |

    - **"You may have applied" (user):** when a possible duplicate is of a job already applied to, the job shows
      "You may have applied to this role via LinkedIn on 3 Nov". Beside it, **View the other job** opens the job
      already applied to in a side panel, with the two compared: title, company, city, level, experience, and the
      description differences. Same job / Different job sit in the panel. On a Naukri recruiter invite the note
      adds "Check with the recruiter before agreeing to be put forward" (agencies are common there, and two
      submissions for one role can cost the candidacy).
    - Description similarity alone never flags a job. City, level and experience range must match too, plus either
      the same company or an anonymous or agency poster.
    - Similarity uses the Voyage embeddings already kept for scoring; without them, word overlap (shingles).
      Thresholds go here for review once tried on the user's jobs.
    - Answers are remembered per pair. "Same job" on an agency posting also records that the agency recruits for
      that company, so its later postings are compared with that company's jobs.

    **Built 2026-11-07** (`app/modules/jobs/duplicates.py`, migration 0015). Thresholds for review:

    | Check | Rule |
    |-------|------|
    | Same title | The same words once abbreviations are spelled out ("VP" = "Vice President", "Sr" = "Senior", "Engg" = "Engineering"), ignoring punctuation, order and "of / the / and" |
    | Similar title | One title contained in the other (Director Product Management / … - Customer Data Platform), or 60% of the words shared; never when a rank word ("Senior", "Lead", "Principal"…) is on one side only |
    | Same city | The cities named (Bangalore = Bengaluru, "Bengaluru East" = Bengaluru); remote counts as a city |
    | Same level | The seniority read from the title (as in scoring) |
    | Descriptions | % of the shorter description's 5-word phrases found in the other, legal boilerplate removed, both at least 300 characters: 85% "almost the same" (same company), 60% for an agency's copy |
    | Unnamed poster | Confidential, Undisclosed, "Leading MNC", "A reputed … company" and the like, or no company |
    | Agency | The name says so: Consultants, Recruitment, Staffing, Placements, Manpower, Executive Search, HR Services… ("Tata Consultancy Services" is a company) |

    - **Merged:** the job stays in the database with status `duplicate`, so "Not the same job" brings it back. It
      leaves every list, count, the readiness view and alerts. The kept job is the applied one, else the earlier one; it
      takes the stronger lead (a recruiter invite) and the apply link. Two applied jobs are never merged.
    - **Alerts:** no WhatsApp alert for a possible duplicate of a job already applied to, until the user answers.
    - **Built 2026-11-09:** remembering that an agency recruits for a company: worked out from "Same job" answers on
      agency pairs (`_recruits`, no new table; "Not the same job" takes it back). That agency's later postings are
      flagged against the company's jobs on title, city, level and years, without the description. E2e test
      `apps/web/e2e/duplicates.spec.ts` (flag, Same job, Not the same job).
    - **Not built yet:** Voyage embeddings for the description check (phrases only for now). (Was also: remembering that
      an agency recruits for a company after "Same job": built 2026-11-09.)
    - **Found in the user's 282 jobs:** nothing certain, one possible: Target's "Director Product Management" (ignored)
      and "Director Product Management - Customer Data Platform" (applied). Same-company pairs from one careers site
      (Databricks, Zscaler…) were not compared: their descriptions share long company text (90%+ alike) though the
      roles differ.

13. **Politeness.** Requests identify as `BrewMyJob/1.0 (+https://brewmyjob.com)`, one company at a time, 20-second
   timeout; a failing feed keeps its last error on the page and is retried the next day.

## Naukri "You applied for N jobs" emails (user feedback 2026-11-15)

Parser `naukri_applied@1` (`catalog/parsers/naukri.py`) reads Naukri's confirmation after an apply (from
`info@naukri.com`, recognised by "Your application was sent"; other `info@naukri.com` mail stays unparsed). The job
applied to is added and **marked Applied on the email's date** (`ParseResult.applied` → `ingestion.tasks._record_applied`,
which calls `applications.mark_applied(on=…)`; a job already applied to or merged as a duplicate is left). The
"Similar jobs for you" are added as recommendations. Job ids come from the `redirect` parameter of Naukri's tracking
links, which are never followed. Fixture: `naukri-applied-similar-jobs-2026-11-12.eml` (sanitised).

The three such emails already received (5, 11 and 12 Nov) were read again once the parser shipped: 3 applications
recorded, 15 similar jobs added.

To review: LinkedIn's "your application was sent to <company>" emails could mark jobs Applied the same way (two
are in the inbox, unparsed); not built yet.
