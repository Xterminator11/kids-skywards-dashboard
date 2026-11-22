#!/bin/bash
# Sends today's homework alert from this Mac through the Messages app.
#   iMessage -> the Apple devices in IMESSAGE_TO (and/or an existing group chat)
#   SMS      -> the numbers in SMS_TO (e.g. a Pixel), through your iPhone's
#               Text Message Forwarding
# The text comes from the dashboard container (GET /api/alert-text). If there's nothing
# due soon or past due, nothing is sent.
#
#   bash deploy/send-alerts.sh               send today's alert (what the 3:30 PM job runs)
#   bash deploy/send-alerts.sh --dry-run     print the alert, send nothing
#   bash deploy/send-alerts.sh --test        send a short test message to everyone
#   bash deploy/send-alerts.sh --list-chats  list Messages group chats and their ids
#
# Settings live in deploy/alerts.env (created by deploy/setup-alerts.sh, not in git).
set -uo pipefail
cd "$(dirname "$0")/.."
CONF="deploy/alerts.env"
# shellcheck disable=SC1090
[ -f "$CONF" ] && source "$CONF"
IMESSAGE_TO="${IMESSAGE_TO:-}"
IMESSAGE_CHAT_ID="${IMESSAGE_CHAT_ID:-}"
SMS_TO="${SMS_TO:-}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost}"
MODE="${1:-send}"

log() { echo "$(date '+%F %T') $*"; }

send_one() {  # kind (imessage|sms|chat), target, message
  /usr/bin/osascript - "$1" "$2" "$3" <<'APPLESCRIPT'
on run argv
  set kind to item 1 of argv
  set target to item 2 of argv
  set msg to item 3 of argv
  tell application "Messages"
    if kind is "chat" then
      send msg to chat id target
    else
      if kind is "sms" then
        set svc to 1st account whose service type = SMS
      else
        set svc to 1st account whose service type = iMessage
      end if
      try
        send msg to participant target of svc
      on error
        send msg to buddy target of svc
      end try
    end if
  end tell
end run
APPLESCRIPT
}

send_all() {
  local msg="$1" failed=0 t
  IFS=',' read -ra people <<< "$IMESSAGE_TO"
  for t in "${people[@]}"; do
    t="$(echo "$t" | xargs)"; [ -z "$t" ] && continue
    if send_one imessage "$t" "$msg"; then log "iMessage sent to $t"; else log "FAILED iMessage to $t"; failed=1; fi
  done
  if [ -n "$IMESSAGE_CHAT_ID" ]; then
    if send_one chat "$IMESSAGE_CHAT_ID" "$msg"; then log "iMessage sent to group chat"; else log "FAILED group chat $IMESSAGE_CHAT_ID"; failed=1; fi
  fi
  IFS=',' read -ra phones <<< "$SMS_TO"
  for t in "${phones[@]}"; do
    t="$(echo "$t" | xargs)"; [ -z "$t" ] && continue
    if send_one sms "$t" "$msg"; then log "SMS sent to $t"; else log "FAILED SMS to $t (is Text Message Forwarding on for this Mac?)"; failed=1; fi
  done
  return $failed
}

case "$MODE" in
  --list-chats)
    /usr/bin/osascript <<'APPLESCRIPT'
tell application "Messages"
  set out to ""
  repeat with c in chats
    set cname to ""
    try
      set cname to name of c
    end try
    if cname is missing value then set cname to ""
    set out to out & (id of c) & "   " & cname & linefeed
  end repeat
  return out
end tell
APPLESCRIPT
    ;;
  --test)
    send_all "✅ Kids homework alerts are set up. You'll get a message on days when something is due soon or past due."
    ;;
  --dry-run|send)
    text="$(curl -fsS --max-time 30 "$DASHBOARD_URL/api/alert-text")" || { log "Couldn't reach the dashboard at $DASHBOARD_URL (is Docker running?)"; exit 1; }
    if [ -z "$text" ]; then log "Nothing due soon or past due; no message today."; exit 0; fi
    if [ "$MODE" = "--dry-run" ]; then printf '%s\n' "$text"; exit 0; fi
    send_all "$text"
    ;;
  *)
    echo "Usage: $0 [--dry-run | --test | --list-chats]"; exit 2 ;;
esac
