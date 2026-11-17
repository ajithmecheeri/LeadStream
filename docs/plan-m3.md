# Milestone 3 plan: resumes, profile and matching

Goal: the user builds their profile from a resume (or by hand), keeps a small library of resumes and cover
letters, and every job gets a match % so the Jobs page shows the best matches first. Generating a *tailored*
resume and cover letter stays in milestone 4.

Started 2026-11-01 after the user added two resumes to `TestFiles/raw/` (git-ignored; never committed, never
used as test fixtures; tests use the fictional resumes in `backend/tests/samples.py`).

## Requirements from the user (2026-11-01)

| # | Requirement | Where |
|---|---|---|
| 1 | Own profile, separate from the demo one | Sign-up already gives each user their own profile; this milestone fills it from a resume |
| 2 | Jobs page shows the highest matches first; weaker matches in a separate tab | Module 6 |
| 3 | Candidate profile from a resume upload **or** manual entry | Module 2 |
| 4 | Job detail shows the suggested resume and cover letter | Module 6 (suggest from the library); milestone 4 generates tailored ones |
| 5 | Several resumes: one primary and up to 3 variations; several cover letters | Module 1 |
| 6 | The AI suggests the matching resume and cover letter for each job | Module 5 |
| 7 | Show the primary resume's match % on each matched job | Modules 5–6 |
| 8 | Use an API now; allow a self-hosted model later | Module 3 (provider interface in the LLM gateway) |

## Modules

| # | Module | Status |
|---|---|---|
| 0 | Settings: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `VOYAGE_MODEL`, `EMBEDDING_DIMS`, `LLM_DAILY_COST_CAP_USD`, `DOCUMENT_MAX_BYTES`. ~~MinIO~~: originals are kept in Postgres for now (see decisions) | **done** |
| 1 | `documents`: resumes and cover letters, uploaded (PDF, DOCX, ODT, RTF, TXT, MD; 5 MB) or pasted; text extraction (`extract.py`); one **primary** resume + up to **3 variations**; up to **5 cover letters**, one default; rename, focus tags, focus search profile, set primary/default, delete (promotes the next), download the original; duplicate check; migration `0004` | **done** |
| 2 | Profile from resume: `POST /candidate/from-resume` returns the facts for review (Claude `resume_extract` when configured, else the rule-based reader `reader.py`); the Profile page fills the form, the user saves | **done** |
| 3 | LLM gateway (`app/modules/llm/gateway.py`): `run()` for prompts (routing per prompt, versioned prompts in `backend/prompts/`, Pydantic validation, one retry, rules fallback), `embed()` for Voyage; every call in `llm_calls` with tokens, cost and latency; per-user daily cost cap | **done** |
| 4 | Embeddings: Voyage `voyage-4-lite`, 1024 numbers per text, stored as `real[]` with a hash of the text (re-embedded only when the text changes), compared in Python. Without `VOYAGE_API_KEY` scoring uses the factors alone | **done** (pgvector deferred, see decisions) |
| 5 | Matching (`app/modules/matching`): hard filters → nine factors → blend with similarity → band; every resume scored per job; best resume, primary resume's %, best cover letter; `matching.score` task, queued after each alert, resume/letter/profile/search-profile change and pasted description; `GET /matching/status`, `POST /matching/rescore`; `GET /jobs?tab=top|other|unscored|all`, match fields on jobs, stats per tab | **done** (rules + similarity; Claude scoring waits for the key) |
| 6 | Web: Profile page with the resume and cover-letter library and "Fill profile"; Jobs tabs **Top matches** / **Other jobs** / **Not scored yet** / All with counts, match % on each card, primary resume's % and a better variation named; job detail Match panel (score, primary %, suggested resume with download, suggested cover letter, every resume's %, factors, strengths and gaps); dashboard "top matches"; Resumes nav link | **done** |
| 7 | Tests: `test_resume_reader.py`, `test_scoring.py` (no database), `test_documents.py`, `test_matching.py`, isolation for the five new tables; web unit tests `lib/documents.test.ts` and match/tab tests; e2e `resumes-and-matching.spec.ts` | **done** |
| 8 | Claude for scoring (`job_score`, Haiku) and resume ranking with suggested edits (`resume_rank`, Sonnet) | waits for `ANTHROPIC_API_KEY` |

