"""Milestone 14.3: browser extension pairings.

Private (RLS FORCE, own_rows policy): extension_tokens, one row per paired browser. A row starts as a pairing
code (hash, 10 minutes) made on Settings; the extension trades the code for its own token (hash kept, never the
token). The token can only read what application forms need; Settings lists and revokes them.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table extension_tokens (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      name text,
      pair_code_hash text,
      pair_expires_at timestamptz,
      token_hash text unique,
      created_at timestamptz not null default now(),
      paired_at timestamptz,
      last_used_at timestamptz,
      revoked_at timestamptz
    )""")
    op.execute("alter table extension_tokens enable row level security")
    op.execute("alter table extension_tokens force row level security")
    op.execute(
        f"create policy own_rows on extension_tokens using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )


def downgrade() -> None:
    op.execute("drop table extension_tokens")
