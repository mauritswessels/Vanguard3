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
#   HEALTHCHECK_URL=https://hc-ping.com/...
#                               pinged after every run; healthchecks.io then
#                               warns you when a morning passes without one
#                               (the server is down, or the run is stuck)
#   PUBLISH_REPO=git@github.com:...  (and PUBLISH_BRANCH, PUBLISH_KEY)
#                               after the orders, put the paper account's
#                               summary on GitHub for the website
#                               (ibkr_summary.py, server/publish.sh;
#                               server/setup.sh --publish sets these)

cd "$(dirname "$0")" || exit 1
mkdir -p ibkr_logs
exec >> ibkr_logs/morning.log 2>&1
echo "== $(date '+%Y-%m-%d %H:%M')"

BRIDGE_ARGS=""
NTFY_TOPIC=""
TELEGRAM_TOKEN=""
TELEGRAM_CHAT_ID=""
HEALTHCHECK_URL=""
PUBLISH_REPO=""
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

limit() {  # seconds command...: stop a step that hangs (where possible)
    if command -v timeout > /dev/null; then
        timeout "$@"
    else
        shift
        "$@"
    fi
}

to_seconds() {  # Docker's UTC time (2026-10-13T05:00:00.5Z) as epoch seconds
    date -d "$1" +%s 2> /dev/null ||                                  # Linux
        date -j -u -f '%Y-%m-%dT%H:%M:%S' "${1%%[.Z]*}" +%s 2> /dev/null  # macOS
}

gateway_minutes() {  # how long the IB Gateway container has been running
    local started since
    started=$(docker inspect -f '{{.State.StartedAt}}' ib-gateway 2> /dev/null) &&
        [ -n "$started" ] && since=$(to_seconds "$started") &&
        echo $(( ($(date +%s) - since) / 60 ))
}

warnings=""
if ! limit 120 git pull --ff-only --quiet; then
    warnings="Warning: could not update from GitHub, so this run used older code."
    echo "$warnings"
fi
# Exact versions, each file checked against its hash in
# requirements-ibkr.txt: a new or tampered release on PyPI never reaches
# this computer by itself.
limit 600 .venv/bin/pip install --quiet --disable-pip-version-check \
    --require-hashes -r requirements-ibkr.txt

# Just after the computer wakes up, the network or TWS may need a moment.
for attempt in 1 2 3; do
    # BRIDGE_ARGS stays unquoted: it may hold several options.
    output=$(limit 900 .venv/bin/python ibkr_bridge.py --send $BRIDGE_ARGS 2>&1)
    status=$?
    [ "$status" -eq 124 ] &&
        output="$output
The bridge was still running after 15 minutes and was stopped."
    echo "$output"
    [ "$status" -eq 0 ] && break
    # 3: the bridge refused to trade on purpose; another try won't help.
    [ "$status" -eq 3 ] && break
    [ "$attempt" -lt 3 ] || break
    # On the cloud server, a fresh start logs IB Gateway in again (IBKR
    # sometimes refuses its early-morning re-login). Not while it is still
    # logging in after a start (the server just booted, or a restart).
    if echo "$output" | grep -q "IB Gateway" && command -v docker > /dev/null &&
            up=$(gateway_minutes); then
        if [ "$up" -ge 5 ]; then
            echo "Restarting IB Gateway before the next try."
            docker restart ib-gateway > /dev/null
        else
            echo "IB Gateway started $up minutes ago; letting it log in."
        fi
    fi
    sleep 120
done

last=$(echo "$output" | grep -v '^Saved to' | tail -n 1)
# Warnings (old results, orders that did not fill) come along.
found=$(echo "$output" | grep '^Warning:' | sort -u)
warnings=$(printf '%s\n%s' "$warnings" "$found" | sed '/^$/d')

# The paper account next to the simulated agent, for the website. Only
# after a run that placed its orders: nothing here can change them, and a
# problem only adds a line to the message.
if [ "$status" -eq 0 ] && [ -n "$PUBLISH_REPO" ]; then
    if published=$(limit 300 .venv/bin/python ibkr_summary.py 2>&1 &&
            limit 120 bash server/publish.sh ibkr_logs/public/ibkr.json 2>&1)
    then
        echo "$published"
    else
        echo "$published"
        why=$(echo "$published" | sed '/^$/d' | tail -n 1)
        warnings=$(printf '%s\n%s' "$warnings" "Could not publish the \
account summary for the website: ${why:-no reason given}" | sed '/^$/d')
    fi
fi
[ -n "$warnings" ] && last="$last
$warnings"
if [ "$status" -eq 0 ]; then
    notify "$last"
else
    notify "Morning run failed: $last" high
fi
if [ -n "$HEALTHCHECK_URL" ]; then
    ping="$HEALTHCHECK_URL"
    [ "$status" -eq 0 ] || ping="$HEALTHCHECK_URL/fail"
    curl -fsS -m 30 --retry 3 "$ping" > /dev/null ||
        echo "Could not reach healthchecks.io."
fi

# On Telegram, the race chart follows, then why the top three hold what
# they hold, then every trade the accounts made (telegram_chart.py).
if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    chart="ibkr_logs/race.png" && reasons="ibkr_logs/why.txt" &&
    alert="ibkr_logs/trades.txt" &&
    caption=$(.venv/bin/python telegram_chart.py "$chart" --why "$reasons" \
        --trades "$alert") &&
    curl -fsS -m 60 -F "chat_id=$TELEGRAM_CHAT_ID" -F "photo=@$chart" \
        -F "caption=$caption" \
        "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendPhoto" > /dev/null &&
    curl -fsS -m 30 -d "chat_id=$TELEGRAM_CHAT_ID" \
        --data-urlencode "text@$reasons" \
        "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" > /dev/null &&
    curl -fsS -m 30 -d "chat_id=$TELEGRAM_CHAT_ID" \
        --data-urlencode "text@$alert" \
        "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" > /dev/null ||
        echo "Could not send the race chart to Telegram."
fi
exit "$status"
