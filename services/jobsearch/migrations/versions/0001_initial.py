"""The Job Search Service's tables, its task queue, and its app role's privileges.

No table holds user data, so there is no row-level security (docs/jobsearch-plan-discovery.md, section 8).
Discovery's tables (leads, discovery_runs, llm_calls) come with step 3.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

import os
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("JOBSEARCH_APP_DB_ROLE", "jobsearch_app")
PROCRASTINATE_SQL = Path(__file__).parents[1] / "sql" / "procrastinate-3.9.0.sql"
SYSTEMS = "'greenhouse','lever','ashby','smartrecruiters','workday'"


def _run_script(sql: str) -> None:
    await_(op.get_bind().connection.driver_connection.execute(sql))


def upgrade() -> None:
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'grant usage on schema public to {APP_ROLE}';
        execute 'alter default privileges in schema public grant select, insert, update, delete on tables to {APP_ROLE}';
        execute 'alter default privileges in schema public grant usage, select on sequences to {APP_ROLE}';
        execute 'alter default privileges in schema public grant execute on functions to {APP_ROLE}';
      else
        raise warning 'role {APP_ROLE} does not exist; run infra/postgres/init/02-jobsearch.sh first';
      end if;
    end $$""")

    op.execute("""
    create table employers (
      id uuid primary key default gen_random_uuid(),
      name text not null,
      website text,
      careers_url text,
      country text not null default 'IN',
      created_at timestamptz not null default now()
    )""")
    op.execute(f"""
    create table employer_boards (
      id uuid primary key default gen_random_uuid(),
      employer_id uuid not null references employers on delete cascade,
      system text not null check (system in ({SYSTEMS})),
      board text not null,
      last_checked_at timestamptz,
      last_error text,
      jobs_total int,
      jobs_in_scope int,
      created_at timestamptz not null default now()
    )""")
    op.execute("create unique index ux_employer_boards_board on employer_boards (system, lower(board))")
    op.execute("create index ix_employer_boards_employer on employer_boards (employer_id)")

    op.execute("""
    create table search_areas (
      id uuid primary key default gen_random_uuid(),
      location text not null,
      role_family text not null,
      titles text[] not null default '{}',
      active boolean not null default true,
      last_api_run_at timestamptz,
      updated_at timestamptz not null default now()
    )""")
    op.execute("create unique index ux_search_areas on search_areas (lower(location), role_family)")

    op.execute("""
    create table listings (
      id uuid primary key default gen_random_uuid(),
      employer_id uuid references employers on delete set null,
      board_id uuid references employer_boards on delete set null,
      company text,
      title text not null,
      location text,
      work_model text,
      experience text,
      salary text,
      description text,
      skills text[] not null default '{}',
      details jsonb not null default '{}',
      requisition_id text,
      posted_at timestamptz,
      status text not null default 'active' check (status in ('pending','active','closed')),
      missed_checks int not null default 0,
      content_hash text not null,
      version int not null default 1,
      first_seen_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now(),
      closed_at timestamptz
    )""")
    op.execute("create index ix_listings_board_status on listings (board_id, status)")
    op.execute("create index ix_listings_requisition on listings (employer_id, requisition_id)")

    op.execute("""
    create table listing_sources (
      id uuid primary key default gen_random_uuid(),
      listing_id uuid not null references listings on delete cascade,
      source text not null,
      source_job_id text not null,
      url text,
      apply_url text,
      first_seen_at timestamptz not null default now(),
      unique (source, source_job_id)
    )""")
    op.execute("create index ix_listing_sources_listing on listing_sources (listing_id)")

    op.execute("""
    create table listing_versions (
      id bigserial primary key,
      listing_id uuid not null references listings on delete cascade,
      version int not null,
      snapshot jsonb not null,
      replaced_at timestamptz not null default now()
    )""")
    op.execute("create index ix_listing_versions_listing on listing_versions (listing_id, version)")

    op.execute("""
    create table events (
      id bigserial primary key,
      type text not null check (type in ('NEW','UPDATED','REPOSTED','CLOSED')),
      listing_id uuid not null references listings on delete cascade,
      occurred_at timestamptz not null default now()
    )""")

    op.execute("""
    create table connector_runs (
      id uuid primary key default gen_random_uuid(),
      connector text not null,
      board_id uuid references employer_boards on delete cascade,
      search_area_id uuid references search_areas on delete set null,
      started_at timestamptz not null default now(),
      finished_at timestamptz,
      found int not null default 0,
      new int not null default 0,
      updated int not null default 0,
      reposted int not null default 0,
      closed int not null default 0,
      pending int not null default 0,
      error text
    )""")
    op.execute("create index ix_connector_runs_started on connector_runs (started_at desc)")
    op.execute("create index ix_connector_runs_board on connector_runs (board_id, started_at desc)")

    op.execute("""
    create table api_quota (
      api text not null,
      day date not null,
      calls int not null default 0,
      primary key (api, day)
    )""")

    _run_script(PROCRASTINATE_SQL.read_text())


def downgrade() -> None:
    op.execute("""
    do $$ declare r record; begin
      for r in select oid::regprocedure as fn from pg_proc where proname like 'procrastinate%' loop
        execute 'drop function if exists ' || r.fn || ' cascade';
      end loop;
    end $$""")
    for t in [
        "procrastinate_events",
        "procrastinate_periodic_defers",
        "procrastinate_jobs",
        "procrastinate_workers",
        "api_quota",
        "connector_runs",
        "events",
        "listing_versions",
        "listing_sources",
        "listings",
        "search_areas",
        "employer_boards",
        "employers",
    ]:
        op.execute(f"drop table if exists {t} cascade")
    for t in ["procrastinate_job_to_defer_v1", "procrastinate_job_event_type", "procrastinate_job_status"]:
        op.execute(f"drop type if exists {t} cascade")
