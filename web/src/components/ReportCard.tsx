/* Report cards (engine/grading.py): every fill graded against the S&P 500
 * 5 and 20 trading days later. A buy is right if the market then beat SPY,
 * a sell if it did worse; the "edge" is that gap. Timing skill shows up in
 * these far sooner than in account returns. */
import { Link } from "react-router";
import { dateShort, pct, share } from "../lib/format";
import type { Agent, GradeStats, RunData } from "../lib/types";
import { Delta, Empty, Swatch, cx } from "./ui";

const rate = (s: GradeStats, h: 5 | 20) => (s[`graded_${h}`] ? share(s[`hit_rate_${h}`]) : "–");
const edge = (s: GradeStats, h: 5 | 20) => s[`avg_edge_${h}`];

/** One account's card, for its profile page. */
export function ReportCardPanel({ a }: { a: Agent }) {
  const c = a.report_card;
  if (!c) return null;
  return (
    <div className="card p-7">
      <div className="eyebrow mb-2 text-gold">Report card</div>
      <h2 className="display mb-2 text-[2rem]">Were its calls right?</h2>
      <p className="text-[13.5px] text-muted">
        Every trade graded against the S&amp;P 500: a buy is right if the market then beat SPY, a sell if it did worse.
        {c.pending ? ` ${c.pending} recent trade${c.pending === 1 ? " is" : "s are"} still too young to grade.` : ""}
      </p>
      {c.graded_5 ? (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3">
            {([5, 20] as const).map((h) => (
              <div key={h} className="rounded-xl border border-line p-4">
                <div className="text-[12px] text-muted">After {h} trading days</div>
                <div className="tabular mt-1 text-[1.5rem] font-medium">{rate(c, h)}<span className="ml-1 text-[13px] font-normal text-muted">right</span></div>
                <div className="mt-1 text-[12px] text-muted">
                  {c[`graded_${h}`] ? <>of {c[`graded_${h}`]} · average edge <Delta value={edge(c, h)}>{pct(edge(c, h), 1)}</Delta></> : "not graded yet"}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-[12.5px] text-ink-2">
            <div>Buys: {rate(c.by_side.buy, 5)} right after 5 days ({c.by_side.buy.graded_5})</div>
            <div>Sells: {rate(c.by_side.sell, 5)} right after 5 days ({c.by_side.sell.graded_5})</div>
          </div>
          {c.recent.length > 0 && (
            <ul className="mt-5 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {c.recent.slice().reverse().slice(0, 9).map((x, i) => (
                <li key={i} className="rounded-lg bg-surface-2 px-3 py-2 text-[12px]">
                  <div className="flex justify-between"><span className="font-mono">{x.ticker}</span><span className={x.side === "BUY" ? "text-up" : "text-down"}>{x.side}</span></div>
                  <div className="mt-0.5 flex justify-between text-muted"><span>{dateShort(x.date)}</span>
                    {x.edge_5 == null ? <span className="text-faint">pending</span> : <Delta value={x.edge_5}>{pct(x.edge_5, 1)}</Delta>}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : <div className="mt-5"><Empty>No trade is old enough to grade yet: a trade is graded 5 trading days after it fills.</Empty></div>}
    </div>
  );
}

/** Every account's card side by side (data.report_cards), best 5-day edge first. */
export function ReportCardTable({ d }: { d: RunData }) {
  const s = d.report_cards;
  if (!s) return <Empty>The first report cards appear after the next evening run.</Empty>;
  const by = new Map(d.agents.map((a) => [a.id, a]));
  return (
    <div className="card scroll-x">
      <table className="w-full min-w-[760px] text-[13.5px]">
        <thead>
          <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
            {["Account", "Graded", "Right after 5 days", "Edge, 5 days", "Right after 20 days", "Edge, 20 days"].map((h, i) => (
              <th key={h} className={cx("py-3.5 font-medium", i === 0 ? "pl-5" : "pr-5 text-right")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {s.accounts.map((r) => {
            const a = by.get(r.id);
            return (
              <tr key={r.id} className="border-b border-line last:border-0">
                <td className="py-3 pl-5">{a ? <Link to={`/agents/${a.id}`} className="flex items-center gap-2.5 hover:text-gold"><Swatch agent={a} />{a.name}</Link> : r.name}</td>
                <td className="tabular py-3 pr-5 text-right text-ink-2">{r.graded_5}</td>
                <td className="tabular py-3 pr-5 text-right text-ink-2">{rate(r as GradeStats, 5)}</td>
                <td className="py-3 pr-5 text-right"><Delta value={r.avg_edge_5}>{pct(r.avg_edge_5, 1)}</Delta></td>
                <td className="tabular py-3 pr-5 text-right text-ink-2">{rate(r as GradeStats, 20)}</td>
                <td className="py-3 pr-5 text-right"><Delta value={r.avg_edge_20}>{pct(r.avg_edge_20, 1)}</Delta></td>
              </tr>
            );
          })}
          <tr className="bg-gold-wash/40">
            <td className="py-3 pl-5 font-medium">All accounts together</td>
            <td className="tabular py-3 pr-5 text-right">{s.pooled.graded_5}</td>
            <td className="tabular py-3 pr-5 text-right">{rate(s.pooled, 5)}</td>
            <td className="py-3 pr-5 text-right"><Delta value={s.pooled.avg_edge_5}>{pct(s.pooled.avg_edge_5, 1)}</Delta></td>
            <td className="tabular py-3 pr-5 text-right">{rate(s.pooled, 20)}</td>
            <td className="py-3 pr-5 text-right"><Delta value={s.pooled.avg_edge_20}>{pct(s.pooled.avg_edge_20, 1)}</Delta></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
