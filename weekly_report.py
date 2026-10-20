"""Weekly report: Claude explains the week's racing in plain words.

Runs every Saturday morning (GitHub Actions, see
``.github/workflows/weekly-report.yml``)::

    python weekly_report.py            # add --dry-run to print the facts only

It reads the dashboard file (``docs/data/paper.json``), collects the facts of
the last five trading sessions for every account (return, trades and the
reasons given, what it holds now), asks Claude to explain them for someone
new to investing, and saves the text in ``docs/data/weekly.json``. The
dashboard shows the newest report and the workflow emails it as a GitHub
issue. Claude only writes about the facts it is given; it decides nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import pandas as pd

import config
from claude_api import call_claude

logger = logging.getLogger("vanguard3.weekly")

SESSIONS = 5            # one trading week
KEEP = 26               # reports kept in weekly.json (about half a year)

SYSTEM = """You write a short weekly report about a paper-trading project.
Several trading agents each manage 100,000 CHF of pretend money; the
reader is a student who is new to investing and coding, and his dad.

Write in plain, friendly English with no jargon (if a term is needed,
explain it in a few words). Use only the facts given: never invent numbers,
trades or reasons. Compare each agent with "Buy & Hold SPY" (simply holding
the S&P 500 fund) and the "Monkey" (random picks), which are the yardsticks.
One week is far too short to judge skill; say so once, briefly.

Format: plain text, no markdown, no headings, no bullet points. 4 to 6 short
paragraphs, 350 words at most:
1. One or two sentences on how the week went overall and what moved markets.
2. The agents that did best and worst, and why, using their trades and reasons.
3. Anything notable (an agent that did nothing and why, a learning or
   AI agent's behaviour, the News Analyst versus its Opus twin).
4. One simple lesson about investing that this week shows."""


def week_facts(payload: dict, sessions: int = SESSIONS) -> dict:
    """The facts of the last ``sessions`` trading days, per account."""
    days = [d for d, _ in payload["agents"][0]["equity"]]
    end = days[-1]
    start_i = max(len(days) - 1 - sessions, 0)
    start = days[start_i]
    first_day = days[start_i + 1] if start_i + 1 < len(days) else end
    agents = []
    for a in payload["agents"]:
        eq = dict(a["equity"])
        week = eq[end] / eq[start] - 1 if eq.get(start) else None
        trades = [{"date": t["date"], "side": t["side"], "ticker": t["ticker"],
                   "reason": (t.get("reason") or "")[:160],
                   **({"result_chf": round(t["pnl_chf"])}
                      if t["side"] == "SELL" and t.get("pnl_chf") is not None
                      else {})}
                  for t in a["trades"] if first_day <= t["date"] <= end]
        value = a["stats"]["final_equity_chf"]
        held = sorted(a["positions"], key=lambda p: -p["value_chf"])
        facts = {
            "name": a["name"],
            "style": a.get("style", ""),
            "week_return": round(week, 4) if week is not None else None,
            "since_start": round(a["stats"]["total_return"], 4),
            "trades_this_week": trades[-12:],
            "trade_count_this_week": len(trades),
            "cash_share": round(a["cash_chf"] / value, 3) if value else None,
            "biggest_holdings": [
                {"ticker": p["ticker"], "share": round(p["value_chf"] / value, 3),
                 "result": round(p["pnl_pct"], 3)} for p in held[:5]],
            "orders_waiting": len(a.get("pending_orders", [])),
        }
        ai = a.get("ai") or {}
        if ai.get("kind") == "news":
            facts["model"] = ai.get("model")
            facts["market_view"] = ai.get("market_view", "")
            facts["status"] = ai.get("status", "")
        elif ai:
            facts["status"] = ai.get("status", "")
        if a.get("team"):
            facts["team_note"] = str(a["team"].get("why", ""))[:200]
        agents.append(facts)
    return {"week_start": first_day, "week_end": end,
            "paper_trading_since": payload["start"], "agents": agents}


def ask_claude(facts: dict, model: str, api_key: str | None = None) -> dict:
    """One Messages API call; returns the report text and token usage."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    reply = call_claude({
        "model": model, "max_tokens": 1500, "system": SYSTEM,
        "messages": [{"role": "user", "content":
                      "This week's facts (returns are fractions, 0.012 = "
                      "+1.2%):\n" + json.dumps(facts, indent=1)}],
    }, key, timeout=120)
    text = "".join(b.get("text", "") for b in reply.get("content", []))
    if not text.strip():
        raise ValueError("Claude sent an empty report")
    return {"text": text.strip(), "model": reply.get("model", model),
            "usage": reply.get("usage", {})}


def save(report: dict, path: Path) -> dict:
    """Put ``report`` first in ``path``, replacing one for the same week."""
    old = json.loads(path.read_text()) if path.exists() else {}
    reports = [r for r in old.get("reports", [])
               if r["week_end"] != report["week_end"]]
    data = {"reports": [report, *reports][:KEEP]}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return data


def issue_text(report: dict) -> str:
    """The report as the body of the GitHub issue that emails it."""
    return (f"{report['text']}\n\n---\nWeek of {report['week_start']} to "
            f"{report['week_end']}, written by Claude from the paper-trading "
            "results. Dashboard: https://mauritswessels.github.io/Vanguard3/\n\n"
            "@Mits-Alt-F4 · automatic weekly report.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path,
                        default=config.DASHBOARD_DATA_DIR / "paper.json")
    parser.add_argument("--out", type=Path,
                        default=config.DASHBOARD_DATA_DIR / "weekly.json")
    parser.add_argument("--issue", type=Path,
                        help="also write the issue text to this file")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the facts, ask nothing, save nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    payload = json.loads(args.results.read_text())
    if payload.get("status") != "live" or not payload.get("agents"):
        logger.info("Paper trading has not started: no report this week")
        return
    facts = week_facts(payload)
    if args.dry_run:
        print(json.dumps(facts, indent=1))
        return
    model = config.NEWS_PARAMS["model"]
    reply = ask_claude(facts, model)
    report = {"week_start": facts["week_start"], "week_end": facts["week_end"],
              "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(
                  timespec="minutes"),
              **reply}
    save(report, args.out)
    if args.issue:
        args.issue.write_text(issue_text(report))
    logger.info("Weekly report for %s to %s saved (%s)", report["week_start"],
                report["week_end"], report["model"])


if __name__ == "__main__":
    main()
