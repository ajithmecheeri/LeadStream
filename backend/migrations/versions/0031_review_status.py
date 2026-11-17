"""Jobs waiting for review: added from Google search results by the extension (POC, user 2026-11-17).

Revision ID: 0031
Revises: 0030
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check "
        "check (status in ('new','seen','ignored','applied','expired','duplicate','review'))"
    )


def downgrade() -> None:
    op.execute("update user_jobs set status = 'new' where status = 'review'")
    op.execute("alter table user_jobs drop constraint user_jobs_status_check")
    op.execute(
        "alter table user_jobs add constraint user_jobs_status_check "
        "check (status in ('new','seen','ignored','applied','expired','duplicate'))"
    )
