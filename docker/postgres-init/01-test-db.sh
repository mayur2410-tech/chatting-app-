#!/bin/sh
# Creates a separate database for the automated tests so they never touch development data.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE DATABASE ${POSTGRES_DB}_test OWNER "$POSTGRES_USER";
EOSQL
