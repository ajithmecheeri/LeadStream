"""One shared list of companies, kept by the admins (user, 2026-11-17; docs/plan-roles-and-plans.md, decision 7).

platform_companies is shared like the job catalog: which employers BrewMyJob reads for everyone, no user data
(added_by is the admin). The companies users followed before are copied in. watched_companies stays (unused) until
a later clean-up.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-17
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    create table platform_companies (
      employer_id uuid primary key,
      name text,
      added_by uuid references users on delete set null,
      created_at timestamptz not null default now()
    )""")
    # watched_companies forces row level security, also for the owner: lift it for the copy only.
    op.execute("alter table watched_companies no force row level security")
    op.execute("""
    insert into platform_companies (employer_id, name, added_by, created_at)
    select distinct on (employer_id) employer_id, name, user_id, created_at
    from watched_companies order by employer_id, created_at
    """)
    op.execute("alter table watched_companies force row level security")


def downgrade() -> None:
    op.execute("drop table if exists platform_companies")
