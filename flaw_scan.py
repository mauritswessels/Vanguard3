"""The flaw scan: checks that must always hold, on the live accounts and
on the project itself.

The weekly flaw scan (``.github/workflows/flaw-scan.yml``) runs it, and so
does every pull request; the evening health check (``health_check.py``)
runs the account checks after each paper-trading run::

    python flaw_scan.py --out scan.md

It writes a short list of problems to ``--out`` (nothing if all is well)
and stops with exit code 1 when it found any. It looks for:

* accounts that do not add up: cash that is not the starting cash plus
  every fill, dividend and split; shares that are not what the fills
  bought and sold; negative cash; a price or value that is not a number;
* waiting orders that cannot be right (a market off the watchlist, no
  shares, two for one market, made after the last session);
* settings that contradict each other (a currency without an exchange
  rate, a US fund without its European stand-in for IBKR, two markets
  with the same IBKR symbol);
* the IBKR bridge's paper-only check gone missing;
* a secret file or an API key in the repository;
* a workflow that pushes to ``main`` outside the shared ``paper-trading``
  queue (two runs writing the accounts at once lose one run's work);
* dashboard data that a browser cannot read (not strict JSON);
* a project journal (the website's timeline) that has fallen more than a
  week behind the pull requests merged into ``main``.

Pure Python, offline, and no change to anything it checks.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent

#: Off by at most this much (CHF), an account still adds up: the saved
#: state rounds every number to 6 decimals.
CENTS = 0.01

#: Files that hold secrets and must never be committed (the .gitignore
#: keeps them out).
SECRET_FILES = ("server/.env", "server/ib_password.txt", "ibkr_morning.env",
                "ibkr_logs/")

#: What keys and tokens look like: Anthropic, GitHub, Telegram bot,
#: Finnhub-style hex keys are too common to tell apart, so are left out.
SECRET_PATTERNS = {
    "an Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "a Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def _number(x) -> bool:
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x))


# -- the accounts --------------------------------------------------------------
def account_problems(acc: dict, last_date: str | None) -> list[str]:
    """What does not add up in one saved account."""
    name = acc.get("name") or acc.get("agent", "?")
    pf = acc.get("portfolio")
    if not pf:
        return []
    out = []

    cash = pf.get("cash")
    if not _number(cash):
        return [f"{name}: its cash is not a number ({cash!r})."]
    if cash < -CENTS:
        out.append(f"{name}: its cash is below zero ({cash:,.2f} CHF).")

    # Cash: the starting cash plus every fill, dividend and split payout.
    flows = [t.get("cash_flow_chf") for t in pf["trades"]]
    paid = [e.get("chf") for e in pf.get("events", [])]
    if all(_number(x) for x in flows + paid):
        expected = pf["initial_cash"] + sum(flows) + sum(paid)
        if abs(expected - cash) > CENTS:
            out.append(f"{name}: its cash is {cash:,.2f} CHF, but its fills "
                       f"and dividends add up to {expected:,.2f} CHF.")
    else:
        out.append(f"{name}: a fill or dividend has an amount that is not a "
                   "number.")

    # Shares: what the fills bought and sold, restated by each split.
    steps = ([(t["date"], 1, t) for t in pf["trades"]]
             + [(e["date"], 0, e) for e in pf.get("events", [])
                if e.get("kind") == "split"])
    shares: dict[str, int] = {}
    for _, kind, x in sorted(steps, key=lambda s: (s[0], s[1])):
        t = x["ticker"]
        if kind == 0:
            shares[t] = int(x["shares"])
        else:
            change = x["quantity"] if x["side"] == "BUY" else -x["quantity"]
            shares[t] = shares.get(t, 0) + change
    held = {}
    for p in pf["positions"]:
        t, q = p["ticker"], p["quantity"]
        if t in held:
            out.append(f"{name}: holds {t} twice.")
        held[t] = q
        if not isinstance(q, int) or q <= 0:
            out.append(f"{name}: holds {q!r} shares of {t}.")
        if not (_number(p.get("cost_basis_chf"))
                and p["cost_basis_chf"] > 0):
            out.append(f"{name}: the cost of its {t} shares is "
                       f"{p.get('cost_basis_chf')!r}.")
        if t not in config.WATCHLIST:
            out.append(f"{name}: holds {t}, which is not on the watchlist.")
    from_fills = {t: q for t, q in shares.items() if q}
    if from_fills != held:
        diff = sorted(set(from_fills.items()) ^ set(held.items()))
        out.append(f"{name}: its holdings do not match its fills "
                   f"({', '.join(f'{t} {q}' for t, q in diff[:6])}).")

    # The equity curve: a number for every day, up to the last session.
    equity = pf.get("equity", {})
    bad = [d for d, v in equity.items() if not (_number(v) and v > 0)]
    if bad:
        out.append(f"{name}: its account value is not a positive number on "
                   f"{', '.join(bad[:3])}.")
    if equity and last_date and max(equity) != last_date:
        out.append(f"{name}: its account value stops on {max(equity)}, the "
                   f"accounts are at {last_date}.")

    # Waiting orders.
    seen = set()
    for o in acc.get("pending_orders", []):
        t = o.get("ticker")
        what = f"{name}: the waiting order to {o.get('side')} {t}"
        if t not in config.WATCHLIST:
            out.append(f"{what} is for a market not on the watchlist.")
        if o.get("side") not in ("BUY", "SELL"):
            out.append(f"{what} is neither a buy nor a sell.")
        if not isinstance(o.get("quantity"), int) or o["quantity"] <= 0:
            out.append(f"{what} has {o.get('quantity')!r} shares.")
        if o.get("kind", "open") not in ("open", "close"):
            out.append(f"{what} has an unknown kind {o.get('kind')!r}.")
        # The midday check orders for today's close, after the last
        # session; an order for an open never comes from after it.
        if (last_date and o.get("kind", "open") == "open"
                and str(o.get("created")) > last_date):
            out.append(f"{what} was made on {o.get('created')}, after the "
                       f"last session ({last_date}).")
        if (t, o.get("kind", "open")) in seen:
            out.append(f"{name}: two waiting orders for {t}; only the newest "
                       "should be left.")
        seen.add((t, o.get("kind", "open")))

    # Numbers the agents keep between evenings.
    s = acc.get("agent_state") or {}
    for t, tgt in (s.get("targets") or {}).items():
        if not _number(tgt.get("weight")):
            out.append(f"{name}: its target for {t} is not a number "
                       f"({tgt.get('weight')!r}); the next run would stop.")
    w = s.get("w")
    if w is not None and not all(_number(x) for row in w for x in row):
        out.append(f"{name}: its learning model holds a value that is not a "
                   "number.")
    return out


def state_problems(state: dict | None) -> list[str]:
    """What does not add up in the saved paper accounts."""
    if not state:
        return []
    out = []
    seen = set()
    for acc in state.get("accounts", []):
        key = (acc.get("agent"), acc.get("name"))
        if key in seen:
            out.append(f"Two accounts are called {key[1]!r}: the second "
                       "would never be updated.")
        seen.add(key)
        out += account_problems(acc, state.get("last_date"))
    return out


# -- the project ----------------------------------------------------------------
def config_problems() -> list[str]:
    """Settings that contradict each other."""
    out = []
    for t, ccy in sorted(config.WATCHLIST.items()):
        if ccy != config.BASE_CURRENCY and ccy not in config.FX_TICKERS:
            out.append(f"{t} trades in {ccy}, but there is no {ccy}/CHF "
                       "rate in FX_TICKERS.")
    missing = sorted(set(config._FUNDS) - set(config.IBKR_STAND_INS))
    if missing:
        out.append("US funds with no European stand-in for IBKR "
                   f"(IBKR_STAND_INS): {', '.join(missing)}. The IBKR copy "
                   "would keep them in cash.")
    import ibkr_bridge
    names: dict[tuple, str] = {}
    for t in config.WATCHLIST:
        key = ibkr_bridge.ib_symbol(t)[:2]
        if key in names:
            out.append(f"{names[key]} and {t} are both {key[0]} "
                       f"({key[1]}) at IBKR: the bridge cannot tell them "
                       "apart.")
        names[key] = t
    return out


def bridge_problems(path: Path | None = None) -> list[str]:
    """The bridge must keep refusing every account that is not a paper
    account (IDs starting with "D")."""
    text = (path or ROOT / "ibkr_bridge.py").read_text()
    if not re.search(r"""a\.startswith\(\s*["']D["']\s*\)""", text):
        return ["ibkr_bridge.py no longer checks that it only trades paper "
                "accounts (IDs starting with \"D\"). Put the check back "
                "before anything is merged."]
    return []


def tracked_files(root: Path = ROOT) -> list[str]:
    try:
        done = subprocess.run(["git", "ls-files"], cwd=root, check=True,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return done.stdout.splitlines()


def secret_problems(root: Path = ROOT, files: list[str] | None = None
                    ) -> list[str]:
    """Secret files or keys in the repository."""
    out = []
    ignore = (root / ".gitignore").read_text().split() \
        if (root / ".gitignore").exists() else []
    for f in SECRET_FILES:
        if f not in ignore:
            out.append(f".gitignore no longer leaves out {f}, which holds "
                       "secrets.")
    files = tracked_files(root) if files is None else files
    for f in files:
        if any(f == s or (s.endswith("/") and f.startswith(s))
               for s in SECRET_FILES):
            out.append(f"{f} is in the repository: it holds secrets. Remove "
                       "it, and change every password or key it held.")
            continue
        path = root / f
        if (f.startswith(("docs/data/", "state/")) or not path.is_file()
                or path.stat().st_size > 2_000_000):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue                          # pictures, archives
        for what, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                out.append(f"{f} holds what looks like {what}. If it is "
                           "real, remove it and replace the key.")
    return out


def workflow_problems(folder: Path | None = None) -> list[str]:
    """Every workflow that pushes waits its turn in the shared queue, so
    two runs never write the accounts at the same time. Every workflow that
    runs on a schedule says so when it fails: nobody watches it start."""
    out = []
    folder = folder or ROOT / ".github" / "workflows"
    for path in sorted(folder.glob("*.y*ml")):
        text = path.read_text()
        if "git push" in text and not re.search(
                r"concurrency:\s*\n\s*group:\s*paper-trading", text):
            out.append(f"{path.name} pushes to GitHub outside the "
                       "paper-trading queue (add 'concurrency: group: "
                       "paper-trading'): it can overwrite another run's "
                       "results.")
        if "cron:" in text and not re.search(r"gh issue (create|comment)",
                                              text):
            out.append(f"{path.name} runs on a schedule but tells no one "
                       "when it fails (add an alert step like the one in "
                       "daily.yml).")
    return out


def data_problems(folder: Path | None = None) -> list[str]:
    """Dashboard files a browser cannot read."""
    out = []
    folder = folder or config.DASHBOARD_DATA_DIR

    def strict(x):
        raise ValueError(f"{x} is not allowed in JSON")

    for path in sorted(folder.glob("*.json")):
        try:
            json.loads(path.read_text(), parse_constant=strict)
        except ValueError as exc:
            out.append(f"docs/data/{path.name} cannot be read by the "
                       f"website: {exc}")
    return out


#: The website's timeline (web/src/content/journal.ts).
JOURNAL_FILE = ROOT / "web" / "src" / "content" / "journal.ts"

#: How far the journal may trail the newest merged pull request, so a
#: change can be merged first and written up a few days later.
JOURNAL_GRACE = timedelta(days=7)


def merged_pull_requests(root: Path = ROOT) -> list[tuple[date, str]]:
    """(day, title) of every pull request merged into the branch checked
    out, newest first. The weekly flaw fixes are left out: they mend, they
    add nothing new. Empty without git or without history (a shallow
    checkout), so the check then passes instead of guessing."""
    try:
        done = subprocess.run(
            ["git", "log", "--first-parent", "--merges",
             "--format=%cs%x1f%s%x1f%b%x1e", "HEAD"],
            cwd=root, check=True, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for record in done.stdout.split("\x1e"):
        parts = record.strip().split("\x1f")
        if len(parts) < 3 or not parts[1].startswith("Merge pull request"):
            continue
        if "weekly-flaw-fix" in parts[1]:
            continue
        title = parts[2].strip().splitlines()[0] if parts[2].strip() else parts[1]
        out.append((date.fromisoformat(parts[0]), title))
    return out


def journal_problems(path: Path | None = None,
                     merged: list[tuple[date, str]] | None = None
                     ) -> list[str]:
    """The website's timeline keeps up with what was built: a pull request
    merged more than a week after the journal's newest entry means someone
    forgot to write it up."""
    text = (path or JOURNAL_FILE).read_text()
    days = re.findall(r'date:\s*"(\d{4}-\d{2}-\d{2})"', text)
    if not days:
        return ["web/src/content/journal.ts has no dated entries, so the "
                "website's timeline is empty."]
    newest = max(date.fromisoformat(d) for d in days)
    merged = merged_pull_requests() if merged is None else merged
    late = [(d, t) for d, t in merged if d > newest + JOURNAL_GRACE]
    if not late:
        return []
    titles = "; ".join(f"{t} ({d})" for d, t in late[:3])
    more = f" and {len(late) - 3} more" if len(late) > 3 else ""
    return [f"The website's timeline stops at {newest}, but pull requests "
            f"were merged after it: {titles}{more}. Add an entry for them "
            "to web/src/content/journal.ts and rebuild the site."]


def scan(state_path: Path = config.PAPER_STATE_FILE) -> list[str]:
    """Every check above."""
    state = (json.loads(state_path.read_text())
             if state_path.exists() else None)
    return (state_problems(state) + config_problems() + bridge_problems()
            + secret_problems() + workflow_problems() + data_problems()
            + journal_problems())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("--out", type=Path, default=None,
                        help="also write the problems to this file")
    args = parser.parse_args()
    found = scan(args.state)
    text = "".join(f"- {p}\n" for p in found)
    if args.out:
        if found:
            args.out.write_text(text)
        else:
            args.out.unlink(missing_ok=True)
    print(text or "No flaws found.")
    raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
