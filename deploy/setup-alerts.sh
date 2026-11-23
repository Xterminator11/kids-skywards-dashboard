#!/bin/bash
# Sets up the daily family alert on this Mac (run after deploy/macmini-setup.sh).
#
#   bash deploy/setup-alerts.sh            ask for recipients and time, install, send a test
#   bash deploy/setup-alerts.sh --remove   stop the daily alert
#
# Before running:
#   - Sign in to the Messages app on this Mac with your Apple ID (Messages > Settings > iMessage).
#   - For SMS to an Android phone: on your iPhone, Settings > Apps > Messages >
#     Text Message Forwarding, and turn on this Mac.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
CONF="deploy/alerts.env"
LABEL="home.kids-dashboard.alerts"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$AGENT"
  echo "Daily alert removed. (Your settings in $CONF were kept.)"
  exit 0
fi

# Defaults from an earlier run, if any.
# shellcheck disable=SC1090
[ -f "$CONF" ] && source "$CONF"
HTTP_PORT="$(grep '^HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "'\"" || true)"
HTTP_PORT="${HTTP_PORT:-8787}"

echo "Phone numbers use the +1 format, e.g. +15125550123. Separate several with commas."
read -rp "iMessage to (Apple devices) [${IMESSAGE_TO:-}]: " a; IMESSAGE_TO="${a:-${IMESSAGE_TO:-}}"
read -rp "Existing iMessage group chat id (optional, see --list-chats) [${IMESSAGE_CHAT_ID:-}]: " a; IMESSAGE_CHAT_ID="${a:-${IMESSAGE_CHAT_ID:-}}"
read -rp "SMS to (Android, sent through your iPhone) [${SMS_TO:-}]: " a; SMS_TO="${a:-${SMS_TO:-}}"
read -rp "Send time, 24-hour HH:MM [${ALERT_TIME:-15:30}]: " a; ALERT_TIME="${a:-${ALERT_TIME:-15:30}}"
if ! [[ "$ALERT_TIME" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then echo "Time must look like 15:30"; exit 1; fi
HOUR=$((10#${BASH_REMATCH[1]})); MINUTE=$((10#${BASH_REMATCH[2]}))

cat > "$CONF" <<CONFEOF
# Family alert settings (used by deploy/send-alerts.sh). Not committed to git.
IMESSAGE_TO="$IMESSAGE_TO"
IMESSAGE_CHAT_ID="$IMESSAGE_CHAT_ID"
SMS_TO="$SMS_TO"
ALERT_TIME="$ALERT_TIME"
DASHBOARD_URL="http://localhost:$HTTP_PORT"
CONFEOF
chmod 600 "$CONF"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/deploy/send-alerts.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/kids-dashboard-alerts.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/kids-dashboard-alerts.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"
echo "Daily alert scheduled for $ALERT_TIME."

echo
echo "Today's alert would say:"
bash deploy/send-alerts.sh --dry-run || true
echo
read -rp "Send a test message to everyone now? macOS will ask to let Terminal control Messages; click OK. [Y/n] " a
if [[ ! "$a" =~ ^[Nn] ]]; then bash deploy/send-alerts.sh --test; fi
echo
echo "Running the scheduled job once now, so macOS can ask permission for it too."
echo "If a box asks to let \"bash\" or \"osascript\" control Messages, click OK."
echo "(This sends today's real alert if there is one.)"
launchctl kickstart -k "gui/$(id -u)/$LABEL" || true
sleep 5
tail -5 "$HOME/Library/Logs/kids-dashboard-alerts.log" 2>/dev/null || true
cat <<DONE

Done. Log: ~/Library/Logs/kids-dashboard-alerts.log
  bash deploy/send-alerts.sh --dry-run    see today's alert
  bash deploy/send-alerts.sh              send it now
  bash deploy/setup-alerts.sh             change recipients or time
  bash deploy/setup-alerts.sh --remove    stop the daily alert
DONE
