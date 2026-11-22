#!/bin/bash
# Sets up the kids dashboard on a Mac (test on a laptop first, then the Mac mini).
#
#   ./deploy/macmini-setup.sh            set up / update and start everything
#   ./deploy/macmini-setup.sh --remove   stop it and remove the kids-dashboard.local name
#                                        (run this on the laptop after testing)
#
# Settings you can pass:  DASHBOARD_NAME=kids-dashboard  HTTP_PORT=80
#
# What it does:
#   1. checks Docker Desktop is installed and running
#   2. creates .env (asks for the Skyward login) and sets the daily scrape to 3:00 PM
#   3. on a Mac mini (no battery): keeps it awake and restarting after a power cut (asks for your password)
#   4. builds and starts the scraper + dashboard containers
#   5. announces http://<DASHBOARD_NAME>.local on your network (LaunchAgent, starts at login)
#   6. checks the page answers and prints the addresses to use on phones
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
NAME="${DASHBOARD_NAME:-kids-dashboard}"
LABEL="home.kids-dashboard.mdns"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

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

if [[ "${1:-}" == "--remove" ]]; then
  step "Stopping the containers"
  compose down || true
  step "Removing the $NAME.local announcement"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$AGENT"
  bash deploy/setup-alerts.sh --remove >/dev/null 2>&1 || true
  echo "Done (containers, .local name and daily alert removed). Your data/ and state/ folders were left in place."
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
HTTP_PORT="${HTTP_PORT:-$(get_env HTTP_PORT)}"; HTTP_PORT="${HTTP_PORT:-80}"
set_env HTTP_PORT "$HTTP_PORT"
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
if lsof -nP -iTCP:"$HTTP_PORT" -sTCP:LISTEN 2>/dev/null | grep -v -i docker | grep -q LISTEN; then
  warn "Something else is already using port $HTTP_PORT:"
  lsof -nP -iTCP:"$HTTP_PORT" -sTCP:LISTEN | head -5
  echo "Run again with another port, e.g.:  HTTP_PORT=8787 ./deploy/macmini-setup.sh"
  exit 1
fi
if ! compose up -d --build --remove-orphans; then
  warn "docker compose failed. If the error mentions port $HTTP_PORT, try:  HTTP_PORT=8787 ./deploy/macmini-setup.sh"
  exit 1
fi
compose ps

if [[ ! -f data/assignments_latest.csv ]]; then
  read -rp "No grades on this Mac yet. Run one Skyward check now (about 2 minutes)? [y/N] " now
  if [[ "$now" =~ ^[Yy] ]]; then
    compose run --rm -e MAX_RETRIES=0 scraper python -m gradebook run || warn "The check failed; see the messages above. The 3 PM run will try again."
  fi
fi

step "5. Announce http://$NAME.local on your network"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/deploy/mdns-advertise.sh</string>
    <string>$NAME</string>
    <string>$HTTP_PORT</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/kids-dashboard-mdns.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/kids-dashboard-mdns.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"
sleep 3

step "6. Check"
suffix=""; [[ "$HTTP_PORT" == "80" ]] || suffix=":$HTTP_PORT"
ok=""
for _ in $(seq 1 20); do
  if curl -fsS "http://localhost:$HTTP_PORT/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[[ -n "$ok" ]] && echo "Dashboard answers on this Mac." || warn "Dashboard isn't answering yet. Check: docker compose logs dashboard"
if dscacheutil -q host -a name "$NAME.local" | grep -q ip_address; then
  echo "$NAME.local resolves on this Mac."
else
  warn "$NAME.local doesn't resolve yet. Check: tail $HOME/Library/Logs/kids-dashboard-mdns.log"
fi
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
IP=$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)

cat <<DONE

All set. On any phone or laptop on your home Wi-Fi, open:

    http://$NAME.local$suffix
    http://$IP$suffix          (backup, if a device can't find .local names)

On iPhone: open it in Safari, tap Share > Add to Home Screen.
On Pixel:  open it in Chrome, tap the menu > Add to Home screen.

The scraper runs every day at 3:00 PM. Handy commands:
    docker compose ps                                        what's running
    docker compose logs -f scraper                           watch a scrape
    docker compose run --rm scraper python -m gradebook run  scrape right now
    git pull && ./deploy/macmini-setup.sh                    update

Next: set up the daily family text alert:   bash deploy/setup-alerts.sh
Full guide: docs/MAC_MINI_SETUP.md

If a phone can't connect: System Settings > Network > Firewall must allow Docker.
Keep this Mac's IP fixed (a DHCP reservation in the router, or a manual IP).
DONE
