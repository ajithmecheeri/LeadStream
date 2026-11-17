"""Milestone 2 jobs: the user's own copy of a job description, and the index the Jobs list filters on.

A pasted full description (POST /jobs/{id}/description) is stored on the user's private user_jobs row, not
in the shared catalog, so one user can't change what other users see.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table user_jobs add column description text")
    op.execute("alter table user_jobs add column description_updated_at timestamptz")
    op.execute(
        "create index ix_user_jobs_user_status_first_seen on user_jobs (user_id, status, first_seen_at desc)"
    )


def downgrade() -> None:
    op.execute("drop index if exists ix_user_jobs_user_status_first_seen")
    op.execute("alter table user_jobs drop column if exists description_updated_at")
    op.execute("alter table user_jobs drop column if exists description")
