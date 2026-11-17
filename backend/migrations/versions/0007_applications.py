"""Milestone 5: applications tracker, Applied and Expired jobs, contacts on a job, app settings.

Private (RLS FORCE, own_rows policy): applications, application_events, job_contacts.
Shared, no user_id: app_settings (values the super admin sets, read by everyone; see docs/plan-m5.md). The app
role may read and update its rows but never add or remove them: the keys are defined here.

user_jobs gains the statuses 'applied' and 'expired'. `expired_by` says who moved it (user, or auto after the
admin's number of days); `confirmed_open_at` is when the user said "still open", which restarts the clock.
job_matches gains `explain` (points lost per factor, skills had and missing).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02
"""

import os

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")
USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"
PRIVATE_TABLES = ["applications", "application_events", "job_contacts"]
APPLICATION_STATUSES = "'applied','interviewing','offer','accepted','rejected','withdrawn','no_response'"


def upgrade() -> None:
    op.execute("""
    create table app_settings (
      key text primary key,
      value jsonb not null,
      updated_by uuid,  -- no foreign key: truncating users (tests) must not cascade to the settings
      updated_at timestamptz not null default now()
    )""")
    op.execute("""
    insert into app_settings (key, value) values
      ('job_expiry_warn_days', '30'),
      ('job_expiry_auto_days', '45')""")
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke insert, delete on app_settings from {APP_ROLE}';
      end if;
    end $$""")

    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check "
        "check (status in ('new','seen','ignored','applied','expired'))"
    )
    op.execute("alter table user_jobs add column expired_at timestamptz")
    op.execute("alter table user_jobs add column expired_by text check (expired_by in ('user','auto'))")
    op.execute("alter table user_jobs add column confirmed_open_at timestamptz")
    op.execute("alter table job_matches add column explain jsonb not null default '{}'")

    op.execute(f"""
    create table applications (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      user_job_id uuid not null unique references user_jobs on delete cascade,
      status text not null default 'applied' check (status in ({APPLICATION_STATUSES})),
      applied_on date not null,
      resume_id uuid references resumes on delete set null,
      cover_letter_id uuid references cover_letters on delete set null,
      follow_up_on date,
      version int not null default 1,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute("create index ix_applications_user_applied on applications (user_id, applied_on desc)")
    op.execute("""
    create table application_events (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      application_id uuid not null references applications on delete cascade,
      kind text not null check (kind in ('applied','status','note','follow_up')),
      from_status text,
      to_status text,
      note text,
      at timestamptz not null default now()
    )""")
    op.execute("create index ix_application_events_app on application_events (application_id, at)")
    op.execute("""
    create table job_contacts (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      user_job_id uuid not null references user_jobs on delete cascade,
      name text,
      role text,
      linkedin_url text,
      email text,
      note text,
      version int not null default 1,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      check (coalesce(name, linkedin_url, email) is not null)
    )""")
    op.execute("create index ix_job_contacts_job on job_contacts (user_job_id)")
    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )


def downgrade() -> None:
    for t in ["job_contacts", "application_events", "applications"]:
        op.execute(f"drop table if exists {t}")
    op.execute("alter table job_matches drop column if exists explain")
    for c in ["confirmed_open_at", "expired_by", "expired_at"]:
        op.execute(f"alter table user_jobs drop column if exists {c}")
    op.execute("update user_jobs set status = 'seen' where status in ('applied','expired')")
    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check check (status in ('new','seen','ignored'))"
    )
    op.execute("drop table if exists app_settings")
