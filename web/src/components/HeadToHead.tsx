/* The race's built-in experiments, head to head: the same idea with one
 * thing changed (a stronger model, an AI reviewer, monthly learning), each
 * pair compared on exactly the same days. */
import { Link } from "react-router";
import { aiCosts, type Pair } from "../lib/metrics";
import { chf, dateShort, num, pct, plural } from "../lib/format";
import type { RunData } from "../lib/types";
import { Sparkline } from "./charts/Sparkline";
import { useChartTheme } from "./charts/useChartTheme";
import { Badge, Delta, Swatch, cx } from "./ui";

const pts = (v: number, d = 2) => (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(d) + " pts";

/** Twins stay identical until the learning one's first monthly review. */
const same = (p: Pair) => p.days > 0 && p.path.every(([, v]) => Math.abs(v) < 1e-9);

function verdict(p: Pair) {
  if (same(p)) return { tone: "neutral" as const, text: "identical so far" };
  if (p.days < 5) return { tone: "neutral" as const, text: "just started" };
  if (p.ahead === "a") return { tone: "up" as const, text: `${p.a.name} clearly ahead` };
  if (p.ahead === "b") return { tone: "down" as const, text: `${p.b.name} clearly ahead` };
  return { tone: "neutral" as const, text: "too close to call" };
}

/** One pair as a card: the gap, its path, and whether it is real yet. */
export function PairCard({ p, question }: { p: Pair; question: string }) {
  const theme = useChartTheme();
  const v = verdict(p);
  return (
    <div className="card flex min-w-0 flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-medium leading-snug">{question}</h3>
        <Badge tone={v.tone}>{v.text}</Badge>
      </div>
      <div className="flex items-center gap-2 text-[12.5px] text-ink-2">
        <Link to={`/agents/${p.a.id}`} className="flex items-center gap-1.5 hover:text-gold"><Swatch agent={p.a} size={8} />{p.a.name}</Link>
        <span className="text-faint">vs</span>
        <Link to={`/agents/${p.b.id}`} className="flex items-center gap-1.5 hover:text-gold"><Swatch agent={p.b} size={8} />{p.b.name}</Link>
      </div>
      <div className="flex items-end justify-between gap-4">
        <div>
          <Delta value={p.lead} className="text-[1.6rem] font-medium leading-none">{pts(p.lead)}</Delta>
          <div className="mt-1.5 text-[12px] text-muted">{p.a.name}'s lead since {dateShort(p.from)}</div>
        </div>
        <Sparkline points={p.path} color={p.lead >= 0 ? theme.up : theme.down} width={130} height={40} />
      </div>
      <div className="grid grid-cols-3 gap-2 border-t border-line pt-4 text-[12px]">
        <div><div className="text-faint">Days compared</div><div className="tabular mt-0.5 text-ink">{p.days}</div></div>
        <div><div className="text-faint">Edge a year</div><div className="tabular mt-0.5 text-ink">{isFinite(p.edge) ? pct(p.edge, 0) : "–"}</div></div>
        <div><div className="text-faint">95% range</div><div className="tabular mt-0.5 text-ink">{isFinite(p.low) ? `${pct(p.low, 0)} to ${pct(p.high, 0)}` : "–"}</div></div>
      </div>
      <p className="text-[12px] text-muted">
        {same(p) ? "Same trades so far: they can only differ after the learning version's first monthly review." :
          p.ahead ? "The range no longer includes zero: the gap is bigger than day-to-day noise." :
          p.daysNeeded ? `If the gap holds, about ${plural(Math.ceil(p.daysNeeded / 5), "more week")} to tell it from noise.` :
            "Not enough days yet to say how long it will take."}
      </p>
    </div>
  );
}

/** Compact rows for the live page. */
export function PairRows({ list }: { list: (Pair & { question: string })[] }) {
  const max = Math.max(...list.map((p) => Math.abs(p.lead)), 0.0001);
  return (
    <ul className="grid gap-3.5">
      {list.map((p) => {
        const v = verdict(p);
        return (
          <li key={p.a.id + p.b.id}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-[12.5px]">
              <span className="truncate text-ink-2">{p.question}</span>
              <Badge tone={v.tone}>{v.text}</Badge>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_1fr_minmax(0,1fr)] items-center gap-3 text-[12px]">
              <span className="flex min-w-0 items-center justify-end gap-1.5 text-right"><span className="truncate">{p.b.name}</span><Swatch agent={p.b} size={7} /></span>
              <span className="relative h-[10px]">
                <span className="absolute inset-y-0 left-1/2 w-px bg-line-2" />
                <span className={cx("absolute inset-y-[1px]", p.lead >= 0 ? "left-1/2 rounded-r" : "right-1/2 rounded-l")}
                  style={{ width: `${(Math.abs(p.lead) / max) * 50}%`, background: `var(--s-${p.lead >= 0 ? p.a.key : p.b.key})` }} />
              </span>
              <span className="flex min-w-0 items-center gap-1.5"><Swatch agent={p.a} size={7} /><span className="truncate">{p.a.name}</span>
                <Delta value={p.lead} className="ml-auto shrink-0 font-medium">{pts(p.lead, 1)}</Delta></span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Profit per franc of Claude usage, for every account that pays for a model. */
export function AiCostTable({ d }: { d: RunData }) {
  const rows = aiCosts(d);
  if (!rows.length) return null;
  return (
    <div className="card scroll-x">
      <table className="w-full min-w-[720px] text-[13.5px]">
        <thead>
          <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
            {["Account", "Model", "Claude calls", "Claude cost CHF", "Profit CHF", "Profit per CHF of Claude"].map((h, i) => (
              <th key={h} className={cx("py-3.5 font-medium", i === 0 ? "pl-5" : "pr-5 text-right")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.agent.id} className="border-b border-line last:border-0">
              <td className="py-3 pl-5"><Link to={`/agents/${r.agent.id}`} className="flex items-center gap-2.5 hover:text-gold"><Swatch agent={r.agent} />{r.agent.name}</Link></td>
              <td className="py-3 pr-5 text-right font-mono text-[12px] text-ink-2">{r.model.replace("claude-", "")}</td>
              <td className="tabular py-3 pr-5 text-right text-ink-2">{r.calls}</td>
              <td className="tabular py-3 pr-5 text-right text-ink-2">{num(r.costChf, 2)}</td>
              <td className="py-3 pr-5 text-right"><Delta value={r.profit}>{chf(r.profit)}</Delta></td>
              <td className="py-3 pr-5 text-right"><Delta value={r.perChf} className="font-medium">{isFinite(r.perChf) ? num(r.perChf, 0) : "–"}</Delta></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
