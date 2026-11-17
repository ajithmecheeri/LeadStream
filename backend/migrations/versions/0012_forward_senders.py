"""Hand-forwarded alerts (user, 2026-11-04): a user may forward LinkedIn/Naukri alerts by hand from addresses
they list, if they can't set up a Gmail filter.

Private (RLS FORCE, own_rows policy): forward_senders, the addresses a user forwards from.
Shared: jobs.verified. A hand forward loses the portal's DKIM signature, so its jobs are unverified: they never
change an existing catalog job, and the first verified sighting (a filtered alert, a feed) replaces their facts.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-04
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table forward_senders (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      address text not null check (address = lower(address)),
      created_at timestamptz not null default now(),
      unique (user_id, address)
    )""")
    op.execute("alter table forward_senders enable row level security")
    op.execute("alter table forward_senders force row level security")
    op.execute(
        f"create policy own_rows on forward_senders using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )
    op.execute("alter table jobs add column verified boolean not null default true")


def downgrade() -> None:
    op.execute("alter table jobs drop column verified")
    op.execute("drop table forward_senders")
