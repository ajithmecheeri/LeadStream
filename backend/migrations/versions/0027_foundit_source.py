"""Jobs the user adds by hand after a Google search (2026-11-14, jobs/found.py): Foundit links join LinkedIn and
Naukri as a source. Only the link's job id is kept; the site is never read.

job_sources gains 'foundit'. No new tables.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-14
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

BEFORE = (
    "'linkedin','naukri','naukri_rdx','greenhouse','lever','ashby','smartrecruiters','adzuna','ai_assistant',"
    "'workday','oracle','eightfold','careers_page'"
)


def _sources(values: str) -> None:
    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({values}))"
    )


def upgrade() -> None:
    _sources(BEFORE + ",'foundit'")


def downgrade() -> None:
    op.execute("delete from job_sources where source = 'foundit'")
    _sources(BEFORE)
