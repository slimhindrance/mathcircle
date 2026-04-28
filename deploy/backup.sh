#!/bin/bash
# Nightly SQLite snapshot to S3.
# - uses sqlite3 .backup so the file is consistent even if uvicorn is mid-write
# - keeps 14 days of backups locally as a hot copy
# - syncs to s3://${MATHCIRCLE_S3_BUCKET}/mathcircle/YYYY-MM-DD.db.gz

set -euo pipefail

DATA_DIR="/opt/mathcircle/data"
BACKUP_DIR="/opt/mathcircle/backups"
LOG_FILE="/opt/mathcircle/logs/backup.log"
DB_FILE="${DATA_DIR}/mathcircle.db"

# S3 bucket is read from /etc/mathcircle/env (single-line shell file)
if [[ -f /etc/mathcircle/env ]]; then
  # shellcheck disable=SC1091
  source /etc/mathcircle/env
fi

if [[ -z "${MATHCIRCLE_S3_BUCKET:-}" ]]; then
  echo "[$(date -Iseconds)] MATHCIRCLE_S3_BUCKET unset; aborting" >> "$LOG_FILE"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

DATE_STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
SNAPSHOT="${BACKUP_DIR}/mathcircle-${DATE_STAMP}.db"
COMPRESSED="${SNAPSHOT}.gz"

echo "[$(date -Iseconds)] starting backup → ${COMPRESSED}" >> "$LOG_FILE"

# Use sqlite3 .backup for a consistent online snapshot.
sqlite3 "$DB_FILE" ".backup '${SNAPSHOT}'"
gzip -f "$SNAPSHOT"

# Push to S3 with server-side encryption.
aws s3 cp "$COMPRESSED" "s3://${MATHCIRCLE_S3_BUCKET}/mathcircle/$(basename "$COMPRESSED")" \
  --storage-class STANDARD_IA \
  --sse AES256 \
  >> "$LOG_FILE" 2>&1

# Prune local backups older than 14 days.
find "$BACKUP_DIR" -name 'mathcircle-*.db.gz' -mtime +14 -delete

echo "[$(date -Iseconds)] backup ok" >> "$LOG_FILE"
