/* Research: is any lead skill or luck, how the rules did over five years of
 * history, and whether tuning their settings really helps (walk-forward). */
import { AlertTriangle, ArrowUpRight, Boxes } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { VerdictBadge } from "../components/agent";
import { LineChart, type Line } from "../components/charts/LineChart";
import { useChartTheme } from "../components/charts/useChartTheme";
import { Delta, Empty, Section, SectionHead, Swatch, cx } from "../components/ui";
import { useJSON } from "../lib/data";
import { chf, date, num, pct, share } from "../lib/format";
import type { RunData, SkillData, SkillWindow, WalkForwardData } from "../lib/types";

export default function Research() {
  return (
    <>
      <Section className="pb-6">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Research</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">Is the edge real?</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            A lead after a few weeks proves little: with this many agents racing, one is bound to be ahead by chance. These studies ask harder questions.
            Is a lead bigger than luck can explain? Would the rules have worked over five years of history? Does tuning their settings help, when tested blind?
          </p>
        </div>
        <div className="mt-8 flex max-w-3xl gap-3 rounded-2xl border border-gold/25 bg-gold-wash p-5 text-[13.5px] leading-relaxed text-ink-2">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-gold" />
          <p><b className="text-ink">Past prices flatter every agent a little.</b> The markets were chosen in 2026 because they are large today, so companies that shrank or vanished
            in those years are missing (survivorship bias). The news agents cannot be replayed at all: Claude already knows how those years turned out. Trust the live race more.</p>
        </div>
      </Section>
      <Skill />
      <Replay />
      <WalkForward />
      <Section className="pt-0">
        <a href="lab/" className="card group flex flex-col gap-6 overflow-hidden p-8 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-5">
            <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-gold-wash text-gold"><Boxes size={22} /></div>
            <div>
              <h3 className="display text-[1.9rem]">3D AI research lab</h3>
              <p className="mt-2 max-w-xl text-[14px] text-muted">A training sandbox in the browser where a separate reinforcement-learning agent practises on past prices, with its network drawn in 3D. It never touches the live accounts.</p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 text-[14px] text-gold">Open the lab <ArrowUpRight size={16} className="transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5" /></span>
        </a>
      </Section>
    </>
  );
}

/* ---------- skill or luck ---------- */

