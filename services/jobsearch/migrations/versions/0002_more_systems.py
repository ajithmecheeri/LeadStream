"""Step 2: Oracle Recruiting Cloud, Eightfold and companies' own careers pages; pages found outside India.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

BEFORE = "'greenhouse','lever','ashby','smartrecruiters','workday'"


def _systems(values: str) -> None:
    op.execute("alter table employer_boards drop constraint employer_boards_system_check")
    op.execute(
        f"alter table employer_boards add constraint employer_boards_system_check check (system in ({values}))"
    )


def upgrade() -> None:
    _systems(BEFORE + ",'oracle','eightfold','careers_page'")
    op.execute("""
    create table board_pages (
      board_id uuid not null references employer_boards on delete cascade,
      page_id text not null,
      checked_at timestamptz not null default now(),
      primary key (board_id, page_id)
    )""")


def downgrade() -> None:
    op.execute("drop table board_pages")
    op.execute("delete from employer_boards where system in ('oracle','eightfold','careers_page')")
    _systems(BEFORE)
