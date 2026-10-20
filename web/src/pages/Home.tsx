/* The live race: the 3D network as the hero, then the headline numbers, the
 * race chart, the standings, the week in plain words and the latest moves. */
import { ArrowRight, BookOpen, FlaskConical, Pause, Play, ScrollText } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { RaceChart } from "../components/charts/RaceChart";
import { Sparkline } from "../components/charts/Sparkline";
import { useChartTheme } from "../components/charts/useChartTheme";
import { Badge, Container, Delta, Empty, Section, SectionHead, Stat, Swatch, cx } from "../components/ui";
import { color, info, ranked } from "../lib/agents";
import { useJSON, useLive } from "../lib/data";
import { chf, date, dateShort, nextRunLabel, pct, plural, share, signedChf } from "../lib/format";
import type { Agent, RunData, WeeklyData } from "../lib/types";

const Network3D = lazy(() => import("../components/network/Network3D"));

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
      <Section id="race">
        <SectionHead eyebrow="The race" title="Every account, every day"
          intro={`All ${d.agents.length} accounts started with ${chf(d.initial_capital_chf)} CHF on ${date(d.start)}. Each line is an account's value after every close, after all trading costs.`} />
        <RaceChart data={d} />
      </Section>
      <Standings d={d} />
      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
          <Weekly />
          <LatestMoves d={d} />
        </div>
      </Section>
      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-2">
          <LearningPays d={d} />
          <MoneyMap d={d} />
        </div>
      </Section>
      <Explore />
    </>
  );
}

/* ---------- hero ---------- */

function HeroShell({ children }: { children?: React.ReactNode }) {
  return (
    <section data-theme="dark" className="relative isolate -mt-16 flex min-h-[900px] flex-col overflow-hidden bg-bg text-ink lg:block lg:h-[max(640px,min(94vh,900px))] lg:min-h-0">
      <div className="pointer-events-none absolute inset-0 -z-10" style={{
        background: "radial-gradient(60% 55% at 62% 46%, rgba(212,178,106,0.16), transparent 70%), radial-gradient(40% 40% at 20% 90%, rgba(212,178,106,0.06), transparent 70%)",
      }} />
      {children}
    </section>
  );
}

