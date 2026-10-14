#!/bin/bash
# Sends the result of every weekday-morning run to Telegram (instead of, or
# next to, the ntfy app). Run it on the server once, after setup.sh:
#
#   bash /opt/Vanguard3/server/telegram.sh
#
# You need a Telegram bot first: in Telegram, open @BotFather, send /newbot
# and follow the questions. BotFather then gives you the bot's token. The
# token stays on this server, in ibkr_morning.env (never in git).

set -euo pipefail
umask 077                      # the token is a secret

HERE="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$(dirname "$HERE")/ibkr_morning.env"
API="https://api.telegram.org"

IFS= read -r -s -p "Bot token from BotFather (hidden while you type): " token
echo
if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    echo "That doesn't look like a bot token (numbers, a colon, then" \
         "letters). Run this again." >&2
    exit 1
fi
if ! curl -fsS -m 30 "$API/bot$token/getMe" > /dev/null; then
    echo "Telegram did not accept that token. Copy it again from" \
         "BotFather and run this again." >&2
    exit 1
fi

echo "Now open your new bot in Telegram, tap Start (or send it any"
read -r -p "message), then come back here and press Enter. "
chat=$(curl -fsS -m 30 "$API/bot$token/getUpdates" | python3 -c '
import json, sys
chats = [u["message"]["chat"]["id"] for u in json.load(sys.stdin)["result"]
         if "message" in u]
print(chats[-1] if chats else "")')
if [ -z "$chat" ]; then
    echo "No message reached the bot yet. Send it a message and run this" \
         "again." >&2
    exit 1
fi

touch "$SETTINGS"
chmod 600 "$SETTINGS"
grep -v '^TELEGRAM_' "$SETTINGS" > "$SETTINGS.new" || true
printf 'TELEGRAM_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$token" "$chat" \
    >> "$SETTINGS.new"
mv "$SETTINGS.new" "$SETTINGS"
chmod 600 "$SETTINGS"

curl -fsS -m 30 -d "chat_id=$chat" --data-urlencode "text=Vanguard3: \
Telegram is connected. A message like this one arrives after every \
weekday morning run." "$API/bot$token/sendMessage" > /dev/null
echo "Done. Check Telegram: a test message is waiting there."
