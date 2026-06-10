#!/usr/bin/env bash
# scripts/backup_db.sh — snapshot BrnzyBot's SQLite databases.
#
# Runs on the VM via cron. Keeps the last 14 daily local snapshots and, if a
# GCS bucket is configured, pushes a copy there too. The bot DB (characters,
# guild config, subscriptions, rate limits) is the irreplaceable one — losing
# it means every guild re-registers from scratch.
#
# Install (on the VM):
#   chmod +x ~/brnzybot-git/scripts/backup_db.sh
#   crontab -e
#   # add:  0 4 * * *  /home/brnz/brnzybot-git/scripts/backup_db.sh >> /home/brnz/.openclaw/logs/backup.log 2>&1
#
# Optional offsite: export BRNZYBOT_BACKUP_BUCKET=gs://your-bucket/brnzybot

set -euo pipefail

# On the VM the host data dir is ~/openclaw-data (bind-mounted to
# /root/.openclaw/data inside the container). Override with BRNZYBOT_DATA_DIR.
DATA_DIR="${BRNZYBOT_DATA_DIR:-$HOME/openclaw-data}"
BACKUP_DIR="${BRNZYBOT_BACKUP_DIR:-$HOME/openclaw-backups}"
KEEP=14
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# Only the durable DBs — the item/strategy DBs are rebuildable, gear_cache is
# a cache. brnzybot.db is the one that must survive.
for db in brnzybot.db; do
    src="$DATA_DIR/$db"
    [ -f "$src" ] || { echo "skip: $src not found"; continue; }
    dest="$BACKUP_DIR/${db%.db}-$STAMP.db"
    # Online backup via Python's sqlite3 (the sqlite3 CLI isn't installed on the
    # VM, but python3 always is). conn.backup() is the same safe online API —
    # consistent snapshot while the bot is still writing.
    python3 - "$src" "$dest" <<'PY'
import sqlite3, sys
src, dest = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dest)
with d:
    s.backup(d)
d.close(); s.close()
PY
    gzip -f "$dest"
    echo "backed up $db -> ${dest}.gz"

    if [ -n "${BRNZYBOT_BACKUP_BUCKET:-}" ]; then
        gsutil -q cp "${dest}.gz" "$BRNZYBOT_BACKUP_BUCKET/" \
            && echo "pushed to $BRNZYBOT_BACKUP_BUCKET" \
            || echo "WARN: gsutil push failed (local copy retained)"
    fi
done

# Prune old local snapshots, keep the most recent $KEEP.
ls -1t "$BACKUP_DIR"/brnzybot-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup done ($STAMP); kept latest $KEEP local snapshots"
