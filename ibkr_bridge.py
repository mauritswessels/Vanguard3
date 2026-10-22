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
   open, just like the simulator's fills. US shares get a limit order
   5% from the last close instead (``us_limit_room``): IBKR cancels US
   market orders sent before the open from an account without paid US
   prices, and a limit order placed then still fills at the opening price.
5. first changes francs into the dollars and euros those buys need (and
   what is left over from sells back into francs), so the account never
   borrows a currency, just like the simulator, which pays in francs.

IBKR does not sell US-listed funds to Swiss and EU private investors, so a
US fund the agent holds is bought as its European version listed in
``config.IBKR_STAND_INS`` (e.g. CSPX in London for SPY). The evening run
publishes those funds' prices with the results.

Safety:

* Only paper accounts (account IDs starting with "D") are ever traded.
* Only markets on the Vanguard3 watchlist are touched; anything else in the
  account is left alone.
* Its own unfilled orders from an earlier run are cancelled first, so
  running it twice does not double the orders.
* It sends nothing when the agent's targets add up to more than its account
  (``IBKR_PARAMS["max_invested"]``): such results must be wrong.
* It asks IB Gateway for a fresh list of positions, and sends nothing when
  that list is empty while the account says it holds positions (just after
  a restart, the list can still be loading; it would then buy everything a
  second time).
* Markets IBKR refuses to sell to this account (a fund without a "KID",
  the key information sheet European and Swiss private investors must get)
  are remembered in ``ibkr_logs/blocked.json`` and left in cash from then
  on. Delete that file to try them again.

Needs ``pip install -r requirements-ibkr.txt`` (the ``ib_async`` library,
and ``certifi`` for checking GitHub's security certificate).
Every run is written to ``ibkr_logs/``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import signal
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config

LOG_DIR = Path(__file__).resolve().parent / "ibkr_logs"

#: Yahoo suffix -> (IBKR primary exchange, currency).
EXCHANGES = {".SW": ("EBS", "CHF"), ".DE": ("IBIS", "EUR"),
             ".PA": ("SBF", "EUR"), ".AS": ("AEB", "EUR")}

#: TWS messages about its own data connections, not about our orders.
QUIET_CODES = {2104, 2106, 2107, 2108, 2119, 2158}

#: Words in IBKR's refusal of a product it does not sell to this account.
BLOCKED_HINTS = ("KID", "key information", "PRIIP")

#: Exit code when the bridge refuses to trade: trying again won't help.
REFUSED = 3

#: IBKR names a currency pair with the earlier of its two currencies here
#: first (EUR.USD, USD.CHF, ...).
PAIR_ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]


# -- what the agent holds ------------------------------------------------------
def ib_symbol(ticker: str) -> tuple[str, str, str]:
    """IBKR ``(symbol, currency, primary exchange)`` of a watchlist ticker;
    a US fund maps to its European version (``config.IBKR_STAND_INS``)."""
    if ticker in config.IBKR_STAND_INS:
        symbol, exchange, currency, _ = config.IBKR_STAND_INS[ticker]
        return symbol, currency, exchange
    for suffix, (exchange, currency) in EXCHANGES.items():
        if ticker.endswith(suffix):
            return ticker[:-len(suffix)], currency, exchange
    return ticker.replace("-", " "), config.WATCHLIST.get(ticker, "USD"), ""


def universe_index() -> dict[tuple[str, str], str]:
    """``(IBKR symbol, currency) -> watchlist ticker``."""
    return {ib_symbol(t)[:2]: t for t in config.WATCHLIST}


def label(ticker: str) -> str:
    """The ticker, plus what IBKR holds for it when that is a stand-in."""
    if ticker in config.IBKR_STAND_INS:
        return f"{ticker} (as {ib_symbol(ticker)[0]})"
    return ticker


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


def ib_price(payload: dict, ticker: str) -> tuple[float, str] | None:
    """Last close of what the IBKR account holds for ``ticker`` (its
    European version for a US fund), and the currency of that price."""
    if ticker in config.IBKR_STAND_INS:
        s = payload.get("stand_ins", {}).get(ticker)
        return (float(s["price"]), s["currency"]) if s else None
    series = payload["prices"].get(ticker)
    currency = payload["currencies"].get(ticker)
    return (float(series[-1][1]), currency) if series and currency else None


