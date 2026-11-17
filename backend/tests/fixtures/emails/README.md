# Sample alert emails

Real job-alert emails for building and testing the alert parsers (milestone 2). Personal data has
been removed; the job content is unchanged. Each `<name>.eml` has a hand-written `<name>.expected.json`
that `tests/test_parsers.py` checks the parser against; `make parse FILE=<name>.eml` shows what it finds.
New samples arrive via `TestFiles/` at the repo root.

| File | Source | Jobs | Notes |
|---|---|---|---|
| `linkedin-alert-vice-president-bangalore-2026-10-29.eml` | LinkedIn Job Alerts (`jobalerts-noreply@linkedin.com`) | 6 | Digest for the alert "vice president in Bangalore Urban" |
| `naukri-alert-recommended-jobs-2026-09-21.eml` | Naukri Alerts (`naukrialerts@naukri.com`) | 11 | Profile-based recommendations: 7 in preference + 4 "outside your preference" |
| `naukri-recruiter-invite-vp-ai-2026-09-18.eml` | Naukri recruiter mail (`<recruiter>…@naukri.com`) | 1 | "You're invited to apply": one job with the full description in the email |
| `linkedin-alert-director-product-bengaluru-2026-10-30.eml` | LinkedIn Job Alerts (`jobalerts-noreply@linkedin.com`) | 6 | Same digest template as the first; says "16 new jobs" but lists 6; has a salary and mixed-case titles |
| `naukri-applied-similar-jobs-2026-11-12.eml` | Naukri (`info@naukri.com`) | 6 | "You applied for 1 job on 12 Nov": the job applied to (marked Applied on that day) + 5 "Similar jobs for you" |

Original, unsanitised emails go in `TestFiles/raw/`, which git ignores. Only sanitised copies are committed.

## Expected parse: linkedin-alert-vice-president-bangalore-2026-10-29.eml

Alert search: `vice president in Bangalore Urban`

| LinkedIn job ID | Title | Company | Location | Extra line in card |
|---|---|---|---|---|
| 4484420848 | Chief Engineer | Commonwealth Bank | Bengaluru East | This company is actively hiring |
| 4484441744 | Sr. Vice President- Projects | Brigade Group | Bengaluru East | This company is actively hiring |
| 4484103275 | SEG & India CFO | Cognizant | Bangalore Urban | 2 connections |
| 4483841832 | Head S&OP/SIOP | Ola Electric | Bangalore Urban | This company is actively hiring; Apply with resume & profile |
| 4482272812 | Professional Services Leader - India | FirstApex | Bangalore Urban | 1 school alum; Apply with resume & profile |
| 4482543710 | Director of Global Account Management - India | JumpCloud | Bengaluru East | — |

