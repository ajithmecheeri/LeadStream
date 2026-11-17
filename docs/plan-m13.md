# Milestone 13 — Ask BrewMyJob (plan and status)

Scope and rules: `docs/milestones.md` (Milestone 13). Part A was built on 2026-11-09 while the user was away
("Please go ahead and complete the work"); the decisions below are for the user's review.

## Status

| Part | What | Status |
|------|------|--------|
| A | "Not for me" with a reason + per-user learning (loop 1) | **built 2026-11-09** |
| B | Ask panel with read tools | waits for the Anthropic key |
| C | Admin review queue + regression cases (loop 2) | not started (reads `job_feedback`) |
| D | Changes with confirmation from the assistant | waits for B |
| E | Evaluation set and prompt versions (loop 3) | after Claude scoring is on |

## What was built (A)

- **Job page:** a **Not for me** button next to Ignore opens a short form: Not my field, Too junior, Too senior,
  Location doesn't work, Not this company, Salary too low, Already applied elsewhere, Something else, and an
  optional note. The job moves to Ignored; the page says "Not for you: <reason>".
- **Learning** (`app/modules/feedback/learning.py`): company, city, field and level reasons become learned
  preferences. Jobs that fall under one are capped at 40 (Other jobs), with "Like jobs you said aren't for you" in
  the points lost and an amber notice on the job naming the preference.
- **Profile → Learned from your feedback:** every preference ("Jobs at Okta", "Jobs in Pune", "Marketing roles",
  "Roles below director level") with Remove. Removing one re-scores every job.
- **API:** `POST /jobs/{id}/not-for-me` (reason, note, version), `GET /preferences/learned`,
  `DELETE /preferences/learned/{id}`. Job detail gains `not_for_me` and `learned`.
- **Data** (migration 0018, private, RLS FORCE, isolation test): `job_feedback` (every answer, kept for part C)
  and `learned_preferences` (unique per kind and value).
- **Tests:** `tests/test_feedback.py` (rules without a database; the learn → cap → forget journey; errors),
  `test_isolation.py`, and the web e2e `duplicates.spec.ts` (Not for me → Profile → Remove).

## Decisions to review

1. **One answer is enough to learn.** The backlog said feedback "turns into preferences"; it didn't say after how
   many. A single "Not this company" is a clear statement, so it's learned at once; it's visible and one click
   to undo. If this proves too eager for field or level, a second matching answer could be required.
2. **Capped, not hidden.** Learned jobs score at most 40 (like "not a fit") and stay in Other jobs, so nothing
   disappears and a wrong lesson is noticed.
3. **Guards against one click hiding a whole search:**
   - field: only a field outside the user's own (headline and search-profile roles); "Not my field" on an
     engineering job teaches a technology leader nothing;
   - level: one step past that job's level, from its title (too junior on a Director job → below senior
     director/head is capped);
   - location: a job is capped only when every city it names is excluded, and never when it's remote;
   - company: named companies only (not "Confidential" or "Leading MNC").
4. **Recorded, not learned:** salary (most alerts don't state one), already applied elsewhere, something else.
   They're kept in `job_feedback` for the admin review queue (part C).
5. **No "duplicate" reason:** duplicates have their own Same job / Different job flow (milestone 9.3).
6. **Ignore stays** as the quick action without a reason.
