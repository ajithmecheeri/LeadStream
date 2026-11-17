"""Google Alerts by RSS (2026-11-15, discovery plan decision 10), and the last pull of the job search service.

- alert_feeds (private, RLS FORCE, own_rows): a Google Alerts RSS feed the user added, and what its last read
  brought. Only the feed is read; the job pages it links to never are.
- jobsearch_sync gains the last pull that brought something (jobs, new, updated, closed), for Job sources.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-15
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table alert_feeds (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references users on delete cascade,
      feed_url text not null,
      query text,
      created_at timestamptz not null default now(),
      last_read_at timestamptz,
      last_error text,
      last_found int not null default 0,
      last_added int not null default 0,
      last_skipped int not null default 0,
      last_job_ids uuid[] not null default '{}',
      unique (user_id, feed_url)
    )""")
    op.execute("alter table alert_feeds enable row level security")
    op.execute("alter table alert_feeds force row level security")
    op.execute(
        f"create policy own_rows on alert_feeds using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )
    op.execute("""
    alter table jobsearch_sync
      add column last_pull_started_at timestamptz,
      add column last_pull_at timestamptz,
      add column last_pull_jobs int,
      add column last_pull_new int,
      add column last_pull_updated int,
      add column last_pull_closed int""")


def downgrade() -> None:
    op.execute("""
    alter table jobsearch_sync
      drop column last_pull_started_at,
      drop column last_pull_at,
      drop column last_pull_jobs,
      drop column last_pull_new,
      drop column last_pull_updated,
      drop column last_pull_closed""")
    op.execute("drop table alert_feeds")
