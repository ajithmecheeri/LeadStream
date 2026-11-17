"""The roles a user's Google Alerts are suggested for (user, 2026-11-15: "add/edit 5 roles").

candidate_profiles gains alert_roles (up to 5; empty: the target roles of the Skill Match profiles).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-15
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table candidate_profiles add column alert_roles text[] not null default '{}'")


def downgrade() -> None:
    op.execute("alter table candidate_profiles drop column alert_roles")
