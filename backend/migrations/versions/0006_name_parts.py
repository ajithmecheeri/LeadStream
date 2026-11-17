"""First, middle and last name on the account (requested 2026-11-01).

`users.name` stays: it is the display name, always built from the parts ("First Middle Last"). Existing accounts
are split at the first space: the first word is the first name, the rest the last name.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table users add column first_name text")
    op.execute("alter table users add column middle_name text")
    op.execute("alter table users add column last_name text")
    op.execute("""
    update users set
      first_name = split_part(btrim(name), ' ', 1),
      last_name = nullif(btrim(substr(btrim(name), length(split_part(btrim(name), ' ', 1)) + 1)), '')
    """)
    op.execute("alter table users alter column first_name set not null")


def downgrade() -> None:
    for c in ("last_name", "middle_name", "first_name"):
        op.execute(f"alter table users drop column if exists {c}")
