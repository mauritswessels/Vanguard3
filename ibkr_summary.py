"""The IBKR paper account next to the simulated agent it copies, for the
website.

Every weekday morning ``ibkr_morning.sh`` runs this after the bridge, on
the computer that runs the bridge. It reads that run's log in
``ibkr_logs/`` and the results the bridge copied, and writes
``ibkr_logs/public/ibkr.json``: the paper account's value, cash and
holdings next to the simulated agent's at the same close, the orders and
what became of them, and how closely the copy follows the simulation.
``server/publish.sh`` then puts the file on GitHub for the website. The
README ("The paper account on the website") describes every field.

    python ibkr_summary.py        # after this morning's run

It is a separate step on purpose: it runs after the orders are placed, so
nothing in it can stop or change them.

The file is public, so nothing personal goes in: no account ID, username,
password or token, and none of IBKR's own messages (they can name the
account). Before the file is written it is searched for the account ID,
for anything shaped like an IBKR account ID, and for every login detail
and token kept on this computer. If one turns up, nothing is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import config
import ibkr_bridge as bridge

ROOT = Path(__file__).resolve().parent
OUT = bridge.LOG_DIR / "public" / "ibkr.json"
SCHEMA = 1

ABOUT = ("The Interactive Brokers paper account that copies the {name} "
         "every weekday morning, next to the simulated {name}. Both are "
         "valued at the same close: the account before that morning's "
         "orders, the simulation at the close whose results were copied. "
         "Returns are in Swiss francs, so the account's own currency does "
         "not blur the comparison.")

#: Settings whose values must never be published (``server/.env``,
#: ``ibkr_morning.env`` or the environment).
PRIVATE_SETTINGS = ("TWS_USERID", "TWS_PASSWORD", "TELEGRAM_TOKEN",
                    "TELEGRAM_CHAT_ID", "NTFY_TOPIC", "HEALTHCHECK_URL",
                    "ANTHROPIC_API_KEY", "FINNHUB_API_KEY")

#: Anything shaped like an IBKR account ID (DU1234567, U1234567, ...).
ACCOUNT_ID = re.compile(r"\b[A-Z]{1,3}\d{5,}\b")

#: The bridge's own words for an order IBKR took (``status_text``); IBKR's
#: messages are never copied.
SENT_NOTE = re.compile(r"(filled at [\d.]+|[\d.]+ filled so far, the rest "
                       r"is waiting|waiting for the market to open|sent, "
                       r"waiting to be filled)")

KID = ("IBKR does not sell this fund to this account (it has no key "
       "information document, which private investors in Europe and "
       "Switzerland must get)")
NO_PRICE = ("No price in the results for the European fund IBKR holds "
            "instead")


class PrivateDataError(ValueError):
    """The summary would show something personal."""


# -- reading the run -----------------------------------------------------------
def runs_of(day: date, log_dir: Path) -> list[dict]:
    """Every bridge run logged on ``day``."""
    path = log_dir / f"{day:%Y-%m-%d}.json"
    return json.loads(path.read_text()) if path.exists() else []


def latest_run(day: date, log_dir: Path) -> dict | None:
    """The last run on ``day`` that placed its orders (not a dry run)."""
    sent = [r for r in runs_of(day, log_dir) if r.get("status") == "sent"]
    return sent[-1] if sent else None


def holds_as(ticker: str) -> str | None:
    """What the IBKR account holds instead of a US fund (CSPX for SPY)."""
    if ticker in config.IBKR_STAND_INS:
        return bridge.ib_symbol(ticker)[0]
    return None


def rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


# -- the two accounts ------------------------------------------------------------
def real_side(run: dict, payload: dict) -> dict:
    """The paper account at the close before the run: value, cash and the
    share of it in each watchlist market (CHF at that close's rates)."""
    value, base = run["net_liq"], run["base"]
    rate = bridge.chf_per_unit(payload, base)
    value_chf = value * rate if rate else None
    held = run.get("held") or {}
    weights = {}
    for ticker, quantity in held.items():
        quote = bridge.ib_price(payload, ticker)
        to_chf = bridge.chf_per_unit(payload, quote[1]) if quote else None
        if quantity and to_chf and value_chf:
            weights[ticker] = quantity * quote[0] * to_chf / value_chf
    gross = run.get("gross")
    cash = value - gross if gross is not None else None
    invested = (gross / value if gross is not None and value
                else sum(weights.values()))
    return {"value": value, "currency": base, "value_chf": value_chf,
            "cash": cash,
            "cash_chf": cash * rate if cash is not None and rate else None,
            "invested": invested,
            "positions": run.get("positions", len(held)),
            "watchlist_positions": len(held), "weights": weights}


def sim_side(payload: dict, agent_id: str) -> dict:
    """The simulated agent at the close of its newest results."""
    agent = next((a for a in payload["agents"] if a["id"] == agent_id), None)
    if agent is None:
        raise SystemExit(f"No agent '{agent_id}' in the results.")
    equity = agent["stats"]["final_equity_chf"]
    weights = {p["ticker"]: p["value_chf"] / equity
               for p in agent["positions"] if p.get("value_chf")}
    cash = agent.get("cash_chf")
    return {"name": agent["name"], "value_chf": equity, "cash_chf": cash,
            "invested": (1 - cash / equity if cash is not None
                         else sum(weights.values())),
            "positions": len(agent["positions"]), "weights": weights}


def holdings_gap(real: dict[str, float], sim: dict[str, float]) -> float:
    """Share of the account held differently from the simulation: half the
    sum of the differences in each market (0 = the same, 1 = nothing in
    common)."""
    return 0.5 * sum(abs(real.get(t, 0.0) - sim.get(t, 0.0))
                     for t in set(real) | set(sim))


def weight_table(real: dict[str, float], sim: dict[str, float]
                 ) -> list[dict]:
    """Both accounts' share in each market, biggest first."""
    rows = [{"ticker": t, "holds_as": holds_as(t),
             "sim": round(sim.get(t, 0.0), 4),
             "real": round(real.get(t, 0.0), 4),
             "difference": round(real.get(t, 0.0) - sim.get(t, 0.0), 4)}
            for t in set(real) | set(sim)]
    return sorted(rows, key=lambda r: (-max(r["sim"], r["real"]),
                                       r["ticker"]))


# -- the orders ------------------------------------------------------------------
def refused(entry: dict) -> bool:
    return entry.get("note", "").startswith("not accepted")


def public_note(entry: dict) -> str:
    """What became of an order, in the bridge's own words; for a refusal
    only IBKR's error codes, never its message."""
    note = entry.get("note", "")
    if entry.get("status") == "unknown market":
        return "IBKR does not know this market"
    if refused(entry):
        codes = sorted(set(re.findall(r"\(code (\d+)\)", note)), key=int)
        return ("IBKR did not accept the order"
                + (f" (code {', '.join(codes)})" if codes else ""))
    return note if SENT_NOTE.fullmatch(note) else "sent"


def order_part(run: dict) -> dict:
    """This run's orders: planned, sent, refused, and the markets kept in
    cash with the reason."""
    orders = [{"ticker": s["ticker"], "holds_as": holds_as(s["ticker"]),
               "side": s["side"], "quantity": s["quantity"],
               "value": rounded(s.get("value"), 2),
               "outcome": "refused" if refused(s) else "sent",
               "note": public_note(s)}
              for s in run.get("sent", [])]
    currency = [{"currency": c["currency"], "side": c["side"],
                 "amount": c["amount"], "value": rounded(c.get("value"), 2),
                 "outcome": "refused" if refused(c) else "sent"}
                for c in run.get("currency", [])]
    kept = ([{"ticker": t, "holds_as": holds_as(t), "reason": KID}
             for t in run.get("kept_in_cash", [])]
            + [{"ticker": t, "holds_as": holds_as(t), "reason": NO_PRICE}
               for t in run.get("no_price", [])])
    return {"planned": len(run.get("plan", [])),
            "sent": sum(o["outcome"] == "sent" for o in orders),
            "refused": sum(o["outcome"] == "refused" for o in orders),
            "orders": orders, "currency": currency,
            "kept_in_cash": sorted(kept, key=lambda k: k["ticker"])}


def fill_outcome(order: dict, held: dict[str, int]) -> str:
    """Whether an order filled, judged from the holding the next morning:
    it reached its target, moved part of the way, or did not move."""
    start, goal = order["now"], order["target"]
    moved = held.get(order["ticker"], 0) - start
    if moved * (goal - start) <= 0:
        return "not filled"
    return "filled" if abs(moved) >= abs(goal - start) else "partly filled"


def previous_part(since: str | None, before: dict[str, dict],
                  held: dict[str, int] | None) -> dict | None:
    """What became of the orders the last earlier run sent."""
    if since is None or held is None:
        return None
    orders = [{"ticker": t, "holds_as": holds_as(t), "side": o["side"],
               "quantity": o["quantity"],
               "outcome": fill_outcome({**o, "ticker": t}, held)}
              for t, o in sorted(before.items())]
    count = {k: sum(o["outcome"] == k for o in orders)
             for k in ("filled", "partly filled", "not filled")}
    return {"date": since, "sent": len(orders), "filled": count["filled"],
            "partly_filled": count["partly filled"],
            "not_filled": count["not filled"], "orders": orders}


# -- the summary -----------------------------------------------------------------
def empty(agent_id: str) -> dict:
    return {"schema": SCHEMA, "generated_utc": None, "about": "",
            "agent": agent_id, "agent_name": None, "account_currency": None,
            "since": None, "latest": None, "history": []}


def tracking_error(history: list[dict], days: int = 60) -> float | None:
    """How much the daily differences swing, scaled to a year: the usual
    measure of how closely a copy follows (0 = perfectly)."""
    diffs = [r["difference"] for r in history[-days:]
             if r.get("difference") is not None]
    if len(diffs) < 5:
        return None
    return statistics.stdev(diffs) * 252 ** 0.5


def update(summary: dict, run: dict, payload: dict, day: date,
           since: str | None, before: dict[str, dict],
           keep_days: int = 750, now: datetime | None = None) -> dict:
    """``summary`` with this morning's run added (a second run on the same
    day replaces the first)."""
    agent_id = run["agent"]
    real = real_side(run, payload)
    sim = sim_side(payload, agent_id)
    orders = order_part(run)
    previous = previous_part(since, before, run.get("held"))
    today = day.isoformat()
    # Both values belong to the same close only when the results are of
    # the last weekday before the run (not when the evening run failed).
    same = run["results_of"] == bridge.previous_weekday(day).isoformat()
    history = [r for r in summary.get("history", []) if r["date"] < today]
    if previous:
        for r in history:
            if r["date"] == previous["date"]:
                r.update(filled=previous["filled"],
                         partly_filled=previous["partly_filled"],
                         not_filled=previous["not_filled"])
    gap = holdings_gap(real["weights"], sim["weights"])
    row = {"date": today, "results_of": run["results_of"],
           "same_close": same,
           "value": rounded(real["value"], 2),
           "value_chf": rounded(real["value_chf"], 2),
           "cash_chf": rounded(real["cash_chf"], 2),
           "invested": rounded(real["invested"], 4),
           "positions": real["positions"],
           "sim_value_chf": rounded(sim["value_chf"], 2),
           "sim_invested": rounded(sim["invested"], 4),
           "sim_positions": sim["positions"],
           "return": None, "sim_return": None, "difference": None,
           "return_total": None, "sim_return_total": None,
           "difference_total": None,
           "holdings_gap": round(gap, 4),
           "planned": orders["planned"], "sent": orders["sent"],
           "refused": orders["refused"],
           "kept_in_cash": len(orders["kept_in_cash"]),
           "filled": None, "partly_filled": None, "not_filled": None}
    start = summary.get("since")
    if same and real["value_chf"]:
        # Returns run from the last row measured at one close for both.
        base = next((r for r in reversed(history)
                     if r.get("return_total") is not None), None)
        if base is None:
            start = today
            row.update(return_total=0.0, sim_return_total=0.0,
                       difference_total=0.0)
        else:
            mine = row["value_chf"] / base["value_chf"] - 1
            theirs = row["sim_value_chf"] / base["sim_value_chf"] - 1
            total = (1 + base["return_total"]) * (1 + mine) - 1
            sim_total = (1 + base["sim_return_total"]) * (1 + theirs) - 1
            row.update(**{"return": round(mine, 6),
                          "sim_return": round(theirs, 6),
                          "difference": round(mine - theirs, 6),
                          "return_total": round(total, 6),
                          "sim_return_total": round(sim_total, 6),
                          "difference_total": round(total - sim_total, 6)})
    history = (history + [row])[-keep_days:]
    now = now or datetime.now(timezone.utc)
    return {
        "schema": SCHEMA,
        "generated_utc": now.isoformat(timespec="seconds"),
        "about": ABOUT.format(name=sim["name"]),
        "agent": agent_id, "agent_name": sim["name"],
        "account_currency": real["currency"], "since": start,
        "latest": {
            "date": today, "results_of": run["results_of"],
            "same_close": same,
            "real": {"value": row["value"], "currency": real["currency"],
                     "value_chf": row["value_chf"],
                     "cash": rounded(real["cash"], 2),
                     "cash_chf": row["cash_chf"],
                     "invested": row["invested"],
                     "positions": real["positions"],
                     "watchlist_positions": real["watchlist_positions"]},
            "sim": {"value_chf": row["sim_value_chf"],
                    "cash_chf": rounded(sim["cash_chf"], 2),
                    "invested": row["sim_invested"],
                    "positions": sim["positions"]},
            "tracking": {
                **{k: row[k] for k in ("return", "sim_return", "difference",
                                       "return_total", "sim_return_total",
                                       "difference_total")},
                "since": start, "holdings_gap": row["holdings_gap"],
                "tracking_error_yearly": rounded(tracking_error(history), 6)},
            "weights": weight_table(real["weights"], sim["weights"]),
            "orders": orders,
            "previous_orders": previous,
        },
        "history": history,
    }


# -- keeping it public -----------------------------------------------------------
def settings(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a shell settings file, quotes removed."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    found = {}
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            found[key.strip()] = value.strip().strip("\"'")
    return found


def private_values(account: str | None, root: Path = ROOT) -> list[str]:
    """The account ID and every login detail and token on this computer:
    none of them may appear in the public file."""
    found = [account or ""]
    for path in (root / "server" / ".env", root / "ibkr_morning.env"):
        values = settings(path)
        found += [values.get(k, "") for k in PRIVATE_SETTINGS]
    try:
        found.append((root / "server" / "ib_password.txt").read_text())
    except OSError:
        pass
    found += [os.environ.get(k, "") for k in PRIVATE_SETTINGS]
    # Very short values (or short numbers) would match by chance.
    return sorted({v.strip() for v in found
                   if len(v.strip()) >= (7 if v.strip().isdigit() else 4)})


def check_public(text: str, private: list[str]) -> None:
    """Raise ``PrivateDataError`` if ``text`` shows anything personal. The
    error does not say what, so it cannot leak into a log or message."""
    if any(v in text for v in private) or ACCOUNT_ID.search(text):
        raise PrivateDataError(
            "The summary would show the account ID or a login detail, so it "
            "was not written.")


def write(summary: dict, path: Path, private: list[str]) -> None:
    """Check ``summary`` and save it (in one step, so a reader never sees
    half a file)."""
    text = json.dumps(summary, indent=1, ensure_ascii=False) + "\n"
    check_public(text, private)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def published_url(root: Path = ROOT) -> str | None:
    """Where ``server/publish.sh`` puts the file (``PUBLISH_REPO`` and
    ``PUBLISH_BRANCH`` in ``ibkr_morning.env``), as a raw GitHub address."""
    values = settings(root / "ibkr_morning.env")
    found = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)"
                         r"([\w.-]+/[\w.-]+?)(?:\.git)?",
                         values.get("PUBLISH_REPO", ""))
    if not found:
        return None
    branch = values.get("PUBLISH_BRANCH") or "ibkr-data"
    return (f"https://raw.githubusercontent.com/{found.group(1)}/{branch}/"
            f"{OUT.name}")


