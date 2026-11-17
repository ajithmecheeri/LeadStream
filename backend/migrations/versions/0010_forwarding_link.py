"""Gmail's forwarding confirmation now carries a link to click instead of a code to type.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table inbound_messages add column forwarding_link text")


def downgrade() -> None:
    op.execute("alter table inbound_messages drop column forwarding_link")
