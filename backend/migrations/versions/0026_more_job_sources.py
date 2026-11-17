"""Job Search Service step 2: jobs from Oracle Recruiting Cloud, Eightfold and companies' own careers pages.

job_sources gains 'oracle', 'eightfold' and 'careers_page'. No new tables.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-14
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

BEFORE = "'linkedin','naukri','naukri_rdx','greenhouse','lever','ashby','smartrecruiters','adzuna','ai_assistant','workday'"


def _sources(values: str) -> None:
    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({values}))"
    )


def upgrade() -> None:
    _sources(BEFORE + ",'oracle','eightfold','careers_page'")


def downgrade() -> None:
    op.execute("delete from job_sources where source in ('oracle','eightfold','careers_page')")
    _sources(BEFORE)
