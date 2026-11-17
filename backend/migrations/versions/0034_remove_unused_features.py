"""Drop the tables of features LeadStream does not have (docs/SUNSTREAM-SPEC.md).

LeadStream started as a copy of BrewMyJob. These features were removed from the code, so their tables go:
the public waitlist and contact messages, the browser extension's pairing tokens, the apply profile, networking
(connections, outreach, suggestions) and Job sources (company feeds, watched and platform companies, the event
feed's position). Nothing here is reversible; a fresh database never needs them.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-17
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

TABLES = [
    "waitlist",
    "contact_messages",
    "extension_tokens",
    "apply_profiles",
    "network_suggestions",
    "outreach_events",
    "outreach",
    "connections",
    "connection_imports",
    "company_feeds",
    "watched_companies",
    "platform_companies",
    "jobsearch_sync",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"drop table if exists {table} cascade")


def downgrade() -> None:
    raise NotImplementedError("The removed features' tables are not recreated; restore from a backup instead.")