function Skill() {
  const s = useJSON<SkillData>("skill");
  return (
    <Section id="skill">
      <SectionHead eyebrow="Study 1" title="Skill or luck?"
        intro={s ? s.method : "Every account is compared with hundreds of monkeys picking at random under the same rules and costs, and with buy-and-hold SPY."} />
      {s === undefined ? <div className="h-80 animate-pulse rounded-3xl bg-surface" /> : !s ? (
        <Empty>The first results of this study appear after its next run.</Empty>
      ) : (
        <div className="grid gap-6">
          {s.past && (() => {
            const before = s.past_before_tuning;
            const isBefore = (a: SkillData["accounts"][number]) => a.past?.window === "before_tuning";
            return (
              <div className={before ? "grid gap-6 xl:grid-cols-2" : ""}>
                <MonkeyHistogram win={s.past} title={before ? "The learning versions, on the last five years" : "The agents that can be replayed"}
                  accounts={s.accounts.filter((a) => !isBefore(a) && !a.past?.in_sample)} />
                {before && <MonkeyHistogram win={before} title="Fixed settings and the AI Learner, on the years before their settings were picked"
                  accounts={s.accounts.filter(isBefore)} />}
              </div>
            );
          })()}
          <div className="grid gap-3 md:grid-cols-3">
            {(Object.entries(s.verdict_meanings) as [keyof SkillData["verdict_meanings"], string][]).map(([v, text]) => (
              <div key={v} className="card p-5"><VerdictBadge verdict={v} /><p className="mt-3 text-[13px] text-muted">{text.replace(/\s*\(see settings\.edge\)/, ` (${share(s.settings.edge)} a year)`)}</p></div>
            ))}
          </div>
          <div className="card scroll-x">
            <table className="w-full min-w-[880px] text-[13.5px]">
              <thead>
                <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
                  <th className="py-3.5 pl-5 font-medium">Account</th><th className="py-3.5 font-medium">Verdict</th>
                  <th className="py-3.5 pr-4 text-right font-medium">Past: beat monkeys</th><th className="py-3.5 pr-4 text-right font-medium">Past: vs SPY a year</th>
                  <th className="py-3.5 pr-4 text-right font-medium">Live days</th><th className="py-3.5 pr-5 text-right font-medium">Live: beat monkeys</th>
                </tr>
              </thead>
              <tbody>
                {s.accounts.filter((a) => !a.yardstick).map((a) => (
                  <tr key={a.id} className="border-b border-line align-top last:border-0">
                    <td className="py-3.5 pl-5"><Link to={`/agents/${a.id}`} className="flex items-center gap-2.5 hover:text-gold"><Swatch agent={{ key: a.key, fixed_twin: a.fixed_twin, benchmark: false }} />{a.name}</Link></td>
                    <td className="py-3.5"><VerdictBadge verdict={a.verdict} /><div className="mt-1 text-[11.5px] text-faint">{a.verdict_from ? `from ${a.verdict_from}` : ""}</div></td>
                    <td className="tabular py-3.5 pr-4 text-right text-ink-2">{a.past ? share(a.past.percentile_vs_monkeys) : "–"}
                      {a.past && <div className="text-[11.5px] text-faint">{years(a.past)}{a.past.in_sample ? " · in-sample, not counted" : ""}</div>}</td>
                    <td className="py-3.5 pr-4 text-right">{a.past ? <Delta value={a.past.excess_vs_spy}>{pct(a.past.excess_vs_spy, 1)}</Delta> : "–"}
                      {a.past && <div className="tabular text-[11.5px] text-faint">{pct(a.past.excess_vs_spy_low, 0)} to {pct(a.past.excess_vs_spy_high, 0)}</div>}</td>
                    <td className="tabular py-3.5 pr-4 text-right text-ink-2">{a.live ? a.live.days : "–"}</td>
                    <td className="tabular py-3.5 pr-5 text-right text-ink-2">{a.live ? share(a.live.percentile_vs_monkeys) : "–"}
                      {a.live?.weeks_needed != null && <div className="text-[11.5px] text-faint">~{Math.round(a.live.weeks_needed)} more weeks to tell</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[12.5px] text-muted">Run {date(s.as_of)} on {s.data_source} prices · {s.settings.monkeys} monkeys · a lead counts as skill below a {share(s.settings.alpha)} chance of luck, after allowing for the number of agents tested.</p>
        </div>
      )}
    </Section>
  );
}

const years = (w: { from: string; to: string }) => `${w.from.slice(0, 4)}–${w.to.slice(2, 4)}`;

/** Where the agents' returns fall among the monkeys' over one window of
 *  years (the luck distribution). */
function MonkeyHistogram({ win, accounts, title }: { win: SkillWindow; accounts: SkillData["accounts"]; title: string }) {
  const theme = useChartTheme();
  const [hover, setHover] = useState<number | null>(null);
  const agents = accounts.filter((a) => a.past && !a.yardstick);
  const spy = agents[0]?.past?.spy_return;
  const vals = [...win.monkey_returns, ...agents.map((a) => a.past!.return), ...(spy != null ? [spy] : [])];
  const lo = Math.floor(Math.min(...vals) * 10) / 10, hi = Math.ceil(Math.max(...vals) * 10) / 10;
  const BINS = 32, step = (hi - lo) / BINS;
  const bins = useMemo(() => {
    const b = Array.from({ length: BINS }, (_, i) => ({ from: lo + i * step, to: lo + (i + 1) * step, n: 0 }));
    win.monkey_returns.forEach((v) => { b[Math.min(BINS - 1, Math.floor((v - lo) / step))].n++; });
    return b;
  }, [win, lo, step]);
  const W = 1000, H = 260, PAD = 34, top = 56;
  const X = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - 2 * PAD);
  const maxN = Math.max(...bins.map((b) => b.n));
  const Y = (n: number) => H - PAD - (n / maxN) * (H - PAD - top);
  const tick = hi - lo > 2 ? 0.5 : 0.25;
  const ticks = Array.from({ length: Math.round((hi - lo) / tick) + 1 }, (_, i) => lo + i * tick).filter((t) => t <= hi + 1e-9);
  return (
    <div className="card min-w-0 p-6">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow text-gold">{years(win)} · {win.monkeys} monkeys</div>
          <h3 className="mt-1 text-[16px] font-medium">{title}</h3>
          <p className="mt-1 max-w-2xl text-[13px] text-muted">Each bar counts monkeys whose random picks earned that return from {date(win.from)} to {date(win.to)}. The coloured lines are the agents over the same days; the dashed line is SPY.</p>
        </div>
        <div className="text-[12.5px] text-ink-2">{hover != null ? `${bins[hover].n} monkeys earned ${pct(bins[hover].from, 0)} to ${pct(bins[hover].to, 0)}` : "Hover a bar"}</div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Histogram of the monkeys' returns ${years(win)}, with each agent's return marked`}>
        {bins.map((b, i) => (
          <rect key={i} x={X(b.from) + 1} y={Y(b.n)} width={Math.max(1, X(b.to) - X(b.from) - 2)} height={H - PAD - Y(b.n)} rx={3}
            fill={hover === i ? theme.gold : theme.faint} opacity={hover === i ? 0.9 : 0.55}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        ))}
        <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke={theme.line} />
        {ticks.map((t) => <text key={t} x={X(t)} y={H - PAD + 18} textAnchor="middle" fontSize="11" fill={theme.muted}>{pct(t, 0)}</text>)}
        {spy != null && <line x1={X(spy)} x2={X(spy)} y1={top - 30} y2={H - PAD} stroke={theme.text} strokeDasharray="5 4" strokeWidth={1.4} />}
        {spy != null && <text x={X(spy) + 5} y={top - 22} fontSize="11" fill={theme.text}>SPY</text>}
        {agents.map((a, i) => (
          <g key={a.id}>
            <line x1={X(a.past!.return)} x2={X(a.past!.return)} y1={top - 6 + i * 9} y2={H - PAD} stroke={theme.series(a.key)} strokeWidth={2} strokeDasharray={a.fixed_twin ? "4 3" : undefined} />
            <circle cx={X(a.past!.return)} cy={top - 6 + i * 9} r={4} fill={a.fixed_twin ? "none" : theme.series(a.key)} stroke={theme.series(a.key)} strokeWidth={2} />
          </g>
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-[12.5px] text-ink-2">
        {agents.map((a) => (
          <span key={a.id} className="flex items-center gap-2"><Swatch agent={{ key: a.key, fixed_twin: a.fixed_twin, benchmark: false }} size={8} />{a.name} {pct(a.past!.return, 0)}
            <span className="text-faint">· beat {share(a.past!.percentile_vs_monkeys)}</span></span>
        ))}
      </div>
    </div>
  );
}

/* ---------- five-year replay ---------- */

function Replay() {
  const theme = useChartTheme();
  const b = useJSON<RunData>("backtest");
  const lines: Line[] = useMemo(() => (b ? b.agents.map((a) => ({
    id: a.id, points: a.equity, color: theme.series(a.key), style: a.benchmark ? "dashed" : "solid", width: a.benchmark ? 1 : 2,
  })) : []), [b, theme]);
  return (
    <Section>
      <SectionHead eyebrow="Study 2" title="Five years of history"
        intro="The rule-based strategies with their launch settings, replayed over the last five years as if they had traded then, with the same costs and the same next-open fills. A sanity check that the rules are not broken, refreshed every week." />
      {b === undefined ? <div className="h-96 animate-pulse rounded-3xl bg-surface" /> : !b ? <Empty>No replay yet.</Empty> : (
        <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
          <div className="card p-6">
            <div className="mb-2 flex flex-wrap gap-4 text-[12.5px]">{b.agents.map((a) => <span key={a.id} className="flex items-center gap-2"><Swatch agent={a} size={8} />{a.name}</span>)}</div>
            <LineChart lines={lines} format={chf} height={340} zeroLine={b.initial_capital_chf} />
            <p className="mt-2 text-[12px] text-faint">Account value in CHF, {date(b.start)} to {date(b.last)}.</p>
          </div>
          <div className="card divide-y divide-line">
            {b.agents.slice().sort((x, y) => y.stats.final_equity_chf - x.stats.final_equity_chf).map((a) => (
              <div key={a.id} className="p-5">
                <div className="flex items-center justify-between"><span className="flex items-center gap-2.5 text-[14px] font-medium"><Swatch agent={a} />{a.name}</span>
                  <Delta value={a.stats.total_return} className="text-[15px] font-medium">{pct(a.stats.total_return, 1)}</Delta></div>
                <div className="mt-2 grid grid-cols-4 gap-2 text-[12px] text-muted">
                  <span>{pct(a.stats.cagr, 1)}<br /><span className="text-faint">a year</span></span>
                  <span>{num(a.stats.sharpe)}<br /><span className="text-faint">Sharpe</span></span>
                  <span>{pct(a.stats.max_drawdown, 0)}<br /><span className="text-faint">max drop</span></span>
                  <span>{a.stats.trades}<br /><span className="text-faint">fills</span></span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

/* ---------- walk-forward ---------- */

function WalkForward() {
  const theme = useChartTheme();
  const w = useJSON<WalkForwardData>("walkforward");
  const [pick, setPick] = useState(0);
  if (w === undefined) return <Section className="pt-0"><div className="h-96 animate-pulse rounded-3xl bg-surface" /></Section>;
  if (!w) return null;
  const a = w.agents[pick];
  const lines: Line[] = [
    { id: "tuned", points: a.tuned_equity, color: theme.series(a.key), width: 2 },
    { id: "default", points: a.default_equity, color: theme.series(a.key), width: 1, style: "dotted" },
    { id: "spy", points: w.benchmark.equity, color: theme.series("benchmark"), width: 1, style: "dashed" },
  ];
  return (
    <Section className="pt-0">
      <SectionHead eyebrow="Study 3" title="Does tuning help, tested blind?"
        intro={`Each year the settings are re-picked using only the ${w.train_years} years before it, then traded blind on that year. Stitching those blind years together shows what tuning would really have earned, compared with simply keeping the default settings.`} />
      <div className="mb-5 flex flex-wrap gap-2">
        {w.agents.map((x, i) => (
          <button key={x.key} type="button" onClick={() => setPick(i)} aria-pressed={i === pick}
            className={cx("flex items-center gap-2 rounded-full border px-4 py-2 text-[13px] transition", i === pick ? "border-gold/50 bg-gold-wash text-ink" : "border-line-2 text-muted hover:text-ink")}>
            <Swatch agent={{ key: x.key, fixed_twin: false, benchmark: false }} size={8} />{x.name}
          </button>
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="card p-6">
          <div className="mb-2 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
            <span>Solid: tuned each year</span><span>Dotted: default settings</span><span>Dashed: {w.benchmark.name}</span>
          </div>
          <LineChart lines={lines} format={chf} height={320} zeroLine={100000} />
        </div>
        <div className="card p-6">
          <div className="grid grid-cols-3 gap-3 border-b border-line pb-5 text-center">
            {[["Tuned", a.tuned.return], ["Default", a.default.return], [w.benchmark.name, w.benchmark.return]].map(([l, v]) => (
              <div key={l as string}><div className="text-[11.5px] text-muted">{l}</div><Delta value={v as number} className="mt-1 block text-[1.2rem] font-medium">{pct(v as number, 0)}</Delta></div>
            ))}
          </div>
          <ul className="mt-4 grid gap-2.5 text-[12.5px]">
            {a.folds.map((f) => (
              <li key={f.test[0]} className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3">
                <span className="text-muted">{f.test[0].slice(0, 4)}–{f.test[1].slice(2, 4)} <span className="font-mono text-[11px] text-faint">{Object.values(f.params).join("/")}</span></span>
                <Delta value={f.test_return}>{pct(f.test_return, 1)}</Delta>
                <span className="w-16 text-right text-faint">vs {pct(f.default_test_return, 1)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-[11.5px] text-faint">Each blind year: the settings picked, the tuned return, and the default settings' return.</p>
        </div>
      </div>
    </Section>
  );
}
