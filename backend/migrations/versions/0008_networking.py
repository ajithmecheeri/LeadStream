"""Milestone 7: networking. LinkedIn connections (imported from the user's own data export), the day's
suggestions, and the outreach tracker.

Private (RLS FORCE, own_rows policy): connections, connection_imports, network_suggestions, outreach,
outreach_events. FitFirst never contacts anyone: these tables record what the user chose to do.

`person_key` identifies a person across imports: the profile URL, or name + company when the export has no URL.
`company_key` is the normalised company name used to match people to jobs (app/modules/networking/companies.py).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"
PRIVATE_TABLES = ["connection_imports", "connections", "network_suggestions", "outreach", "outreach_events"]


def upgrade() -> None:
    op.execute("""
    create table connection_imports (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      file_name text,
      total int not null default 0,
      added int not null default 0,
      updated int not null default 0,
      skipped int not null default 0,
      kept_email boolean not null default false,
      created_at timestamptz not null default now()
    )""")
    op.execute("""
    create table connections (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      person_key text not null,
      first_name text,
      last_name text,
      profile_url text,
      email text,
      company text,
      position text,
      connected_on date,
      company_key text,
      import_id uuid references connection_imports on delete set null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique (user_id, person_key)
    )""")
    op.execute("create index ix_connections_company on connections (user_id, company_key)")
    op.execute("""
    create table outreach (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      kind text not null check (kind in ('warm','target','manual')),
      person_name text,
      title text,
      company text,
      profile_url text,
      connection_id uuid references connections on delete set null,
      user_job_id uuid references user_jobs on delete set null,
      note text,
      stage text not null default 'sent'
        check (stage in ('sent','accepted','conversation','referral','closed')),
      stage_at timestamptz not null default now(),
      followed_up_at timestamptz,
      version int not null default 1,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute("create index ix_outreach_user_stage on outreach (user_id, stage, stage_at)")
    op.execute("""
    create table outreach_events (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      outreach_id uuid not null references outreach on delete cascade,
      kind text not null check (kind in ('sent','stage','followed_up','note')),
      stage text,
      note text,
      at timestamptz not null default now()
    )""")
    op.execute("create index ix_outreach_events_outreach on outreach_events (outreach_id, at)")
    op.execute("""
    create table network_suggestions (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      day date not null,
      kind text not null check (kind in ('warm','target','followup')),
      person_key text not null,
      position smallint not null default 0,
      connection_id uuid references connections on delete cascade,
      user_job_id uuid references user_jobs on delete cascade,
      outreach_id uuid references outreach on delete cascade,
      payload jsonb not null default '{}',
      status text not null default 'open' check (status in ('open','done','skipped')),
      created_at timestamptz not null default now(),
      unique (user_id, day, kind, person_key)
    )""")
    op.execute("create index ix_network_suggestions_day on network_suggestions (user_id, day)")
    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )


def downgrade() -> None:
    for t in reversed(PRIVATE_TABLES):
        op.execute(f"drop table if exists {t} cascade")
