#!/usr/bin/env bash
# Daily backup of SQLite + results. Cron:  15 4 * * *  /opt/mcbench/server/scripts/backup.sh >> /var/log/mcbench-backup.log 2>&1
# Works on the host against the docker volume (default) or any DATA_DIR.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
DATA_DIR="${DATA_DIR_HOST:-$(docker volume inspect -f '{{.Mountpoint}}' server_mcbench-data 2>/dev/null || echo ./var)}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
python3 - "$DATA_DIR/mcbench.db" "$WORK/mcbench.db" <<'PY'
import sqlite3,sys
src=sqlite3.connect(sys.argv[1]);dst=sqlite3.connect(sys.argv[2]);src.backup(dst)
dst.execute("UPDATE submissions SET key_enc=NULL");dst.commit()   # never back up keys, even encrypted
PY
tar -czf "$WORK/mcbench-$STAMP.tar.gz" -C "$WORK" mcbench.db -C "$DATA_DIR" results
case "${BACKUP_TARGET:-none}" in
  github)
    git clone --depth 1 "$BACKUP_GIT_REPO" "$WORK/repo"
    mkdir -p "$WORK/repo/backups" && cp "$WORK/mcbench-$STAMP.tar.gz" "$WORK/repo/backups/"
    ls -1t "$WORK/repo/backups"/*.tar.gz | tail -n +15 | xargs -r git -C "$WORK/repo" rm -q   # keep 14
    git -C "$WORK/repo" add backups && git -C "$WORK/repo" commit -qm "backup $STAMP" && git -C "$WORK/repo" push -q ;;
  r2)
    aws s3 cp "$WORK/mcbench-$STAMP.tar.gz" "s3://$R2_BUCKET/mcbench-$STAMP.tar.gz" --endpoint-url "$R2_ENDPOINT" ;;
  none) mkdir -p ./backups && cp "$WORK/mcbench-$STAMP.tar.gz" ./backups/ ;;
esac
echo "backup ok $STAMP -> ${BACKUP_TARGET:-none}"
