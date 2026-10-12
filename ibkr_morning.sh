#!/bin/bash
# Weekday-morning run of the IBKR bridge. macOS starts it by itself once
# "python ibkr_schedule.py" has set it up. It updates this folder from
# GitHub, copies the agent into the paper account (ibkr_bridge.py --send)
# and shows a notification with the result. Details: ibkr_logs/morning.log.

cd "$(dirname "$0")" || exit 1
mkdir -p ibkr_logs
exec >> ibkr_logs/morning.log 2>&1
echo "== $(date '+%Y-%m-%d %H:%M')"

notify() {
    osascript -e 'on run argv' \
        -e 'display notification (item 1 of argv) with title "Vanguard3"' \
        -e 'end run' "$1" > /dev/null
}

git pull --ff-only --quiet ||
    echo "Could not update from GitHub; using this copy."
.venv/bin/pip install --quiet --disable-pip-version-check \
    -r requirements-ibkr.txt

# Just after the Mac wakes up, the network or TWS may need a moment.
for attempt in 1 2 3; do
    output=$(.venv/bin/python ibkr_bridge.py --send 2>&1)
    status=$?
    echo "$output"
    [ "$status" -eq 0 ] && break
    [ "$attempt" -lt 3 ] && sleep 120
done

last=$(echo "$output" | grep -v '^Saved to' | tail -n 1)
if [ "$status" -eq 0 ]; then
    notify "$last"
else
    notify "Morning run failed: $last"
fi
exit "$status"