def load_summary(path: Path, agent_id: str, root: Path = ROOT) -> dict:
    """The summary so far: this computer's copy or, when that is gone (a
    new server), the published one, so the history carries on."""
    if path.exists():
        found = json.loads(path.read_text())
    else:
        url, found = published_url(root), None
        try:
            if url:
                with urllib.request.urlopen(
                        url, timeout=30, context=bridge.https_context()) as r:
                    found = json.loads(r.read())
        except (OSError, ValueError):      # also: nothing published yet
            found = None
        if found:
            print(f"Carrying on the history published at {url}.")
    if (not isinstance(found, dict) or found.get("schema") != SCHEMA
            or found.get("agent") != agent_id):
        return empty(agent_id)          # another agent: a fresh history
    return found


def main() -> None:
    p = config.IBKR_PARAMS
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", default=p["results_url"],
                        help="URL or file of paper.json")
    parser.add_argument("--out", type=Path, default=OUT,
                        help=f"the summary file (default {OUT})")
    args = parser.parse_args()

    today = date.today()
    run = latest_run(today, bridge.LOG_DIR)
    if run is None:
        raise SystemExit("No run placed its orders today, so there is "
                         "nothing new to show.")
    payload = bridge.load_results(args.results)
    if payload["last"] != run["results_of"]:
        raise SystemExit(f"The results are now of {payload['last']}, not of "
                         f"{run['results_of']} as this morning's run.")
    since, before = bridge.last_sent(today)
    summary = update(load_summary(args.out, run["agent"]), run, payload,
                     today, since, before, p["summary_days"])
    write(summary, args.out, private_values(run.get("account")))
    track = summary["latest"]["tracking"]
    gap = (f"{track['difference_total']:+.2%} since {track['since']}"
           if track["difference_total"] is not None
           else "no comparison today (the results are not of the last "
                "close)")
    print(f"Summary for the website saved to {args.out}: paper account "
          f"{summary['latest']['real']['value_chf']:,.0f} CHF against "
          f"the simulation, {gap}.")


if __name__ == "__main__":
    main()
