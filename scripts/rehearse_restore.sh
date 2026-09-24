#!/usr/bin/env bash
# Migration/restore rehearsal (Phase 08).
#
# 1. dumps the current database,
# 2. restores it into a scratch database,
# 3. compares table row counts between the two,
# 4. runs alembic against the scratch copy and requires it to be at head,
# 5. drops the scratch database.
#
# V1 is forward-only: this proves the restore path and that the additive
# migrations apply to a restored copy; there is no destructive step to rehearse.
set -euo pipefail

SOURCE_URI="${1:?usage: rehearse_restore.sh <postgres-uri> [scratch-name]}"
SCRATCH="${2:-copilot_restore_rehearsal}"
if [[ ! "$SCRATCH" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "invalid scratch database name: $SCRATCH" >&2
  exit 1
fi
DUMP_FILE="$(mktemp -t copilot-dump-XXXXXX.sql)"
SOURCE_COUNTS="$(mktemp -t copilot-counts-source-XXXXXX.txt)"
SCRATCH_COUNTS="$(mktemp -t copilot-counts-scratch-XXXXXX.txt)"
SCRATCH_URI="${SOURCE_URI%/*}/$SCRATCH"

pick_tool() {
  local name="$1"
  if [[ -x "/opt/homebrew/opt/postgresql@16/bin/$name" ]]; then
    echo "/opt/homebrew/opt/postgresql@16/bin/$name"
    return
  fi
  command -v "$name" || true
}

PSQL="$(pick_tool psql)"
PG_DUMP="$(pick_tool pg_dump)"
: "${PSQL:?psql not found}" "${PG_DUMP:?pg_dump not found}"

ADMIN_URI="${SOURCE_URI%/*}/postgres"

echo "== dumping $SOURCE_URI"
"$PG_DUMP" --no-owner --no-privileges --clean --if-exists -d "$SOURCE_URI" -f "$DUMP_FILE"

echo "== recreating scratch database $SCRATCH"
"$PSQL" -d "$ADMIN_URI" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $SCRATCH WITH (FORCE);"
"$PSQL" -d "$ADMIN_URI" -v ON_ERROR_STOP=1 -c "CREATE DATABASE $SCRATCH;"

echo "== restoring into $SCRATCH"
"$PSQL" -d "$SCRATCH_URI" -v ON_ERROR_STOP=1 -q -f "$DUMP_FILE" >/dev/null

echo "== comparing row counts"
count_rows() {
  local uri="$1"
  local tables
  tables=$("$PSQL" -d "$uri" -tAc "SELECT relname FROM pg_stat_user_tables ORDER BY relname;")
  while IFS= read -r table; do
    [[ -z "$table" ]] && continue
    local count
    count=$("$PSQL" -d "$uri" -tAc "SELECT count(*) FROM \"$table\";")
    echo "$table=$count"
  done <<< "$tables"
}
count_rows "$SOURCE_URI" > "$SOURCE_COUNTS"
count_rows "$SCRATCH_URI" > "$SCRATCH_COUNTS"
if ! diff -u "$SOURCE_COUNTS" "$SCRATCH_COUNTS"; then
  echo "row counts differ after restore" >&2
  exit 1
fi
cat "$SOURCE_COUNTS"

echo "== verifying additive migration is already at head on the restored copy"
if command -v uv >/dev/null; then
  PY_URL="${SCRATCH_URI/postgresql:/postgresql+asyncpg:}"
  (
    cd "$(dirname "$0")/../services/api"
    current="$(DATABASE_URL="$PY_URL" uv run alembic current)"
    echo "$current"
    if ! grep -q '(head)' <<<"$current"; then
      echo "restored copy is not at alembic head: $current" >&2
      exit 1
    fi
    DATABASE_URL="$PY_URL" uv run alembic upgrade head
  )
fi

echo "== dropping scratch database"
"$PSQL" -d "$ADMIN_URI" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $SCRATCH WITH (FORCE);"
rm -f "$DUMP_FILE" "$SOURCE_COUNTS" "$SCRATCH_COUNTS"
echo "restore rehearsal passed"
