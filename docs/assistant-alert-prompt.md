# Job alerts from an AI assistant (ChatGPT, Gemini, Claude…)

BrewMyJob reads job lists that your own AI assistant emails you on a schedule. The assistant does the
searching with your subscription; BrewMyJob only reads the email you forward, scores each job against your
search profiles and links it to jobs you already have.

## Set it up (ChatGPT)

1. In ChatGPT, create a **scheduled task** (daily or every few days) with the prompt below. Change the
   roles and city to yours.
2. Let it send the result by email to yourself (Gmail connector), or forward the email it sends.
3. In Gmail, add a filter on the subject (for example "Job Opportunities") that forwards to your BrewMyJob
   address (Mail setup). The address you send from must be listed on Mail setup.

## Prompt

```
Search for senior leadership jobs (Director, Senior Director, VP, Head of Engineering, Product or AI) in
Bengaluru posted in the last 3 days, on employer career pages and public job listings. Don't include jobs
you sent me before. Email me the list with the subject "<City> Leadership Job Opportunities" in exactly
this plain-text format, one numbered entry per job:

1) <JOB TITLE>
Employer: <company name, or "Not disclosed">
Location / work mode: <city>; <hybrid | remote | on-site | not stated>
Posted: <date as 04 Nov 2026, or "about N days ago">
Application deadline: <date, only if stated>
Experience: <years asked, e.g. 15+ years, or "Not stated">
Role summary: <3–5 sentences from the employer's page: scope, team size, key skills>
Source: <where you found it>
Application:
<the employer's job page link>
Job ID: <the employer's job or requisition ID, if shown>

Only list jobs you found on a page you can link to. Never invent a job, a link or a detail.
```

## What BrewMyJob does with it

- Each entry becomes a job (source "AI assistant alert"), scored against your search profiles. An entry
  needs a title and an employer or a link.
- The role summary is the assistant's summary, not the employer's description. The job reaches **Strong**
  (and a WhatsApp alert) once you paste the description from the employer's page.
- A job you already have from LinkedIn, Naukri or a company feed is matched to it, not added twice.
- Assistants can make mistakes: check the job on the employer's page before you apply.
- When the posting dates disagree, the deadline has passed (or is today), or a job only your assistant has
  found was posted a month or more ago, the job shows **May have expired** with the reason. Check the
  employer's page, then choose **Still open** or **Expired**.
- The assistant's layout changes from run to run even with the same prompt. The parser reads numbered entries,
  a bold or plain "Company — Title" heading (also over two lines), and known labels whether each starts a line
  or they run on in one paragraph ("Source/age: … Location/work mode: … Experience: … Scope: … Apply/view: …").
  A new label is added to `_LABELS` in `parsers/assistant.py` (v3 since 2026-11-09, after a run that put
  everything in the title).