function Hero({ d }: { d: RunData }) {
  const navigate = useNavigate();
  const days = d.agents[0]?.equity.length || 1;
  const [day, setDay] = useState(days - 1);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => setDay(days - 1), [days]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setDay((x) => {
      if (x >= days - 1) { setPlaying(false); return x; }
      return x + 1;
    }), 650);
    return () => clearInterval(t);
  }, [playing, days]);

  const racing = d.agents.filter((a) => !a.benchmark);
  const leader = ranked(racing)[0];
  const spy = d.agents.find((a) => a.key === "benchmark");
  const shownDate = d.agents[0]?.equity[day]?.[0] || d.last;

  return (
    <HeroShell>
      <Suspense fallback={<div className="absolute inset-0 grid place-items-center"><div className="size-40 animate-pulse rounded-full bg-gold/10 blur-2xl" /></div>}>
        <Network3D data={d} day={day} focus={focus} setFocus={setFocus} onSelect={(a) => navigate(`/agents/${a.id}`)} />
      </Suspense>
      <div className="pointer-events-none absolute inset-0 hidden lg:block" style={{
        background: "linear-gradient(90deg, rgba(11,10,8,0.92) 0%, rgba(11,10,8,0.55) 34%, rgba(11,10,8,0) 58%), linear-gradient(0deg, rgba(11,10,8,1) 0%, rgba(11,10,8,0) 30%), linear-gradient(180deg, rgba(11,10,8,0.85) 0%, rgba(11,10,8,0) 18%)",
      }} />
      <div className="pointer-events-none absolute inset-0 lg:hidden" style={{
        background: "linear-gradient(0deg, rgba(11,10,8,1) 0%, rgba(11,10,8,0.94) 46%, rgba(11,10,8,0) 72%), linear-gradient(180deg, rgba(11,10,8,0.8) 0%, rgba(11,10,8,0) 14%)",
      }} />
      <Container className="pointer-events-none relative flex flex-1 flex-col justify-end pb-10 pt-[400px] lg:h-full lg:pt-28">
        <div className="pointer-events-auto max-w-[620px]">
          <div className="eyebrow mb-5 flex items-center gap-3 text-gold">
            <span className="h-px w-8 bg-gold/60" /> Live experiment · day {days} · since {date(d.start)}
          </div>
          <h1 className="display text-[3.1rem] leading-[0.98] sm:text-[4.6rem]">
            Can machines<br /><span className="gold-text italic">beat the market?</span>
          </h1>
          <p className="mt-6 max-w-[520px] text-[16.5px] leading-relaxed text-ink-2">
            {plural(racing.length, "trading agent")}, from simple rules to Claude reading the news, each manage {chf(d.initial_capital_chf)} CHF of paper money on {Object.keys(d.prices).length} world markets.
            Two yardsticks keep them honest: the S&amp;P 500, and a monkey picking at random.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/agents" className="inline-flex items-center gap-2 rounded-full bg-gold px-5 py-2.5 text-[14px] font-medium text-gold-ink shadow-[0_8px_30px_-8px_rgba(212,178,106,0.6)] transition hover:bg-gold-2">
              Meet the agents <ArrowRight size={16} />
            </Link>
            <Link to="/methodology" className="inline-flex items-center gap-2 rounded-full border border-line-2 px-5 py-2.5 text-[14px] font-medium text-ink transition hover:border-gold/50">
              How it works
            </Link>
          </div>
        </div>

        <div className="pointer-events-auto mt-10 grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
          <div className="glass flex items-center gap-4 rounded-2xl px-4 py-3">
            <button type="button" onClick={() => { if (day >= days - 1) setDay(0); setPlaying((p) => !p); }}
              className="grid size-9 shrink-0 place-items-center rounded-full bg-gold text-gold-ink" aria-label={playing ? "Pause the replay" : "Replay since launch"}>
              {playing ? <Pause size={15} /> : <Play size={15} className="translate-x-[1px]" />}
            </button>
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex justify-between text-[12px]">
                <span className="text-ink-2">{day === days - 1 ? "Today" : "Replay"} · <span className="text-ink">{date(shownDate)}</span></span>
                <span className="text-muted">day {day + 1} of {days}</span>
              </div>
              <input type="range" min={0} max={days - 1} value={day} onChange={(e) => { setPlaying(false); setDay(+e.target.value); }}
                aria-label="Day since launch" className="v3-range w-full" />
            </div>
          </div>
          <div className="glass hidden gap-5 rounded-2xl px-5 py-3 text-[12px] text-ink-2 md:flex">
            <span><b className="text-ink">Leader</b> {leader?.name} <Delta value={leader?.stats.total_return}>{pct(leader?.stats.total_return)}</Delta></span>
            <span><b className="text-ink">S&amp;P 500</b> <Delta value={spy?.stats.total_return}>{pct(spy?.stats.total_return)}</Delta></span>
            <span className="text-muted">Drag to turn · hover an agent</span>
          </div>
        </div>
      </Container>
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
  return (
    <section className="relative border-b border-line">
      <Container className="grid grid-cols-2 gap-3 py-8 md:grid-cols-3 lg:grid-cols-5">
        <div className="card col-span-2 flex flex-col justify-between gap-4 p-5 ring-1 ring-gold/20 md:col-span-1 lg:col-span-1">
          <div className="eyebrow text-gold">In the lead</div>
          <div>
            <Link to={`/agents/${leader.id}`} className="flex items-center gap-2 text-[17px] font-medium hover:text-gold">
              <Swatch agent={leader} /> {leader.name}
            </Link>
            <div className="tabular mt-2 text-[1.9rem] font-medium leading-none text-up">{pct(leader.stats.total_return)}</div>
            <div className="mt-2 text-[13px] text-muted">{chf(leader.stats.final_equity_chf)} CHF</div>
          </div>
        </div>
        <Stat label="S&P 500 (SPY)" value={<Delta value={spy?.stats.total_return}>{pct(spy?.stats.total_return)}</Delta>}
          sub={`${beatSpy} of ${racing.length} agents ahead of it`} />
        <Stat label="The Monkey" value={<Delta value={monkey?.stats.total_return}>{pct(monkey?.stats.total_return)}</Delta>}
          sub={`${beatMonkey} of ${racing.length} agents ahead of luck`} />
        <Stat label="Trades so far" value={fills.toLocaleString("en")} sub={`${held} positions held · ${queued} orders queued`} />
        <Stat label="Next update" value={<span className="text-[1.25rem]">{nextRunLabel()}</span>}
          sub={`Prices to the ${dateShort(d.last)} close`} />
      </Container>
    </section>
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
      <SectionHead eyebrow="Standings" title="The leaderboard"
        intro="Ranked by account value at the last close. The two yardsticks are shown in place but not ranked: an agent has to beat both to show it has an edge."
        right={<Link to="/analytics" className="inline-flex items-center gap-1.5 text-[13.5px] text-gold hover:text-gold-2">Full analytics <ArrowRight size={14} /></Link>} />
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
                  <td className="py-3.5 pl-5">
                    {yard ? <span className="text-[11px] uppercase tracking-wider text-gold">Ref</span>
                      : <span className={cx("tabular text-[15px]", rank === 1 ? "text-gold" : "text-muted")}>{String(rank).padStart(2, "0")}</span>}
                  </td>
                  <td className="py-3">
                    <Link to={`/agents/${a.id}`} className="flex items-center gap-3">
                      <Swatch agent={a} />
                      <span className="min-w-0">
                        <span className="block font-medium group-hover:text-gold">{a.name}</span>
                        <span className="block truncate text-[12.5px] text-muted">{a.fixed_twin ? "Same rules, never re-tuned" : info(a).tagline}</span>
                      </span>
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

/* ---------- the week in plain words ---------- */

function Weekly() {
  const w = useJSON<WeeklyData>("weekly");
  const r = w?.reports?.[0];
  const paras = r ? r.text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean) : [];
  return (
    <article className="card relative overflow-hidden p-7 sm:p-9">
      <div className="pointer-events-none absolute -right-20 -top-20 size-64 rounded-full bg-gold/10 blur-3xl" />
      <div className="eyebrow mb-3 flex items-center gap-2 text-gold"><ScrollText size={13} /> The week in plain words</div>
      {r ? (
        <>
          <h3 className="display text-[1.9rem]">{dateShort(r.week_start)} – {date(r.week_end)}</h3>
          <div className="prose-v3 mt-5 max-h-[520px] overflow-y-auto pr-2 text-[15px] leading-[1.75] text-ink-2">
            <p className="text-[16.5px] text-ink first-letter:float-left first-letter:mr-2 first-letter:font-[family-name:var(--font-display)] first-letter:text-[3.4rem] first-letter:leading-[0.85] first-letter:text-gold">{paras[0]}</p>
            {paras.slice(1).map((p, i) => <p key={i}>{p}</p>)}
          </div>
          <div className="mt-6 flex items-center gap-2 border-t border-line pt-4 text-[12px] text-muted">
            Written by Claude from the week's facts. It describes; it decides nothing.
          </div>
        </>
      ) : (
        <p className="mt-4 text-muted">{w === undefined ? "Loading…" : "The first weekly report appears on Saturday morning."}</p>
      )}
    </article>
  );
}

/* ---------- latest moves ---------- */

function LatestMoves({ d }: { d: RunData }) {
  const items = useMemo(() => {
    type Move = { agent: Agent; kind: "BOUGHT" | "SOLD" | "QUEUED BUY" | "QUEUED SELL"; ticker: string; detail: string; pnl?: number | null; date: string };
    // The newest fills first, at most two per account, then a few orders
    // queued for the next open, so no single busy account fills the list.
    const fills: Move[] = [], queued: Move[] = [];
    d.agents.filter((a) => !a.fixed_twin).forEach((a) => {
      a.trades.slice().reverse().slice(0, 2).forEach((t) => fills.push({ agent: a, kind: t.side === "BUY" ? "BOUGHT" : "SOLD", ticker: t.ticker,
        detail: t.reason, pnl: t.side === "SELL" ? t.pnl_chf : null, date: t.date }));
      const seen = new Set<string>();
      a.pending_orders.filter((o) => !seen.has(o.side + o.ticker) && seen.add(o.side + o.ticker)).slice(0, 1)
        .forEach((o) => queued.push({ agent: a, kind: o.side === "BUY" ? "QUEUED BUY" : "QUEUED SELL", ticker: o.ticker, detail: o.reason, date: d.last }));
    });
    fills.sort((x, y) => (x.date < y.date ? 1 : x.date > y.date ? -1 : 0));
    return [...fills.slice(0, 8), ...queued.slice(0, 4)];
  }, [d]);
  return (
    <div className="card flex flex-col p-7">
      <div className="mb-5 flex items-center justify-between">
        <div className="eyebrow text-gold">Latest moves</div>
        <Link to="/trades" className="text-[13px] text-gold hover:text-gold-2">All trades →</Link>
      </div>
      <ul className="grid gap-1">
        {items.map((m, i) => (
          <li key={i} className="flex items-start gap-3 rounded-xl px-2 py-2.5 hover:bg-surface-2">
            <span className="mt-1.5"><Swatch agent={m.agent} size={8} /></span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px]">
                <span className={cx("text-[10.5px] font-semibold tracking-wider",
                  m.kind === "BOUGHT" ? "text-up" : m.kind === "SOLD" ? "text-down" : "text-gold")}>{m.kind}</span>
                <span className="font-mono text-[13px] font-medium">{m.ticker}</span>
                <span className="truncate text-muted">· {m.agent.name}</span>
                <span className="ml-auto shrink-0 text-[12px] text-faint">{m.kind.startsWith("QUEUED") ? "next open" : dateShort(m.date)}</span>
              </div>
              <div className="mt-0.5 line-clamp-1 text-[12.5px] text-muted">
                {m.pnl != null && <Delta value={m.pnl} className="mr-1.5">{signedChf(m.pnl)} CHF ·</Delta>}{m.detail}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------- does learning pay? ---------- */

function LearningPays({ d }: { d: RunData }) {
  const pairs = d.agents.filter((a) => a.learning && !a.fixed_twin)
    .map((a) => [a, d.agents.find((b) => b.fixed_twin && b.key === a.key)] as const).filter((p): p is [Agent, Agent] => !!p[1]);
  const reviews = pairs.reduce((n, [a]) => n + (a.learning_log?.length || 0), 0);
  return (
    <div className="card p-7">
      <div className="eyebrow mb-2 text-gold">Experiment</div>
      <h3 className="display text-[1.9rem]">Does learning pay?</h3>
      <p className="mt-2 text-[14px] text-muted">
        Each rule-based strategy runs twice: one re-tunes itself every month on the last three years, its twin never changes.
        {reviews ? ` ${plural(reviews, "monthly review")} so far.` : " The first review is on the first trading day of next month; until then the twins match."}
      </p>
      <div className="mt-5 grid gap-2">
        {pairs.map(([a, b]) => {
          const diff = a.stats.final_equity_chf - b.stats.final_equity_chf;
          return (
            <Link key={a.id} to={`/agents/${a.id}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-4 rounded-xl border border-line px-4 py-3 hover:border-gold/30">
              <span className="flex items-center gap-2.5 text-[14px]"><Swatch agent={a} /> {a.name}</span>
              <span className="tabular text-[13px] text-muted">{pct(a.stats.total_return)} vs {pct(b.stats.total_return)}</span>
              <Badge tone={diff > 0.5 ? "up" : diff < -0.5 ? "down" : "neutral"}>{Math.abs(diff) < 0.5 ? "even" : `${signedChf(diff)} CHF`}</Badge>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- where the money is ---------- */

function MoneyMap({ d }: { d: RunData }) {
  const accts = d.agents.filter((a) => !a.fixed_twin);
  return (
    <div className="card p-7">
      <div className="eyebrow mb-2 text-gold">Portfolios</div>
      <h3 className="display text-[1.9rem]">Where the money is</h3>
      <p className="mt-2 text-[14px] text-muted">Each bar is one account today: a segment per holding, sized by its share. The plain part is cash.</p>
      <div className="mt-5 grid gap-3.5">
        {accts.map((a) => {
          const eq = a.stats.final_equity_chf || 1;
          const cash = Math.max(0, a.cash_chf / eq);
          return (
            <div key={a.id}>
              <div className="mb-1.5 flex items-center justify-between text-[12.5px]">
                <span className="flex items-center gap-2"><Swatch agent={a} size={8} /> {a.name}</span>
                <span className="text-muted">{a.positions.length} holdings · {share(cash)} cash</span>
              </div>
              <div className="flex h-2.5 gap-[2px] overflow-hidden rounded-full bg-surface-3">
                {a.positions.slice().sort((x, y) => y.value_chf - x.value_chf).map((p) => (
                  <div key={p.ticker} title={`${p.ticker} · ${chf(p.value_chf)} CHF (${share(p.value_chf / eq, 1)})`}
                    style={{ width: `${(p.value_chf / eq) * 100}%`, background: color(a.key), opacity: 0.55 + 0.45 * Math.min(1, p.value_chf / eq / 0.15) }} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- explore ---------- */

function Explore() {
  const cards = [
    { to: "/research", icon: FlaskConical, title: "Research", text: "Five years of replays, a walk-forward test and the luck-versus-skill verdicts." },
    { to: "/methodology", icon: BookOpen, title: "Methodology", text: "How the simulation works: costs, timing, data, and the traps it avoids." },
    { to: "/journal", icon: ScrollText, title: "Project journal", text: "How Vanguard3 grew, from three simple rules to Claude reading the news." },
  ];
  return (
    <Section className="pt-0">
      <div className="grid gap-4 md:grid-cols-3">
        {cards.map(({ to, icon: Icon, title, text }) => (
          <Link key={to} to={to} className="card group p-7 transition hover:-translate-y-0.5 hover:border-gold/30">
            <Icon size={20} className="text-gold" />
            <h3 className="display mt-5 text-[1.7rem]">{title}</h3>
            <p className="mt-2 text-[14px] text-muted">{text}</p>
            <span className="mt-5 inline-flex items-center gap-1.5 text-[13px] text-gold">Open <ArrowRight size={14} className="transition group-hover:translate-x-0.5" /></span>
          </Link>
        ))}
      </div>
    </Section>
  );
}

