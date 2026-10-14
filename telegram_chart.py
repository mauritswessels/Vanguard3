"""The race chart for the Telegram message after each morning run.

    python telegram_chart.py race.png      # writes the chart, prints the caption

Draws every account's return since launch from the dashboard results
(``docs/data/paper.json`` on GitHub) in the dashboard's colours: learning
agents solid, their fixed twins dashed, the yardsticks grey and brown. The
caption lists the top three and the two yardsticks. ``ibkr_morning.sh``
sends both to Telegram when ``TELEGRAM_TOKEN`` is set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config
from ibkr_bridge import load_results

#: Same colours as the dashboard (docs/index.html, --a-<key>).
COLORS = {"trend": "#5b93ff", "reversion": "#ffb547",
          "volatility": "#3fd0c9", "benchmark": "#8d9096",
          "learner": "#b6e36b", "news": "#ff7ac0", "news_opus": "#ff8f6b",
          "monkey": "#c39a74", "manager": "#a98bff"}
BG, PANEL, INK, MUTED, LINE = "#111213", "#17191c", "#e8e9eb", "#8d9096", "#2a2d31"


def returns(agent: dict) -> tuple[list[str], list[float]]:
    """Dates and return since launch, in percent."""
    days = [d for d, _ in agent["equity"]]
    start = agent["equity"][0][1]
    return days, [(v / start - 1) * 100 for _, v in agent["equity"]]


def caption(payload: dict) -> str:
    """Top three and the yardsticks, one line each."""
    agents = payload["agents"]
    ranked = sorted((a for a in agents if not a.get("benchmark")
                     and a["key"] != "monkey" and "(fixed)" not in a["name"]),
                    key=lambda a: -a["stats"]["total_return"])
    lines = [f"The race, day {len(agents[0]['equity'])} "
             f"(close of {payload['last']})"]
    for i, a in enumerate(ranked[:3], 1):
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
    import pandas as pd

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
    ax.set_xticklabels([pd.Timestamp(d).strftime("%d %b")
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
    args = parser.parse_args()
    payload = load_results(args.results)
    if not payload.get("agents"):
        sys.exit("No results yet: nothing to draw.")
    draw(payload, args.png)
    print(caption(payload))


if __name__ == "__main__":
    main()