def agent_weights(payload: dict, agent_id: str
                  ) -> tuple[dict | None, dict[str, float]]:
    """Share of the agent's account in each market once its pending orders
    fill (they fill at the next open)."""
    agent = next((a for a in payload["agents"] if a["id"] == agent_id), None)
    if agent is None:
        return None, {}
    qty = {p["ticker"]: p["quantity"] for p in agent["positions"]}
    # The simulator keeps one waiting order per market, its newest; older
    # results could hold several, which must not be added up.
    newest = {o["ticker"]: o for o in agent.get("pending_orders", [])}
    for o in newest.values():
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
                min_trade_pct: float, keep: frozenset = frozenset()
                ) -> list[dict]:
    """Orders that bring the paper account to the agent's shares.

    ``held`` are the paper account's watchlist positions in shares,
    ``net_liq`` its value in its base currency ``base``. Changes smaller
    than ``min_trade_pct`` of the account are skipped to save fees, except
    full exits. A market with no price in the results can't be sized: it
    is left as it is, unless the agent no longer holds it (and it is not
    in ``keep``, the markets the agent holds but that have no price):
    then it is sold in full at the market, which needs no price.
    """
    rate = chf_per_unit(payload, base)
    if not rate:
        raise ValueError(f"No {base}/CHF rate in the results: the bridge "
                         "works with accounts in CHF, USD or EUR")
    orders = []
    for t in sorted(set(weights) | set(held)):
        quote = ib_price(payload, t)
        to_chf = chf_per_unit(payload, quote[1]) if quote else None
        if not to_chf:
            _, currency, exchange = ib_symbol(t)
            # A US share needs a limit, and so a price (see run()).
            if (held.get(t, 0) > 0 and t not in weights and t not in keep
                    and exchange):
                orders.append({"ticker": t, "side": "SELL",
                               "quantity": held[t], "now": held[t],
                               "target": 0, "value": 0.0,
                               "currency": currency, "price": None})
            continue
        price, currency = quote
        unit = price * to_chf / rate           # one share, account currency
        target = int(weights.get(t, 0.0) * net_liq // unit)
        now = held.get(t, 0)
        diff = target - now
        if diff == 0 or (target > 0
                         and abs(diff) * unit < min_trade_pct * net_liq):
            continue
        orders.append({"ticker": t, "side": "BUY" if diff > 0 else "SELL",
                       "quantity": abs(diff), "now": now, "target": target,
                       "value": round(abs(diff) * unit, 2),
                       "currency": currency, "price": price})
    # Sells first so their money is there for the buys.
    orders.sort(key=lambda o: (o["side"] != "SELL", -o["value"]))
    return orders


def limit_price(side: str, last: float, room: float) -> float:
    """Limit for a US share: ``room`` (a share of the price) above the last
    close for a buy, below it for a sell, in whole cents. Like a market
    order it fills at the opening price, unless the price jumps by more
    than ``room`` overnight; then it waits for a better price that day
    and, if none comes, the next run sends it again."""
    cents = last * 100 * (1 + room if side == "BUY" else 1 - room)
    cents = round(cents, 6)                 # 19611.000000001 is 19611
    return (math.ceil(cents) if side == "BUY" else math.floor(cents)) / 100


def currency_plan(plan: list[dict], cash: dict[str, float], base: str,
                  payload: dict, min_value: float) -> list[dict]:
    """Currency to change so that, once the orders fill, no foreign
    currency is borrowed and none is left over: dollars and euros for the
    buys (plus any already borrowed) are bought with the account's own
    currency, what sells and earlier trades leave over is changed back.
    ``cash`` is the cash per currency now; changes worth less than
    ``min_value`` (account currency) are skipped."""
    flow: dict[str, float] = {}
    for o in plan:
        if o["currency"] != base and o["price"] is not None:
            value = o["quantity"] * o["price"]
            flow[o["currency"]] = flow.get(o["currency"], 0.0) + (
                value if o["side"] == "BUY" else -value)
    to_base = chf_per_unit(payload, base)
    out = []
    for ccy in sorted((set(flow) | set(cash)) - {base}):
        rate = chf_per_unit(payload, ccy)
        if not rate or not to_base or ccy not in PAIR_ORDER:
            continue
        after = cash.get(ccy, 0.0) - flow.get(ccy, 0.0)
        value = abs(after) * rate / to_base
        if value < min_value:
            continue
        # A little extra when buying, a little kept when selling: prices
        # move before the orders fill.
        amount = (math.ceil(-after * 1.01) if after < 0
                  else math.floor(after * 0.99))
        out.append({"currency": ccy, "side": "BUY" if after < 0 else "SELL",
                    "amount": amount, "value": round(value, 2)})
    return out


def forex_order(currency: str, base: str, side: str, amount: int,
                payload: dict) -> tuple[str, str, int]:
    """IBKR pair, action and quantity that buy (or sell) ``amount`` of
    ``currency`` for the account's ``base`` currency."""
    if PAIR_ORDER.index(currency) < PAIR_ORDER.index(base):
        return currency + base, side, amount
    # The pair is quoted the other way round: trade the base currency.
    per_unit = chf_per_unit(payload, currency) / chf_per_unit(payload, base)
    return (base + currency, "SELL" if side == "BUY" else "BUY",
            math.ceil(amount * per_unit))


# -- checks ------------------------------------------------------------------
def previous_weekday(day: date) -> date:
    """The weekday before ``day``: the close whose results the morning run
    should have."""
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def stale_warning(payload: dict, today: date) -> str | None:
    """A warning when last night's results are missing."""
    last = date.fromisoformat(payload["last"])
    expected = previous_weekday(today)
    if last >= expected:
        return None
    return (f"Warning: the newest results are from {last:%a %d %b}, not "
            f"{expected:%a %d %b}. Unless that was a holiday, the evening "
            "run did not finish; this copies the older results.")


def too_much(weights: dict[str, float], limit: float) -> str | None:
    """Why the agent's targets cannot be right, if they add up to more than
    ``limit`` times its account."""
    total = sum(weights.values())
    if total <= limit:
        return None
    return (f"The agent's targets add up to {total:.0%} of its account, "
            "which can't be right, so no orders were sent. Check the "
            "evening run's results.")


def blocked_markets(path: Path | None = None) -> dict[str, str]:
    """Markets IBKR refused to sell to this account: ``IBKR symbol ->
    reason``."""
    path = path or LOG_DIR / "blocked.json"
    return json.loads(path.read_text()) if path.exists() else {}


def remember_blocked(sent: list[dict], path: Path | None = None) -> list[str]:
    """Add the markets IBKR refused for good (no KID) to ``blocked.json``.
    Returns the new ones."""
    path = path or LOG_DIR / "blocked.json"
    blocked = blocked_markets(path)
    new = [s["ticker"] for s in sent
           if s["note"].startswith("not accepted")
           and any(h.lower() in s["note"].lower() for h in BLOCKED_HINTS)
           and ib_symbol(s["ticker"])[0] not in blocked]
    if new:
        for s in sent:
            if s["ticker"] in new:
                blocked[ib_symbol(s["ticker"])[0]] = s["note"]
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(blocked, indent=1))
    return new


