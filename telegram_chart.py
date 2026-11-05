"""The two Telegram messages after each morning run: headline and details.

    python telegram_chart.py race.png --details details.txt --ibkr "Done: ..."

writes the race chart to ``race.png``, the details message to
``details.txt`` and prints the headline (the chart's caption). Both texts
use Telegram's HTML formatting (bold headings), so ``ibkr_morning.sh``
sends them with ``parse_mode=HTML``.

1. **Headline**: the chart (who is ahead of or behind SPY, and every
   account's return since launch), with the top three, the last place,
   the yardsticks and one line on the IBKR run underneath.
2. **Details**: the full IBKR result, then for the top three and the last
   place how it picks, its biggest holdings with the reason it bought
   them, its big trades of the last session with the reason, and what it
   trades at the next open. Small trades are only counted.

The accounts joined on different days, so they are ranked by their lead
over Buy & Hold SPY over the same days (``same_days`` in the results),
not by their return since their own start. Fixed twins and yardsticks are
not ranked.

The older call (``--why why.txt --trades trades.txt``, plain text) still
works, for the one morning after an update when the server's running
script is the old one.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

import config
from ibkr_bridge import load_results

#: Agent colours for the chart (the platform's own are in web/src/styles.css).
COLORS = {"trend": "#5b93ff", "reversion": "#ffb547",
          "volatility": "#3fd0c9", "benchmark": "#8d9096",
          "learner": "#b6e36b", "news": "#ff7ac0", "news_opus": "#ff8f6b",
          "learner_opus": "#5fd6a0", "daytrader": "#26b5c6",
          "monkey": "#c39a74", "manager": "#a98bff",
          "equal_weight": "#c9ccd1"}
BG, PANEL, INK, MUTED, LINE = "#111213", "#17191c", "#e8e9eb", "#8d9096", "#2a2d31"
UP, DOWN, FAINT = "#4cc38a", "#f06a6a", "#3a3d42"

DASHBOARD = "https://vanguard3.xyz/"

#: Telegram refuses longer messages and photo captions (visible characters).
TELEGRAM_LIMIT = 4096
CAPTION_LIMIT = 1024

#: A trade this big (share of the account) is shown with its reason;
#: smaller ones are only counted.
BIG_TRADE = 0.05

MEDALS = ["🥇", "🥈", "🥉"]
RULE = "━━━━━━━━━━━━━━"


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
    "daytrader": "Trades US shares during the day on live prices and holds "
                 "nothing overnight.",
}

#: The agents' own reasons -> plain words (anything else is shown as is).
PLAIN = [
    (r"Up-trend, ADX [\d.]+", "in a steady rise"),
    (r"Oversold, RSI [\d.]+", "fell sharply and looks cheap"),
    (r"Donchian breakout", "broke above its recent high"),
    (r"Broke Donchian exit channel", "fell below its recent low"),
    (r"Reverted to 20-day mean", "recovered to its usual price"),
    (r"EMA fast crossed below slow", "the rise ended"),
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


def esc(text: str) -> str:
    """Text that is safe inside Telegram's HTML."""
    return html.escape(str(text), quote=False)


def visible(text: str) -> str:
    """What Telegram shows of an HTML text (its limits count this)."""
    return html.unescape(re.sub(r"</?[bi]>", "", text))


def day(d: str) -> str:
    return date.fromisoformat(d).strftime("%-d %b")


def weekday(d: str) -> str:
    return date.fromisoformat(d).strftime("%a %-d %b")


def pct(x: float, places: int = 2) -> str:
    return f"{x:+.{places}%}"


def vs_spy(agent: dict) -> dict | None:
    """The agent against Buy & Hold SPY over the days both were trading
    (``None`` in results from before same-days figures, or before it
    joined)."""
    return (agent.get("same_days") or {}).get("benchmark")


def ranked(payload: dict) -> list[dict]:
    """The racing agents, best first (no fixed twins or yardsticks): by
    their lead over SPY over the same days, those not trading yet last.
    Older results without same-days figures rank by return since start."""
    racers = [a for a in payload["agents"] if not a.get("benchmark")
              and a["key"] != "monkey" and "(fixed)" not in a["name"]]
    if not any(vs_spy(a) for a in racers):
        return sorted(racers, key=lambda a: -a["stats"]["total_return"])
    return sorted(racers, key=lambda a: (vs_spy(a) is None,
                                         -(vs_spy(a) or {}).get("difference", 0)))


def podium(payload: dict, top: int = 3) -> list[tuple[str, dict]]:
    """The top three with their medals, then the last place (the last one
    that is already trading), as (label, agent)."""
    order = ranked(payload)
    picks = [(MEDALS[i] if i < len(MEDALS) else f"{i + 1}.", a)
             for i, a in enumerate(order[:top])]
    rest = order[top:]
    trading = [a for a in rest if vs_spy(a)] or rest
    if trading:
        picks.append(("🔻", trading[-1]))
    return picks


