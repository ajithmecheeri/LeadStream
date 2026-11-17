"""Key skills on a search profile (user feedback 2026-11-04): jobs that ask for them score higher.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table search_profiles add column skills text[] not null default '{}'")


def downgrade() -> None:
    op.execute("alter table search_profiles drop column skills")
