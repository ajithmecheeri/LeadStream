"""Milestone 1 foundation: users, sessions, consent, candidate and search profiles, notification settings.

Row-level security: every private table gets a policy that compares user_id with the per-transaction
setting app.user_id. FORCE makes the policy apply to the table owner too. The API connects as the
APP_DB_ROLE role (no BYPASSRLS), so a missing or wrong app.user_id returns no rows.

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""

import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")
PRIVATE_TABLES = ["consents", "candidate_profiles", "search_profiles", "notification_settings"]
USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("create extension if not exists citext")
    op.execute("create extension if not exists pgcrypto")

    op.execute("""
    create table users (
      id uuid primary key default gen_random_uuid(),
      email citext unique not null,
      name text not null,
      password_hash text,
      cognito_sub text unique,
      role varchar(16) not null default 'user' check (role in ('user','admin')),
      inbound_token text unique not null,
      timezone text not null default 'Asia/Kolkata',
      status varchar(16) not null default 'active' check (status in ('active','disabled','deleted')),
      plan_id text,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")

    op.execute("""
    create table refresh_tokens (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      family_id uuid not null,
      token_hash text unique not null,
      client varchar(16) not null default 'web' check (client in ('web','mobile')),
      created_at timestamptz not null default now(),
      expires_at timestamptz not null,
      rotated_at timestamptz,
      revoked_at timestamptz,
      user_agent text,
      ip inet
    )""")
    op.execute("create index ix_refresh_tokens_user_id on refresh_tokens (user_id)")
    op.execute("create index ix_refresh_tokens_family_id on refresh_tokens (family_id)")

    op.execute("""
    create table consents (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      notice_version text not null,
      purposes text[] not null,
      granted_at timestamptz not null default now(),
      withdrawn_at timestamptz
    )""")
    op.execute("create index ix_consents_user_id on consents (user_id)")

    op.execute("""
    create table candidate_profiles (
      user_id uuid primary key references users on delete cascade,
      headline text,
      summary text,
      current_location text,
      years_experience int check (years_experience between 0 and 60),
      skills text[] not null default '{}',
      domains text[] not null default '{}',
      notice_days int check (notice_days between 0 and 365),
      current_ctc text,
      expected_ctc text,
      work_authorization text,
      linkedin_url text,
      version int not null default 1,
      updated_at timestamptz not null default now()
    )""")

    op.execute("""
    create table search_profiles (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      name text not null,
      target_roles text[] not null,
      locations text[] not null,
      work_models text[] not null,
      min_seniority smallint not null check (min_seniority between 1 and 9),
      excluded_companies text[] not null default '{}',
      weights jsonb not null,
      threshold smallint not null default 85 check (threshold between 50 and 100),
      active boolean not null default true,
      default_resume_id uuid,
      version int not null default 1,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute("create index ix_search_profiles_user_id on search_profiles (user_id)")
    op.execute("create unique index ux_search_profiles_user_name on search_profiles (user_id, lower(name))")

    op.execute("""
    create table notification_settings (
      user_id uuid primary key references users on delete cascade,
      push boolean not null default true,
      email boolean not null default true,
      quiet_start time default '22:00',
      quiet_end time default '07:00',
      max_push_per_day int not null default 10,
      digest_time time not null default '19:00',
      network_daily_cap int not null default 5,
      network_weekly_limit int not null default 100
    )""")

    op.execute("""
    create table audit_events (
      id bigserial primary key,
      user_id uuid,
      actor text not null,
      event text not null,
      entity text,
      meta jsonb,
      at timestamptz not null default now()
    )""")
    op.execute("create index ix_audit_events_user_at on audit_events (user_id, at desc)")

    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )

    # Privileges for the API role. Default privileges cover tables created by later migrations.
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'grant usage on schema public to {APP_ROLE}';
        execute 'grant select, insert, update, delete on all tables in schema public to {APP_ROLE}';
        execute 'grant usage, select on all sequences in schema public to {APP_ROLE}';
        execute 'alter default privileges in schema public grant select, insert, update, delete on tables to {APP_ROLE}';
        execute 'alter default privileges in schema public grant usage, select on sequences to {APP_ROLE}';
      else
        raise warning 'role {APP_ROLE} does not exist; run infra/postgres/init/01-roles.sh first';
      end if;
    end $$""")
    # The app never deletes audit history.
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke update, delete on audit_events from {APP_ROLE}';
      end if;
    end $$""")


def downgrade() -> None:
    for t in [
        "audit_events",
        "notification_settings",
        "search_profiles",
        "candidate_profiles",
        "consents",
        "refresh_tokens",
        "users",
    ]:
        op.execute(f"drop table if exists {t} cascade")