The canonical job URL is `https://www.linkedin.com/jobs/view/<job ID>/`; dedupe on the job ID, not the
tracking link. The email has a `text/plain` and a `text/html` part; parse the HTML, use the plain text as a
fallback and a cross-check (both must give the same six jobs). Footer links ("See all jobs", "Manage your
job alerts", Premium upsell) are not jobs.

## Expected parse: naukri-alert-recommended-jobs-2026-09-21.eml

Subject: `<Name>, Top Openings for Chief Architect, Strategy Manager, Managing Director`. These are Naukri's
profile recommendations, not a saved search, so there is no alert name.

| # | Naukri job ID | Title | Company (as shown, may be truncated) | Location | Section |
|---|---|---|---|---|---|
| 1 | 170926037140 | Principle Solution Architect - Java /Product architecture | Crescendo Global Le... | Hybrid - Bengaluru | preference |
| 2 | 170926018827 | Chief Architect - Physical AI & Robotics | Cyient | Bengaluru | preference |
| 3 | 140926009658 | Principal AI Architect | Spencer N Hills Con... | Hybrid - Bengaluru | preference |
| 4 | 150926009525 | Product Management - Retail | Epam Systems | Bengaluru | preference |
| 5 | 150926020443 | Director Strategic Business & Corporate Affairs | Matrix Hr Technologies | Bengaluru | preference |
| 6 | 180926922566 | Director, Finance (FPNA with experience in BI skills required) | Visa Consolidated S... | Bengaluru | preference |
| 7 | 040226029402 | Program Manager Global - DVP/AVP - Automotive Domain | BharatHire.Com Priv... | Pune, Chennai, Be... | preference |
| 8 | 160926035791 | Director, Technical POM Product Management | BNY | Pune(Kharadi) | outside preference |
| 9 | 160926025637 | Head of AI Platform & Architecture | Maxic Arrow | Jaipur | outside preference |
| 10 | 160926936460 | S&C GN - TS&T - Enterprise AI Value Strategy - Senior Manager | Accenture | Gurugram | outside preference |
| 11 | 170926034622 | CTO/Head Technology/Chief Engineering Head | Orcapod Consulting ... | Pune | outside preference |

Parsing notes:

- **Parse the HTML part.** The `text/plain` part is one line ("Job recommendations based on your Naukri.com
  profile") and has no jobs.
- **Job ID** is the 12-digit number at the end of the `/jd/job-listings-…-<id>` path. Canonical URL:
  `https://www.naukri.com/job-listings-<id>` or the `/jd/` path without its query string. Each job link
  appears twice in the HTML (logo and title); dedupe on the ID.
- **Company and location are truncated** in the card ("Crescendo Global Le…"). Take the full values from
  the job page when fetching the description, or from the URL slug as a fallback.
- **Number lines like `3.6`** are AmbitionBox ratings (their own links to ambitionbox.com), not part of
  the title or location.
- **"Jobs outside your preference"** marks the start of the second section. Keep the flag; it's a useful
  hint for scoring.
- **Not jobs:** the "Are these jobs relevant? Yes/No" links (`cm.naukri.com`), "View All Recommendations",
  app, social and unsubscribe links.
- **Security:** Naukri says these emails carry **auto-login** links. FitFirst must strip query strings
  from stored URLs, never follow `cm.naukri.com`, `mnjuser` or unsubscribe links, and never show raw
  links from the email to anyone other than the owner.

## Expected parse: naukri-recruiter-invite-vp-ai-2026-09-18.eml

A recruiter found the profile through Naukri's resume database (Resdex) and invited the candidate to apply.
One job per email, and unlike the alert digests **the full job description is inside the email**, so no
page fetch is needed.

| Field | Value |
|---|---|
| Source type | `naukri_recruiter_invite` |
| Naukri message/job ref | `180926021094` (the `mid` / `f` parameter of the Apply link) |
| Title | VP-AI Senior Leader |
| Company | Not named. Sender shows "Naukri Premium - Employer Services" (a Naukri hiring service acting for a client) |
| Location | Mumbai, Bengaluru |
| Experience | 20 - 30 years |
| Salary | Not Disclosed |
| Work model | In office |
| Key skills | generative ai, Architect, Data Science, Agentic Ai |
| Industry | FMCG |
| Department | Data Science & Analytics |
| Role | Data Science & Machine Learning - Other |
| Employment type | Full Time, Permanent |
| Education | Graduation Not Required |
| Description | "Roles and Responsibilities" (4 bullets) + "Job Requirements" (3 bullets), as HTML |

Parsing notes:

- **Recognise it by** subject `✉️ Job | <title> in [<locations>]`, heading "you're invited to apply to this
  job", and the `applyBroadcastMail` link. It's HTML only; there is no text/plain part.
- **Sender varies per recruiter**: `<name><base64 "naukri.com">@naukri.com`. The sender allow-list must
  accept any `@naukri.com` address **with DKIM passing**, not only `naukrialerts@naukri.com`.
- **No public job page.** There's no `/jd/` link; the Apply link needs the candidate's Naukri login. Store
  the description from the email, mark the job "apply via Naukri (recruiter invite)", and never open the link
  server-side.
- **Fields are label/value rows** ("Industry type" → "FMCG"); the five rows under the title are location,
  experience, salary, work model and skills, in that order, identified by icon (`i3_1`, `i4_1`, `i4`, `i6`,
  `i7`).
- **Dedupe:** use `naukri:rdx:<mid>`. The same role may also appear later as a public listing; fuzzy match on
  title + locations to link them.
- **Readiness hint:** a recruiter invite is a warm lead. Show it prominently even at a slightly lower score.

## Expected parse: linkedin-alert-director-product-bengaluru-2026-10-30.eml

Alert search: `Director Product Development in Greater Bengaluru Area`. Template `email_job_alert_digest_01`,
the same as the first LinkedIn file; the subject is again the first job's title and company.

| LinkedIn job ID | Title | Company | Location | Work model (HTML) | Salary (HTML) | Extra line (plain text) |
|---|---|---|---|---|---|---|
| 4482596080 | BUK TESCO Bank IN- Platforms-API Technical Product Owner - VP | Barclays | Bengaluru | — | — | 1 connection |
| 4484593586 | Associate Product Director | Vegapay | Bengaluru | On-site | — | — |
| 4484175392 | Vice President Products | GreyLabs AI | Bangalore Urban | On-site | — | — |
| 4475812480 | SENIOR DIRECTOR, SOFTWARE ENGINEERING | Walmart Global Tech India | Bengaluru | — | — | 1 connection |
| 4484937952 | Founding Engineering Manager | HuntingCube | Bengaluru East | — | ₹1.3M-₹1.7M / year | This company is actively hiring |
| 4484989007 | Group Product Manager | Microsoft | Bengaluru | On-site | — | 4 connections |

Parsing notes (these apply to the first LinkedIn file too):

- **Work model and salary are only in the HTML.** The card line is `Company · Location (Work model)`, and
  salary is a separate line (`₹1.3M-₹1.7M / year`). The plain text has neither.
- **Extra lines are worded differently** in the two parts: HTML "Actively recruiting" / "Easy Apply" vs plain
  text "This company is actively hiring" / "Apply with resume & profile". Cross-check the two parts on job
  ID, title and company only.
- **The job count in the header is not the number of cards.** "16 new jobs match your preferences" sits
  above six cards; the rest are behind "See all jobs". Parse the cards; never expect the header count.
- **Keep titles as written** (`SENIOR DIRECTOR, SOFTWARE ENGINEERING`); lowercase them only for the
  fingerprint.
- **Recognise the template** by `X-LinkedIn-Template: email_job_alert_digest_01`, not by the subject.

## What was changed from the original email

- LinkedIn: recipient name, email address, headline and profile link replaced with `Test Candidate`,
  `candidate@example.com`, `Engineering leader at Example Corp`, `test-candidate`.
- Tracking and sign-in tokens in links (`trackingId`, `refId`, `lipi`, `midToken`, `midSig`, `otpToken`,
  `savedSearchId`, …) replaced with `REDACTED`.
- LinkedIn delivery headers removed: `Received`, `DKIM-Signature`, `ARC-*`, `Authentication-Results`,
  `Return-Path`, `Delivered-To`, `List-Unsubscribe`, LinkedIn IDs.
- LinkedIn (2026-10-30 file): as above, plus the recipient's profile photo URL and the `e`, `referenceId`
  and `upsellOrderOrigin` link parameters replaced with `REDACTED`; `Message-ID` set to
  `<fitfirst-fixture-linkedin-alert-0002@example.com>`. The job cards are byte-for-byte unchanged.
- Naukri: recipient name and email replaced in the headers and body; the Naukri user ID (`uid`, `xid`,
  `userId`) set to `00000000`; encoded username/email tokens, event IDs and unsubscribe data replaced with
  `REDACTED`; delivery headers (`Received`, `DKIM-*`, `Authentication-Results`, `X-YMailISG`, …) removed.
- Naukri recruiter invite: as above, plus the recruiter's name in the sender address replaced with
  `recruiter.example`, the apply link's user token (`uId`) and recruiter card ID (`vCardId`) redacted.

Because the DKIM signature was removed, use these files to test **parsing** only. Test sender and DKIM
checks in the inbound endpoint with separately signed fixtures.

## Expected parse: ai-assistant-chatgpt-leadership-bengaluru-2026-11-08.eml

A job list written by the user's scheduled ChatGPT task and sent from their own Gmail (then forwarded with
Gmail's Forward button). Read by `ai_assistant_alert` only when the sender is an address listed on Mail setup
(the tests pass `candidate@example.com`). Decision 13 in `docs/plan-m9.md`.

| # | Title (as parsed) | Employer | Location | Work model | Experience | Posted |
|---|---|---|---|---|---|---|
| 1 | Head of Product – Agentic Engineering | SAP | Bangalore | Hybrid | — | about 3 days ago (5 Nov) |
| 2 | Director of Engineering – AI Inference Platform | Arm | Bengaluru | Hybrid | — | 04 Nov 2026 |
| 3 | Director of Software Engineering – Reconciliations Platform | JPMorganChase | Bengaluru | — | 10+ years | 04 Nov 2026 |
| 4 | Senior Director – Product Management | Capital One | Bengaluru | — | 16+ years | 06 Nov 2026 |
| 5 | VP – Regional Delivery Executive | SAP | Bangalore | Hybrid | 15+ years | about 3 days ago |

Parsing notes:

- **Plain text**, numbered entries `1) TITLE` with labelled lines; values wrap over several lines and run until
  a blank line or the next label. The text after the last entry ("SEARCH COVERAGE AND LIMITATIONS") is not a job.
- **All-capitals titles** are title-cased, keeping acronyms (AI, VP, SAP…); mixed-case titles are kept as written.
- **Links** are wrapped by Gmail (`https://www.google.com/url?q=<link>&source=gmail&ust=…`): unwrap them.
- The role summary, deadline, reference and source go in `details`; the email has no employer description.

Changes from the original: sender, recipient and forwarding address replaced (`candidate@example.com`,
`alerts-example@in.brewmyjob.com`), name replaced with `Test Candidate`, delivery headers removed,
`Message-ID` set to `<fitfirst-fixture-ai-assistant-0001@example.com>`. The job entries are unchanged.

## Expected parse: ai-assistant-chatgpt-leadership-bengaluru-2026-11-09.eml

The same ChatGPT task a day later, in a different layout: 17 jobs as `N) Company — Title (requisition)`, headings
that wrap onto a second line, `Scope:` instead of "Role summary", `Listing:` / `Apply:` links, `Location: Bengaluru
| On-site`, and two sections (employer pages; job-board or recruiter listings whose employer page wasn't verified).
Several "Posted" lines disagree with themselves (Walmart: "posted yesterday" vs "23 days ago"; GE HealthCare:
"30+ days ago" vs "5 Nov"), and Tredence has an application deadline on the alert day. The expected file lists
the 17 jobs; `test_an_assistant_job_list_records_doubts_about_the_posting` checks the dates and doubts.
Sanitised as the first file (`Message-ID` `<fitfirst-fixture-ai-assistant-0002@example.com>`).

## Expected parse: naukri-applied-similar-jobs-2026-11-12.eml

Naukri's confirmation after an apply ("You applied for 1 job on 12 Nov", from `info@naukri.com`; user feedback
2026-11-15). Recognised by the sender and the line "Your application was sent" (other `info@naukri.com` mail, such
as OTPs, is never parsed). The first job (link with `utm_source=appliedJD`) is the one applied to: it is added and
marked **Applied on the date in "Applied on November 12, 2026"** (`ParseResult.applied`, never stored in the shared
catalog). The five "Similar jobs for you" are added as recommendations. Every link goes through
`dl.naukri.com?…&redirect=<job page>`; the job id is read from `redirect` and the link is never followed.
Ratings (`3.7`, `null`) are dropped. `parser`, cards and expected values are in the `.expected.json`.

Changes from the original: recipient name, email and phone replaced (`Test Candidate`, `candidate@example.com`,
`9000000000`); each tracking link's `data` (communication and event ids) set to `REDACTED` and only `utm_*`/`xp` kept
in its `redirect`; the open-tracking image replaced; all delivery and forwarding headers removed; `Message-ID` set to
`<fitfirst-fixture-naukri-applied-0001@example.com>`. The job cards are unchanged.
