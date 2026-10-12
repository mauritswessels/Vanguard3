"""Copy one agent's holdings into an Interactive Brokers PAPER account.

Runs on your own computer, next to Trader Workstation (TWS) logged in to
Paper Trading with the API switched on, or on a cloud server next to IB
Gateway (see ``server/setup.sh``)::

    python ibkr_bridge.py              # shows the plan, sends nothing
    python ibkr_bridge.py --send       # places the orders in the paper account
    python ibkr_bridge.py --port 4002  # talks to IB Gateway instead of TWS

What it does:

1. downloads the latest results (``docs/data/paper.json``) from GitHub,
2. works out what the chosen agent will hold once its pending orders fill,
   as a share of its account (``IBKR_PARAMS["agent"]`` in ``config.py``),
3. reads the paper account's value and positions through TWS,
4. sends market orders so the paper account holds the same shares, scaled
   to its own size. Orders sent while a market is closed wait for its next
   open, just like the simulator's fills.

Safety:

* Only paper accounts (account IDs starting with "D") are ever traded.
* Only markets on the Vanguard3 watchlist are touched; anything else in the
  account is left alone.
* Its own unfilled orders from an earlier run are cancelled first, so
  running it twice does not double the orders.

Needs ``pip install -r requirements-ibkr.txt`` (the ``ib_async`` library,
and ``certifi`` for checking GitHub's security certificate).
Every run is written to ``ibkr_logs/``.
"""

from __future__ import annotations

import argparse
import json
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import config

LOG_DIR = Path(__file__).resolve().parent / "ibkr_logs"

#: Yahoo suffix -> (IBKR primary exchange, currency).
EXCHANGES = {".SW": ("EBS", "CHF"), ".DE": ("IBIS", "EUR"),
             ".PA": ("SBF", "EUR"), ".AS": ("AEB", "EUR")}

#: TWS messages about its own data connections, not about our orders.
QUIET_CODES = {2104, 2106, 2107, 2108, 2119, 2158}


# -- what the agent holds ------------------------------------------------------
def ib_symbol(ticker: str) -> tuple[str, str, str]:
    """IBKR ``(symbol, currency, primary exchange)`` of a watchlist ticker."""
    for suffix, (exchange, currency) in EXCHANGES.items():
        if ticker.endswith(suffix):
            return ticker[:-len(suffix)], currency, exchange
    return ticker.replace("-", " "), config.WATCHLIST.get(ticker, "USD"), ""


def universe_index() -> dict[tuple[str, str], str]:
    """``(IBKR symbol, currency) -> watchlist ticker``."""
    return {ib_symbol(t)[:2]: t for t in config.WATCHLIST}


def https_context() -> ssl.SSLContext:
    """The computer's certificates plus certifi's, when installed. Python
    from python.org on a Mac has none of its own until its 'Install
    Certificates' step has run."""
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return context
    context.load_verify_locations(cafile=certifi.where())
    return context


def load_results(source: str) -> dict:
    """The dashboard results, from a URL or a local file."""
    if not source.startswith("http"):
        return json.loads(Path(source).read_text())
    try:
        with urllib.request.urlopen(source, timeout=30,
                                    context=https_context()) as r:
            return json.loads(r.read())
    except OSError as exc:
        # URLError wraps the real cause; HTTPError says it best itself.
        cause = exc.reason if type(exc) is urllib.error.URLError else exc
        if isinstance(cause, ssl.SSLCertVerificationError):
            raise SystemExit(
                "Could not download the agents' results: Python could not "
                "check GitHub's security certificate. Fix it once with\n"
                "  .venv/bin/pip install -r requirements-ibkr.txt\n"
                "and run the bridge again.")
        raise SystemExit("Could not download the agents' results from "
                         f"GitHub ({cause}). Check the internet connection "
                         "and try again.")


def chf_per_unit(payload: dict, currency: str) -> float | None:
    """CHF price of one unit of ``currency`` at the last close."""
    if currency == "CHF":
        return 1.0
    series = payload.get("fx", {}).get(currency)
    return float(series[-1][1]) if series else None


def price_chf(payload: dict, ticker: str) -> float | None:
    """Last close of ``ticker`` in CHF."""
    series = payload["prices"].get(ticker)
    rate = chf_per_unit(payload, payload["currencies"].get(ticker, ""))
    return float(series[-1][1]) * rate if series and rate else None


