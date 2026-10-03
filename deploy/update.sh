#!/usr/bin/env bash
# Get the latest Upajna from GitHub and restart with it. Your data and settings are kept.
#   ~/upajna/deploy/update.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DC="sudo docker compose --env-file $DIR/.env -f $DIR/deploy/docker-compose.yml"
"$DIR/deploy/backup.sh"                 # a fresh backup before every update
git -C "$DIR" pull --ff-only
$DC up -d --build
sudo docker image prune -f >/dev/null
echo "Updated. Running: $(git -C "$DIR" log -1 --format='%h %s')"
