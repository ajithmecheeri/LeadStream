"""Milestone 9: jobs from company career feeds and job-search APIs.

Shared (no user_id, no RLS, like the job catalog): company_feeds, one row per company board on a hiring system
(Greenhouse, Lever, Ashby, SmartRecruiters), fetched once however many users follow it. The app role can't
delete them.
Private (RLS FORCE, own_rows policy): watched_companies (which feeds a user follows) and source_runs (what each
check found for the user).

New catalog sources and leads: company feeds and Adzuna.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03
"""

import os

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")
USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"
PRIVATE_TABLES = ["watched_companies", "source_runs"]
SOURCES = "'linkedin','naukri','naukri_rdx','greenhouse','lever','ashby','smartrecruiters','adzuna'"
LEADS = "'alert','recommendation','recruiter_invite','company_feed','job_board'"


def upgrade() -> None:
    op.execute("""
    create table company_feeds (
      id uuid primary key default gen_random_uuid(),
      name text not null,
      ats text not null check (ats in ('greenhouse','lever','ashby','smartrecruiters')),
      board text not null,
      last_checked_at timestamptz,
      last_error text,
      jobs_total int,
      jobs_india int,
      created_at timestamptz not null default now()
    )""")
    op.execute("create unique index ux_company_feeds_board on company_feeds (ats, lower(board))")

    op.execute("""
    create table watched_companies (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      company_feed_id uuid not null references company_feeds on delete cascade,
      created_at timestamptz not null default now(),
      unique (user_id, company_feed_id)
    )""")

    op.execute("""
    create table source_runs (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      source text not null,
      company_feed_id uuid references company_feeds on delete cascade,
      ran_at timestamptz not null default now(),
      found int not null default 0,
      added int not null default 0,
      skipped int not null default 0,
      error text
    )""")
    op.execute("create index ix_source_runs_user on source_runs (user_id, source, ran_at desc)")

    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )

    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({SOURCES}))"
    )
    op.execute("alter table user_jobs drop constraint user_jobs_lead_check")
    op.execute(f"alter table user_jobs add constraint user_jobs_lead_check check (lead in ({LEADS}))")

    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke delete on company_feeds from {APP_ROLE}';
      end if;
    end $$""")


def downgrade() -> None:
    for t in reversed(PRIVATE_TABLES):
        op.execute(f"drop table if exists {t} cascade")
    op.execute("drop table if exists company_feeds cascade")
    op.execute("alter table user_jobs drop constraint user_jobs_lead_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_lead_check "
        "check (lead in ('alert','recommendation','recruiter_invite'))"
    )
    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        "alter table job_sources add constraint job_sources_source_check "
        "check (source in ('linkedin','naukri','naukri_rdx'))"
    )
