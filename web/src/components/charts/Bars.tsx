/* Horizontal bars for one number per account: signed values grow left or
 * right from a shared zero line, each row labelled with its name and value
 * (so colour never carries the meaning alone). Rows link to the agent. */
import { Link } from "react-router";
import type { Agent } from "../../lib/types";
import { Swatch, cx } from "../ui";

export interface BarRow { agent: Agent; value: number; note?: string }

export function Bars({ rows, format, tone = true }: { rows: BarRow[]; format: (v: number) => string; tone?: boolean }) {
  const lo = Math.min(0, ...rows.map((r) => r.value)), hi = Math.max(0, ...rows.map((r) => r.value));
  const span = hi - lo || 1, zero = (-lo / span) * 100;
  return (
    <ul className="grid gap-[7px]">
      {rows.map(({ agent: a, value: v, note }) => {
        const w = (Math.abs(v) / span) * 100;
        return (
          <li key={a.id}>
            <Link to={`/agents/${a.id}`} className="group grid grid-cols-[minmax(0,150px)_1fr_72px] items-center gap-3 text-[12.5px]" title={note ? `${a.name}: ${format(v)} · ${note}` : `${a.name}: ${format(v)}`}>
              <span className="flex min-w-0 items-center gap-2"><Swatch agent={a} size={8} /><span className="truncate group-hover:text-gold">{a.name}</span></span>
              <span className="relative h-[14px]">
                <span className="absolute inset-y-0 w-px bg-line-2" style={{ left: `${zero}%` }} />
                <span
                  className={cx("absolute inset-y-[2px] transition-opacity group-hover:opacity-100", a.fixed_twin ? "opacity-55" : "opacity-90")}
                  style={{
                    left: v >= 0 ? `${zero}%` : `${zero - w}%`, width: `${Math.max(w, 0.6)}%`,
                    background: a.fixed_twin ? `repeating-linear-gradient(135deg, var(--s-${a.key}) 0 3px, transparent 3px 6px)` : `var(--s-${a.key})`,
                    borderRadius: v >= 0 ? "0 4px 4px 0" : "4px 0 0 4px",
                  }}
                />
              </span>
              <span className={cx("tabular text-right font-medium", tone && (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted"))}>{format(v)}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
