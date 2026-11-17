"""Milestone 10: messages from the public contact page (/contact).

Shared, no user_id (the sender may have no account), like the waitlist. The app role can add and read (the super
admin's list on Admin settings); it can't change or delete a row.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09
"""

import os

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "fitfirst_app")


def upgrade() -> None:
    op.execute("""
    create table contact_messages (
      id uuid primary key,
      name text not null check (length(name) <= 100),
      email text not null,
      topic text not null check (topic in ('general', 'support', 'privacy', 'feedback')),
      message text not null check (length(message) <= 2000),
      created_at timestamptz not null default now()
    )""")
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        execute 'revoke update, delete on contact_messages from {APP_ROLE}';
      end if;
    end $$""")


def downgrade() -> None:
    op.execute("drop table if exists contact_messages")
