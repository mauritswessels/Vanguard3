/* Pieces shared by the agent pages and the trade explorer: verdict badges,
 * an agent's card, its decision feed and round-trip trade cards. */
import { ArrowRight, ChevronDown, Newspaper } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { badge, info } from "../lib/agents";
import { chf, date, dateShort, num, pct, share, signedChf } from "../lib/format";
import type { Activity, Agent, Decision, Trip, Verdict } from "../lib/types";
import { Sparkline } from "./charts/Sparkline";
import { useChartTheme } from "./charts/useChartTheme";
import { Badge, Delta, Empty, Swatch, cx } from "./ui";

export function VerdictBadge({ verdict }: { verdict: Verdict | null | undefined }) {
  if (!verdict) return null;
  const t = verdict === "skill" ? "up" : verdict === "looks like luck" ? "down" : "neutral";
  const label = verdict === "skill" ? "Skill" : verdict === "looks like luck" ? "Looks like luck" : "Can't tell yet";
  return <Badge tone={t}>{label}</Badge>;
}

export function AgentCard({ a, rank, verdict }: { a: Agent; rank?: number; verdict?: Verdict | null }) {
  const theme = useChartTheme();
  const i = info(a);
  return (
    <Link to={`/agents/${a.id}`} className="card group flex flex-col gap-5 p-6 transition hover:-translate-y-0.5 hover:border-gold/30">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Swatch agent={a} size={12} />
          <div>
            <div className="text-[16px] font-medium group-hover:text-gold">{a.name}</div>
            <div className="text-[12px] text-muted">{badge(a)}</div>
          </div>
        </div>
        {rank != null && <span className="tabular text-[13px] text-faint">#{rank}</span>}
      </div>
      <p className="text-[13.5px] leading-relaxed text-ink-2">{a.fixed_twin ? "Same rules as its learning twin, but it never re-tunes its settings." : i.tagline}</p>
      <div className="flex items-end justify-between gap-3">
        <div>
          <Delta value={a.stats.total_return} className="text-[1.5rem] font-medium leading-none">{pct(a.stats.total_return)}</Delta>
          <div className="mt-1.5 text-[12px] text-muted">{chf(a.stats.final_equity_chf)} CHF</div>
        </div>
        <Sparkline points={a.equity} color={theme.series(a.key)} width={120} height={38} />
      </div>
      <div className="flex items-center justify-between border-t border-line pt-4 text-[12px] text-muted">
        <span>{a.positions.length} holdings · {a.stats.trades} fills</span>
        {verdict ? <VerdictBadge verdict={verdict} /> : <ArrowRight size={14} className="text-faint transition group-hover:translate-x-0.5 group-hover:text-gold" />}
      </div>
    </Link>
  );
}

/** What an agent saw and said when it decided: its reason, the rule check,
 *  and for the news agents the target weight, market view and headlines. */
export function DecisionBlock({ d, label }: { d: Decision | null; label: string }) {
  const [open, setOpen] = useState(false);
  if (!d) return null;
  const det = d.details || {};
  const heads = (det.headlines as string[] | undefined) || [];
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 p-4">
      <div className="eyebrow mb-2">{label} · decided {dateShort(d.date)}{d.time === "midday" ? " at midday" : " after the close"}</div>
      <p className="text-[14px] text-ink">{d.reason}</p>
      {d.check && <p className="mt-1.5 text-[13px] text-muted">{d.check}</p>}
      <div className="mt-2 flex flex-wrap gap-2 text-[12px] text-muted">
        {d.score != null && <span>Score {num(d.score, 2)}</span>}
        {det.target_weight != null && <span>Target {share(det.target_weight as number, 1)} of the account</span>}
        {d.stop != null && <span>Stop {num(d.stop, 2)}</span>}
      </div>
      {det.market_view && <blockquote className="mt-3 border-l-2 border-gold/50 pl-3 text-[13px] italic text-ink-2">“{det.market_view as string}”</blockquote>}
      {heads.length > 0 && (
        <div className="mt-3">
          <button type="button" onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1.5 text-[12.5px] text-gold hover:text-gold-2" aria-expanded={open}>
            <Newspaper size={13} /> {heads.length} headlines it read <ChevronDown size={13} className={cx("transition", open && "rotate-180")} />
          </button>
          {open && (
            <ul className="mt-2 grid gap-1.5 text-[12.5px] text-ink-2">
              {heads.map((h, i) => <li key={i} className="border-l border-line-2 pl-3">{h}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** One position from first buy to last sell, with both decisions. */
export function TripCard({ a, t, showAgent = false }: { a: Agent; t: Trip; showAgent?: boolean }) {
  const [open, setOpen] = useState(false);
  const closed = t.status === "closed";
  return (
    <div className="card overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-4 p-5 text-left hover:bg-surface-2/60">
        <div className={cx("grid size-11 place-items-center rounded-xl font-mono text-[12px] font-semibold",
          !closed ? "bg-gold-wash text-gold" : t.pnl_chf >= 0 ? "bg-up-wash text-up" : "bg-down-wash text-down")}>
          {t.ticker.replace(/\..+$/, "").slice(0, 4)}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[14px] font-medium">{t.ticker}</span>
            <Badge tone={closed ? "neutral" : "gold"}>{closed ? `closed after ${t.holding_days} day${t.holding_days === 1 ? "" : "s"}` : "open"}</Badge>
            {showAgent && <span className="flex items-center gap-1.5 text-[12.5px] text-muted"><Swatch agent={a} size={7} />{a.name}</span>}
          </div>
          <div className="mt-1 truncate text-[12.5px] text-muted">
            {date(t.entry_date)}{closed && t.exit_date ? ` → ${date(t.exit_date)}` : " → now"} · {share(t.size_pct, 1)} of the account · {t.entry?.reason || ""}
          </div>
        </div>
        <div className="text-right">
          <Delta value={t.pnl_chf} className="block text-[15px] font-medium">{signedChf(t.pnl_chf)}</Delta>
          <Delta value={t.pnl_pct} className="text-[12px]">{pct(t.pnl_pct)}</Delta>
        </div>
      </button>
      {open && (
        <div className="grid gap-3 border-t border-line p-5 md:grid-cols-2">
          <DecisionBlock d={t.entry} label="Why it bought" />
          {closed ? <DecisionBlock d={t.exit} label="Why it sold" /> : (
            <div className="rounded-xl border border-dashed border-line-2 p-4 text-[13px] text-muted">Still held. It cost {chf(t.cost_chf)} CHF at {num(t.entry_price, 2)} a share.</div>
          )}
        </div>
      )}
    </div>
  );
}

const WHY: Record<string, string> = {
  "insufficient cash": "not enough cash", expired: "its market did not open for a week", "no position": "nothing left to sell",
};

/** Day by day: fills, wishes it could not afford, refused orders, dividends and splits. */
export function ActivityFeed({ a, limit = 20 }: { a: Agent; limit?: number }) {
  const days = a.activity.slice().reverse().slice(0, limit);
  if (!days.length) return <Empty>No decisions yet.</Empty>;
  return (
    <ol className="relative grid gap-6 border-l border-line pl-6">
      {days.map((day: Activity, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[29px] top-1.5 size-2.5 rounded-full border-2 border-gold bg-bg" />
          <div className="eyebrow mb-2">{date(day.date)}{day.time === "midday" ? " · midday check" : " · after the close"}</div>
          <ul className="grid gap-1.5 text-[13.5px]">
            {day.fills.map((f, j) => (
              <li key={"f" + j} className="flex flex-wrap items-center gap-2">
                <span className={cx("text-[10.5px] font-semibold tracking-wider", f.side === "BUY" ? "text-up" : "text-down")}>{f.side === "BUY" ? "BOUGHT" : "SOLD"}</span>
                <span className="font-mono">{f.ticker}</span>
                <span className="tabular text-muted">{f.quantity} @ {num(f.price, 2)}</span>
                {f.side === "SELL" && f.pnl_chf != null && <Delta value={f.pnl_chf}>{signedChf(f.pnl_chf)} CHF</Delta>}
                {f.at_open && <span className="text-[12px] text-faint">at the open, ordered the evening before</span>}
                {f.at_close && <span className="text-[12px] text-faint">at the close, ordered at midday</span>}
              </li>
            ))}
            {day.signals.filter((s) => !s.ordered).slice(0, 6).map((s, j) => (
              <li key={"s" + j} className="flex flex-wrap items-center gap-2 text-ink-2">
                <span className="text-[10.5px] font-semibold tracking-wider text-gold">{s.action === "BUY" ? "WANTED IN" : "WANTED OUT"}</span>
                <span className="font-mono">{s.ticker}</span>
                <span className="text-muted">{s.reason}{s.note ? ` · ${s.note}` : ", no cash left"}</span>
              </li>
            ))}
            {(day.rejected || []).map((r, j) => (
              <li key={"r" + j} className="flex flex-wrap items-center gap-2 text-ink-2">
                <span className="text-[10.5px] font-semibold tracking-wider text-down">NOT FILLED</span>
                <span className="font-mono">{r.ticker}</span>
                <span className="text-muted">{r.side === "BUY" ? "buy" : "sell"} {r.quantity} shares: {WHY[r.why] || r.why}</span>
              </li>
            ))}
            {(day.corporate || []).map((e, j) => (
              <li key={"c" + j} className="flex flex-wrap items-center gap-2 text-ink-2">
                <span className="text-[10.5px] font-semibold tracking-wider text-gold">{e.kind === "dividend" ? "DIVIDEND" : "SPLIT"}</span>
                <span className="font-mono">{e.ticker}</span>
                <span className="text-muted">{e.kind === "dividend" ? `+${chf(e.chf)} CHF paid into cash` : `${e.shares_before} shares became ${e.shares}`}</span>
              </li>
            ))}
            {!day.fills.length && !day.signals.some((s) => !s.ordered) && !(day.rejected || []).length && !(day.corporate || []).length && (
              <li className="text-muted">No trades: {day.signals.length ? `${day.signals.length} signals, all ordered for the next open` : "nothing met its rules"}.</li>
            )}
          </ul>
        </li>
      ))}
    </ol>
  );
}
