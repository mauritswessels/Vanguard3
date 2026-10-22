#!/bin/bash
# Puts the paper account's summary for the website (ibkr_logs/public/
# ibkr.json, written by ibkr_summary.py) on GitHub. ibkr_morning.sh runs it
# after every weekday-morning run, once "setup.sh --publish" has set it up.
#
#   bash server/publish.sh ibkr_logs/public/ibkr.json   publish the file
#   bash server/publish.sh --check                      may the key push?
#
# It pushes one commit holding only the summary (and a short README) to its
# own branch, replacing yesterday's: the file keeps its own history. It
# uses the deploy key setup.sh made, and refuses to push to main or master.
#
# Settings in ibkr_morning.env (setup.sh --publish writes them):
#   PUBLISH_REPO=git@github.com:<owner>/<name>.git
#   PUBLISH_BRANCH=ibkr-data
#   PUBLISH_KEY=/root/.ssh/vanguard3_publish

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

PUBLISH_REPO=""
PUBLISH_BRANCH="ibkr-data"
PUBLISH_KEY="${HOME:-/root}/.ssh/vanguard3_publish"
if [ -f "$REPO/ibkr_morning.env" ]; then
    . "$REPO/ibkr_morning.env"
fi

fail() { echo "$*" >&2; exit 1; }

[ -n "$PUBLISH_REPO" ] ||
    fail "Publishing is not set up yet: bash $HERE/setup.sh --publish"
case "$PUBLISH_BRANCH" in
    main | master | HEAD | refs/* | -* | "")
        fail "Will not publish to the branch '$PUBLISH_BRANCH': it needs" \
             "its own branch, such as ibkr-data." ;;
esac
git check-ref-format --branch "$PUBLISH_BRANCH" > /dev/null 2>&1 ||
    fail "'$PUBLISH_BRANCH' is not a branch name."

if [ "${1:-}" = "--check" ]; then
    check=yes
    file=""
else
    check=""
    file="${1:-$REPO/ibkr_logs/public/ibkr.json}"
    [ -s "$file" ] || fail "No summary at $file (ibkr_summary.py writes it)."
fi

case "$PUBLISH_REPO" in
    *:*)    # GitHub, over SSH: only with the deploy key, only to GitHub
        [ -r "$PUBLISH_KEY" ] ||
            fail "No deploy key at $PUBLISH_KEY: bash $HERE/setup.sh --publish"
        export GIT_SSH_COMMAND="ssh -i '$PUBLISH_KEY' -o IdentitiesOnly=yes \
-o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes \
-o UserKnownHostsFile='$HERE/github_known_hosts'" ;;
esac

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GIT_DIR="$work/git"
git init --quiet --bare "$GIT_DIR"
export GIT_AUTHOR_NAME="Vanguard3 server" GIT_COMMITTER_NAME="Vanguard3 server"
export GIT_AUTHOR_EMAIL="server@vanguard3.invalid"
export GIT_COMMITTER_EMAIL="server@vanguard3.invalid"

if [ -n "$check" ]; then        # a dry run: GitHub checks, nothing changes
    file="$work/ibkr.json"
    echo '{}' > "$file"
fi
cat > "$work/README.md" <<'EOF'
# Vanguard3: the IBKR paper account

`ibkr.json` is the Interactive Brokers paper account that copies the Team
Manager, next to the simulated Team Manager, one row per weekday morning.
The Vanguard3 server replaces it after every morning run. The README of
Vanguard3 ("The paper account on the website") describes every field.
EOF
readme=$(git hash-object -w "$work/README.md")
json=$(git hash-object -w "$file")
tree=$(printf '100644 blob %s\tREADME.md\n100644 blob %s\tibkr.json\n' \
    "$readme" "$json" | git mktree)
commit=$(git commit-tree "$tree" -m "Paper account summary, $(date +%Y-%m-%d)")

if ! out=$(git push --quiet --force ${check:+--dry-run} "$PUBLISH_REPO" \
        "$commit:refs/heads/$PUBLISH_BRANCH" 2>&1); then
    echo "$out" >&2
    why=$(echo "$out" | grep -m 1 -E 'ERROR|denied|fatal|error' ||
          echo "$out" | head -n 1)
    fail "GitHub did not take the summary ($why)"
fi

where="$PUBLISH_REPO, branch $PUBLISH_BRANCH"
if [[ "$PUBLISH_REPO" =~ github\.com[:/]([^/]+/[^/]+)$ ]]; then
    where="https://raw.githubusercontent.com/${BASH_REMATCH[1]%.git}/$PUBLISH_BRANCH/ibkr.json"
fi
if [ -n "$check" ]; then
    echo "The deploy key may push to $PUBLISH_REPO."
else
    echo "Published: $where"
fi
