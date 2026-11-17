"""Each run's jobs, kept or skipped and why (user, 2026-11-16: "see last run jobs even if not matching").

source_runs gains jobs: [{"job_id": …, "why": null | "Below your level (Manager)"}], at most 300 per run.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-16
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table source_runs add column jobs jsonb not null default '[]'")


def downgrade() -> None:
    op.execute("alter table source_runs drop column jobs")
