"""Duplicates (milestone 9.3, decision 12 in docs/plan-m9.md).

user_jobs gains status 'duplicate' and `duplicate_of`: a job merged into another of the user's jobs is kept (so
the merge can be undone) but leaves every list, count and alert. The catalog row is untouched: whether two
postings are one role is the user's view, not a shared fact.

Private (RLS FORCE, own_rows policy): job_duplicates, one row per pair of the user's jobs found to be the same
role ('same': merged when found), possibly the same ('likely': same company) or possibly posted by an agency
('agency'), with the user's answer (same / different), remembered so the pair isn't asked about again.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check "
        "check (status in ('new','seen','ignored','applied','expired','duplicate'))"
    )
    op.execute("alter table user_jobs add column duplicate_of uuid references user_jobs on delete set null")
    op.execute("""
    create table job_duplicates (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      user_job_id uuid not null references user_jobs on delete cascade,
      other_id uuid not null references user_jobs on delete cascade,
      kind text not null check (kind in ('same', 'likely', 'agency')),
      reason text not null,
      similarity smallint,
      answer text check (answer in ('same', 'different')),
      created_at timestamptz not null default now(),
      answered_at timestamptz,
      check (user_job_id <> other_id),
      unique (user_id, user_job_id, other_id)
    )""")
    op.execute("create index ix_job_duplicates_other on job_duplicates (user_id, other_id)")
    op.execute("alter table job_duplicates enable row level security")
    op.execute("alter table job_duplicates force row level security")
    op.execute(
        f"create policy own_rows on job_duplicates using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )


def downgrade() -> None:
    op.execute("drop table job_duplicates")
    op.execute("update user_jobs set status = 'seen' where status = 'duplicate'")
    op.execute("alter table user_jobs drop column duplicate_of")
    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check "
        "check (status in ('new','seen','ignored','applied','expired'))"
    )