def last_sent(today: date, log_dir: Path | None = None
              ) -> tuple[str | None, dict[str, dict]]:
    """Date and accepted orders of the last earlier run that sent orders."""
    log_dir = log_dir or LOG_DIR
    for path in sorted(log_dir.glob("????-??-??.json"), reverse=True):
        if path.stem >= today.isoformat():
            continue
        for run in reversed(json.loads(path.read_text())):
            if run.get("status") == "sent":
                return path.stem, {
                    s["ticker"]: s for s in run.get("sent", [])
                    if not s["note"].startswith("not accepted")}
    return None, {}


def not_filled(plan: list[dict], before: dict[str, dict]) -> list[str]:
    """Markets an earlier run already sent (most of) the same order for:
    that order did not fill."""
    return [o["ticker"] for o in plan
            if o["ticker"] in before
            and before[o["ticker"]]["side"] == o["side"]
            and o["quantity"] >= 0.5 * before[o["ticker"]]["quantity"]]


# -- talking to TWS ------------------------------------------------------------
def account_value(ib, account: str) -> tuple[float, str, float]:
    """Net liquidation value, base currency and value of all positions
    (in the base currency) of ``account``."""
    tags = {v.tag: v for v in ib.accountSummary(account)}
    if "NetLiquidation" not in tags:
        raise RuntimeError("TWS did not report the account value")
    net = tags["NetLiquidation"]
    gross = tags.get("GrossPositionValue")
    return (float(net.value), net.currency,
            float(gross.value) if gross else 0.0)


def cash_balances(ib, account: str) -> dict[str, float]:
    """Cash in each currency of ``account`` (below zero: borrowed)."""
    return {v.currency: float(v.value) for v in ib.accountValues(account)
            if v.tag == "CashBalance" and v.currency not in ("", "BASE")}


def ib_holdings(ib, account: str) -> tuple[dict[str, int], int]:
    """Watchlist positions of ``account`` in shares (others are ignored),
    and how many positions it has in all."""
    index = universe_index()
    held, count = {}, 0
    # A fresh request, not the list IB Gateway collected while starting:
    # that one can still be empty just after a restart.
    for pos in ib.reqPositions():
        if pos.account != account or not pos.position:
            continue
        count += 1
        c = pos.contract
        ticker = index.get((c.symbol, c.currency))
        if c.secType == "STK" and ticker:
            held[ticker] = int(pos.position)
    return held, count


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
    if s.status == "ValidationError":
        # Only a warning (e.g. "not sent to the exchange until 09:30"):
        # the order stays live.
        return "waiting for the market to open"
    why = "; ".join(errors) or s.status
    return f"not accepted: {why}"