def lead(agent: dict, start: str | None = None) -> str:
    """✅ 1.20% ahead of SPY (since the day it joined, if later)."""
    v = vs_spy(agent)
    if not v:
        return ""
    ahead = v["difference"] >= 0
    since = f" since {day(v['from'])}" if v["from"] != start else ""
    return (f"{'✅' if ahead else '❌'} {abs(v['difference']):.2%} "
            f"{'ahead of' if ahead else 'behind'} SPY{since}")


def ibkr_lines(text: str) -> list[str]:
    """The bridge's last words (and the run's warnings), one tidy line per
    point, each with a symbol."""
    out = []
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Morning run failed:"):
            out.append("❌ " + line)
            continue
        if line.startswith("Warning:"):
            rest = line[len("Warning:"):].strip()
            out.append("⚠️ " + rest[:1].upper() + rest[1:])
            continue
        if not line.startswith("Done:"):
            out.append("⚠️ " + line)
            continue
        for part in line[len("Done:"):].strip().rstrip(".").split("; "):
            m = re.fullmatch(r"(\d+) of (\d+) orders placed", part)
            if m:
                ok = m.group(1) == m.group(2)
                out.append(f"{'✅' if ok else '⚠️'} {part[0].upper()}{part[1:]}")
            elif part == "no orders needed":
                out.append("✅ No orders needed, it already matches")
            elif part.startswith("not accepted:"):
                out.append("❌ Not accepted:" + part[len("not accepted:"):])
            elif part.startswith("currency:"):
                out.append("💱 Currency:" + part[len("currency:"):])
            elif part.startswith("kept in cash:"):
                out.append("💵 Kept in cash:" + part[len("kept in cash:"):])
            else:
                out.append(f"⚠️ {part[0].upper()}{part[1:]}")
    return out


def caption(payload: dict, ibkr: str = "",
            today: date | None = None) -> str:
    """The headline under the chart: top three, last place, yardsticks,
    and how the IBKR run went, in at most 1,024 characters."""
    agents, start = payload["agents"], payload.get("start")
    today = today or date.today()
    lines = [f"<b>📊 Vanguard3 · {today:%a} {today.day} {today:%b}</b>",
             f"Race day {len(agents[0]['equity'])}, results of the close "
             f"on {weekday(payload['last'])}"]
    picks = podium(payload)
    lines += ["", "<b>🏆 Top 3</b> (compared with SPY on the same days)"]
    for label, a in picks:
        if label == "🔻":
            lines += ["", "<b>🔻 Last place</b>"]
        row = f"{'' if label == '🔻' else label + ' '}<b>{esc(a['name'])}</b>"
        row += f"  {pct(a['stats']['total_return'])}"
        lines.append(row)
        if lead(a, start):
            lines.append(f"      {lead(a, start)}")
    marks = []
    for a in agents:
        if a.get("benchmark") or a["key"] == "monkey":
            since = (f" (since {day(a['joined'])})" if a.get("joined")
                     and a["joined"] != start else "")
            name = a["name"].replace("Buy & Hold ", "")
            marks.append(f"{esc(name)} {pct(a['stats']['total_return'])}"
                         f"{since}")
    if marks:
        lines += ["", "<b>📏 Yardsticks</b>", *marks]
    notes = ibkr_lines(ibkr)
    if notes:
        first = notes[0] if len(notes[0]) <= 160 else notes[0][:157] + "..."
        lines += ["", "<b>🏦 IBKR this morning</b>", esc(first)]
        if len(notes) > 1:
            lines.append(f"➕ {len(notes) - 1} more in the next message")
    return "\n".join(lines)


def holdings(agent: dict, most: int) -> list[str]:
    value = agent["stats"]["final_equity_chf"]
    cash = agent["cash_chf"] / value if value else 1
    held = sorted(agent["positions"], key=lambda p: -p["value_chf"])
    if not held:
        return ["💼 <b>Holds</b> nothing yet, all cash"]
    lines = [f"💼 <b>Holds</b> {1 - cash:.0%} invested · {cash:.0%} cash"]
    bought = {}
    for t in agent["trades"]:
        if t["side"] == "BUY":
            bought[t["ticker"]] = t
    for p in held[:most]:
        arrow = "📈" if p["pnl_pct"] >= 0 else "📉"
        lines.append(f"▸ <b>{esc(p['ticker'])}</b> · "
                     f"{p['value_chf'] / value:.0%} of the account · "
                     f"{arrow} {p['pnl_pct']:+.1%}")
        t = bought.get(p["ticker"])
        if t:
            lines.append(f"   <i>{esc(plain(t['reason']))}, bought "
                         f"{day(t['date'])}</i>")
    if len(held) > most:
        lines.append(f"▸ and {len(held) - most} smaller ones")
    return lines


