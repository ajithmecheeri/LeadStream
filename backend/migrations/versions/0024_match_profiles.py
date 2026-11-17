"""Skill Match profiles: one search profile per resume (user feedback 2026-11-13).

Each resume gets its own match profile. Its skills come in two lists: `resume_skills`, read from the resume and
refreshed whenever the resume changes, and `skills`, the ones the user added by hand (kept across refreshes).
Deleting a resume deletes its match profile (on delete cascade).

The user chose to start fresh: every resume gets a new profile with the settings (locations, work models,
seniority, exclusions, weights, threshold) of the user's oldest profile, and the old profiles that belong to no
resume are removed. Target roles and resume skills are filled by the app from the resume on first use
(profiles.service.ensure_match_profiles), because reading a resume needs Python.

search_profiles is already private (RLS FORCE, own_rows) from 0001; FORCE is lifted only while this migration's
data step runs, in the same transaction.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-13
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

DEFAULT_WEIGHTS = '{"role": 20, "exp": 15, "core": 15, "cloud": 10, "ai": 10, "domain": 10, "loc": 10, "skills": 5, "comp": 5}'
TABLES = ("search_profiles", "resumes", "candidate_profiles", "job_matches")


def upgrade() -> None:
    op.execute(
        "alter table search_profiles add column resume_id uuid references resumes(id) on delete cascade"
    )
    op.execute(
        "create unique index ux_search_profiles_resume on search_profiles (resume_id) where resume_id is not null"
    )
    op.execute("alter table search_profiles add column resume_skills text[] not null default '{}'")
    op.execute("alter table search_profiles add column resume_read_at timestamptz")

    for t in TABLES:
        op.execute(f"alter table {t} no force row level security")
    op.execute("""
        create temp table match_template on commit drop as
        select distinct on (user_id) user_id, locations, work_models, min_seniority, excluded_companies,
               weights, threshold
        from search_profiles order by user_id, created_at
    """)
    # The widest of the user's old profiles, so no job they were open to is ruled out: the lowest seniority
    # and every place (2026-11-13: the oldest profile alone was VP-only and ruled out the Director roles).
    op.execute("""
        update match_template t set
          min_seniority = w.min_seniority,
          locations = w.locations,
          work_models = w.work_models
        from (
          select user_id, min(min_seniority) min_seniority,
                 array(select distinct x from search_profiles s2, unnest(s2.locations) x
                       where s2.user_id = s.user_id) locations,
                 array(select distinct x from search_profiles s2, unnest(s2.work_models) x
                       where s2.user_id = s.user_id) work_models
          from search_profiles s group by user_id
        ) w
        where w.user_id = t.user_id
    """)
    op.execute("""
        update job_matches set search_profile_id = null
        where search_profile_id in (
            select id from search_profiles s where exists (select 1 from resumes r where r.user_id = s.user_id)
        )
    """)
    op.execute(
        "delete from search_profiles s where exists (select 1 from resumes r where r.user_id = s.user_id)"
    )
    op.execute(f"""
        insert into search_profiles (user_id, name, target_roles, locations, work_models, min_seniority,
                                     excluded_companies, weights, threshold, active, resume_id, skills)
        select r.user_id,
               left(r.label, 50) || case when n > 1 then ' (' || n || ')' else '' end,
               '{{}}',
               coalesce(t.locations, case when c.current_location is not null then array[c.current_location]
                                          else '{{}}'::text[] end),
               coalesce(t.work_models, '{{Hybrid,On-site,Remote}}'),
               coalesce(t.min_seniority, 5),
               coalesce(t.excluded_companies, '{{}}'),
               coalesce(t.weights, '{DEFAULT_WEIGHTS}'::jsonb),
               coalesce(t.threshold, 85),
               true, r.id, '{{}}'
        from (select *, row_number() over (partition by user_id, lower(label) order by created_at) n
              from resumes) r
        left join match_template t on t.user_id = r.user_id
        left join candidate_profiles c on c.user_id = r.user_id
    """)
    for t in TABLES:
        op.execute(f"alter table {t} force row level security")


def downgrade() -> None:
    op.execute("drop index if exists ux_search_profiles_resume")
    for c in ("resume_read_at", "resume_skills", "resume_id"):
        op.execute(f"alter table search_profiles drop column if exists {c}")
