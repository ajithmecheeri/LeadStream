"""Milestone 13 part A: "Not for me" with a reason, and what BrewMyJob learns from it.

Private (RLS FORCE, own_rows policy):
- job_feedback: one row per "Not for me" (the user's job, reason, optional note).
- learned_preferences: what the feedback taught, per user: jobs at a company, in a city, in a field, below or above
  a level. Matching caps jobs like these at 40 (Other jobs); the user sees and removes them on Profile.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"
REASONS = "'field','too_junior','too_senior','location','company','salary','applied_elsewhere','other'"


def _private(table: str) -> None:
    op.execute(f"alter table {table} enable row level security")
    op.execute(f"alter table {table} force row level security")
    op.execute(
        f"create policy own_rows on {table} using (user_id = {USER_SETTING}) with check (user_id = {USER_SETTING})"
    )


def upgrade() -> None:
    op.execute(f"""
    create table job_feedback (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      user_job_id uuid not null references user_jobs on delete cascade,
      reason text not null check (reason in ({REASONS})),
      note text check (length(note) <= 500),
      created_at timestamptz not null default now()
    )""")
    op.execute("create index ix_job_feedback_job on job_feedback (user_id, user_job_id)")
    _private("job_feedback")
    op.execute("""
    create table learned_preferences (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      kind text not null check (kind in ('company','location','field','level_min','level_max')),
      value text not null,
      label text not null,
      feedback_id uuid references job_feedback on delete set null,
      created_at timestamptz not null default now(),
      unique (user_id, kind, value)
    )""")
    _private("learned_preferences")


def downgrade() -> None:
    op.execute("drop table learned_preferences")
    op.execute("drop table job_feedback")
