/* The live race at a glance: the 3D globe of accounts and markets, the
 * headline numbers and the charts that matter. The explanations live on
 * the Agents, Methodology and Journal pages. */
import { Expand, Hand, Minus, Pause, Play, Plus, RotateCcw, Shrink } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Bars } from "../components/charts/Bars";
import { LineChart, type Line } from "../components/charts/LineChart";
import { RaceChart } from "../components/charts/RaceChart";
import { Sparkline } from "../components/charts/Sparkline";
import { useChartTheme } from "../components/charts/useChartTheme";
import type { NetworkApi } from "../components/network/Network3D";
import { Badge, Container, Delta, Empty, Section, Stat, Swatch, cx } from "../components/ui";
import { badge, color, ranked } from "../lib/agents";
import { useLive } from "../lib/data";
import { chf, date, dateShort, nextRunLabel, pct, share, signedChf } from "../lib/format";
import { drawdownCurve, exposure, range } from "../lib/metrics";
import type { Agent, RunData } from "../lib/types";

const Network3D = lazy(() => import("../components/network/Network3D"));

/** The globe's sector colours (kept here so the legend renders before the 3D code loads). */
const SECTORS: [string, string][] = [
  ["US stocks", "#efe3c4"], ["Stock funds (ETFs)", "#d9b46c"], ["Bonds and commodities", "#9fb4c8"],
  ["European stocks", "#b9a7e0"], ["Swiss stocks", "#e79a86"],
];

export default function Home() {
  const d = useLive();
  if (d === undefined) return <HeroShell />;
  if (d === null || d.status === "waiting") {
    return <Section><Empty>The live race has not started yet. The first results appear after the next evening run.</Empty></Section>;
  }
  return (
    <>
      <Hero d={d} />
      <Headline d={d} />
      <Section className="py-10">
        <Title eyebrow="The race" title="Return since launch" />
        <RaceChart data={d} />
      </Section>
      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel eyebrow="Ranking" title="Total return">
            <Bars rows={ranked(d.agents).map((a) => ({ agent: a, value: a.stats.total_return }))} format={(v) => pct(v)} />
          </Panel>
          <Panel eyebrow={`Last session · ${dateShort(d.last)}`} title="Profit on the day">
            <Bars rows={dayRows(d)} format={(v) => signedChf(v)} />
          </Panel>
        </div>
      </Section>
      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
          <Drawdowns d={d} />
          <Exposure d={d} />
        </div>
      </Section>
      <Standings d={d} />
      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <LatestMoves d={d} />
          <Twins d={d} />
        </div>
      </Section>
    </>
  );
}

const dayRows = (d: RunData) => d.agents.map((a) => {
  const e = a.equity; return { agent: a, value: e.length < 2 ? 0 : e[e.length - 1][1] - e[e.length - 2][1] };
}).sort((x, y) => y.value - x.value);

function Title({ eyebrow, title, right }: { eyebrow: string; title: string; right?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="eyebrow mb-2 text-gold">{eyebrow}</div>
        <h2 className="display text-[2rem]">{title}</h2>
      </div>
      {right}
    </div>
  );
}

