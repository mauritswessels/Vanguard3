"""The race chart for the Telegram message after each morning run.

    python telegram_chart.py race.png      # writes the chart, prints the caption
    python telegram_chart.py race.png --why why.txt   # and the "why" message

Draws every account's return since launch from the dashboard results
(``docs/data/paper.json`` on GitHub) in the dashboard's colours: learning
agents solid, their fixed twins dashed, the yardsticks grey and brown. The
caption lists the top three and the two yardsticks. ``--why`` also writes a
message saying, for each of the top three, how it picks, what it holds and
why it bought it, and what it will trade at the next open, in plain words.
``ibkr_morning.sh`` sends all of it to Telegram when ``TELEGRAM_TOKEN`` is
set.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import config
from ibkr_bridge import load_results

#: Same colours as the dashboard (docs/index.html, --a-<key>).
COLORS = {"trend": "#5b93ff", "reversion": "#ffb547",
          "volatility": "#3fd0c9", "benchmark": "#8d9096",
          "learner": "#b6e36b", "news": "#ff7ac0", "news_opus": "#ff8f6b",
          "learner_opus": "#5fd6a0",
          "monkey": "#c39a74", "manager": "#a98bff"}
BG, PANEL, INK, MUTED, LINE = "#111213", "#17191c", "#e8e9eb", "#8d9096", "#2a2d31"


def returns(agent: dict) -> tuple[list[str], list[float]]:
    """Dates and return since launch, in percent."""
    days = [d for d, _ in agent["equity"]]
    start = agent["equity"][0][1]
    return days, [(v / start - 1) * 100 for _, v in agent["equity"]]


#: How each agent picks, in plain words.
STYLES = {
    "trend": "Buys markets in a steady rise and sells when the rise ends.",
    "reversion": "Buys markets that fell too far, too fast, and sells when "
                 "they recover.",
    "volatility": "Buys markets that break above their recent high, with a "
                  "safety stop that follows the price up.",
    "learner": "A self-learning model that scores every market each evening.",
    "learner_opus": "The AI Learner's picks, each one checked by Claude Opus.",
    "news": "Claude reads the news and company results each evening.",
    "news_opus": "Claude Opus reads the news and company results each "
                 "evening.",
    "manager": "Copies the agents with the best recent results.",
}

#: The agents' own reasons -> plain words (anything else is shown as is).
PLAIN = [
    (r"Up-trend, ADX [\d.]+", "in a steady rise"),
    (r"Oversold, RSI [\d.]+", "fell sharply and looks cheap"),
    (r"Donchian breakout", "broke above its recent high"),
    (r"Model score favours BUY; biggest factor: (.+) \((?:for|against)\)",
     r"its model likes it, mostly because of the \1"),
    (r"Model score favours SELL; biggest factor: (.+) \((?:for|against)\)",
     r"its model turned against it, mostly because of the \1"),
    (r"Exploring: tried \w+ at random to learn", "a random try, to learn"),
    (r"Opus approved: (.+)", r"\1"),
    (r"Team target ([\d.]+)% .*", r"copying its agents (\1% of the account)"),
    (r"Initial benchmark buy", "bought once at the start"),
]


def plain(reason: str) -> str:
    """An agent's reason in plain words, at most one line."""
    reason = (reason or "").strip()
    for pattern, words in PLAIN:
        if re.fullmatch(pattern, reason):
            reason = re.sub(pattern, words, reason)
            break
    reason = reason.rstrip(".")
    return reason if len(reason) <= 120 else reason[:117].rstrip() + "..."


def day(d: str) -> str:
    return date.fromisoformat(d).strftime("%-d %b")


def ranked(payload: dict) -> list[dict]:
    """The racing agents, best first (no fixed twins or yardsticks)."""
    return sorted((a for a in payload["agents"] if not a.get("benchmark")
                   and a["key"] != "monkey" and "(fixed)" not in a["name"]),
                  key=lambda a: -a["stats"]["total_return"])


