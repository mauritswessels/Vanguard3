/* The race: every account's value since launch on one chart, with a legend
 * that doubles as the readout (each account's value at the hovered day) and
 * as the switch to hide or show a line. */
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { ORDER } from "../../lib/agents";
import { chf, pct, signedChf, dateShort, tone } from "../../lib/format";
import { curve, range as makeRange, RANGES, type CurveMode, type RangeKind } from "../../lib/metrics";
import type { RunData } from "../../lib/types";
import { Segmented, Swatch, cx } from "../ui";
import { LineChart, type Line } from "./LineChart";
import { useChartTheme } from "./useChartTheme";

const MODES: [CurveMode, string][] = [["return", "Return"], ["value", "CHF"], ["pnl", "Profit"]];

export function RaceChart({ data, height = 400, compact = false }: { data: RunData; height?: number; compact?: boolean }) {
  const theme = useChartTheme();
  const [mode, setMode] = useState<CurveMode>("return");
  const [kind, setKind] = useState<RangeKind>("all");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<{ date: string | null; values: Map<string, number> }>({ date: null, values: new Map() });
  const r = makeRange(kind, data);

  const agents = useMemo(() => data.agents.slice().sort((a, b) =>
    (b.stats.final_equity_chf ?? 0) - (a.stats.final_equity_chf ?? 0) || ORDER.indexOf(a.key) - ORDER.indexOf(b.key)), [data]);

  const lines: Line[] = useMemo(() => agents.map((a) => ({
    id: a.id,
    points: curve(a, data, r, mode),
    color: theme.series(a.key),
    style: a.key === "monkey" ? "dotted" : a.fixed_twin || a.key === "benchmark" ? "dashed" : "solid",
    width: a.fixed_twin || a.benchmark ? 1 : 2,
    hidden: hidden.has(a.id),
  })), [agents, data, r.from, r.to, mode, theme, hidden]); // eslint-disable-line react-hooks/exhaustive-deps

  const fmt = (v: number) => (mode === "return" ? pct(v, 1) : mode === "pnl" ? signedChf(v) : chf(v));
  const last = (id: string) => { const l = lines.find((x) => x.id === id); return l?.points[l.points.length - 1]?.[1]; };
  const toggle = (id: string) => setHidden((h) => { const n = new Set(h); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="text-[13px] text-muted">
          {hover.date ? <>Close of <span className="text-ink">{dateShort(hover.date)}</span></> : <>Since {r.from ? dateShort(r.from) : "launch"} · hover the chart to read any day</>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Segmented label="Measure" value={mode} options={MODES} onChange={setMode} />
          {!compact && <Segmented label="Time range" value={kind} options={RANGES.filter(([k]) => k !== "today")} onChange={setKind} />}
        </div>
      </div>
      <div className="grid lg:grid-cols-[1fr_300px]">
        <div className="px-2 pt-3 sm:px-4">
          <LineChart lines={lines} format={fmt} height={height} zeroLine={mode === "value" ? data.initial_capital_chf : 0}
            onHover={(date, values) => setHover({ date, values })} />
        </div>
        <ul className="grid content-start gap-0 border-t border-line p-3 lg:border-l lg:border-t-0" aria-label="Accounts on the chart">
          {agents.map((a) => {
            const v = hover.date ? hover.values.get(a.id) : last(a.id);
            const off = hidden.has(a.id);
            return (
              <li key={a.id} className="group flex items-center gap-1">
                <button type="button" onClick={() => toggle(a.id)} aria-pressed={!off} title={off ? "Show this line" : "Hide this line"}
                  className={cx("flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-[5px] text-left text-[13px] transition hover:bg-surface-2", off && "opacity-40")}>
                  <Swatch agent={a} size={9} />
                  <span className="truncate">{a.name}</span>
                  <span className={cx("tabular ml-auto pl-2 font-medium", mode !== "value" && tone(v))}>{v == null ? "–" : fmt(v)}</span>
                </button>
                <Link to={`/agents/${a.id}`} className="hidden rounded-md px-1.5 py-1 text-[12px] text-faint hover:text-gold group-hover:block" aria-label={`Open ${a.name}`}>→</Link>
              </li>
            );
          })}
          <li className="mt-2 px-2 text-[11.5px] leading-relaxed text-faint">Dashed: fixed twins and buy-and-hold SPY. Dotted: the Monkey. Click a name to hide its line.</li>
        </ul>
      </div>
    </div>
  );
}