function Panel({ eyebrow, title, right, children, className }: { eyebrow: string; title: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("card min-w-0 p-6", className)}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="eyebrow mb-1.5 text-gold">{eyebrow}</div>
          <h3 className="text-[17px] font-medium">{title}</h3>
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

/* ---------- hero: the globe ---------- */

function HeroShell({ children }: { children?: React.ReactNode }) {
  return (
    <section data-theme="dark" className="relative isolate -mt-16 h-[max(620px,min(100svh,940px))] overflow-hidden bg-bg text-ink">
      <div className="pointer-events-none absolute inset-0 -z-10" style={{
        background: "radial-gradient(55% 60% at 50% 50%, rgba(212,178,106,0.14), transparent 70%)",
      }} />
      {children}
    </section>
  );
}

function Hero({ d }: { d: RunData }) {
  const navigate = useNavigate();
  const shell = useRef<HTMLDivElement>(null);
  const api = useRef<NetworkApi | null>(null);
  const days = d.agents[0]?.equity.length || 1;
  const [day, setDay] = useState(days - 1);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [explore, setExplore] = useState(false);
  const [full, setFull] = useState(false);
  const [touch] = useState(() => window.matchMedia("(pointer: coarse)").matches || window.innerWidth < 768);
  useEffect(() => setDay(days - 1), [days]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setDay((x) => {
      if (x >= days - 1) { setPlaying(false); return x; }
      return x + 1;
    }), 650);
    return () => clearInterval(t);
  }, [playing, days]);
  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === shell.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else shell.current?.requestFullscreen?.();
  };

  const racing = d.agents.filter((a) => !a.benchmark);
  const leader = ranked(racing)[0];
  const spy = d.agents.find((a) => a.key === "benchmark");
  const shownDate = d.agents[0]?.equity[day]?.[0] || d.last;
  const btn = "grid size-9 place-items-center rounded-full border border-line-2 bg-bg/60 text-ink-2 backdrop-blur transition hover:border-gold/50 hover:text-gold";

  return (
    <HeroShell>
      <div ref={shell} className="absolute inset-0 bg-bg">
        <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(55% 60% at 50% 50%, rgba(212,178,106,0.14), transparent 70%)" }} />
        <Suspense fallback={<div className="absolute inset-0 grid place-items-center"><div className="size-48 animate-pulse rounded-full bg-gold/10 blur-2xl" /></div>}>
          <Network3D data={d} day={day} focus={focus} setFocus={setFocus} onSelect={(a) => navigate(`/agents/${a.id}`)}
            apiRef={api} explore={explore} labels={!touch || explore || full} />
        </Suspense>
        <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-bg to-transparent" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-44 bg-gradient-to-t from-bg to-transparent" />

        <Container className="pointer-events-none relative flex h-full flex-col justify-between pb-6 pt-24">
          <div className="pointer-events-auto flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="eyebrow mb-3 flex items-center gap-3 text-gold"><span className="h-px w-6 bg-gold/60" />Live · day {days} · since {dateShort(d.start)}</div>
              <h1 className="display text-[2.4rem] leading-none sm:text-[3.2rem]">Can machines <span className="gold-text italic">beat the market?</span></h1>
            </div>
            <div className="glass hidden gap-6 rounded-2xl px-5 py-3 text-[12.5px] md:flex">
              <div><div className="eyebrow">Leader</div><Link to={`/agents/${leader.id}`} className="mt-1 flex items-center gap-2 hover:text-gold"><Swatch agent={leader} size={8} />{leader.name} <Delta value={leader.stats.total_return}>{pct(leader.stats.total_return)}</Delta></Link></div>
              <div><div className="eyebrow">S&amp;P 500</div><Delta value={spy?.stats.total_return} className="mt-1 block">{pct(spy?.stats.total_return)}</Delta></div>
            </div>
          </div>

          <div className="pointer-events-auto grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px] text-ink-2" aria-label="Market colours on the globe">
                {SECTORS.map(([n, c]) => <li key={n} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: c, boxShadow: `0 0 8px ${c}` }} />{n}</li>)}
              </ul>
              <div className="flex items-center gap-2">
                {touch && (
                  <button type="button" onClick={() => setExplore((e) => !e)} aria-pressed={explore}
                    className={cx("inline-flex h-9 items-center gap-2 rounded-full border px-4 text-[12.5px] backdrop-blur", explore ? "border-gold bg-gold text-gold-ink" : "border-line-2 bg-bg/60 text-ink-2")}>
                    <Hand size={14} /> {explore ? "Done" : "Explore"}
                  </button>
                )}
                <button type="button" className={btn} onClick={() => api.current?.zoom(0.8)} aria-label="Zoom in"><Plus size={15} /></button>
                <button type="button" className={btn} onClick={() => api.current?.zoom(1.25)} aria-label="Zoom out"><Minus size={15} /></button>
                <button type="button" className={btn} onClick={() => api.current?.reset()} aria-label="Reset the view"><RotateCcw size={14} /></button>
                <button type="button" className={btn} onClick={toggleFull} aria-label={full ? "Leave full screen" : "Full screen"}>{full ? <Shrink size={14} /> : <Expand size={14} />}</button>
              </div>
            </div>
            <div className="glass flex items-center gap-4 rounded-2xl px-4 py-3">
              <button type="button" onClick={() => { if (day >= days - 1) setDay(0); setPlaying((p) => !p); }}
                className="grid size-9 shrink-0 place-items-center rounded-full bg-gold text-gold-ink" aria-label={playing ? "Pause the replay" : "Replay since launch"}>
                {playing ? <Pause size={15} /> : <Play size={15} className="translate-x-[1px]" />}
              </button>
              <div className="min-w-0 flex-1">
                <div className="mb-1.5 flex justify-between gap-3 text-[12px]">
                  <span className="text-ink-2">{day === days - 1 ? "Today" : "Replay"} · <span className="text-ink">{date(shownDate)}</span></span>
                  <span className="hidden text-muted sm:inline">{touch ? "Tap Explore to spin and pinch" : "Drag to spin · pinch or ⌘ + scroll to zoom · click an agent"}</span>
                </div>
                <input type="range" min={0} max={days - 1} value={day} onChange={(e) => { setPlaying(false); setDay(+e.target.value); }}
                  aria-label="Day since launch" className="v3-range w-full" />
              </div>
            </div>
          </div>
        </Container>
      </div>
    </HeroShell>
  );
}

