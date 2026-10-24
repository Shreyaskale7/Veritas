#!/bin/bash
# Runs once, on the first start of an empty database volume (mounted into /docker-entrypoint-initdb.d).
# Production: schema + application layer only (no users: create the first admin with ops/create_admin.sql).
# VERITAS_DEMO=1: also loads the seed users (password veritas2026) and the demo marks.
set -euo pipefail
P="psql -v ON_ERROR_STOP=1 -U postgres -d $POSTGRES_DB"
$P -f /sql/schema.sql
if [ "${VERITAS_DEMO:-0}" = "1" ]; then $P -f /sql/seed.sql; fi
$P -f /sql/app_bootstrap.sql
if [ "${VERITAS_DEMO:-0}" = "1" ]; then $P -f /sql/demo_data.sql; fi
# the application role gets the password from the environment, never the one hard-coded in app_bootstrap.sql
$P -v pw="$VERITAS_APP_PASSWORD" <<< "ALTER ROLE veritas_login PASSWORD :'pw';"
