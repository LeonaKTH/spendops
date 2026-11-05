#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="$ROOT/tools/pgsql/bin"
PGDATA="$ROOT/tools/pgdata"

if [ -f "$PGDATA/PG_VERSION" ]; then
  "$PGBIN/pg_ctl.exe" -D "$PGDATA" stop -m fast >/dev/null 2>&1 || true
  echo "PostgreSQL stopped"
fi

if [ -x "$ROOT/tools/redis/redis-cli.exe" ]; then
  "$ROOT/tools/redis/redis-cli.exe" -h 127.0.0.1 -p 6379 shutdown nosave \
    >/dev/null 2>&1 || true
  echo "Redis stopped"
fi
