"""Job Search Service, steps 0 and 1 (docs/plan-jobsearch-build.md).

- Followed companies and source runs now point to the service's employers (`employer_id`, no foreign key: the
  employers live in the service's database). The old feeds keep their ids there (decision 8), so the column is
  only renamed.
- company_feeds stays until the switch is confirmed; `exported_at` marks the rows sent to the service.
- jobsearch_sync (shared, one row): the event-feed cursor and the last demand sent.
- job_sources gains 'workday'.
- candidate_profiles.job_locations: where the user wants to work, asked at sign-up (step 1).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-14
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

SOURCES = (
    "'linkedin','naukri','naukri_rdx','greenhouse','lever','ashby','smartrecruiters','adzuna','ai_assistant'"
)


def upgrade() -> None:
    op.execute("alter table watched_companies drop constraint watched_companies_company_feed_id_fkey")
    op.execute("alter table watched_companies rename column company_feed_id to employer_id")
    op.execute("alter table watched_companies add column name text")
    # FORCE row-level security applies to the owner too: lifted for this one copy, as in 0024.
    op.execute("alter table watched_companies no force row level security")
    op.execute("update watched_companies w set name = f.name from company_feeds f where f.id = w.employer_id")
    op.execute("alter table watched_companies force row level security")
    op.execute("alter table source_runs drop constraint source_runs_company_feed_id_fkey")
    op.execute("alter table source_runs rename column company_feed_id to employer_id")
    op.execute("alter table company_feeds add column exported_at timestamptz")

    op.execute("""
    create table jobsearch_sync (
      id int primary key default 1 check (id = 1),
      cursor bigint not null default 0,
      demand_hash text,
      pulled_at timestamptz,
      pushed_at timestamptz,
      last_error text
    )""")
    op.execute("insert into jobsearch_sync (id) values (1)")

    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({SOURCES},'workday'))"
    )
    op.execute("alter table candidate_profiles add column job_locations text[] not null default '{}'")


def downgrade() -> None:
    op.execute("alter table candidate_profiles drop column job_locations")
    op.execute("delete from job_sources where source = 'workday'")
    op.execute("alter table job_sources drop constraint job_sources_source_check")
    op.execute(
        f"alter table job_sources add constraint job_sources_source_check check (source in ({SOURCES}))"
    )
    op.execute("drop table jobsearch_sync")
    op.execute("alter table company_feeds drop column exported_at")
    # Rows that point to employers the app never had as feeds (added through the service) can't go back.
    for t in ("source_runs", "watched_companies"):
        op.execute(f"alter table {t} no force row level security")
    op.execute(
        "delete from source_runs where employer_id is not null "
        "and employer_id not in (select id from company_feeds)"
    )
    op.execute("alter table source_runs rename column employer_id to company_feed_id")
    op.execute(
        "alter table source_runs add constraint source_runs_company_feed_id_fkey foreign key (company_feed_id) "
        "references company_feeds on delete cascade"
    )
    op.execute("delete from watched_companies where employer_id not in (select id from company_feeds)")
    op.execute("alter table watched_companies drop column name")
    op.execute("alter table watched_companies rename column employer_id to company_feed_id")
    op.execute(
        "alter table watched_companies add constraint watched_companies_company_feed_id_fkey "
        "foreign key (company_feed_id) references company_feeds on delete cascade"
    )
    for t in ("source_runs", "watched_companies"):
        op.execute(f"alter table {t} force row level security")
