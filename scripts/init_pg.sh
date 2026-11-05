#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="$ROOT/tools/pgsql/bin"
PGDATA="$ROOT/tools/pgdata"
PORT="${PGPORT:-5432}"

if [ ! -x "$PGBIN/initdb.exe" ]; then
  echo "PostgreSQL binaries not found: $PGBIN"
  echo "Run the setup first or check tools/pgsql."
  exit 1
fi

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "Initializing PostgreSQL data directory..."
  "$PGBIN/initdb.exe" -D "$PGDATA" -U bi --auth=trust --encoding=UTF8 --locale=C
fi

if ! "$PGBIN/pg_ctl.exe" -D "$PGDATA" status >/dev/null 2>&1; then
  echo "Starting PostgreSQL on port $PORT..."
  "$PGBIN/pg_ctl.exe" -D "$PGDATA" -l "$ROOT/tools/postgres.log" -o "-p $PORT" start
  sleep 2
fi

if ! "$PGBIN/psql.exe" -h 127.0.0.1 -p "$PORT" -U bi -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='bi'" | grep -q 1; then
  "$PGBIN/createdb.exe" -h 127.0.0.1 -p "$PORT" -U bi bi
  echo "Created database bi"
fi

echo "PostgreSQL ready: postgresql://bi@127.0.0.1:$PORT/bi"
