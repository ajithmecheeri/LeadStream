"""WhatsApp alerts for strong matches (user, 2026-11-05; milestone 6).

notification_settings gains the user's WhatsApp number, its verification (a one-time code sent by WhatsApp; only
its sha256 is kept) and an on/off switch for job alerts.

Private (RLS FORCE, own_rows policy): notifications, the outbox. One row per message: queued, held for quiet
hours, sent, logged (no WhatsApp keys yet: written to the worker log instead), failed or skipped (with why).
At most one new-job message per job and channel, so a job seen again never sends twice.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    alter table notification_settings
      add column whatsapp_number text check (whatsapp_number ~ '^[1-9][0-9]{9,14}$'),
      add column whatsapp_verified_at timestamptz,
      add column whatsapp_jobs boolean not null default true,
      add column whatsapp_code_hash text,
      add column whatsapp_code_sent_at timestamptz,
      add column whatsapp_code_tries smallint not null default 0
    """)
    op.execute("""
    create table notifications (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      user_job_id uuid references user_jobs on delete cascade,
      channel text not null check (channel in ('whatsapp')),
      kind text not null check (kind in ('new_job', 'test', 'code')),
      status text not null default 'queued'
        check (status in ('queued', 'held', 'sent', 'logged', 'failed', 'skipped')),
      body text not null,
      send_after timestamptz not null default now(),
      attempts smallint not null default 0,
      provider_id text,
      error text,
      created_at timestamptz not null default now(),
      sent_at timestamptz
    )""")
    op.execute(
        "create unique index ux_notifications_one_per_job on notifications (user_id, user_job_id, channel) "
        "where kind = 'new_job'"
    )
    op.execute("create index ix_notifications_user_created on notifications (user_id, created_at desc)")
    op.execute("alter table notifications enable row level security")
    op.execute("alter table notifications force row level security")
    op.execute(
        f"create policy own_rows on notifications using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )


def downgrade() -> None:
    op.execute("drop table notifications")
    op.execute("""
    alter table notification_settings
      drop column whatsapp_number,
      drop column whatsapp_verified_at,
      drop column whatsapp_jobs,
      drop column whatsapp_code_hash,
      drop column whatsapp_code_sent_at,
      drop column whatsapp_code_tries
    """)
