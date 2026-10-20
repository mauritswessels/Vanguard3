/* The platform's numbers must match the Python scoreboard (engine/metrics.py,
 * exported by reporting.py as each account's "stats") on the real data the
 * bots publish. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { hydrate } from "./data";
import { all, range, stats } from "./metrics";
import type { RunData } from "./types";

const load = (name: string): RunData =>
  hydrate(JSON.parse(readFileSync(resolve(import.meta.dirname, `../../../docs/data/${name}.json`), "utf8")));

describe.each(["paper", "backtest"])("%s.json, all time", (name) => {
  const d = load(name);
  const r = range("all", d);

  it.each(d.agents.map((a) => [a.name, a] as const))("%s matches the Python scoreboard", (_, a) => {
    const s = stats(a, d, r);
    expect(s.value).toBeCloseTo(a.stats.final_equity_chf, 2);
    expect(s.ret).toBeCloseTo(a.stats.total_return, 5);
    expect(s.maxDD).toBeCloseTo(a.stats.max_drawdown, 5);
    if (s.returns > 1) expect(s.vol).toBeCloseTo(a.stats.volatility, 4);
    if (isFinite(s.sharpe) && Math.abs(a.stats.sharpe) < 50) expect(s.sharpe).toBeCloseTo(a.stats.sharpe, 2);
    expect(s.book.cash).toBeCloseTo(a.stats.cash_chf, 2);
  });
});

describe("ranges", () => {
  const d = load("paper");
  it("a shorter range starts from the last close before it", () => {
    const week = range("7d", d);
    for (const s of all(d, week)) {
      expect(isFinite(s.ret)).toBe(true);
      expect(s.start).toBeGreaterThan(0);
    }
  });
});
