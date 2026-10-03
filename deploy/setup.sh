#!/usr/bin/env bash
# One-time setup of Upajna on a fresh Ubuntu server (AWS Lightsail).
#
# Run it from the server's browser terminal:
#   bash <(curl -fsSL https://raw.githubusercontent.com/GnanithaG/Upajna/main/deploy/setup.sh)
#
# It asks for your password and API keys, keeps them only on this server (in ~/upajna/.env),
# and starts the app with HTTPS. Safe to run again: it keeps an existing .env.
set -euo pipefail

REPO="${REPO:-https://github.com/GnanithaG/Upajna.git}"
DIR="${DIR:-$HOME/upajna}"
say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ask()  { local v; read -r -p "$1" v; printf '%s' "$v"; }
asks() { local v; read -r -s -p "$1" v; echo >&2; printf '%s' "$v"; }   # hidden input

# 1. Docker -------------------------------------------------------------------------------
if ! command -v docker >/dev/null; then
  say "Installing Docker (2-3 minutes)"
  curl -fsSL https://get.docker.com | sudo sh
fi
DC="sudo docker compose --env-file $DIR/.env -f $DIR/deploy/docker-compose.yml"

# 2. Swap: extra memory on disk so building and Chromium don't run out on a 2 GB server --------
if ! sudo swapon --show | grep -q /swapfile; then
  say "Adding 2 GB of swap"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# 3. Code ---------------------------------------------------------------------------------
if [ -d "$DIR/.git" ]; then
  say "Updating the code"; git -C "$DIR" pull --ff-only
else
  say "Downloading Upajna"; git clone "$REPO" "$DIR"
fi

# 4. Secrets (.env) -------------------------------------------------------------------------
if [ ! -f "$DIR/.env" ]; then
  say "A few questions. Your answers stay on this server only."
  while :; do
    PW=$(asks "Choose a password for signing in to Upajna (12+ characters): ")
    [ ${#PW} -ge 12 ] || { echo "Please use at least 12 characters."; continue; }
    case "$PW" in *"'"*) echo "Please don't use the ' character."; continue;; esac
    PW2=$(asks "Type it again: ")
    [ "$PW" = "$PW2" ] && break || echo "They didn't match. Try again."
  done
  ANTH=""; while [ -z "$ANTH" ]; do ANTH=$(asks "Paste your Claude API key (starts with sk-ant-): "); done
  echo "Job search keys are optional. Press Enter to skip any of them."
  JS=$(asks "JSearch (RapidAPI) key: ")
  AZ_ID=$(ask "Adzuna App ID: ")
  AZ_KEY=""; [ -n "$AZ_ID" ] && AZ_KEY=$(asks "Adzuna App Key: ")
  MAIL=$(ask "Your email (used only to identify notifications): ")

  IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
  DOMAIN_DEFAULT="${IP//./-}.sslip.io"
  DOMAIN=$(ask "Web address [$DOMAIN_DEFAULT]: "); DOMAIN="${DOMAIN:-$DOMAIN_DEFAULT}"

  umask 077
  cat > "$DIR/.env" <<EOF
# Upajna settings for this server. Keep this file private; it is never uploaded to GitHub.
DOMAIN=$DOMAIN
APP_PASSWORD='$PW'
SESSION_SECRET=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 24)
ANTHROPIC_API_KEY='$ANTH'
JSEARCH_API_KEY='$JS'
JSEARCH_QUERIES_PER_RUN=3
ADZUNA_APP_ID='$AZ_ID'
ADZUNA_APP_KEY='$AZ_KEY'
APPLY_SUBMIT=false
VAPID_SUBJECT='mailto:${MAIL:-you@example.com}'
TZ_NAME=America/Los_Angeles
SEARCH_CRON='0 11,15,19 * * *'
EOF
  chmod 600 "$DIR/.env"
  unset PW PW2 ANTH JS AZ_KEY
else
  say "Keeping your existing settings in $DIR/.env"
fi

# 5. Build and start ------------------------------------------------------------------------
say "Building Upajna (first time takes ~5 minutes)"
$DC build
if ! grep -q '^VAPID_PUBLIC_KEY=.' "$DIR/.env"; then
  say "Creating notification keys"
  $DC run --rm --no-deps app python scripts/gen_vapid.py | grep '^VAPID_' >> "$DIR/.env"
fi
$DC up -d

# 6. Nightly database backup at 3:30am ---------------------------------------------------------
chmod +x "$DIR"/deploy/*.sh
# (A brand-new server has no schedule yet, so "crontab -l" and grep find nothing; that's fine.)
{ { crontab -l 2>/dev/null || true; } | { grep -v 'deploy/backup.sh' || true; }
  echo "30 3 * * * $DIR/deploy/backup.sh >> $HOME/backups.log 2>&1"; } | crontab -

# 7. Check -------------------------------------------------------------------------------------
DOMAIN=$(grep '^DOMAIN=' "$DIR/.env" | cut -d= -f2 | tr -d "'")
say "Waiting for HTTPS to come up at https://$DOMAIN"
for i in $(seq 1 60); do
  if curl -fsS "https://$DOMAIN/api/health" >/dev/null 2>&1; then
    say "Upajna is live: https://$DOMAIN"
    echo "Open it on your laptop and phone, and sign in with the password you chose."
    exit 0
  fi
  sleep 5
done
echo "Not answering yet. Check that ports 80 and 443 are open in the Lightsail Networking tab, then run:"
echo "  $DC logs --tail 50"
exit 1
