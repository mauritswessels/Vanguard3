#!/bin/bash
# Weekday-morning run of the IBKR bridge. A Mac starts it by itself once
# "python ibkr_schedule.py" has set it up; a cloud server once
# server/setup.sh has. It updates this folder from GitHub, copies the agent
# into the paper account (ibkr_bridge.py --send) and sends a notification
# with the result. Details: ibkr_logs/morning.log.
#
# Optional settings in ibkr_morning.env next to this script (setup.sh
# writes it on a server):
#   BRIDGE_ARGS="--port 4002"   more options for ibkr_bridge.py
#   NTFY_TOPIC=...              also send the result to the ntfy phone app
#   TELEGRAM_TOKEN=... and TELEGRAM_CHAT_ID=...
#                               or to Telegram (server/telegram.sh sets these)

cd "$(dirname "$0")" || exit 1
mkdir -p ibkr_logs
exec >> ibkr_logs/morning.log 2>&1
echo "== $(date '+%Y-%m-%d %H:%M')"

BRIDGE_ARGS=""
NTFY_TOPIC=""
TELEGRAM_TOKEN=""
TELEGRAM_CHAT_ID=""
if [ -f ibkr_morning.env ]; then
    . ./ibkr_morning.env
fi

notify() {  # message [ntfy priority]
    if [ -n "$NTFY_TOPIC" ]; then
        curl -fsS -m 30 -H "Title: Vanguard3" -H "Priority: ${2:-default}" \
            -d "$1" "https://ntfy.sh/$NTFY_TOPIC" > /dev/null ||
            echo "Could not send the phone notification."
    fi
    if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -fsS -m 30 -d "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "text=Vanguard3: $1" \
            "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
            > /dev/null || echo "Could not send the Telegram message."
    fi
    if command -v osascript > /dev/null; then
        osascript -e 'on run argv' \
            -e 'display notification (item 1 of argv) with title "Vanguard3"' \
            -e 'end run' "$1" > /dev/null
    fi
}

git pull --ff-only --quiet ||
    echo "Could not update from GitHub; using this copy."
.venv/bin/pip install --quiet --disable-pip-version-check \
    -r requirements-ibkr.txt

# Just after the computer wakes up, the network or TWS may need a moment.
for attempt in 1 2 3; do
    # BRIDGE_ARGS stays unquoted: it may hold several options.
    output=$(.venv/bin/python ibkr_bridge.py --send $BRIDGE_ARGS 2>&1)
    status=$?
    echo "$output"
    [ "$status" -eq 0 ] && break
    [ "$attempt" -lt 3 ] && sleep 120
done

last=$(echo "$output" | grep -v '^Saved to' | tail -n 1)
if [ "$status" -eq 0 ]; then
    notify "$last"
else
    notify "Morning run failed: $last" high
fi

# On Telegram, the race chart follows (telegram_chart.py).
if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    .venv/bin/pip install --quiet --disable-pip-version-check matplotlib &&
    chart="ibkr_logs/race.png" &&
    caption=$(.venv/bin/python telegram_chart.py "$chart") &&
    curl -fsS -m 60 -F "chat_id=$TELEGRAM_CHAT_ID" -F "photo=@$chart" \
        -F "caption=$caption" \
        "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendPhoto" > /dev/null ||
        echo "Could not send the race chart to Telegram."
fi
exit "$status"