/* ---------- headline numbers ---------- */

function Headline({ d }: { d: RunData }) {
  const racing = d.agents.filter((a) => !a.benchmark);
  const leader = ranked(racing)[0];
  const spy = d.agents.find((a) => a.key === "benchmark");
  const monkey = d.agents.find((a) => a.key === "monkey");
  const beatSpy = racing.filter((a) => spy && a.stats.final_equity_chf > spy.stats.final_equity_chf).length;
  const beatMonkey = racing.filter((a) => monkey && a.stats.final_equity_chf > monkey.stats.final_equity_chf).length;
  const fills = d.agents.reduce((n, a) => n + a.trades.length, 0);
  const queued = d.agents.reduce((n, a) => n + a.pending_orders.length, 0);
  const held = d.agents.reduce((n, a) => n + a.positions.length, 0);
  const best = dayRows(d)[0];
  return (
    <section className="border-b border-line">
      <Container className="grid grid-cols-2 gap-3 py-8 md:grid-cols-3 lg:grid-cols-6">
        <div className="card col-span-2 flex flex-col justify-between gap-4 p-5 ring-1 ring-gold/20 md:col-span-1">
          <div className="eyebrow text-gold">In the lead</div>
          <div>
            <Link to={`/agents/${leader.id}`} className="flex items-center gap-2 text-[16px] font-medium hover:text-gold"><Swatch agent={leader} /> {leader.name}</Link>
            <div className="tabular mt-2 text-[1.8rem] font-medium leading-none text-up">{pct(leader.stats.total_return)}</div>
            <div className="mt-2 text-[12.5px] text-muted">{chf(leader.stats.final_equity_chf)} CHF</div>
          </div>
        </div>
        <Stat label="S&P 500" value={<Delta value={spy?.stats.total_return}>{pct(spy?.stats.total_return)}</Delta>} sub={`${beatSpy} of ${racing.length} agents ahead`} />
        <Stat label="The Monkey" value={<Delta value={monkey?.stats.total_return}>{pct(monkey?.stats.total_return)}</Delta>} sub={`${beatMonkey} of ${racing.length} ahead of luck`} />
        <Stat label="Best last session" value={<Delta value={best.value}>{signedChf(best.value)}</Delta>} sub={best.agent.name} />
        <Stat label="Trades" value={fills.toLocaleString("en")} sub={`${held} held · ${queued} queued`} />
        <Stat label="Next update" value={<span className="text-[1.15rem]">{nextRunLabel()}</span>} sub={`Prices to ${dateShort(d.last)}`} />
      </Container>
    </section>
  );
}

/* ---------- drawdowns and exposure ---------- */

function Drawdowns({ d }: { d: RunData }) {
  const theme = useChartTheme();
  const lines: Line[] = useMemo(() => {
    const r = range("all", d);
    return d.agents.map((a) => ({
      id: a.id, points: drawdownCurve(a, d, r), color: theme.series(a.key),
      style: a.key === "monkey" ? "dotted" : a.fixed_twin || a.benchmark ? "dashed" : "solid", width: a.fixed_twin || a.benchmark ? 1 : 2,
    }));
  }, [d, theme]);
  return (
    <Panel eyebrow="Risk" title="Drop from each account's peak" right={<Link to="/analytics" className="text-[12.5px] text-gold hover:text-gold-2">Analytics →</Link>}>
      <LineChart lines={lines} format={(v) => pct(v, 1)} height={280} zeroLine={0} />
    </Panel>
  );
}

