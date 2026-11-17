"""Milestone 2 ingestion: received alert emails, the shared job catalog, each user's jobs, the task queue.

Private (RLS FORCE, own_rows policy): inbound_messages, inbound_raw, user_jobs.
Shared (no user_id, public posting data): jobs, job_sources. The app role may read, add and update them
but never delete. Private apply links (Naukri recruiter invites carry the user's login token) live on
user_jobs, never in the catalog.

Procrastinate's schema is applied from a vendored copy (migrations/sql/procrastinate-<version>.sql) so a
fresh database always gets the same schema; upgrading Procrastinate means a new migration that runs its
migration files.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""

import os
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")
PRIVATE_TABLES = ["inbound_messages", "inbound_raw", "user_jobs"]
USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"
PROCRASTINATE_SQL = Path(__file__).parents[1] / "sql" / "procrastinate-3.9.0.sql"


def _run_script(sql: str) -> None:
    """Run a multi-statement SQL script on the migration's own connection (and transaction)."""
    await_(op.get_bind().connection.driver_connection.execute(sql))


def upgrade() -> None:
    op.execute("""
    create table inbound_messages (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      message_id text not null,
      channel varchar(8) not null default 'email' check (channel in ('email','paste')),
      sender text not null,
      subject text,
      received_at timestamptz not null default now(),
      status varchar(16) not null default 'accepted'
        check (status in ('accepted','parsed','unparsed','failed')),
      parser text,
      alert_name text,
      cards_found int,
      error text,
      forwarding_code text,
      processed_at timestamptz,
      unique (user_id, message_id)
    )""")
    op.execute(
        "create index ix_inbound_messages_user_received on inbound_messages (user_id, received_at desc)"
    )

    op.execute("""
    create table inbound_raw (
      inbound_message_id uuid primary key references inbound_messages on delete cascade,
      user_id uuid not null references users on delete cascade,
      body bytea not null,
      created_at timestamptz not null default now()
    )""")
    op.execute("create index ix_inbound_raw_user_created on inbound_raw (user_id, created_at)")

    op.execute("""
    create table jobs (
      id uuid primary key default gen_random_uuid(),
      fingerprint text unique,
      title text not null,
      company text,
      location text,
      work_model text,
      experience text,
      salary text,
      skills text[] not null default '{}',
      description text,
      about_company text,
      offer text,
      description_complete boolean not null default false,
      details jsonb not null default '{}',
      posted_at timestamptz,
      first_seen_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")

    op.execute("""
    create table job_sources (
      id uuid primary key default gen_random_uuid(),
      job_id uuid not null references jobs on delete cascade,
      source varchar(16) not null check (source in ('linkedin','naukri','naukri_rdx')),
      source_job_id text not null,
      url text,
      first_seen_at timestamptz not null default now(),
      unique (source, source_job_id)
    )""")
    op.execute("create unique index ux_job_sources_url on job_sources (url) where url is not null")
    op.execute("create index ix_job_sources_job_id on job_sources (job_id)")

    op.execute("""
    create table user_jobs (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      job_id uuid not null references jobs on delete cascade,
      inbound_message_id uuid references inbound_messages on delete set null,
      status varchar(16) not null default 'new' check (status in ('new','seen','ignored')),
      lead varchar(24) not null check (lead in ('alert','recommendation','recruiter_invite')),
      outside_preference boolean not null default false,
      apply_url text,
      card_details jsonb not null default '{}',
      version int not null default 1,
      first_seen_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique (user_id, job_id)
    )""")
    op.execute("create index ix_user_jobs_user_first_seen on user_jobs (user_id, first_seen_at desc)")

    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )

    _run_script(PROCRASTINATE_SQL.read_text())

    # Default privileges from 0001 already grant the app role select/insert/update/delete on new tables
    # (including Procrastinate's). The shared catalog is append-and-merge only.
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke delete on jobs, job_sources from {APP_ROLE}';
      end if;
    end $$""")


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
        "user_jobs",
        "job_sources",
        "jobs",
        "inbound_raw",
        "inbound_messages",
    ]:
        op.execute(f"drop table if exists {t} cascade")
    for t in ["procrastinate_job_to_defer_v1", "procrastinate_job_event_type", "procrastinate_job_status"]:
        op.execute(f"drop type if exists {t} cascade")
