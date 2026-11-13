#!/bin/bash
# Starts the website's GitHub runs on time from this server. GitHub's own
# timetable sometimes starts them hours late (in November 2026 by 3 to 7
# hours), which cost the Day Trader whole days of live trading and the
# midday check its prices. This server's clock is reliable, so it asks
# GitHub to start each run at the right moment:
#
#   bash /opt/Vanguard3/server/trigger.sh --setup         once: token + timers
#   bash /opt/Vanguard3/server/trigger.sh day-trader.yml  start one run now
#
# Weekdays, New York time (Swiss time is 6 hours later, 5 for a few weeks
# in spring and autumn):
#   09:05  Day trader        (it waits for 10:00 by itself)
#   10:37  Midday news check (New York has been open an hour, Europe still is)
#   16:40  Daily paper trading (40 minutes after the close)
#
# The token can only start runs of the one repository (a fine-grained
# token with "Actions: read and write"): it cannot change the code, the
# secrets or the settings, and it stays in ibkr_morning.env on this server.
# GitHub's own timetable stays as a backup: a run that finds its work
# already done stops after a minute (the midday check makes no second
# Claude call).

set -euo pipefail
umask 077                      # the token is a secret

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
SETTINGS="$REPO/ibkr_morning.env"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
GITHUB_REPO="mauritswessels/Vanguard3"
API="https://api.github.com"
LOG="$REPO/ibkr_logs/trigger.log"

# Workflow file -> when it starts (systemd calendar, New York time).
WORKFLOWS="day-trader.yml midday-news.yml daily.yml"
when() {
    case "$1" in
        day-trader.yml)  echo "Mon..Fri 09:05 America/New_York" ;;
        midday-news.yml) echo "Mon..Fri 10:37 America/New_York" ;;
        daily.yml)       echo "Mon..Fri 16:40 America/New_York" ;;
    esac
}

TRIGGER_TOKEN=""
TELEGRAM_TOKEN=""
TELEGRAM_CHAT_ID=""
[ -f "$SETTINGS" ] && . "$SETTINGS"

# GitHub's API with the token. The token goes to curl on its standard
# input, never on the command line, where other programs could see it.
github() {
    local method="$1" path="$2" data="${3:-}"
    printf 'header = "Authorization: Bearer %s"\n' "$TRIGGER_TOKEN" |
        curl -fsS -m 30 -K - -X "$method" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            ${data:+-d "$data"} "$API/repos/$GITHUB_REPO$path"
}

setup() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Please run this as root: sudo bash $0 --setup" >&2
        exit 1
    fi
    cat <<EOF
This server will start the GitHub runs on time. It needs a token from
GitHub that may only start runs (signed in as mauritswessels):

  https://github.com/settings/personal-access-tokens/new
  Token name: Vanguard3 server     Expiration: 1 year (or longer)
  Repository access: Only select repositories > $GITHUB_REPO
  Permissions > Repository permissions > Actions: Read and write
  > Generate token, then copy it

EOF
    IFS= read -r -s -p "Token (hidden while you type): " TRIGGER_TOKEN
    echo
    if [[ ! "$TRIGGER_TOKEN" =~ ^(github_pat_|ghp_)[A-Za-z0-9_]+$ ]]; then
        echo "That doesn't look like a GitHub token (it starts with" \
             "github_pat_). Run this again." >&2
        exit 1
    fi
    if ! github GET /actions/workflows > /dev/null; then
        echo "GitHub did not accept that token for $GITHUB_REPO. Check" \
             "that it has access to that repository, then run this again." >&2
        exit 1
    fi

    touch "$SETTINGS"
    chmod 600 "$SETTINGS"
    grep -v '^TRIGGER_TOKEN=' "$SETTINGS" > "$SETTINGS.new" || true
    printf 'TRIGGER_TOKEN=%s\n' "$TRIGGER_TOKEN" >> "$SETTINGS.new"
    mv "$SETTINGS.new" "$SETTINGS"
    chmod 600 "$SETTINGS"

    cat > "$UNIT_DIR/vanguard3-trigger@.service" <<EOF
[Unit]
Description=Vanguard3: start the GitHub run %i
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Environment=HOME=/root
ExecStart=/bin/bash $HERE/trigger.sh %i
TimeoutStartSec=5min
EOF
    local timers="" wf name
    for wf in $WORKFLOWS; do
        name="vanguard3-trigger-${wf%.yml}"
        cat > "$UNIT_DIR/$name.timer" <<EOF
[Unit]
Description=Vanguard3: start the GitHub run $wf on time

[Timer]
OnCalendar=$(when "$wf")
Unit=vanguard3-trigger@$wf.service

[Install]
WantedBy=timers.target
EOF
        timers="$timers $name.timer"
    done
    systemctl daemon-reload
    # $timers stays unquoted: it holds several names.
    systemctl enable --now $timers
    cat <<EOF

Done. From now on this server starts the GitHub runs on time, every
weekday (New York time):
  09:05 Day trader, 10:37 Midday news check, 16:40 Daily paper trading
What it did: tail $LOG
When they run next: systemctl list-timers 'vanguard3-trigger*'
EOF
}

start() {
    local wf="$1" stamp
    stamp="$(date '+%Y-%m-%d %H:%M %Z')"
    mkdir -p "$(dirname "$LOG")"
    if [ -z "$TRIGGER_TOKEN" ]; then
        echo "No token yet: bash $HERE/trigger.sh --setup" >&2
        exit 1
    fi
    if github POST "/actions/workflows/$wf/dispatches" '{"ref":"main"}' \
            > /dev/null; then
        echo "$stamp started $wf" | tee -a "$LOG"
        return 0
    fi
    echo "$stamp GitHub did not start $wf" | tee -a "$LOG" >&2
    if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -fsS -m 30 -d "chat_id=$TELEGRAM_CHAT_ID" \
            --data-urlencode "text=Vanguard3: the server could not start \
the GitHub run $wf (GitHub's own timetable still starts it, perhaps late). \
The token may have expired: bash $HERE/trigger.sh --setup" \
            "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
            > /dev/null || true
    fi
    exit 1
}

case "${1:-}" in
    --setup) setup ;;
    "")
        echo "Usage: bash $0 --setup | bash $0 <$WORKFLOWS>" >&2
        exit 2 ;;
    *)
        if [[ " $WORKFLOWS " != *" $1 "* ]]; then
            echo "Not one of this server's runs: $1 (only: $WORKFLOWS)" >&2
            exit 2
        fi
        start "$1" ;;
esac