Verified 2026-11-01: 181 backend tests, 19 web unit tests, 3 e2e tests (`make e2e-docker`), lint clean.

## Decisions

- **BRD and LLD updated (2026-11-01)** with these requirements: BRD FR-03, FR-04, FR-05, FR-17, new FR-27 to
  FR-29, screens 3 and 5, two open questions closed; LLD modules M3 and M8, provider routing in M16,
  `resume_extract` prompt, the M3 and `/jobs` endpoints, `resumes` (per user, `is_primary`) and the new
  `cover_letters` table. The user copies the same changes into the Claude Docs originals.
- **Testing starts with Voyage only (2026-11-01):** no Anthropic key yet, so the rule-based paths are first-class:
  resume reading by rules and scoring by filters + factors + Voyage similarity. Results record `method = rules`;
  "Fill from resume" switches to Claude as soon as `ANTHROPIC_API_KEY` is set, with no code change.
- **Resumes belong to the user, not to a search profile** (the LLD had `search_profile_id not null`); a resume
  may optionally name a focus profile.
- **Uploads are JSON with base64** (like `POST /inbox/upload`), not multipart: one typed client for web and
  mobile, and no extra dependency. 5 MB limit.
- **Originals are stored in Postgres** (`stored_files`, bytea, private) rather than MinIO, like the raw emails.
  A user has at most nine documents; object storage arrives with the deploy (milestone 8) or packs (4).
- **Embeddings as `real[]`, not pgvector:** installing the `vector` extension needs the database superuser,
  which migrations don't have. With hundreds of jobs and four resumes per user, comparing in Python is
  instant. pgvector comes back when search across many rows needs an index (a superuser step at deploy).
- **One `job_matches` row per user job** (best search profile's verdict, `ranking` with every resume's score),
  in place of the LLD's `job_scores` + `resume_recommendations`. The per-profile split returns if users ask to
  compare profiles side by side.
- **Match bands** (BRD §5): Strong ≥ the search profile's threshold (default 85), Good 70 up to the threshold,
  Low below 70; "filtered" when every active search profile rules the job out (with the reason). Top matches =
  Strong + Good, sorted by score.
- **Scoring rules:**
  - Hard filters never use unknown facts: an unknown or cut-off location ("Pune, Chennai, Be...") never rules a
    job out; seniority rules out only jobs two or more levels below the profile's minimum.
  - A factor the job gives no evidence for (no salary, no skills) is left out and the remaining weights are
    scaled up, so a thin alert is judged on what it says.
  - A title in an unrelated job family (finance, operations, sales, HR for a technology leader) is capped at 45:
    location and experience alone can't make it a match.
  - Similarity (Voyage) carries 35% of the score when available, mapped from cosine 0.40 (unrelated) to 0.65
    (close), calibrated on the user's real resumes against the 17 sample jobs: technology and architecture roles
    scored 70–92, finance, S&OP and account management 33–45.
  - "finance" in a title is a job function, not the financial-services industry.
  - **Key skills on a search profile** (user feedback 2026-11-04: "10-20 skillsets to start with"): up to 20 per
    profile (migration 0013). The Skills factor is then 60% the share of key skills the job asks for (full
    marks at 6, or all of them when fewer) and 40% the share of the skills the job asks for that the resume
    shows. A title-only alert that names none is left out, not marked down. The match reason names the skills
    found. Default weights are unchanged (Skills 5), so users without key skills score as before; the editor
    offers "Make skills count more" (15) once skills are added.
  - **Skills by meaning, not spelling** (user, 2026-11-04: "one to one match is not expected… Architecture is
    asked, Enterprise Architecture is in skills, it matches"; `matching/skills.py`). A key skill matches fully
    through the phrase, a part of it (split on and / & / ,), a spelling (GenAI = generative AI = LLM) or a
    narrower term (AWS for cloud); partly (0.75) through a part's main word only ("architecture" for
    "Enterprise Architecture"). Generic words (management, enterprise, strategy, data…) never match alone.
  - **Skills a job asks for** = the listed ones, about 100 vocabulary terms its text names (DevSecOps, TOGAF,
    Databricks…) and the key skills it names. The job page's Skills box (highlighted red when any are missing)
    lists those the resume doesn't show, with "I have this skill". A resume shows a skill only fully ("DevOps"
    isn't "DevSecOps"), except the user's own broad key skills, checked by meaning. Rule-based until the
    Anthropic key; Claude can judge skill equivalence later through the gateway.
    2026-11-04 (Okta "Director, Site Reliability Engineering" showed nothing missing): SRE practices added to
    the vocabulary (incident management, SLOs, capacity planning, infrastructure as code, release management,
    FinOps, multi-cloud, Prometheus, Grafana, Datadog, Splunk…), and legal boilerplate lines (equal opportunity,
    accommodation, AI-in-hiring notices) are left out of the text scoring reads.
