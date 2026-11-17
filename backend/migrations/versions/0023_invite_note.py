"""The user's own invitation note for people they don't know yet (user feedback 2026-11-11).

Networking suggests people to find at companies hiring for a Top match, with a note to copy. The user writes
that note once on the Networking page; empty means the built-in note. candidate_profiles is already private
(RLS FORCE, own_rows) from 0001.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-11
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table candidate_profiles add column invite_note text")


def downgrade() -> None:
    op.execute("alter table candidate_profiles drop column invite_note")
