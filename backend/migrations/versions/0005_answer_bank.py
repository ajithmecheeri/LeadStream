"""Milestone 4: the answer bank, and gaps the user has acknowledged on a job.

Private (RLS FORCE, own_rows policy): answers.

Readiness and blockers are worked out from current data on every read (match, answers, profile, cover
letters, description), so there is no readiness/blockers table to keep in step; see docs/plan-m4.md.
`search_profile_id` on answers is for per-profile overrides later; the API uses only shared answers for now.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table answers (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      key text not null check (key ~ '^[a-z0-9_]{2,60}$'),
      search_profile_id uuid references search_profiles on delete cascade,
      question text not null,
      answer text not null,
      version int not null default 1,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute(
        "create unique index ux_answers_scope on answers "
        "(user_id, key, coalesce(search_profile_id, '00000000-0000-0000-0000-000000000000'))"
    )
    op.execute("alter table answers enable row level security")
    op.execute("alter table answers force row level security")
    op.execute(
        f"create policy own_rows on answers using (user_id = {USER_SETTING}) with check (user_id = {USER_SETTING})"
    )
    # Blockers the user has looked at and accepted for this job ("gap:skills"); they stop counting.
    op.execute("alter table user_jobs add column acknowledged text[] not null default '{}'")


def downgrade() -> None:
    op.execute("alter table user_jobs drop column if exists acknowledged")
    op.execute("drop table if exists answers")
