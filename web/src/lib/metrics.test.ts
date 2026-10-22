/* The platform's numbers must match the Python scoreboard (engine/metrics.py,
 * exported by reporting.py as each account's "stats") on the real data the
 * bots publish. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { hydrate } from "./data";
import { aiCosts, all, headToHead, pairs, range, stats } from "./metrics";
import type { Agent, RunData } from "./types";

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

describe("head to head", () => {
  const d = load("paper");
  const base = d.agents[0];
  const clone = (equity: Agent["equity"]): Agent => ({ ...base, id: "x", equity, activity: base.activity });

  it("an account against itself is level, and not called either way", () => {
    const p = headToHead(base, base, d);
    expect(p.lead).toBeCloseTo(0, 12);
    expect(p.ahead).toBeNull();
  });

  it("measures the gap only over the days both were trading", () => {
    const late = { ...clone(base.equity), activity: [{ date: base.equity[4][0], fills: [], signals: [] }] };
    const p = headToHead(base, late, d);
    expect(p.from).toBe(base.equity[4][0]);
    expect(p.days).toBe(base.equity.length - 5);
  });

  it("a steady daily lead is called once the range clears zero", () => {
    const up = clone(base.equity.map(([t], i) => [t, 100000 * 1.002 ** i]));
    const flat = clone(base.equity.map(([t], i) => [t, 100000 * (1 + (i % 2 ? 0.0005 : -0.0005))]));
    const p = headToHead(up, flat, d);
    expect(p.lead).toBeGreaterThan(0);
    expect(p.ahead).toBe("a");
  });

  it("finds the race's built-in pairs and the Claude costs", () => {
    expect(pairs(d).length).toBeGreaterThanOrEqual(3);
    for (const c of aiCosts(d)) expect(c.costChf).toBeGreaterThanOrEqual(0);
  });
});
