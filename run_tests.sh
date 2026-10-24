#!/usr/bin/env bash
# Usage: PGHOST=... PGPORT=... PGUSER=postgres ./run_tests.sh
# Rebuilds two scratch databases (default veritas_test and veritas_test_app) and never touches the real "veritas" one.
#   1. veritas_test      schema + seed, then the base ledger suite (tests.sql, 84 tests)
#   2. veritas_test_app  schema + seed + application layer (installed twice: it must be idempotent), then tests_app.sql (25 tests)
set -euo pipefail
cd "$(dirname "$0")"
DB="${VERITAS_TEST_DB:-veritas_test}"
DB_APP="${DB}_app"
for d in "$DB" "$DB_APP"; do psql -d postgres -qc "DROP DATABASE IF EXISTS $d WITH (FORCE)" -c "CREATE DATABASE $d"; done

psql -d "$DB" -q -v ON_ERROR_STOP=1 -f schema.sql
psql -d "$DB" -q -v ON_ERROR_STOP=1 -f seed.sql
psql -d "$DB" -q -v ON_ERROR_STOP=1 -f tests.sql

psql -d "$DB_APP" -q -v ON_ERROR_STOP=1 -f schema.sql
psql -d "$DB_APP" -q -v ON_ERROR_STOP=1 -f seed.sql
psql -d "$DB_APP" -q -v ON_ERROR_STOP=1 -f app_bootstrap.sql 2>&1 | grep -v NOTICE || true
psql -d "$DB_APP" -q -v ON_ERROR_STOP=1 -f app_bootstrap.sql 2>&1 | grep -v NOTICE || true   # second run: idempotent
psql -d "$DB_APP" -q -v ON_ERROR_STOP=1 -f tests_app.sql
