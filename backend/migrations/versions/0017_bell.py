"""In-app bell (milestone 6.2): when the user last opened it, for the unread count. The bell's items are worked
out on read (notifications/bell.py), so no new table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table notification_settings add column bell_seen_at timestamptz")


def downgrade() -> None:
    op.execute("alter table notification_settings drop column bell_seen_at")