function Exposure({ d }: { d: RunData }) {
  const accts = d.agents.filter((a) => !a.fixed_twin);
  const ex = exposure(accts, d);
  const tint = (name: string) => SECTORS.find(([n]) => n === name)?.[1] || "var(--muted)";
  return (
    <Panel eyebrow="Portfolios" title="Invested vs cash">
      <ul className="grid gap-[9px]">
        {accts.map((a) => {
          const eq = a.stats.final_equity_chf || 1, inv = Math.max(0, 1 - a.cash_chf / eq);
          return (
            <li key={a.id}>
              <Link to={`/agents/${a.id}`} className="group grid grid-cols-[minmax(0,140px)_1fr_76px] items-center gap-3 text-[12.5px]"
                title={`${a.name}: ${share(inv)} invested in ${a.positions.length} markets`}>
                <span className="flex min-w-0 items-center gap-2"><Swatch agent={a} size={8} /><span className="truncate group-hover:text-gold">{a.name}</span></span>
                <span className="flex h-[12px] overflow-hidden rounded-full bg-surface-3">
                  <span className="h-full rounded-full" style={{ width: `${inv * 100}%`, background: color(a.key) }} />
                </span>
                <span className="tabular text-right text-muted">{share(inv)} · {a.positions.length}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="mt-6 border-t border-line pt-5">
        <div className="eyebrow mb-3">All accounts by kind of market</div>
        <div className="flex h-3 gap-[2px] overflow-hidden rounded-full">
          {ex.byGroup.map((g) => <span key={g.name} title={`${g.name}: ${share(g.pct, 1)}`} style={{ width: `${g.pct * 100}%`, background: tint(g.name) }} />)}
          <span title={`Cash: ${share(ex.cashPct, 1)}`} className="bg-surface-3" style={{ width: `${ex.cashPct * 100}%` }} />
        </div>
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-ink-2">
          {ex.byGroup.map((g) => (
            <li key={g.name} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: tint(g.name) }} />{g.name} <span className="text-muted">{share(g.pct)}</span></li>
          ))}
          <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-surface-3 ring-1 ring-line-2" />Cash <span className="text-muted">{share(ex.cashPct)}</span></li>
        </ul>
      </div>
    </Panel>
  );
}

/* ---------- standings ---------- */

function Standings({ d }: { d: RunData }) {
  const theme = useChartTheme();
  const rows = ranked(d.agents);
  let rank = 0;
  const dayChange = (a: Agent) => { const e = a.equity; return e.length < 2 ? null : e[e.length - 1][1] - e[e.length - 2][1]; };
  return (
    <Section id="standings" className="pt-0">
      <Title eyebrow="Standings" title="Leaderboard" right={<Link to="/agents" className="text-[13px] text-gold hover:text-gold-2">All agents →</Link>} />
      <div className="card scroll-x">
        <table className="w-full min-w-[820px] text-[14px]">
          <thead>
            <tr className="whitespace-nowrap border-b border-line text-left text-[11.5px] uppercase tracking-[0.1em] text-muted">
              <th className="w-14 py-3.5 pl-5 font-medium">#</th>
              <th className="py-3.5 font-medium">Agent</th>
              <th className="py-3.5 text-right font-medium">Value CHF</th>
              <th className="py-3.5 text-right font-medium">Return</th>
              <th className="py-3.5 text-right font-medium">Last day</th>
              <th className="py-3.5 text-right font-medium">Max drop</th>
              <th className="py-3.5 text-right font-medium">Fills</th>
              <th className="py-3.5 pr-2 text-right font-medium">Win rate</th>
              <th className="py-3.5 pr-5 text-right font-medium">Path</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => {
              const yard = a.benchmark;
              if (!yard) rank++;
              const dc = dayChange(a);
              return (
                <tr key={a.id} className={cx("group border-b border-line transition-colors last:border-0 hover:bg-surface-2", yard && "bg-gold-wash/40")}>
                  <td className="py-3 pl-5">
                    {yard ? <span className="text-[11px] uppercase tracking-wider text-gold">Ref</span>
                      : <span className={cx("tabular text-[15px]", rank === 1 ? "text-gold" : "text-muted")}>{String(rank).padStart(2, "0")}</span>}
                  </td>
                  <td className="py-3">
                    <Link to={`/agents/${a.id}`} className="flex items-center gap-3">
                      <Swatch agent={a} />
                      <span className="font-medium group-hover:text-gold">{a.name}</span>
                      <span className="hidden text-[12px] text-faint xl:inline">{badge(a)}</span>
                    </Link>
                  </td>
                  <td className="tabular py-3 text-right font-medium">{chf(a.stats.final_equity_chf)}</td>
                  <td className="py-3 text-right"><Delta value={a.stats.total_return} className="font-medium">{pct(a.stats.total_return)}</Delta></td>
                  <td className="py-3 text-right"><Delta value={dc}>{signedChf(dc)}</Delta></td>
                  <td className="tabular py-3 text-right text-ink-2">{a.stats.max_drawdown ? pct(a.stats.max_drawdown) : "0%"}</td>
                  <td className="tabular py-3 text-right text-ink-2">{a.stats.trades}</td>
                  <td className="tabular py-3 pr-2 text-right text-ink-2">{a.stats.win_rate == null ? "–" : share(a.stats.win_rate)}</td>
                  <td className="py-2 pr-5"><div className="flex justify-end"><Sparkline points={a.equity} color={theme.series(a.key)} /></div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

/* ---------- latest moves ---------- */

function LatestMoves({ d }: { d: RunData }) {
  const items = useMemo(() => {
    type Move = { agent: Agent; kind: "BOUGHT" | "SOLD" | "QUEUED BUY" | "QUEUED SELL"; ticker: string; pnl?: number | null; date: string };
    // The newest fills first, at most two per account, then a few orders
    // queued for the next open, so no single busy account fills the list.
    const fills: Move[] = [], queued: Move[] = [];
    d.agents.filter((a) => !a.fixed_twin).forEach((a) => {
      a.trades.slice().reverse().slice(0, 2).forEach((t) => fills.push({ agent: a, kind: t.side === "BUY" ? "BOUGHT" : "SOLD", ticker: t.ticker,
        pnl: t.side === "SELL" ? t.pnl_chf : null, date: t.date }));
      const seen = new Set<string>();
      a.pending_orders.filter((o) => !seen.has(o.side + o.ticker) && seen.add(o.side + o.ticker)).slice(0, 1)
        .forEach((o) => queued.push({ agent: a, kind: o.side === "BUY" ? "QUEUED BUY" : "QUEUED SELL", ticker: o.ticker, date: d.last }));
    });
    fills.sort((x, y) => (x.date < y.date ? 1 : x.date > y.date ? -1 : 0));
    return [...fills.slice(0, 8), ...queued.slice(0, 4)];
  }, [d]);
  return (
    <Panel eyebrow="Activity" title="Latest moves" right={<Link to="/trades" className="text-[12.5px] text-gold hover:text-gold-2">All trades →</Link>}>
      <ul className="grid gap-0.5">
        {items.map((m, i) => (
          <li key={i} className="grid grid-cols-[auto_88px_76px_1fr_auto] items-center gap-3 rounded-lg px-2 py-2 text-[13px] hover:bg-surface-2">
            <Swatch agent={m.agent} size={8} />
            <span className={cx("text-[10.5px] font-semibold tracking-wider", m.kind === "BOUGHT" ? "text-up" : m.kind === "SOLD" ? "text-down" : "text-gold")}>{m.kind}</span>
            <span className="font-mono font-medium">{m.ticker}</span>
            <span className="truncate text-muted">{m.agent.name}{m.pnl != null && <> · <Delta value={m.pnl}>{signedChf(m.pnl)} CHF</Delta></>}</span>
            <span className="text-[12px] text-faint">{m.kind.startsWith("QUEUED") ? "next open" : dateShort(m.date)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ---------- learning vs fixed twins ---------- */

function Twins({ d }: { d: RunData }) {
  const pairs = d.agents.filter((a) => a.learning && !a.fixed_twin)
    .map((a) => [a, d.agents.find((b) => b.fixed_twin && b.key === a.key)] as const).filter((p): p is readonly [Agent, Agent] => !!p[1]);
  const rows = pairs.flatMap(([a, b]) => [{ agent: a, value: a.stats.total_return }, { agent: b, value: b.stats.total_return }]);
  const reviews = pairs.reduce((n, [a]) => n + (a.learning_log?.length || 0), 0);
  return (
    <Panel eyebrow="Experiment" title="Learning vs fixed twins" right={<Badge>{reviews ? `${reviews} reviews` : "first review next month"}</Badge>}>
      <Bars rows={rows} format={(v) => pct(v)} />
      <div className="mt-5 grid gap-1.5 border-t border-line pt-4">
        {pairs.map(([a, b]) => {
          const diff = a.stats.final_equity_chf - b.stats.final_equity_chf;
          return (
            <div key={a.id} className="flex items-center justify-between text-[12.5px]">
              <span className="flex items-center gap-2 text-ink-2"><Swatch agent={a} size={8} />{a.name} vs its twin</span>
              <Badge tone={diff > 0.5 ? "up" : diff < -0.5 ? "down" : "neutral"}>{Math.abs(diff) < 0.5 ? "even" : `${signedChf(diff)} CHF`}</Badge>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
