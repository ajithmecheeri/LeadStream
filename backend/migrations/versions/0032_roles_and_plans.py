"""Roles, invites and plans (user, 2026-11-17; docs/plan-roles-and-plans.md).

users.role: job_seeker | admin | super_admin (was user | admin). users.access_until: the end of the job seeker's
paid or coupon period (no row level security on users; read by the auth service). subscriptions: each period,
private (RLS FORCE). invites: made by the super admin (no user data of the invitee beyond the email, like the
waitlist); only a hash of the link's token is kept.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-17
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

USER_SETTING = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("alter table users drop constraint users_role_check")  # was ('user','admin'), migration 0001
    op.execute("update users set role = 'super_admin' where role = 'admin'")
    op.execute("update users set role = 'job_seeker' where role = 'user'")
    op.execute("alter table users alter column role set default 'job_seeker'")
    op.execute(
        "alter table users add constraint users_role_check check (role in ('job_seeker','admin','super_admin'))"
    )
    op.execute("alter table users add column access_until timestamptz")

    op.execute("""
    create table invites (
      id uuid primary key,
      email text not null,
      role text not null check (role in ('job_seeker','admin')),
      free_months int not null default 0 check (free_months in (0, 1, 3)),
      token_hash text not null unique,
      created_by uuid references users on delete set null,
      created_at timestamptz not null default now(),
      expires_at timestamptz not null,
      accepted_at timestamptz,
      accepted_by uuid references users on delete set null,
      revoked_at timestamptz
    )""")
    op.execute("create index ix_invites_email on invites (lower(email))")

    op.execute("""
    create table subscriptions (
      id uuid primary key,
      user_id uuid not null references users on delete cascade,
      kind text not null check (kind in ('coupon','payment')),
      plan text not null,
      months int not null,
      starts_at timestamptz not null,
      ends_at timestamptz not null,
      invite_id uuid references invites on delete set null,
      created_at timestamptz not null default now()
    )""")
    op.execute("create index ix_subscriptions_user on subscriptions (user_id, ends_at desc)")
    op.execute("alter table subscriptions enable row level security")
    op.execute("alter table subscriptions force row level security")
    op.execute(
        f"create policy own_rows on subscriptions using (user_id = {USER_SETTING}) "
        f"with check (user_id = {USER_SETTING})"
    )


def downgrade() -> None:
    op.execute("drop table if exists subscriptions")
    op.execute("drop table if exists invites")
    op.execute("alter table users drop column access_until")
    op.execute("alter table users drop constraint users_role_check")
    op.execute("alter table users alter column role set default 'user'")
    op.execute("update users set role = 'user' where role in ('job_seeker')")
    op.execute("update users set role = 'admin' where role in ('admin','super_admin')")
    op.execute("alter table users add constraint users_role_check check (role in ('user','admin'))")
