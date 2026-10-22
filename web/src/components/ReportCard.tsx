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

/** The News Analysts' stated chances against what happened: a well
 *  calibrated forecaster's points sit on the diagonal. */
export function CalibrationPanel({ a }: { a: Agent }) {
  const c = a.report_card?.calibration;
  if (!c) return null;
  const W = 260, H = 260, P = 34;
  const X = (v: number) => P + v * (W - P - 10), Y = (v: number) => H - P - v * (H - P - 10);
  const pts = c.buckets.filter((b) => b.count && b.avg_probability != null && b.came_true != null);
  const max = Math.max(1, ...pts.map((b) => b.count));
  return (
    <div className="card p-7">
      <div className="eyebrow mb-2 text-gold">Calibration</div>
      <h2 className="display mb-2 text-[2rem]">Does its confidence mean anything?</h2>
      <p className="text-[13.5px] text-muted">
        With every target, Claude states the chance that the market beats the S&amp;P 500 over the next {c.horizon} trading days.
        If it is well calibrated, about 70% of its “70%” calls come true.
        {c.stated > c.scored ? ` ${c.stated - c.scored} stated chance${c.stated - c.scored === 1 ? " is" : "s are"} still waiting for its window.` : ""}
      </p>
      {c.scored ? (
        <div className="mt-5 grid items-center gap-6 sm:grid-cols-[260px_1fr]">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[260px]" role="img" aria-label="Stated chance against how often it came true">
            <rect x={P} y={10} width={W - P - 10} height={H - P - 10} fill="none" stroke="var(--line-2)" />
            <line x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} stroke="var(--faint)" strokeDasharray="4 4" />
            {[0, 0.5, 1].map((t) => (
              <g key={t}>
                <text x={X(t)} y={H - P + 16} textAnchor="middle" fontSize="10" fill="var(--muted)">{Math.round(t * 100)}%</text>
                <text x={P - 6} y={Y(t) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{Math.round(t * 100)}%</text>
              </g>
            ))}
            <text x={(W + P) / 2} y={H - 2} textAnchor="middle" fontSize="10" fill="var(--muted)">stated chance</text>
            {pts.map((b) => (
              <g key={b.from}>
                <title>{`${b.count} calls stated ${share(b.avg_probability, 0)} on average; ${share(b.came_true, 0)} came true`}</title>
                <circle cx={X(b.avg_probability!)} cy={Y(b.came_true!)} r={4 + 8 * Math.sqrt(b.count / max)} fill="var(--gold)" fillOpacity={0.8} stroke="var(--bg)" strokeWidth={2} />
              </g>
            ))}
          </svg>
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-line p-4">
                <div className="text-[12px] text-muted">Brier score (lower is better)</div>
                <div className="tabular mt-1 text-[1.4rem] font-medium">{c.brier != null ? c.brier.toFixed(3) : "–"}</div>
                <div className="mt-1 text-[12px] text-muted">always guessing {share(c.base_rate, 0)}: {c.base_rate_brier != null ? c.base_rate_brier.toFixed(3) : "–"}</div>
              </div>
              <div className="rounded-xl border border-line p-4">
                <div className="text-[12px] text-muted">Skill over that guess</div>
                <div className="tabular mt-1 text-[1.4rem] font-medium"><Delta value={c.skill}>{c.skill != null ? pct(c.skill, 0) : "–"}</Delta></div>
                <div className="mt-1 text-[12px] text-muted">{c.scored} calls scored · stated {share(c.avg_probability, 0)} on average</div>
              </div>
            </div>
            <ul className="grid gap-1 text-[12.5px] text-ink-2">
              {c.buckets.map((b) => (
                <li key={b.from} className="grid grid-cols-[90px_1fr_auto] gap-3">
                  <span className="text-muted">{share(b.from, 0)}–{share(b.to, 0)}</span>
                  <span>{b.count ? `${b.count} call${b.count === 1 ? "" : "s"}` : "none"}</span>
                  <span className="tabular">{b.count && b.came_true != null ? `${share(b.came_true, 0)} came true` : ""}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : <div className="mt-5"><Empty>No stated chance is old enough to check yet: each is checked {c.horizon} trading days after its trade.</Empty></div>}
      <p className="mt-5 text-[11.5px] text-faint">A positive skill means its chances beat always guessing the share that came true, a figure only known afterwards, so this is a sanity check rather than a fair rival.</p>
    </div>
  );
}
