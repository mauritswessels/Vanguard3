/* Simulation vs reality: the IBKR paper account that copies an agent every
 * morning, next to that agent in the simulation. The gap shows what a real
 * broker changes: refused orders, late or partial fills, European versions
 * of US funds, and slightly different prices. */
import { useMemo } from "react";
import { Link } from "react-router";
import { IBKR_URL, useRemoteJSON } from "../lib/data";
import { chf, dateShort, pct, plural, share } from "../lib/format";
import type { IbkrSummary, Point } from "../lib/types";
import { LineChart, type Line } from "./charts/LineChart";
import { useChartTheme } from "./charts/useChartTheme";
import { Delta, Empty, Stat, cx } from "./ui";

export function useIbkr() {
  return useRemoteJSON<IbkrSummary>(IBKR_URL);
}

export function RealityCheck({ compact = false }: { compact?: boolean }) {
  const s = useIbkr();
  const theme = useChartTheme();
  const rows = useMemo(() => (s?.history || []).filter((r) => r.same_close && r.return_total != null), [s]);
  if (s === undefined) return <div className="h-72 animate-pulse rounded-3xl bg-surface" />;
  if (!s) {
    return (
      <Empty>
        The real IBKR paper account appears here once the cloud server starts publishing its morning summary
        (a one-time setup, described in the README under “Simulation vs reality”).
      </Empty>
    );
  }
  const L = s.latest, last = rows[rows.length - 1];
  const lines: Line[] = [
    { id: "real", points: rows.map((r): Point => [r.results_of, r.return_total!]), color: theme.text, width: 3 },
    { id: "sim", points: rows.map((r): Point => [r.results_of, r.sim_return_total!]), color: theme.series(s.agent), width: 2, style: "dashed" },
  ];
  const prev = L.previous_orders;
  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Real account" value={`${chf(L.real.value_chf)} CHF`} sub={`${L.real.positions} positions · ${share(L.real.invested)} invested`} />
        <Stat label={`Simulated ${s.agent_name}`} value={`${chf(L.sim.value_chf)} CHF`} sub={`${L.sim.positions} positions · ${share(L.sim.invested)} invested`} />
        <Stat label="Real minus simulated" value={last?.difference_total != null ? <Delta value={last.difference_total}>{pct(last.difference_total)}</Delta> : "–"}
          sub={`return since ${dateShort(s.since)}`} />
        <Stat label="Held differently" value={L.tracking.holdings_gap != null ? share(L.tracking.holdings_gap, 1) : "–"}
          sub={L.tracking.tracking_error_yearly != null ? `tracking error ${share(L.tracking.tracking_error_yearly, 1)} a year` : "share of the account"} />
      </div>
      <div className={cx("grid gap-6", !compact && "lg:grid-cols-[1.4fr_1fr]")}>
        <div className="card min-w-0 p-6">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
            <div className="eyebrow text-gold">Return since {dateShort(s.since)}, in CHF</div>
            <div className="flex gap-4 text-[12px] text-ink-2">
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-ink" />Real IBKR paper account</span>
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 border-t-2 border-dashed" style={{ borderColor: theme.series(s.agent) }} />Simulation</span>
            </div>
          </div>
          {rows.length > 1 ? <LineChart lines={lines} format={(v) => pct(v, 1)} height={260} zeroLine={0} />
            : <div className="grid h-[260px] place-items-center text-[13px] text-muted">The line starts after the second morning run.</div>}
        </div>
        {!compact && (
          <div className="card p-6">
            <div className="eyebrow mb-3 text-gold">Morning of {dateShort(L.date)}</div>
            <p className="text-[13.5px] text-ink-2">
              Copied the {dateShort(L.results_of)} close: {plural(L.orders.planned, "order")} worked out, {L.orders.sent} taken by IBKR
              {L.orders.refused ? `, ${L.orders.refused} refused` : ""}.
              {prev ? ` The ${dateShort(prev.date)} orders: ${prev.filled} filled${prev.partly_filled ? `, ${prev.partly_filled} partly` : ""}${prev.not_filled ? `, ${prev.not_filled} not filled` : ""}.` : ""}
            </p>
            {L.orders.kept_in_cash.length > 0 && (
              <ul className="mt-4 grid gap-1.5 text-[12.5px]">
                {L.orders.kept_in_cash.slice(0, 6).map((k) => (
                  <li key={k.ticker} className="flex gap-2"><span className="font-mono text-ink">{k.ticker}</span><span className="text-muted">kept in cash: {k.reason}</span></li>
                ))}
              </ul>
            )}
            <div className="eyebrow mb-2 mt-5">Biggest differences in holdings</div>
            <ul className="grid gap-1.5 text-[12.5px]">
              {L.weights.slice().sort((x, y) => Math.abs(y.difference) - Math.abs(x.difference)).slice(0, 6).map((w) => (
                <li key={w.ticker} className="grid grid-cols-[1fr_auto_auto_auto] gap-3">
                  <span className="font-mono">{w.ticker}{w.holds_as ? <span className="text-faint"> as {w.holds_as}</span> : ""}</span>
                  <span className="tabular text-muted">sim {share(w.sim, 1)}</span>
                  <span className="tabular text-muted">real {share(w.real, 1)}</span>
                  <Delta value={w.difference} className="w-14 text-right">{pct(w.difference, 1)}</Delta>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <p className="text-[12px] text-muted">{s.about} No account details are published. <Link to="/methodology" className="text-gold">How the simulation fills orders →</Link></p>
    </div>
  );
}
