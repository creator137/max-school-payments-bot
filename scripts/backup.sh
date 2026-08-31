#!/bin/sh
set -eu

backup_dir="${BACKUP_DIR:-./backups}"
mkdir -p "$backup_dir"
timestamp=$(date +%Y%m%d_%H%M%S)

if docker compose ps database >/dev/null 2>&1; then
  docker compose exec -T database pg_dump -U school -Fc school_payments > "$backup_dir/database_$timestamp.dump"
  tar -czf "$backup_dir/receipts_$timestamp.tar.gz" storage/receipts 2>/dev/null || true
  echo "PostgreSQL backup created in $backup_dir"
else
  uv run python -c 'import sqlite3; source=sqlite3.connect("school_payments.db"); target=sqlite3.connect("'"$backup_dir"'/database_'"$timestamp"'.db"); source.backup(target); target.close(); source.close()'
  tar -czf "$backup_dir/receipts_$timestamp.tar.gz" storage/receipts 2>/dev/null || true
  echo "SQLite backup created in $backup_dir"
fi

