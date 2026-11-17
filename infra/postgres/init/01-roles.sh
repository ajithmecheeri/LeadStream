#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates: the schema owner (runs migrations), the API role (subject to row-level security),
# and the app + test databases. To re-run, remove the volume: make reset-db
set -eu
: "${DB_OWNER:=fitfirst}" "${DB_OWNER_PASSWORD:=fitfirst}"
: "${APP_DB_ROLE:=fitfirst_app}" "${APP_DB_PASSWORD:=fitfirst_app}"
: "${DB_NAME:=fitfirst}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
create role ${DB_OWNER} login password '${DB_OWNER_PASSWORD}' nosuperuser nobypassrls createdb;
create role ${APP_DB_ROLE} login password '${APP_DB_PASSWORD}' nosuperuser nobypassrls nocreatedb;
create database ${DB_NAME} owner ${DB_OWNER};
create database ${DB_NAME}_test owner ${DB_OWNER};
grant connect on database ${DB_NAME} to ${APP_DB_ROLE};
grant connect on database ${DB_NAME}_test to ${APP_DB_ROLE};
SQL

for db in "${DB_NAME}" "${DB_NAME}_test"; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
alter schema public owner to ${DB_OWNER};
grant usage on schema public to ${APP_DB_ROLE};
SQL
done
