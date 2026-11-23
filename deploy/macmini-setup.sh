#!/bin/bash
# Sets up the kids dashboard on a Mac (test on a laptop first, then the Mac mini).
#
#   bash deploy/macmini-setup.sh            set up / update and start everything
#   bash deploy/macmini-setup.sh --remove   stop it and remove the kids-dashboard.local name
#                                           (run this on the laptop after testing)
#
# Needs the shared home server next to this folder (../home-server), which owns port 80
# and gives every app on this Mac its own name. See docs/MAC_MINI_SETUP.md.
#
# Settings you can pass:  DASHBOARD_NAME=kids-dashboard  HTTP_PORT=8787  HOME_SERVER_DIR=../home-server
#
# What it does:
#   1. checks Docker Desktop is installed and running
#   2. creates .env (asks for the Skyward login) and sets the daily scrape to 3:00 PM
#   3. on a Mac mini (no battery): keeps it awake and restarting after a power cut (asks for your password)
#   4. builds and starts the scraper + dashboard containers
#   5. starts/updates the home server and registers https://<DASHBOARD_NAME>.local with it
#   6. checks the page answers and prints the addresses to use on phones
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
NAME="${DASHBOARD_NAME:-kids-dashboard}"
# The home server lives next to this repo unless HOME_SERVER_DIR says otherwise.
HOME_SERVER_DIR="${HOME_SERVER_DIR:-$REPO/../home-server}"
# Older versions of this script announced the name themselves; the home server does it now.
OLD_LABEL="home.kids-dashboard.mdns"
OLD_AGENT="$HOME/Library/LaunchAgents/$OLD_LABEL.plist"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

