"""Milestone 13 C (first step): mark "Not for me" answers as reviewed.

`make feedback` lists the answers nobody has reviewed yet, with the job and its score; once the rules have been
tuned for them, `make feedback-done` stamps them (when, and what was done) so the next review starts with the new
ones. job_feedback is already private (RLS FORCE, own_rows) from 0018.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-11
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table job_feedback add column reviewed_at timestamptz, add column review_note text")


def downgrade() -> None:
    op.execute("alter table job_feedback drop column reviewed_at, drop column review_note")
