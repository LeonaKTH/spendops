#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT/scripts/init_pg.sh"

REDIS_DIR="$ROOT/tools/redis"
REDIS_BIN="$REDIS_DIR/redis-server.exe"

if [ -x "$REDIS_BIN" ]; then
  if ! "$REDIS_DIR/redis-cli.exe" -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    "$REDIS_BIN" --port 6379 --bind 127.0.0.1 --dir "$REDIS_DIR" \
      > "$ROOT/tools/redis.log" 2>&1 &
    sleep 1
  fi
  echo "Redis ready: redis://127.0.0.1:6379/0"
else
  echo "Redis not found: $REDIS_BIN (skipped)"
fi