# Set KEY=value in .env (replaces an existing line, keeps everything else).
set_env() {
  local key="$1" value="$2" quoted
  if [[ "$value" == *"'"* ]]; then quoted="\"$value\""; else quoted="'$value'"; fi
  touch .env
  grep -v "^${key}=" .env > .env.tmp || true
  printf '%s=%s\n' "$key" "$quoted" >> .env.tmp
  mv .env.tmp .env
}
get_env() { grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//' || true; }

compose() { docker compose "$@"; }
remove_old_agent() {
  launchctl bootout "gui/$(id -u)/$OLD_LABEL" 2>/dev/null || true
  rm -f "$OLD_AGENT"
}

if [[ "${1:-}" == "--remove" ]]; then
  step "Stopping the containers"
  compose down || true
  step "Removing the $NAME.local name"
  remove_old_agent
  if [[ -f "$HOME_SERVER_DIR/sites/$NAME.caddy" ]]; then
    bash "$HOME_SERVER_DIR/bin/remove-app.sh" "$NAME" || true
  fi
  bash deploy/setup-alerts.sh --remove >/dev/null 2>&1 || true
  echo "Done (containers, .local name and daily alert removed). Your data/ and state/ folders were left in place."
  echo "The home server itself keeps running for other apps. Stop it with: bash $HOME_SERVER_DIR/bin/setup.sh --remove"
  exit 0
fi

step "1. Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed. Get it from https://www.docker.com/products/docker-desktop/"
  echo "Then open it once, turn on Settings > General > 'Start Docker Desktop when you sign in', and run this again."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { echo "Docker didn't start. Open Docker Desktop, wait for it, then run this again."; exit 1; }
fi
echo "Docker is running."

step "2. Settings (.env)"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi
if [[ -z "$(get_env SKYWARD_USERNAME)" || -z "$(get_env SKYWARD_PASSWORD)" ]]; then
  read -rp "Skyward username: " sky_user
  read -rsp "Skyward password (not shown): " sky_pass; echo
  set_env SKYWARD_USERNAME "$sky_user"
  set_env SKYWARD_PASSWORD "$sky_pass"
fi
[[ -n "$(get_env SKYWARD_URL)" ]] || set_env SKYWARD_URL "$(grep '^SKYWARD_URL=' .env.example | cut -d= -f2-)"
set_env SCHEDULE_CRON "${SCHEDULE_CRON:-0 15 * * *}"
set_env TZ "${TZ_NAME:-America/Chicago}"
HTTP_PORT="${HTTP_PORT:-$(get_env HTTP_PORT)}"; HTTP_PORT="${HTTP_PORT:-8787}"
if [[ "$HTTP_PORT" == "80" ]]; then
  # Port 80 now belongs to the home server, which forwards kids-dashboard.local here.
  echo "Moving the dashboard's direct port from 80 to 8787 (the home server takes port 80)."
  HTTP_PORT=8787
fi
set_env HTTP_PORT "$HTTP_PORT"
# The home server serves https now; move the alert link over if it's still the old http one.
[[ "$(get_env ALERT_LINK)" == "http://kids-dashboard.local" ]] && set_env ALERT_LINK "https://kids-dashboard.local"
chmod 600 .env
mkdir -p data state
echo "Daily scrape: $(get_env SCHEDULE_CRON) ($(get_env TZ)). Dashboard port on this Mac: $HTTP_PORT."

step "3. Power settings"
if pmset -g batt 2>/dev/null | grep -q InternalBattery; then
  echo "This Mac has a battery (a laptop), so power settings are left alone. Fine for testing."
else
  echo "Keeping this Mac awake, waking for network, and restarting after a power cut (needs your password)."
  sudo pmset -a sleep 0 disksleep 0 autorestart 1 womp 1 || warn "Couldn't change power settings; set them in System Settings > Energy."
fi

step "4. Build and start the containers"
if [[ ! -f "$HOME_SERVER_DIR/bin/add-app.sh" ]]; then
  echo "The home server isn't at $HOME_SERVER_DIR."
  echo "Put the home-server folder next to this one (see docs/MAC_MINI_SETUP.md, step 2),"
  echo "or run with HOME_SERVER_DIR=/path/to/home-server bash deploy/macmini-setup.sh"
  exit 1
fi
if lsof -nP -iTCP:"$HTTP_PORT" -sTCP:LISTEN 2>/dev/null | grep -v -i docker | grep -q LISTEN; then
  warn "Something else is already using port $HTTP_PORT:"
  lsof -nP -iTCP:"$HTTP_PORT" -sTCP:LISTEN | head -5
  echo "Run again with another port, e.g.:  HTTP_PORT=8790 bash deploy/macmini-setup.sh"
  exit 1
fi
# The network the home server's Caddy uses to reach the dashboard.
docker network inspect home-proxy >/dev/null 2>&1 || docker network create home-proxy >/dev/null
if ! compose up -d --build --remove-orphans; then
  warn "docker compose failed. If the error mentions port $HTTP_PORT, try:  HTTP_PORT=8790 bash deploy/macmini-setup.sh"
  exit 1
fi
compose ps

if [[ ! -f data/assignments_latest.csv ]]; then
  read -rp "No grades on this Mac yet. Run one Skyward check now (about 2 minutes)? [y/N] " now
  if [[ "$now" =~ ^[Yy] ]]; then
    compose run --rm -e MAX_RETRIES=0 scraper python -m gradebook run || warn "The check failed; see the messages above. The 3 PM run will try again."
  fi
fi

step "5. Give it the name https://$NAME.local (home server)"
remove_old_agent
# Starts or updates the home server (Caddy on 80/443, its private CA, the name announcer).
bash "$HOME_SERVER_DIR/bin/setup.sh"
# --default: the Mac's plain IP address (https://<ip>) also opens the dashboard.
bash "$HOME_SERVER_DIR/bin/add-app.sh" "$NAME" kids-dashboard:8787 --default
sleep 3

step "6. Check"
ok=""
for _ in $(seq 1 20); do
  if curl -fsS "http://localhost:$HTTP_PORT/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[[ -n "$ok" ]] && echo "Dashboard answers on port $HTTP_PORT." || warn "Dashboard isn't answering yet. Check: docker compose logs dashboard"
CA="$HOME_SERVER_DIR/certs/home-ca.crt"
if curl -fsS --cacert "$CA" --resolve "$NAME.local:443:127.0.0.1" "https://$NAME.local/health" >/dev/null 2>&1; then
  echo "The home server forwards https://$NAME.local to it, with a valid home certificate."
else
  warn "The home server isn't forwarding $NAME.local yet. Check: docker logs home-proxy"
fi
if dscacheutil -q host -a name "$NAME.local" | grep -q ip_address; then
  echo "$NAME.local resolves on this Mac."
else
  warn "$NAME.local doesn't resolve yet. Check: tail $HOME/Library/Logs/home-server-mdns.log"
fi
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
IP=$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)

cat <<DONE

All set. On any phone or laptop on your home Wi-Fi, open:

    https://$NAME.local
    https://$IP             (backup, if a device can't find .local names)
    http://$IP:$HTTP_PORT         (direct to the dashboard, no https, if the home server is down)

First, each device trusts the home certificate once (otherwise it shows a warning):
    open http://$IP/home-ca.crt on the device, then follow docs/MAC_MINI_SETUP.md step 4.
    On this Mac:  bash $HOME_SERVER_DIR/bin/trust-this-mac.sh

On iPhone: open it in Safari, tap Share > Add to Home Screen.
On Pixel:  open it in Chrome, tap the menu > Add to Home screen.

The scraper runs every day at 3:00 PM. Handy commands:
    docker compose ps                                        what's running
    docker compose logs -f scraper                           watch a scrape
    docker compose run --rm scraper python -m gradebook run  scrape right now
    git pull && bash deploy/macmini-setup.sh                 update

Next: set up the daily family text alert:   bash deploy/setup-alerts.sh
Full guide: docs/MAC_MINI_SETUP.md

If a phone can't connect: System Settings > Network > Firewall must allow Docker.
Keep this Mac's IP fixed (a DHCP reservation in the router, or a manual IP).
DONE