def run(ib, api, payload: dict, p: dict, send: bool = False,
        say=print, today: date | None = None) -> dict:
    """Plan (and with ``send`` place) the orders. ``ib`` is a connected
    ``ib_async.IB``; ``api`` provides ``Stock``, ``Forex``,
    ``MarketOrder`` and ``LimitOrder``."""
    today = today or date.today()
    agent, weights = agent_weights(payload, p["agent"])
    if agent is None:
        say(f"No agent '{p['agent']}' in the results yet (agents just added "
            "join on the next evening run). Nothing to do.")
        return {"status": "no agent"}
    wrong = too_much(weights, p.get("max_invested", 1.05))
    if wrong:
        say(wrong)
        raise SystemExit(REFUSED)
    blocked = blocked_markets(p.get("blocked_file"))
    kept = sorted(t for t in weights if ib_symbol(t)[0] in blocked)
    unpriced = sorted(t for t in weights
                      if t not in kept and ib_price(payload, t) is None)
    weights = {t: w for t, w in weights.items()
               if t not in kept and t not in unpriced}

    accounts = [a for a in ib.managedAccounts() if a.startswith("D")]
    if not accounts:
        raise SystemExit("TWS is logged in to a live account. The bridge "
                         "only trades paper accounts: log in to TWS with "
                         "Paper Trading selected.")
    account = accounts[0]
    net_liq, base, gross = account_value(ib, account)
    held, count = ib_holdings(ib, account)
    if count == 0 and gross > 0.01 * net_liq:
        say(f"IBKR says the account holds {gross:,.0f} {base} in positions "
            "but listed none, so no orders were sent (they would buy "
            "everything a second time). Run it again in a few minutes.")
        raise SystemExit(REFUSED)
    plan = plan_orders(weights, held, net_liq, base, payload,
                       p["min_trade_pct"], keep=frozenset(unpriced))
    # IBKR cancels a US market order sent before the open when the account
    # has no paid US prices ("No market data on major exchange for market
    # order", code 202). A limit order needs none, and placed before the
    # open it fills at the opening price just the same.
    for o in plan:
        _, currency, exchange = ib_symbol(o["ticker"])
        if (p.get("us_limit_room") and currency == "USD" and not exchange
                and o["price"] is not None):
            o["limit"] = limit_price(o["side"], o["price"],
                                     p["us_limit_room"])
    fx = (currency_plan(plan, cash_balances(ib, account), base, payload,
                        p["min_trade_pct"] * net_liq)
          if p.get("change_currency") else [])

    say(f"Copying {agent['name']}: {len(weights)} markets, results of the "
        f"{payload['last']} close.")
    say(f"IBKR paper account {account}: {net_liq:,.2f} {base}, "
        f"{len(held)} watchlist positions.")
    if kept:
        say(f"Kept in cash: {', '.join(kept)} (IBKR does not sell these to "
            "this account; see ibkr_logs/blocked.json).")
    if unpriced:
        say(f"Kept in cash: {', '.join(unpriced)} (no price in the results "
            "for what IBKR holds instead; see the evening run's log).")
    for c in fx:
        why = ("for the buys, so nothing is borrowed" if c["side"] == "BUY"
               else f"left over, back into {base}")
        say(f"  {'Buy' if c['side'] == 'BUY' else 'Sell'} {c['amount']:,} "
            f"{c['currency']} (about {c['value']:,.0f} {base}): {why}")
    if not plan:
        say("Already matches the agent. No orders needed.")
    for o in plan:
        limit = f", limit {o['limit']:.2f} USD" if "limit" in o else ""
        value = (f"about {o['value']:,.0f} {base}" if o["price"] is not None
                 else "no price in the results, sold at the market")
        say(f"  {o['side']:<4} {o['quantity']:>6} {label(o['ticker']):<8} "
            f"(holds {o['now']}, target {o['target']}, {value}{limit})")
    since, before = last_sent(today, p.get("log_dir"))
    unfilled = not_filled(plan, before)
    if unfilled:
        say(f"Warning: the orders for {', '.join(unfilled)} sent on {since} "
            "did not fill; they are sent again.")
    # held, positions and gross only go to the log (ibkr_summary.py reads
    # them for the website); they change no order.
    result = {"account": account, "base": base, "net_liq": net_liq,
              "gross": gross, "positions": count, "held": held,
              "agent": p["agent"], "results_of": payload["last"],
              "plan": plan, "sent": [], "kept_in_cash": kept,
              "no_price": unpriced, "currency": fx, "not_filled": unfilled}

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
    # Currency first, so the buys find their dollars and euros.
    changes = []
    for c in fx:
        pair, action, qty = forex_order(c["currency"], base, c["side"],
                                        c["amount"], payload)
        contract = api.Forex(pair)
        found = ib.qualifyContracts(contract)
        if not found or found[0] is None:
            c["note"] = "not accepted: unknown currency pair"
            continue
        order = api.MarketOrder(action, qty, tif="DAY",
                                orderRef=p["order_ref"], account=account)
        changes.append((c, ib.placeOrder(contract, order)))
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
        kind = dict(tif="DAY", orderRef=p["order_ref"], account=account)
        if "limit" in o:                      # a US share, see above
            order = api.LimitOrder(o["side"], o["quantity"], o["limit"],
                                   **kind)
        else:
            order = api.MarketOrder(o["side"], o["quantity"], **kind)
        sent.append((o, ib.placeOrder(contract, order)))
    ib.sleep(3)
    for c, trade in changes:
        c["note"] = status_text(trade, errors.get(trade.order.orderId, []))
        say(f"  {'Buy' if c['side'] == 'BUY' else 'Sell'} {c['amount']:,} "
            f"{c['currency']}: {c['note']}")
    for o, trade in sent:
        text = status_text(trade, errors.get(trade.order.orderId, []))
        limit = f" (limit {o['limit']:.2f})" if "limit" in o else ""
        say(f"  {o['side']} {o['quantity']} {label(o['ticker'])}{limit}: "
            f"{text}")
        result["sent"].append({**o, "status": trade.orderStatus.status,
                               "note": text})
    refused = [s["ticker"] for s in result["sent"]
               if s["note"].startswith("not accepted")]
    kept += remember_blocked(result["sent"], p.get("blocked_file"))
    if not plan:
        done = "Done: no orders needed"
    else:
        done = (f"Done: {len(plan) - len(refused)} of {len(plan)} orders "
                "placed"
                + (f"; not accepted: {', '.join(refused)}" if refused else ""))
    changed = [f"{'bought' if c['side'] == 'BUY' else 'sold'} "
               f"{c['amount']:,} {c['currency']}" for c in fx
               if not c.get("note", "").startswith("not accepted")]
    if changed:
        done += "; currency: " + ", ".join(changed)
    if kept:
        done += (f"; kept in cash: {', '.join(sorted(kept))} (IBKR does not "
                 "sell these to this account)")
    if unpriced:
        done += f"; no price for: {', '.join(unpriced)}"
    say(done + ".")
    result["kept_in_cash"] = sorted(kept)
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