def agent_weights(payload: dict, agent_id: str
                  ) -> tuple[dict | None, dict[str, float]]:
    """Share of the agent's account in each market once its pending orders
    fill (they fill at the next open)."""
    agent = next((a for a in payload["agents"] if a["id"] == agent_id), None)
    if agent is None:
        return None, {}
    qty = {p["ticker"]: p["quantity"] for p in agent["positions"]}
    for o in agent.get("pending_orders", []):
        sign = 1 if o["side"] == "BUY" else -1
        qty[o["ticker"]] = max(qty.get(o["ticker"], 0) + sign * o["quantity"],
                               0)
    equity = agent["stats"]["final_equity_chf"]
    weights = {}
    for t, q in qty.items():
        price = price_chf(payload, t)
        if q > 0 and price:
            weights[t] = q * price / equity
    return agent, weights


def plan_orders(weights: dict[str, float], held: dict[str, int],
                net_liq: float, base: str, payload: dict,
                min_trade_pct: float) -> list[dict]:
    """Orders that bring the paper account to the agent's shares.

    ``held`` are the paper account's watchlist positions in shares,
    ``net_liq`` its value in its base currency ``base``. Changes smaller
    than ``min_trade_pct`` of the account are skipped to save fees, except
    full exits.
    """
    rate = chf_per_unit(payload, base)
    if not rate:
        raise ValueError(f"No {base}/CHF rate in the results: the bridge "
                         "works with accounts in CHF, USD or EUR")
    orders = []
    for t in sorted(set(weights) | set(held)):
        price = price_chf(payload, t)
        if not price:
            continue
        unit = price / rate                    # one share, account currency
        target = int(weights.get(t, 0.0) * net_liq // unit)
        now = held.get(t, 0)
        diff = target - now
        if diff == 0 or (target > 0
                         and abs(diff) * unit < min_trade_pct * net_liq):
            continue
        orders.append({"ticker": t, "side": "BUY" if diff > 0 else "SELL",
                       "quantity": abs(diff), "now": now, "target": target,
                       "value": round(abs(diff) * unit, 2)})
    # Sells first so their money is there for the buys.
    orders.sort(key=lambda o: (o["side"] != "SELL", -o["value"]))
    return orders


# -- talking to TWS ------------------------------------------------------------
def account_value(ib, account: str) -> tuple[float, str]:
    """Net liquidation value and base currency of ``account``."""
    for v in ib.accountSummary(account):
        if v.tag == "NetLiquidation":
            return float(v.value), v.currency
    raise RuntimeError("TWS did not report the account value")


def ib_holdings(ib, account: str) -> dict[str, int]:
    """Watchlist positions of ``account`` in shares; others are ignored."""
    index = universe_index()
    held = {}
    for pos in ib.positions(account):
        c = pos.contract
        ticker = index.get((c.symbol, c.currency))
        if c.secType == "STK" and ticker and pos.position:
            held[ticker] = int(pos.position)
    return held


def status_text(trade, errors: list[str]) -> str:
    """Plain-English state of one sent order."""
    s = trade.orderStatus
    if s.status == "Filled":
        return f"filled at {s.avgFillPrice:.2f}"
    if s.filled:
        return f"{s.filled:g} filled so far, the rest is waiting"
    if s.status == "PreSubmitted":
        return "waiting for the market to open"
    if s.status in ("Submitted", "PendingSubmit"):
        return "sent, waiting to be filled"
    why = "; ".join(errors) or s.status
    return f"not accepted: {why}"


def run(ib, api, payload: dict, p: dict, send: bool = False,
        say=print) -> dict:
    """Plan (and with ``send`` place) the orders. ``ib`` is a connected
    ``ib_async.IB``; ``api`` provides ``Stock`` and ``MarketOrder``."""
    agent, weights = agent_weights(payload, p["agent"])
    if agent is None:
        say(f"No agent '{p['agent']}' in the results yet (agents just added "
            "join on the next evening run). Nothing to do.")
        return {"status": "no agent"}
    accounts = [a for a in ib.managedAccounts() if a.startswith("D")]
    if not accounts:
        raise SystemExit("TWS is logged in to a live account. The bridge "
                         "only trades paper accounts: log in to TWS with "
                         "Paper Trading selected.")
    account = accounts[0]
    net_liq, base = account_value(ib, account)
    held = ib_holdings(ib, account)
    plan = plan_orders(weights, held, net_liq, base, payload,
                       p["min_trade_pct"])

    say(f"Copying {agent['name']}: {len(weights)} markets, results of the "
        f"{payload['last']} close.")
    say(f"IBKR paper account {account}: {net_liq:,.2f} {base}, "
        f"{len(held)} watchlist positions.")
    if not plan:
        say("Already matches the agent. No orders needed.")
    for o in plan:
        say(f"  {o['side']:<4} {o['quantity']:>6} {o['ticker']:<8} "
            f"(holds {o['now']}, target {o['target']}, "
            f"about {o['value']:,.0f} {base})")
    result = {"account": account, "base": base, "net_liq": net_liq,
              "agent": p["agent"], "results_of": payload["last"],
              "plan": plan, "sent": []}

    ours = [t for t in ib.reqAllOpenOrders()
            if t.order.orderRef == p["order_ref"] and not t.isDone()]
    if not send:
        if ours:
            say(f"{len(ours)} orders from an earlier run are still waiting; "
                "--send replaces them.")
        say("Dry run: nothing was sent. Run again with --send to place "
            "these orders.")
        result["status"] = "dry run"
        return result

    for t in ours:
        ib.cancelOrder(t.order)
    if ours:
        ib.sleep(2)
        if any(not t.isDone() for t in ours):
            raise SystemExit("Orders from an earlier run could not be "
                             "cancelled yet. Try again in a minute.")

    errors: dict[int, list[str]] = {}

    def on_error(req_id, code, message, contract=None):
        if code not in QUIET_CODES:
            errors.setdefault(req_id, []).append(f"{message} (code {code})")

    ib.errorEvent += on_error
    sent = []
    for o in plan:
        symbol, currency, exchange = ib_symbol(o["ticker"])
        contract = api.Stock(symbol, "SMART", currency,
                             primaryExchange=exchange)
        found = ib.qualifyContracts(contract)
        if not found or found[0] is None:
            say(f"  {o['ticker']}: IBKR does not know this market, skipped")
            result["sent"].append({**o, "status": "unknown market",
                                   "note": "not accepted: unknown market"})
            continue
        order = api.MarketOrder(o["side"], o["quantity"], tif="DAY",
                                orderRef=p["order_ref"], account=account)
        sent.append((o, ib.placeOrder(contract, order)))
    ib.sleep(3)
    for o, trade in sent:
        text = status_text(trade, errors.get(trade.order.orderId, []))
        say(f"  {o['side']} {o['quantity']} {o['ticker']}: {text}")
        result["sent"].append({**o, "status": trade.orderStatus.status,
                               "note": text})
    refused = [s["ticker"] for s in result["sent"]
               if s["note"].startswith("not accepted")]
    if not plan:
        say("Done: no orders needed.")
    else:
        say(f"Done: {len(plan) - len(refused)} of {len(plan)} orders placed"
            + (f"; not accepted: {', '.join(refused)}" if refused else "")
            + ".")
    result["status"] = "sent"
    return result


def not_reachable(port: int, exc: Exception) -> str:
    """What to check when nothing answers on the API port. Its last line is
    what the morning run's notification shows."""
    why = str(exc) or type(exc).__name__
    if port in (4001, 4002):      # IB Gateway, as on the cloud server
        return (f"Could not reach IB Gateway on port {port} ({why}).\n"
                "Is IB Gateway running and logged in? Its log: "
                "docker logs --tail 30 ib-gateway")
    return (f"Could not reach TWS on port {port} ({why}).\nIs TWS open and "
            "logged in to Paper Trading, with 'Enable ActiveX and Socket "
            "Clients' ticked in the API settings?")


def write_log(result: dict) -> Path:
    """Append this run to ``ibkr_logs/<today>.json``."""
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"{date.today():%Y-%m-%d}.json"
    runs = json.loads(path.read_text()) if path.exists() else []
    runs.append({"time": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), **result})
    path.write_text(json.dumps(runs, indent=1))
    return path


