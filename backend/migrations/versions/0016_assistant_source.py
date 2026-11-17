"""Jobs from an AI assistant's alert email (user, 2026-11-08: a scheduled ChatGPT task mailing job lists).

job_sources gains source 'ai_assistant'. No new tables.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-08
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

BEFORE = "'linkedin','naukri','naukri_rdx','greenhouse','lever','ashby','smartrecruiters','adzuna'"


def _sources(values: str) -> None:
    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({values}))"
    )


def upgrade() -> None:
    _sources(BEFORE + ",'ai_assistant'")


def downgrade() -> None:
    op.execute("delete from job_sources where source = 'ai_assistant'")  # the jobs stay, without this source
    _sources(BEFORE)