def fill(t: dict) -> str:
    """🟢 Bought 30 UNH · 9,044 CHF (and how a sale went)."""
    verb = "🟢 Bought" if t["side"] == "BUY" else "🔴 Sold"
    when = {"midday": " at midday",
            "intraday": " during the day"}.get(t.get("session"), "")
    text = (f"{verb} {t['quantity']:g} <b>{esc(t['ticker'])}</b>{when} · "
            f"{t['value_chf']:,.0f} CHF")
    if t.get("pnl_chf") is not None:
        text += (f" · {'✅' if t['pnl_chf'] >= 0 else '❌'} "
                 f"{t['pnl_chf']:+,.0f} CHF on it")
    return text


def traded(agent: dict, last: str, most: int) -> list[str]:
    """The big trades of the last session with their reason; small ones
    only counted."""
    value = agent["stats"]["final_equity_chf"] or 1
    done = [t for t in agent["trades"] if t["date"] == last]
    if not done:
        return []
    big = sorted((t for t in done if t["value_chf"] >= BIG_TRADE * value),
                 key=lambda t: -t["value_chf"])
    lines = [f"🔁 <b>Traded on {day(last)}</b>"]
    for t in big[:most]:
        lines += [fill(t), f"   <i>{esc(plain(t['reason']))}</i>"]
    small = len(done) - len(big[:most])
    if small:
        lines.append(f"➕ {small} smaller trade{'s' if small > 1 else ''} "
                     f"(under {BIG_TRADE:.0%} of the account)")
    return lines


def planned(agent: dict, most: int) -> list[str]:
    orders = agent.get("pending_orders", [])
    if not orders:
        return ["⏭️ <b>Next open</b> nothing planned"]
    lines = ["⏭️ <b>Next open</b>"]
    for o in orders[:most]:
        verb = "🟢 Buy" if o["side"] == "BUY" else "🔴 Sell"
        size = f"{o['quantity']:g} " if o.get("quantity") else ""
        lines += [f"{verb} {size}<b>{esc(o['ticker'])}</b>",
                  f"   <i>{esc(plain(o['reason']))}</i>"]
    if len(orders) > most:
        lines.append(f"➕ {len(orders) - most} more orders")
    return lines


def details(payload: dict, ibkr: str = "", most: int = 3) -> str:
    """The second message: the IBKR run in full, then the top three and
    the last place in depth. Fits one Telegram message."""
    start, last = payload.get("start"), payload["last"]
    lines = [f"<b>🔎 The details · close of {weekday(last)}</b>"]
    notes = ibkr_lines(ibkr)
    if notes:
        lines += ["", "<b>🏦 IBKR this morning</b>", *map(esc, notes)]
    for label, a in podium(payload):
        name = "Last place: " + a["name"] if label == "🔻" else a["name"]
        lines += ["", RULE, f"{label} <b>{esc(name)}</b>  "
                  f"{pct(a['stats']['total_return'])}"]
        if lead(a, start):
            lines.append(lead(a, start))
        style = STYLES.get(a["key"], a.get("style", ""))
        if style:
            lines.append(f"<i>{esc(style)}</i>")
        lines += ["", *holdings(a, most)]
        made = traded(a, last, most)
        if made:
            lines += ["", *made]
        lines += ["", *planned(a, most)]
    lines += ["", RULE, f"📋 Every account and trade: {DASHBOARD}"]
    text = "\n".join(lines)
    if len(visible(text)) <= TELEGRAM_LIMIT or most <= 1:
        return text
    return details(payload, ibkr, most - 1)