def why(payload: dict, top: int = 3) -> str:
    """For each of the top agents: how it picks, what it holds and why,
    and what it will trade at the next open."""
    lines = [f"Why the top {top} hold what they hold "
             f"(close of {day(payload['last'])})"]
    for i, a in enumerate(ranked(payload)[:top], 1):
        lines += ["", f"{i}. {a['name']} {a['stats']['total_return']:+.2%}",
                  STYLES.get(a["key"], a.get("style", ""))]
        value = a["stats"]["final_equity_chf"]
        bought = {}
        for t in a["trades"]:
            if t["side"] == "BUY":
                bought[t["ticker"]] = t
        held = sorted(a["positions"], key=lambda p: -p["value_chf"])
        for p in held[:3]:
            t = bought.get(p["ticker"])
            note = (f", bought {day(t['date'])}: {plain(t['reason'])}"
                    if t else "")
            lines.append(f"- {p['ticker']} {p['value_chf'] / value:.0%} of the "
                         f"account ({p['pnl_pct']:+.1%}){note}")
        if len(held) > 3:
            lines.append(f"- and {len(held) - 3} more")
        if not held:
            lines.append("- Holds nothing yet")
        lines.append(f"- Cash: {a['cash_chf'] / value:.0%}")
        orders = a.get("pending_orders", [])
        for o in orders[:3]:
            verb = "Buys" if o["side"] == "BUY" else "Sells"
            lines.append(f"- Next open: {verb.lower()} {o['ticker']} "
                         f"({plain(o['reason'])})")
        if len(orders) > 3:
            lines.append(f"- Next open: {len(orders) - 3} more orders")
        if not orders:
            lines.append("- Next open: no trades planned")
    return "\n".join(lines)


def caption(payload: dict) -> str:
    """Top three and the yardsticks, one line each."""
    agents = payload["agents"]
    lines = [f"The race, day {len(agents[0]['equity'])} "
             f"(close of {payload['last']})"]
    for i, a in enumerate(ranked(payload)[:3], 1):
        lines.append(f"{i}. {a['name']} {a['stats']['total_return']:+.2%}")
    for a in agents:
        if a.get("benchmark") or a["key"] == "monkey":
            lines.append(f"Yardstick {a['name']} {a['stats']['total_return']:+.2%}")
    return "\n".join(lines)


def spread(values: list[float], gap: float) -> list[float]:
    """Label heights near ``values`` but at least ``gap`` apart."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for prev, i in zip(order, order[1:]):
        out[i] = max(out[i], out[prev] + gap)
    shift = (sum(out) - sum(values)) / len(values) if values else 0
    return [v - shift for v in out]


def draw(payload: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    days = [d for d, _ in payload["agents"][0]["equity"]]
    x = list(range(len(days)))              # trading days, no weekend gaps
    labels = []
    for a in sorted(payload["agents"],
                    key=lambda a: a["stats"]["total_return"]):
        _, ret = returns(a)
        twin = "(fixed)" in a["name"]
        color = COLORS.get(a["key"], MUTED)
        ax.plot(x[-len(ret):], ret, color=color,
                linestyle="--" if twin else "-",
                linewidth=1.2 if twin or a.get("benchmark") else 2,
                alpha=0.7 if twin else 1,
                marker="o" if len(days) < 6 else None, markersize=3)
        if not twin:
            labels.append((ret[-1], f"{a['name']} {ret[-1]:+.1f}%", color))
    ax.axhline(0, color=MUTED, linewidth=0.8)
    low, high = ax.get_ylim()
    heights = spread([y for y, _, _ in labels], (high - low) * 0.045)
    for (y, text, color), h in zip(labels, heights):
        ax.annotate(text, (x[-1], y), xytext=(x[-1] + 0.25, h),
                    color=color, fontsize=7, va="center",
                    annotation_clip=False)
    step = max(1, len(days) // 8)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([date.fromisoformat(d).strftime("%d %b")
                        for d in days[::step]])
    ax.set_xlim(-0.3, x[-1] + max(1.5, len(days) * 0.45))
    ax.set_title(f"The race since launch, {payload['start']} to "
                 f"{payload['last']}", color=INK, fontsize=11, loc="left")
    ax.set_ylabel("return since start (%)", color=MUTED, fontsize=8)
    ax.tick_params(colors=MUTED, labelsize=7)
    ax.grid(color=LINE, linewidth=0.6)
    for side in ax.spines.values():
        side.set_color(LINE)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("png", type=Path, help="where to write the chart")
    parser.add_argument("--results",
                        default=config.IBKR_PARAMS["results_url"],
                        help="URL or file of paper.json")
    parser.add_argument("--why", type=Path,
                        help="also write the top three's reasons to this file")
    args = parser.parse_args()
    payload = load_results(args.results)
    if not payload.get("agents"):
        sys.exit("No results yet: nothing to draw.")
    draw(payload, args.png)
    if args.why:
        args.why.write_text(why(payload))
    print(caption(payload))


if __name__ == "__main__":
    main()
