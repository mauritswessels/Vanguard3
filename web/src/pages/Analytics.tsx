/* The numbers behind the race: performance over any time range, risk, and
 * any two agents side by side. Every figure comes from lib/metrics.ts. */
import { AlertTriangle, Info } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { LineChart, type Line } from "../components/charts/LineChart";
import { AiCostTable, PairCard } from "../components/HeadToHead";
import { ReportCardTable } from "../components/ReportCard";
import { useChartTheme } from "../components/charts/useChartTheme";
import { Delta, Empty, Section, Segmented, Swatch, cx } from "../components/ui";
import { ORDER } from "../lib/agents";
import { useLive } from "../lib/data";
import { chf, num, pct, share, signedChf } from "../lib/format";
import {
  all, alerts, compareSummary, curve, drawdownCurve, exposure, MIN_RETURNS, pairs, range, RANGES, stats,
  type AgentStats, type Range, type RangeKind,
} from "../lib/metrics";
import type { RunData } from "../lib/types";

type Tab = "performance" | "pairs" | "cards" | "risk" | "compare";

export default function Analytics() {
  const d = useLive();
  const [tab, setTab] = useState<Tab>("performance");
  const [kind, setKind] = useState<RangeKind>("all");
  if (d === undefined) return <Section><div className="h-[60vh] animate-pulse rounded-3xl bg-surface" /></Section>;
  if (!d) return <Section><Empty>No live data yet.</Empty></Section>;
  const r = range(kind, d);
  return (
    <>
      <Section className="pb-6">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Analytics</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">The numbers behind the race</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            Returns, risk and trading statistics for every account over any period. The formulas match the Python engine that runs the race,
            so for “all time” every figure equals the official scoreboard.
          </p>
        </div>
      </Section>
      <Section className="pt-0">
        <div className="glass sticky top-16 z-30 mb-8 flex flex-wrap items-center justify-between gap-2 rounded-2xl p-2">
          <Segmented label="View" value={tab} options={[["performance", "Performance"], ["pairs", "Head to head"], ["cards", "Report cards"], ["risk", "Risk"], ["compare", "Compare two"]]} onChange={setTab} />
          {tab === "pairs" || tab === "cards" ? <span className="px-3 text-[12.5px] text-muted">{tab === "pairs" ? "Each pair on the days both were trading" : "Every trade, graded against SPY"}</span>
            : <Segmented label="Time range" value={kind} options={RANGES} onChange={setKind} />}
        </div>
        {tab === "performance" && <Performance d={d} r={r} />}
        {tab === "pairs" && <HeadToHead d={d} />}
        {tab === "cards" && (
          <div className="grid gap-5">
            <p className="max-w-3xl text-[14.5px] text-ink-2">
              Every trade is graded 5 and 20 trading days after it fills: a buy is right if the market then did better than the S&amp;P 500,
              a sell if it did worse. The edge is that gap. Calls pile up much faster than days, so timing skill shows here long before it shows in returns.
            </p>
            <ReportCardTable d={d} />
          </div>
        )}
        {tab === "risk" && <Risk d={d} r={r} />}
        {tab === "compare" && <Compare d={d} r={r} />}
      </Section>
    </>
  );
}

const sorted = (d: RunData) => d.agents.slice().sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key) || Number(a.fixed_twin) - Number(b.fixed_twin));
const ratio = (s: AgentStats, v: number) => (s.enough && isFinite(v) ? num(v) : "–");