def main() -> None:
    p = dict(config.IBKR_PARAMS)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--send", action="store_true",
                        help="place the orders (default: only show the plan)")
    parser.add_argument("--agent", default=p["agent"],
                        help="agent to copy, e.g. manager, trend, news "
                             f"(default {p['agent']})")
    parser.add_argument("--port", type=int, default=p["port"],
                        help=f"API port (default {p['port']}, TWS; "
                             "IB Gateway: 4002)")
    parser.add_argument("--results", default=p["results_url"],
                        help="URL or file of paper.json")
    args = parser.parse_args()
    p.update(agent=args.agent, port=args.port)

    try:
        import ib_async as api
    except ImportError:
        raise SystemExit("The IBKR library is missing. Install it with:\n"
                         "  pip install -r requirements-ibkr.txt")
    payload = load_results(args.results)
    age = (date.today() - date.fromisoformat(payload["last"])).days
    if age > 4:
        print(f"Warning: the newest results are from {payload['last']}. "
              "Check that the evening runs are working.")

    ib = api.IB()
    try:
        ib.connect(p["host"], p["port"], clientId=p["client_id"], timeout=15)
    except Exception as exc:
        raise SystemExit(not_reachable(p["port"], exc))
    try:
        result = run(ib, api, payload, p, send=args.send)
    finally:
        ib.disconnect()
    print(f"Saved to {write_log(result)}")


if __name__ == "__main__":
    main()
