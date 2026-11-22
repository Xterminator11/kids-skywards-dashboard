#!/bin/bash
# Announces <name>.local on the home network, pointing at this Mac's current IP, so every
# phone and laptop can open http://<name>.local. Uses macOS's built-in dns-sd (Bonjour);
# the computer's own name is not changed. Re-announces if the IP changes.
# Started at login by the LaunchAgent that macmini-setup.sh installs.
NAME="${1:-kids-dashboard}"
PORT="${2:-80}"

current_ip() {
  local iface
  iface=$(/sbin/route -n get default 2>/dev/null | awk '/interface:/{print $2}')
  [ -n "$iface" ] && /usr/sbin/ipconfig getifaddr "$iface"
}

pid=""
ip=""
trap '[ -n "$pid" ] && kill "$pid" 2>/dev/null' EXIT INT TERM

while true; do
  new_ip=$(current_ip || true)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    pid=""; ip=""          # dns-sd stopped; start it again
  fi
  if [ "$new_ip" != "$ip" ]; then
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    pid=""; ip="$new_ip"
    if [ -n "$ip" ]; then
      echo "$(date '+%F %T') announcing $NAME.local -> $ip (port $PORT)"
      /usr/bin/dns-sd -P "Kids Dashboard" _http._tcp local "$PORT" "$NAME.local" "$ip" path=/ &
      pid=$!
    else
      echo "$(date '+%F %T') no network yet; waiting"
    fi
  fi
  sleep 30
done