- **Scores from alerts are provisional** ("from the alert" on the card); pasting the full description queues a
  re-score of that job only.
- **Re-scoring is queued, never inline:** a full re-score per user is queued at most once at a time
  (Procrastinate queueing lock `score-all:<user>`) and runs 3 seconds later, so the request that asked for it
  has committed and quick edits collapse into one run.
- **Cost control:** daily cap per user (`LLM_DAILY_COST_CAP_USD`, default US$1) across Claude and Voyage;
  embeddings are reused while the text is unchanged.
- **Self-hosted model later:** `ROUTES` in the gateway maps each prompt to a provider and model; `llm_calls`
  records both, so quality and cost can be compared before switching a task.

## What the user can test now

Sign up with your own email at http://localhost:8080, upload your resume on **Profile**, click **Fill profile**,
review and save, add a cover letter, create a search profile, and upload alert emails on **Inbox**. The Jobs
page then opens on **Top matches**.

## Requirements read by section (user feedback 2026-11-16)

A Nuralx "CTO - AI Security" job (PhD, model forensics, interpretability, unlearning) scored 85 Strong with no gaps:
the description was read as one bag of words. Now `matching/requirements.py` reads it by section:

- **Must-haves:** bullets under "Preferred candidate profile" (Naukri's name for its requirements), "Target(ed)
  profile", "Candidate/Desired profile", "Qualifications", "Requirements", "Must have", "What you'll need",
  "Education"…, and any line saying "must", "mandatory" or "required".
- **Preferred only:** bullets under "Preferred skills/qualifications", "Nice/Good to have", "Bonus"…, and lines
  saying "preferred", "a plus", "advantage". They are shown on the job page and never cost points; their skills are
  left out of "asked for".
- Each must-have is checked against the resume (the skills it names, or its degree): met, partly, missing, or
  unclear (names nothing checkable: judge it yourself). Each missing one costs 4 points (2 when partly), up to 20
  (`MUST_POINTS`, `MUST_MAX`); a required PhD/Doctorate no resume shows caps the score at 55 (`DEGREE_CAP`).
- Vocabulary added: fine-tuning (LoRA, PEFT), foundation models, interpretability (model internals), AI security,
  model forensics, machine unlearning, research publications, patents.
- Equal scores (both capped): the resume showing more of the must-haves and skills is suggested.

The Nuralx job is now 55 Low: "Asks for a PhD", "2 must-haves not shown". All jobs were re-scored.

To review: the points (4 / 2 / max 20) and the PhD cap (55); Master's degrees are listed and checked but not capped.
