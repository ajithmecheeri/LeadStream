"""Milestone 14.1: the apply profile, what application forms ask for that the candidate profile doesn't hold:
phone, postal address, websites, languages, work history and education as structured entries.

Private (RLS FORCE, own_rows policy): apply_profiles, one row per user. Work history, education and languages are
JSON lists validated by the API (app/modules/apply/schemas.py) and saved as one form with a version.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-09
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table apply_profiles (
      user_id uuid primary key references users on delete cascade,
      phone text,
      address_line1 text,
      address_line2 text,
      city text,
      state text,
      postal_code text,
      country text,
      websites text[] not null default '{}',
      languages jsonb not null default '[]',
      work_history jsonb not null default '[]',
      education jsonb not null default '[]',
      version integer not null default 1,
      updated_at timestamptz not null default now()
    )""")
    op.execute("alter table apply_profiles enable row level security")
    op.execute("alter table apply_profiles force row level security")
    op.execute(
        f"create policy own_rows on apply_profiles using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )


def downgrade() -> None:
    op.execute("drop table apply_profiles")
