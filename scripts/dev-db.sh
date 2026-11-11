#!/usr/bin/env bash
# Local (non-Docker) Postgres 16 cluster for development on port 5433.
# Usage: scripts/dev-db.sh start|stop|status   (needs PostgreSQL 16 binaries; set PG_BIN if not on PATH)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/.devdata/pg"
PORT="${DEV_DB_PORT:-5433}"
PG_BIN="${PG_BIN:-}"
if [ -z "$PG_BIN" ]; then
  if command -v pg_ctl >/dev/null 2>&1; then PG_BIN="$(dirname "$(command -v pg_ctl)")";
  elif [ -d "/c/Program Files/PostgreSQL/16/bin" ]; then PG_BIN="/c/Program Files/PostgreSQL/16/bin";
  else echo "PostgreSQL 16 binaries not found; set PG_BIN" >&2; exit 1; fi
fi
case "${1:-start}" in
  start)
    if [ ! -f "$DATA/PG_VERSION" ]; then
      mkdir -p "$DATA"
      "$PG_BIN/initdb" -D "$DATA" -U smartstock --auth=trust -E UTF8 --locale=C >/dev/null
    fi
    "$PG_BIN/pg_ctl" -D "$DATA" -o "-p $PORT -c listen_addresses=localhost" -l "$ROOT/.devdata/pg.log" -w start </dev/null >/dev/null 2>&1
    for db in smartstock smartstock_test; do
      "$PG_BIN/psql" -h localhost -p "$PORT" -U smartstock -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || "$PG_BIN/createdb" -h localhost -p "$PORT" -U smartstock "$db"
    done ;;
  stop) "$PG_BIN/pg_ctl" -D "$DATA" -m fast stop ;;
  status) "$PG_BIN/pg_ctl" -D "$DATA" status ;;
esac
