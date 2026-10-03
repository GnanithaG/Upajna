#!/usr/bin/env bash
# Save a copy of the database to ~/backups (keeps the last 14). Runs nightly from cron.
# Restore one with:
#   gunzip -c ~/backups/upajna-DATE.sql.gz | sudo docker compose --env-file ~/upajna/.env \
#     -f ~/upajna/deploy/docker-compose.yml exec -T db psql -U upajna -d upajna
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HOME/backups"; mkdir -p "$OUT"
sudo docker compose --env-file "$DIR/.env" -f "$DIR/deploy/docker-compose.yml" exec -T db \
  pg_dump -U upajna -d upajna --clean --if-exists | gzip > "$OUT/upajna-$(date +%F-%H%M).sql.gz"
ls -1t "$OUT"/upajna-*.sql.gz | tail -n +15 | xargs -r rm --
echo "Backup saved: $(ls -1t "$OUT"/upajna-*.sql.gz | head -1)"
