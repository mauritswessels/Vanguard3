#!/bin/bash
# Sets up a cloud server (Ubuntu 24.04) that copies the agent into the IBKR
# paper account every weekday morning, so your own computer can stay off.
# Run it as root once the project is cloned:
#
#   git clone https://github.com/mauritswessels/Vanguard3.git /opt/Vanguard3
#   bash /opt/Vanguard3/server/setup.sh
#
# It installs Docker and Python, asks once for the IBKR paper login, starts
# IB Gateway (IBKR's trading app for servers) and plans the weekday runs.
# Running it again is safe. To type in a new login: setup.sh --login

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
APT_DIR="${APT_DIR:-/etc/apt/apt.conf.d}"

say() { printf '\n== %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run this as root: sudo bash $0" >&2
    exit 1
fi

say "Installing Docker and Python (a minute or two)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 python3-venv git curl \
    unattended-upgrades
timedatectl set-timezone Europe/Zurich

say "Security updates by themselves"
# Ubuntu installs security updates every day; a restart they need (a new
# kernel) happens at 11:00, after the morning run. IB Gateway and the
# weekday runs start again on their own.
cat > "$APT_DIR/52vanguard3-updates" <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "11:00";
EOF
systemctl enable --now docker

say "Preparing the bridge"
[ -x "$REPO/.venv/bin/python" ] || python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install --quiet --disable-pip-version-check \
    -r "$REPO/requirements-ibkr.txt"

new_login=""
if [ "${1:-}" = "--login" ] || [ ! -s "$HERE/.env" ] ||
        [ ! -s "$HERE/ib_password.txt" ]; then
    say "Your IBKR paper trading login"
    echo "Use the PAPER username, not your normal one. On the IBKR website:"
    echo "person icon (top right) > Settings > Paper Trading Account. The"
    echo "password can be reset there too."
    read -r -p "Paper username: " user
    IFS= read -r -s -p "Paper password (hidden while you type): " password
    echo
    if [ -z "$user" ] || [ -z "$password" ] || [[ "$user" =~ [[:space:]] ]]
    then
        echo "That doesn't look like a username and password." \
             "Run the setup again." >&2
        exit 1
    fi
    (umask 077
     printf 'TWS_USERID=%s\n' "$user" > "$HERE/.env"
     printf '%s' "$password" > "$HERE/ib_password.txt")
    # IB Gateway runs as user 1000 inside its container.
    chown 1000:1000 "$HERE/ib_password.txt"
    new_login=yes
fi

if [ ! -f "$REPO/ibkr_morning.env" ]; then
    topic="vanguard3-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
    cat > "$REPO/ibkr_morning.env" <<EOF
# Settings for ibkr_morning.sh on this server (written by server/setup.sh).
BRIDGE_ARGS="--port 4002"
NTFY_TOPIC=$topic
EOF
fi
BRIDGE_ARGS=""
NTFY_TOPIC=""
. "$REPO/ibkr_morning.env"

say "Starting IB Gateway"
docker compose -f "$HERE/docker-compose.yml" up -d \
    ${new_login:+--force-recreate}

say "Planning the weekday runs"
cat > "$UNIT_DIR/vanguard3-bridge.service" <<EOF
[Unit]
Description=Vanguard3: copy the agent into the IBKR paper account
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
Environment=HOME=/root
ExecStart=/bin/bash $REPO/ibkr_morning.sh
# A run that hangs would block every later one.
TimeoutStartSec=40min
EOF
cat > "$UNIT_DIR/vanguard3-bridge.timer" <<EOF
[Unit]
Description=Vanguard3: the bridge every weekday morning

[Timer]
OnCalendar=Mon..Fri 08:30 Europe/Zurich
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > "$UNIT_DIR/vanguard3-update.service" <<EOF
[Unit]
Description=Vanguard3: update IB Gateway
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
WorkingDirectory=$HERE
ExecStart=/usr/bin/docker compose pull --quiet
ExecStart=/usr/bin/docker compose up -d
ExecStart=/usr/bin/docker image prune -f
EOF
cat > "$UNIT_DIR/vanguard3-update.timer" <<EOF
[Unit]
Description=Vanguard3: update IB Gateway every Saturday

[Timer]
OnCalendar=Sat 10:00 Europe/Zurich
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now vanguard3-bridge.timer vanguard3-update.timer

say "Checking the connection (IB Gateway takes a minute to log in)"
connected=""
for attempt in 1 2 3 4 5 6; do
    sleep 20
    # BRIDGE_ARGS stays unquoted: it may hold several options.
    if output=$("$REPO/.venv/bin/python" "$REPO/ibkr_bridge.py" \
            $BRIDGE_ARGS 2>&1); then
        connected=yes
        break
    fi
done
echo "$output"

if [ -z "$connected" ]; then
    say "IB Gateway did not answer"
    docker logs --tail 15 ib-gateway 2>&1 || true
    cat <<EOF

Most likely the paper username or password is wrong. Type them again with:
  bash $HERE/setup.sh --login
If they are right, wait two minutes and check again with:
  $REPO/.venv/bin/python $REPO/ibkr_bridge.py $BRIDGE_ARGS
EOF
    exit 1
fi

say "Done"
echo "Every weekday at 08:30 (Swiss time) the bridge copies the agent into"
echo "your paper account. Above is what it would do right now (nothing was"
echo "sent)."
if [ -n "$NTFY_TOPIC" ]; then
    curl -fsS -m 30 -H "Title: Vanguard3" -d "The server is ready. A \
message like this one arrives after every weekday morning run." \
        "https://ntfy.sh/$NTFY_TOPIC" > /dev/null || true
    echo
    echo "For a message on your phone after each run, install the free ntfy"
    echo "app and subscribe to this topic:"
    echo "  $NTFY_TOPIC"
fi
cat <<EOF

Useful commands on this server:
  systemctl start vanguard3-bridge        run it right now
  systemctl list-timers 'vanguard3*'      when it runs next
  tail -n 40 $REPO/ibkr_logs/morning.log
                                          what the last runs did
  docker logs --tail 30 ib-gateway        what IB Gateway is doing
EOF
