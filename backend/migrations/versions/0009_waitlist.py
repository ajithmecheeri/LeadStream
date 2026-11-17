"""Milestone 10: the waitlist on the public home page.

Shared, no user_id (the people on it have no account yet). The app role can add and read (the super admin's
list); it can't change a row. Only the email, where it was given, and when are kept.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

import os

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")


def upgrade() -> None:
    op.execute("""
    create table waitlist (
      id uuid primary key,
      email text not null,
      source text not null default 'home',
      created_at timestamptz not null default now()
    )""")
    op.execute("create unique index waitlist_email on waitlist (lower(email))")
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke update on waitlist from {APP_ROLE}';
      end if;
    end $$""")


def downgrade() -> None:
    op.execute("drop table if exists waitlist")
