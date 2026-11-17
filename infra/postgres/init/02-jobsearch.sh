#!/bin/sh
# The Job Search Service's roles and databases (docs/jobsearch-plan-discovery.md, section 12).
# Runs when the Postgres volume is first created (docker-entrypoint-initdb.d), and again from the
# `jobsearch-db` one-shot container on an existing volume: every step is skipped when already done.
set -eu
: "${JOBSEARCH_DB_OWNER:=jobsearch}" "${JOBSEARCH_DB_OWNER_PASSWORD:=jobsearch}"
: "${JOBSEARCH_APP_DB_ROLE:=jobsearch_app}" "${JOBSEARCH_APP_DB_PASSWORD:=jobsearch_app}"
: "${JOBSEARCH_DB_NAME:=jobsearch}"
PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
export PGUSER

psql -v ON_ERROR_STOP=1 --dbname postgres <<SQL
do \$\$ begin
  if not exists (select 1 from pg_roles where rolname = '${JOBSEARCH_DB_OWNER}') then
    create role ${JOBSEARCH_DB_OWNER} login password '${JOBSEARCH_DB_OWNER_PASSWORD}' nosuperuser nobypassrls createdb;
  end if;
  if not exists (select 1 from pg_roles where rolname = '${JOBSEARCH_APP_DB_ROLE}') then
    create role ${JOBSEARCH_APP_DB_ROLE} login password '${JOBSEARCH_APP_DB_PASSWORD}' nosuperuser nobypassrls nocreatedb;
  end if;
end \$\$;
select 'create database ${JOBSEARCH_DB_NAME} owner ${JOBSEARCH_DB_OWNER}'
  where not exists (select 1 from pg_database where datname = '${JOBSEARCH_DB_NAME}') \gexec
select 'create database ${JOBSEARCH_DB_NAME}_test owner ${JOBSEARCH_DB_OWNER}'
  where not exists (select 1 from pg_database where datname = '${JOBSEARCH_DB_NAME}_test') \gexec
grant connect on database ${JOBSEARCH_DB_NAME} to ${JOBSEARCH_APP_DB_ROLE};
grant connect on database ${JOBSEARCH_DB_NAME}_test to ${JOBSEARCH_APP_DB_ROLE};
SQL

for db in "${JOBSEARCH_DB_NAME}" "${JOBSEARCH_DB_NAME}_test"; do
psql -v ON_ERROR_STOP=1 --dbname "$db" <<SQL
alter schema public owner to ${JOBSEARCH_DB_OWNER};
grant usage on schema public to ${JOBSEARCH_APP_DB_ROLE};
SQL
done