function Performance({ d, r }: { d: RunData; r: Range }) {
  const theme = useChartTheme();
  const S = useMemo(() => all(d, r).sort((x, y) => y.ret - x.ret), [d, r]);
  const agent = (id: string) => d.agents.find((a) => a.id === id)!;
  // Newer files compare every account with SPY over the days both traded.
  const fair = d.agents.some((a) => a.same_days?.benchmark);
  const dd: Line[] = d.agents.map((a) => ({
    id: a.id, points: drawdownCurve(a, d, r), color: theme.series(a.key),
    style: a.key === "monkey" ? "dotted" : a.fixed_twin || a.benchmark ? "dashed" : "solid", width: a.fixed_twin || a.benchmark ? 1 : 2,
  }));
  return (
    <div className="grid gap-6">
      <div className="card scroll-x">
        <table className="w-full min-w-[1000px] text-[13.5px]">
          <thead>
            <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
              {["Account", "Return", ...(fair ? ["vs SPY, same days"] : []), "Profit CHF", "Volatility", "Sharpe", "Max drop", "Win rate", "Profit factor", "Fills", "Fees CHF", "Invested"].map((h, i, all) => (
                <th key={h} className={cx("py-3.5 font-medium", i === 0 ? "pl-5 text-left" : "pr-4 text-right", i === all.length - 1 && "pr-5")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {S.map((s) => (
              <tr key={s.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                <td className="py-3 pl-5"><Link to={`/agents/${s.id}`} className="flex items-center gap-2.5 hover:text-gold"><Swatch agent={agent(s.id)} />{s.name}</Link></td>
                <td className="py-3 pr-4 text-right"><Delta value={s.ret} className="font-medium">{pct(s.ret)}</Delta></td>
                {fair && <td className="py-3 pr-4 text-right">{(() => {
                  const x = agent(s.id).same_days?.benchmark;
                  return x ? <Delta value={x.difference}>{pct(x.difference)}</Delta> : <span className="text-faint">–</span>;
                })()}</td>}
                <td className="py-3 pr-4 text-right"><Delta value={s.pnl}>{signedChf(s.pnl)}</Delta></td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{s.enough ? share(s.vol, 1) : "–"}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{ratio(s, s.sharpe)}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{pct(s.maxDD)}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{s.closed ? share(s.winRate) : "–"}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{s.closed && isFinite(s.profitFactor) ? num(s.profitFactor) : s.profitFactor === Infinity ? "∞" : "–"}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{s.fills}</td>
                <td className="tabular py-3 pr-4 text-right text-ink-2">{chf(s.fees)}</td>
                <td className="tabular py-3 pr-5 text-right text-ink-2">{isFinite(s.avgExposure) ? share(s.avgExposure) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="flex gap-2 text-[12.5px] text-muted"><Info size={14} className="mt-0.5 shrink-0" />
        Volatility and the Sharpe ratio need at least {MIN_RETURNS} trading days in the range to mean anything, so they stay empty until then.
        “Invested” is the average share of the account in the markets rather than in cash.</p>
      <div className="card p-6">
        <div className="eyebrow mb-1 text-gold">Drawdowns</div>
        <p className="mb-3 text-[13px] text-muted">How far each account was below its own previous high, day by day, over {r.label}.</p>
        <LineChart lines={dd} format={(v) => pct(v, 1)} height={300} zeroLine={0} />
      </div>
    </div>
  );
}

function HeadToHead({ d }: { d: RunData }) {
  return (
    <div className="grid gap-10">
      <div>
        <p className="mb-5 max-w-3xl text-[14.5px] text-ink-2">
          The race has experiments built in: the same idea with one thing changed. Comparing each pair day by day, on the same markets, cancels most
          of the market's noise, so a real difference shows long before a lead over the S&amp;P 500 would.
        </p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {pairs(d).map((p) => <PairCard key={p.a.id + p.b.id} p={p} question={p.question} />)}
        </div>
      </div>
      <div>
        <h2 className="display mb-2 text-[2rem]">The cost of intelligence</h2>
        <p className="mb-5 max-w-3xl text-[14.5px] text-ink-2">What each Claude-driven account has paid for the model, estimated from its token counts, against what it has earned since it joined.</p>
        <AiCostTable d={d} />
      </div>
    </div>
  );
}

function Risk({ d, r }: { d: RunData; r: Range }) {
  const warn = alerts(d, r);
  const accounts = d.agents.filter((a) => !a.fixed_twin);
  const ex = exposure(accounts, d);
  const S = all(d, r);
  return (
    <div className="grid gap-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="card p-7">
          <div className="eyebrow mb-4 text-gold">Warnings</div>
          {warn.length ? (
            <ul className="grid gap-3">
              {warn.map((w, i) => (
                <li key={i} className={cx("flex gap-3 rounded-xl border p-4 text-[13.5px]", w.level === "warn" ? "border-down/25 bg-down-wash" : "border-line bg-surface-2")}>
                  {w.level === "warn" ? <AlertTriangle size={16} className="mt-0.5 shrink-0 text-down" /> : <Info size={16} className="mt-0.5 shrink-0 text-gold" />}
                  <div><div className="font-medium">{w.kind}</div><div className="mt-0.5 text-ink-2">{w.text}</div></div>
                </li>
              ))}
            </ul>
          ) : <Empty>No warnings for {r.label}.</Empty>}
        </div>
        <div className="card p-7">
          <div className="eyebrow mb-1 text-gold">Where all the money is</div>
          <p className="mb-5 text-[13px] text-muted">Every account together (without the twins): {share(ex.long)} invested, {share(ex.cashPct)} in cash.</p>
          <ul className="grid gap-3">
            {ex.byGroup.map((g) => (
              <li key={g.name}>
                <div className="mb-1.5 flex justify-between text-[13px]"><span>{g.name}</span><span className="tabular text-muted">{share(g.pct, 1)}</span></div>
                <div className="h-2 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-gold" style={{ width: `${g.pct * 100}%` }} /></div>
              </li>
            ))}
          </ul>
          <div className="eyebrow mb-3 mt-7">Most held markets</div>
          <div className="flex flex-wrap gap-1.5">
            {ex.byAsset.slice(0, 14).map((x) => <span key={x.name} className="rounded-md bg-surface-3 px-2.5 py-1 font-mono text-[12px]">{x.name} <span className="text-muted">{share(x.pct, 1)}</span></span>)}
          </div>
        </div>
      </div>
      <div className="card scroll-x">
        <table className="w-full min-w-[760px] text-[13.5px]">
          <thead>
            <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
              {["Account", "Below its peak", "Largest holding", "Worth N equal positions", "Cash", "Open positions"].map((h, i) => (
                <th key={h} className={cx("py-3.5 font-medium", i === 0 ? "pl-5" : "pr-5 text-right")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {S.map((s) => {
              const a = d.agents.find((x) => x.id === s.id)!;
              return (
                <tr key={s.id} className="border-b border-line last:border-0">
                  <td className="py-3 pl-5"><span className="flex items-center gap-2.5"><Swatch agent={a} />{s.name}</span></td>
                  <td className="tabular py-3 pr-5 text-right text-ink-2">{pct(s.curDD)}</td>
                  <td className="py-3 pr-5 text-right text-ink-2">{s.book.largest ? <><span className="font-mono">{s.book.largest.ticker}</span> {share(s.book.largest.pct, 1)}</> : "–"}</td>
                  <td className="tabular py-3 pr-5 text-right text-ink-2">{s.book.effective ? num(s.book.effective, 1) : "–"}</td>
                  <td className="tabular py-3 pr-5 text-right text-ink-2">{share(s.book.cashPct, 1)}</td>
                  <td className="tabular py-3 pr-5 text-right text-ink-2">{s.book.open}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Compare({ d, r }: { d: RunData; r: Range }) {
  const theme = useChartTheme();
  const list = sorted(d);
  const [A, setA] = useState(list.find((a) => a.key === "news")?.id || list[0].id);
  const [B, setB] = useState(list.find((a) => a.key === "news_opus")?.id || list[1].id);
  const a = d.agents.find((x) => x.id === A)!, b = d.agents.find((x) => x.id === B)!;
  const sa = stats(a, d, r), sb = stats(b, d, r);
  const lines: Line[] = [a, b].map((x, i) => ({ id: x.id + i, points: curve(x, d, r, "return"), color: theme.series(x.key), style: i ? "dashed" : "solid", width: 2 }));
  const rows: [string, (s: AgentStats) => string][] = [
    ["Return", (s) => pct(s.ret)], ["Profit", (s) => signedChf(s.pnl) + " CHF"], ["Largest drop", (s) => pct(s.maxDD)],
    ["Volatility", (s) => (s.enough ? share(s.vol, 1) : "–")], ["Sharpe ratio", (s) => ratio(s, s.sharpe)],
    ["Win rate", (s) => (s.closed ? `${share(s.winRate)} of ${s.closed}` : "–")], ["Fills", (s) => String(s.fills)],
    ["Average position", (s) => (isFinite(s.avgSize) ? share(s.avgSize, 1) : "–")], ["Invested on average", (s) => (isFinite(s.avgExposure) ? share(s.avgExposure) : "–")],
    ["Fees", (s) => chf(s.fees) + " CHF"],
  ];
  const pick = (v: string, set: (x: string) => void, label: string) => (
    <select value={v} onChange={(e) => set(e.target.value)} aria-label={label}
      className="w-full rounded-xl border border-line-2 bg-surface px-4 py-3 text-[14px] text-ink outline-none focus:border-gold">
      {list.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
    </select>
  );
  return (
    <div className="grid gap-6">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
        {pick(A, setA, "First agent")}<span className="display text-center text-[1.6rem] text-gold">vs</span>{pick(B, setB, "Second agent")}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className="card p-7">
          <div className="eyebrow mb-4 text-gold">In plain words</div>
          <ul className="grid gap-3 text-[15px] leading-relaxed text-ink-2">
            {compareSummary(sa, sb, r).map((s, i) => <li key={i} className="flex gap-3"><span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-gold" />{s}</li>)}
          </ul>
        </div>
        <div className="card p-6">
          <div className="mb-2 flex flex-wrap gap-4 text-[12.5px]">
            <span className="flex items-center gap-2"><Swatch agent={a} />{a.name} (solid)</span>
            <span className="flex items-center gap-2"><Swatch agent={b} />{b.name} (dashed)</span>
          </div>
          <LineChart lines={lines} format={(v) => pct(v, 1)} height={280} zeroLine={0} />
        </div>
      </div>
      <div className="card overflow-hidden">
        <div className="grid grid-cols-[1.2fr_1fr_1fr] border-b border-line px-5 py-3.5 text-[12px] uppercase tracking-[0.1em] text-muted">
          <span /><span className="flex items-center justify-end gap-2 normal-case tracking-normal text-ink"><Swatch agent={a} size={8} />{a.name}</span>
          <span className="flex items-center justify-end gap-2 normal-case tracking-normal text-ink"><Swatch agent={b} size={8} />{b.name}</span>
        </div>
        {rows.map(([label, f]) => (
          <div key={label} className="grid grid-cols-[1.2fr_1fr_1fr] border-b border-line px-5 py-3 text-[14px] last:border-0">
            <span className="text-muted">{label}</span><span className="tabular text-right">{f(sa)}</span><span className="tabular text-right">{f(sb)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
