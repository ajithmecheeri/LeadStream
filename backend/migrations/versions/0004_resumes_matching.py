"""Milestone 3: resume and cover-letter library, job matches, AI call log, embeddings.

Private (RLS FORCE, own_rows policy): stored_files, resumes, cover_letters, job_matches, llm_calls.

- Resumes belong to the user (one primary, up to 3 variations); a resume may name a focus search profile.
  The LLD had them per search profile; see docs/plan-m3.md.
- Original uploads are kept in stored_files (bytea) until object storage arrives, like inbound_raw.
- job_matches holds one row per user job: the best search profile's verdict, the band that decides the Jobs
  tab, and a score for every resume (`ranking`). It replaces the LLD's job_scores + resume_recommendations
  for now; the per-profile split returns if users ask to compare profiles side by side.
- Embeddings (Voyage voyage-4-lite, 1024 numbers) are real[] with the hash of the text they were made from, so
  unchanged text is never sent twice. user_jobs carries its own (the user may have pasted a description).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PRIVATE_TABLES = ["stored_files", "resumes", "cover_letters", "job_matches", "llm_calls"]
USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
    create table stored_files (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      name text not null,
      kind text not null check (kind in ('pdf','docx','odt','rtf','txt','md')),
      size int not null,
      sha256 text not null,
      data bytea not null,
      created_at timestamptz not null default now()
    )""")

    op.execute("""
    create table resumes (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      search_profile_id uuid references search_profiles on delete set null,
      label text not null,
      focus_tags text[] not null default '{}',
      text text not null,
      file_id uuid references stored_files on delete set null,
      source text not null default 'upload' check (source in ('upload','paste','tailored')),
      is_primary boolean not null default false,
      version int not null default 1,
      embedding real[],
      embedding_key text,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute("create unique index ux_resumes_one_primary on resumes (user_id) where is_primary")
    op.execute("create index ix_resumes_user on resumes (user_id, created_at)")

    op.execute("""
    create table cover_letters (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      label text not null,
      text text not null,
      file_id uuid references stored_files on delete set null,
      is_default boolean not null default false,
      version int not null default 1,
      embedding real[],
      embedding_key text,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )""")
    op.execute("create unique index ux_cover_letters_one_default on cover_letters (user_id) where is_default")
    op.execute("create index ix_cover_letters_user on cover_letters (user_id, created_at)")

    op.execute("""
    create table job_matches (
      user_job_id uuid primary key references user_jobs on delete cascade,
      user_id uuid not null references users on delete cascade,
      search_profile_id uuid references search_profiles on delete set null,
      band text not null check (band in ('strong','good','low','filtered')),
      score smallint not null check (score between 0 and 100),
      filter_reason text,
      factors jsonb not null default '{}',
      ranking jsonb not null default '[]',
      primary_resume_id uuid references resumes on delete set null,
      primary_score smallint,
      best_resume_id uuid references resumes on delete set null,
      best_score smallint,
      cover_letter_id uuid references cover_letters on delete set null,
      strengths text[] not null default '{}',
      gaps text[] not null default '{}',
      method text not null default 'rules' check (method in ('rules','llm')),
      provisional boolean not null default true,
      scored_at timestamptz not null default now()
    )""")
    op.execute("create index ix_job_matches_user_band on job_matches (user_id, band, score desc)")

    op.execute("""
    create table llm_calls (
      id bigserial primary key,
      user_id uuid not null references users on delete cascade,
      provider text not null,
      model text not null,
      prompt text not null,
      prompt_version text,
      input_tokens int not null default 0,
      output_tokens int not null default 0,
      cost_usd numeric(10,6) not null default 0,
      latency_ms int,
      ok boolean not null,
      error text,
      created_at timestamptz not null default now()
    )""")
    op.execute("create index ix_llm_calls_user_created on llm_calls (user_id, created_at desc)")

    op.execute("alter table user_jobs add column embedding real[]")
    op.execute("alter table user_jobs add column embedding_key text")
    op.execute(
        "alter table search_profiles add constraint fk_search_profiles_default_resume "
        "foreign key (default_resume_id) references resumes on delete set null"
    )

    for t in PRIVATE_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy own_rows on {t} using (user_id = {USER_SETTING}) "
            f"with check (user_id = {USER_SETTING})"
        )
    # Default privileges from 0001 grant the app role access to the new tables and the llm_calls sequence.


def downgrade() -> None:
    op.execute("alter table search_profiles drop constraint if exists fk_search_profiles_default_resume")
    op.execute("alter table user_jobs drop column if exists embedding_key")
    op.execute("alter table user_jobs drop column if exists embedding")
    for t in ["llm_calls", "job_matches", "cover_letters", "resumes", "stored_files"]:
        op.execute(f"drop table if exists {t}")