def not_answering(port: int, seconds: int) -> str:
    """What to say when the app is connected but stays silent: it is most
    likely logged out of IBKR. One line, for the morning notification."""
    if port in (4001, 4002):
        return (f"IB Gateway stopped answering for {seconds} seconds: it is "
                "probably logged out of IBKR (its log: docker logs --tail 30 "
                "ib-gateway)")
    return (f"TWS stopped answering for {seconds} seconds: is it still "
            "logged in to Paper Trading?")


@contextlib.contextmanager
def time_limit(seconds: int):
    """Raise ``TimeoutError`` if the block runs longer than ``seconds``
    (where the system has alarms: macOS and Linux)."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def stop(*_):
        raise TimeoutError

    old = signal.signal(signal.SIGALRM, stop)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


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
    stale = stale_warning(payload, date.today())
    if stale:
        print(stale)

    ib = api.IB()
    # A logged-out TWS or IB Gateway still accepts the connection but never
    # answers; without a limit the run would wait forever.
    ib.RequestTimeout = p["answer_seconds"]
    try:
        # A startup step that times out is an error, not just a log line.
        ib.connect(p["host"], p["port"], clientId=p["client_id"], timeout=15,
                   raiseSyncErrors=True)
    except Exception as exc:
        raise SystemExit(not_reachable(p["port"], exc))
    try:
        with time_limit(p["max_minutes"] * 60):
            result = run(ib, api, payload, p, send=args.send)
    except (TimeoutError, asyncio.TimeoutError):
        raise SystemExit(not_answering(p["port"], p["answer_seconds"]))
    finally:
        ib.disconnect()
    print(f"Saved to {write_log(result)}")


if __name__ == "__main__":
    main()