def spread(values: list[float], gap: float) -> list[float]:
    """Label heights near ``values`` but at least ``gap`` apart."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for prev, i in zip(order, order[1:]):
        out[i] = max(out[i], out[prev] + gap)
    shift = (sum(out) - sum(values)) / len(values) if values else 0
    return [v - shift for v in out]


def style_axes(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=10)
    for side in ax.spines.values():
        side.set_color(LINE)


def draw(payload: dict, path: Path) -> None:
    """Two charts, one above the other, sized for a phone: who is ahead
    of or behind SPY, and the race since launch with the top three and
    the last place in colour."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (bars, race) = plt.subplots(
        2, 1, figsize=(7, 9.4), dpi=150,
        gridspec_kw={"height_ratios": [1, 1.15]})
    fig.patch.set_facecolor(BG)

    # 1. Ahead of or behind SPY over the same days.
    order = ranked(payload)
    others = [a for a in payload["agents"]
              if a["key"] in ("monkey", "equal_weight")]
    rows = [a for a in order + others if vs_spy(a)]
    if rows:
        names = [a["name"] for a in rows][::-1]
        diffs = [vs_spy(a)["difference"] * 100 for a in rows][::-1]
        colors = [(MUTED if a in others else UP if d >= 0 else DOWN)
                  for a, d in zip(rows[::-1], diffs)]
        y = list(range(len(rows)))
        bars.barh(y, diffs, color=colors, height=0.62)
        bars.set_yticks(y)
        bars.set_yticklabels(names, color=INK, fontsize=11)
        bars.axvline(0, color=MUTED, linewidth=0.9)
        span = max(abs(d) for d in diffs) or 1
        bars.set_xlim(-span * 1.35 if min(diffs) < 0 else -span * 0.1,
                      span * 1.35 if max(diffs) > 0 else span * 0.1)
        for yy, d in zip(y, diffs):
            bars.annotate(f"{d:+.1f}%", (d, yy),
                          xytext=(4 if d >= 0 else -4, 0),
                          textcoords="offset points",
                          ha="left" if d >= 0 else "right", va="center",
                          color=INK, fontsize=10)
        bars.set_xlabel("points ahead of (+) or behind (-) SPY, same days",
                        color=MUTED, fontsize=10)
        bars.grid(axis="x", color=LINE, linewidth=0.6)
        bars.set_axisbelow(True)
    else:
        bars.text(0.5, 0.5, "Not enough days yet to compare with SPY",
                  color=MUTED, ha="center", va="center",
                  transform=bars.transAxes)
        bars.set_xticks([])
        bars.set_yticks([])
    bars.set_title("Who is ahead of SPY", color=INK, fontsize=14,
                   loc="left", fontweight="bold")
    style_axes(bars)

    # 2. The race since launch: colour for the ones in the message.
    days = [d for d, _ in payload["agents"][0]["equity"]]
    x = list(range(len(days)))              # trading days, no weekend gaps
    shown = {id(a) for _, a in podium(payload)}
    labels = []
    for a in sorted(payload["agents"],
                    key=lambda a: (id(a) in shown or a["key"] == "benchmark",
                                   a["stats"]["total_return"])):
        _, ret = returns(a)
        lit = id(a) in shown or a["key"] == "benchmark"
        color = COLORS.get(a["key"], MUTED) if lit else FAINT
        race.plot(x[-len(ret):], ret, color=color,
                  linestyle="--" if a["key"] == "benchmark" else "-",
                  linewidth=2.2 if lit else 1,
                  marker="o" if len(days) < 6 else None, markersize=3)
        if lit:
            name = "SPY" if a["key"] == "benchmark" else a["name"]
            labels.append((ret[-1], f"{name} {ret[-1]:+.1f}%", color))
    race.axhline(0, color=MUTED, linewidth=0.8)
    low, high = race.get_ylim()
    heights = spread([y for y, _, _ in labels], (high - low) * 0.075)
    for (y, text, color), h in zip(labels, heights):
        race.annotate(text, (x[-1], y), xytext=(x[-1] + 0.3, h),
                      color=color, fontsize=10.5, va="center",
                      annotation_clip=False)
    step = max(1, len(days) // 4)
    race.set_xticks(x[::step])
    race.set_xticklabels([day(d) for d in days[::step]])
    race.set_xlim(-0.3, x[-1] + max(1.5, len(days) * 0.7))
    race.set_title(f"Return since {day(payload['start'])} (grey: the others)",
                   color=INK, fontsize=14, loc="left",
                   fontweight="bold")
    race.set_ylabel("%", color=MUTED, fontsize=8)
    race.grid(color=LINE, linewidth=0.6)
    style_axes(race)
    fig.tight_layout(h_pad=2.5)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def plain_text(text: str) -> str:
    """The same message without HTML, for the older server script."""
    return visible(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("png", type=Path, help="where to write the chart")
    parser.add_argument("--results",
                        default=config.IBKR_PARAMS["results_url"],
                        help="URL or file of paper.json")
    parser.add_argument("--details", type=Path,
                        help="also write the details message to this file")
    parser.add_argument("--ibkr", default="",
                        help="how the IBKR run went (the bridge's last line)")
    parser.add_argument("--why", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--trades", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    payload = load_results(args.results)
    if not payload.get("agents"):
        sys.exit("No results yet: nothing to draw.")
    draw(payload, args.png)
    head, more = caption(payload, args.ibkr), details(payload, args.ibkr)
    if args.details:
        args.details.write_text(more)
    if args.why or args.trades:             # the older script: plain text
        head = plain_text(head)
        if args.why:
            args.why.write_text(plain_text(more))
        if args.trades:
            args.trades.write_text(f"Every account and trade: {DASHBOARD}")
    print(head)


if __name__ == "__main__":
    main()
