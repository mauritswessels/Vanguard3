/* One agent in depth: how it thinks, how it is doing against the yardsticks,
 * what it holds, every decision with its reasons, and how it learns. */
import { ArrowLeft, ArrowRight, History } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ActivityFeed, TripCard, VerdictBadge } from "../components/agent";
import { PairCard } from "../components/HeadToHead";
import { ReportCardPanel } from "../components/ReportCard";
import { LineChart, type Line } from "../components/charts/LineChart";
import { useChartTheme } from "../components/charts/useChartTheme";
import { Badge, Container, Delta, Empty, Section, Segmented, Stat, Swatch, cx } from "../components/ui";
import { badge, color, info, ranked } from "../lib/agents";
import { useJSON, useLive } from "../lib/data";
import { chf, date, dateShort, num, pct, plural, share, signedChf, swissTime } from "../lib/format";
import { aiCosts, curve, pairs, range, stats } from "../lib/metrics";
import type { Agent, LearnerAI, NewsAI, Point, RunData, SkillData } from "../lib/types";

export default function AgentProfile() {
  const { id } = useParams();
  const d = useLive();
  const skill = useJSON<SkillData>("skill");
  if (d === undefined) return <Section><div className="h-[60vh] animate-pulse rounded-3xl bg-surface" /></Section>;
  const a = d?.agents.find((x) => x.id === id);
  if (!d || !a) return <Section><Empty>No agent called “{id}”. <Link className="text-gold" to="/agents">See all agents →</Link></Empty></Section>;
  const s = skill?.accounts.find((x) => x.id === a.id);
  return <Profile key={a.id} d={d} a={a} verdict={s} />;
}

function Profile({ d, a, verdict }: { d: RunData; a: Agent; verdict?: SkillData["accounts"][number] }) {
  const i = info(a);
  const all = range("all", d);
  const st = stats(a, d, all);
  const spy = d.agents.find((x) => x.key === "benchmark");
  const racing = ranked(d.agents.filter((x) => !x.benchmark));
  const rank = racing.findIndex((x) => x.id === a.id) + 1;
  const twin = d.agents.find((x) => x.key === a.key && x.id !== a.id);
  const vsSpy = spy ? a.stats.total_return - spy.stats.total_return : null;

  return (
    <>
      <section className="relative overflow-hidden border-b border-line">
        <div className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(50% 80% at 85% 0%, color-mix(in srgb, ${color(a.key)} 18%, transparent), transparent 70%)` }} />
        <Container className="relative py-12 sm:py-16">
          <Link to="/agents" className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-gold"><ArrowLeft size={14} /> All agents</Link>
          <div className="mt-8 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Swatch agent={a} size={12} />
                <Badge tone="gold">{badge(a)}</Badge>
                <Badge>{i.family}</Badge>
                {verdict?.verdict && <VerdictBadge verdict={verdict.verdict} />}
              </div>
              <h1 className="display text-[3rem] sm:text-[4.4rem]">{a.name}</h1>
              <p className="mt-4 text-[18px] text-ink-2">{a.fixed_twin ? "The same rules as its learning twin, but its settings never change." : i.tagline}</p>
            </div>
            <div className="text-left lg:text-right">
              <div className="eyebrow">Account value</div>
              <div className="tabular mt-2 text-[2.6rem] font-medium leading-none">{chf(a.stats.final_equity_chf)} <span className="text-[1.1rem] text-muted">CHF</span></div>
              <Delta value={a.stats.total_return} className="mt-2 block text-[17px]">{pct(a.stats.total_return)} since {dateShort(d.start)}</Delta>
            </div>
          </div>
        </Container>
      </section>

      <Container className="grid grid-cols-2 gap-3 py-8 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Rank" value={a.benchmark ? "Yardstick" : `${rank} of ${racing.length}`} sub={a.joined && a.joined > d.start ? `joined ${dateShort(a.joined)}` : undefined} />
        {(() => {
          // Against each yardstick over the days both were trading (newer
          // files); older ones only have the return since each start.
          const fair = a.same_days?.benchmark;
          const v = fair ? fair.difference : vsSpy;
          return <Stat label="vs S&P 500" value={<Delta value={v}>{v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(2) + " pts"}</Delta>}
            sub={fair ? `same ${plural(fair.days, "day")} since ${dateShort(fair.from)}` : "since each started"} />;
        })()}
        {a.same_days?.equal_weight
          ? <Stat label="vs all markets" value={<Delta value={a.same_days.equal_weight.difference}>{(a.same_days.equal_weight.difference >= 0 ? "+" : "−") + Math.abs(a.same_days.equal_weight.difference * 100).toFixed(2) + " pts"}</Delta>}
              sub={`equal shares, same ${plural(a.same_days.equal_weight.days, "day")}`} />
          : <Stat label="Largest drop" value={pct(a.stats.max_drawdown)} sub="from a peak" />}
        <Stat label="Win rate" value={a.stats.win_rate == null ? "–" : share(a.stats.win_rate)} sub={`${plural(st.closed, "closed position")} · ${a.stats.trades} fills`} />
        {a.report_card?.graded_5
          ? <Stat label="Calls right" value={share(a.report_card.hit_rate_5)} sub={`of ${a.report_card.graded_5}, after 5 days vs SPY`} />
          : <Stat label="Largest drop" value={pct(a.stats.max_drawdown)} sub={`from a peak · ${share(st.book.cashPct)} cash`} />}
        {(() => {
          const ai = aiCosts(d).find((c) => c.agent.id === a.id);
          return ai ? <Stat label="Claude cost" value={`${num(ai.costChf, 2)} CHF`} sub={isFinite(ai.perChf) ? `${num(ai.perChf, 0)} CHF profit per CHF` : `${ai.calls} calls`} />
            : <Stat label="Costs paid" value={chf(a.stats.commissions_chf + a.stats.slippage_fx_chf)} sub="fees, slippage, FX" />;
        })()}
      </Container>

      <Section className="pt-4">
        <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
          <Performance d={d} a={a} twin={twin} />
          <div className="card p-7">
            <div className="eyebrow mb-3 text-gold">How it thinks</div>
            <div className="prose-v3 text-[15px] leading-relaxed text-ink-2">{i.thinks.map((p, k) => <p key={k}>{p}</p>)}</div>
            <ul className="mt-6 grid gap-2">
              {i.rules.map((r) => <li key={r} className="flex gap-3 text-[13.5px]"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-gold" />{r}</li>)}
            </ul>
            {Object.keys(a.params).length > 0 && (
              <div className="mt-6 flex flex-wrap gap-1.5 border-t border-line pt-5">
                {Object.entries(a.params).map(([k, v]) => <span key={k} className="rounded-md bg-surface-3 px-2 py-1 font-mono text-[11px] text-ink-2">{k}={String(v)}</span>)}
              </div>
            )}
            {twin && (
              <Link to={`/agents/${twin.id}`} className="mt-6 flex items-center justify-between rounded-xl border border-line px-4 py-3 text-[13.5px] hover:border-gold/30">
                <span className="flex items-center gap-2.5"><Swatch agent={twin} /> {a.fixed_twin ? "Its learning twin" : "Its fixed twin"}: {twin.name}</span>
                <Delta value={twin.stats.total_return}>{pct(twin.stats.total_return)}</Delta>
              </Link>
            )}
          </div>
        </div>
      </Section>

      {(() => {
        const mine = pairs(d).filter((p) => p.a.id === a.id || p.b.id === a.id);
        return mine.length > 0 && (
          <Section className="pt-0">
            <div className="grid gap-4 md:grid-cols-2">{mine.map((p) => <PairCard key={p.a.id + p.b.id} p={p} question={p.question} />)}</div>
          </Section>
        );
      })()}

      {verdict && verdict.summary.length > 0 && (
        <Section className="pt-0">
          <div className="card flex flex-col gap-5 p-7 md:flex-row md:items-start">
            <div className="md:w-56">
              <div className="eyebrow mb-3 text-gold">Skill or luck?</div>
              <VerdictBadge verdict={verdict.verdict} />
              <div className="mt-3 text-[12px] text-muted">{verdict.verdict_from ? `Judged on ${verdict.verdict_from}` : ""}</div>
            </div>
            <div className="prose-v3 flex-1 text-[14.5px] leading-relaxed text-ink-2">{verdict.summary.map((p, k) => <p key={k}>{p}</p>)}</div>
            <Link to="/research#skill" className="shrink-0 text-[13px] text-gold hover:text-gold-2">How this is tested →</Link>
          </div>
        </Section>
      )}

      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <Holdings a={a} d={d} />
          <Learning a={a} d={d} />
        </div>
      </Section>

      {a.report_card && <Section className="pt-0"><ReportCardPanel a={a} /></Section>}

      <Section className="pt-0"><TradeChart d={d} a={a} /></Section>

      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <div className="mb-5 flex items-end justify-between">
              <div>
                <div className="eyebrow mb-2 text-gold">Positions</div>
                <h2 className="display text-[2rem]">Every position, entry to exit</h2>
              </div>
              <Link to="/trades" className="text-[13px] text-gold hover:text-gold-2">All trades →</Link>
            </div>
            <div className="grid gap-3">
              {a.trips.length ? a.trips.slice().sort((x, y) => (x.status === y.status ? (x.entry_date < y.entry_date ? 1 : -1) : x.status === "open" ? -1 : 1))
                .slice(0, 30).map((t) => <TripCard key={t.id} a={a} t={t} />) : <Empty>No positions yet.</Empty>}
            </div>
          </div>
          <div>
            <div className="mb-5">
              <div className="eyebrow mb-2 text-gold">Decisions</div>
              <h2 className="display text-[2rem]">Day by day</h2>
            </div>
            <div className="card p-7"><ActivityFeed a={a} limit={15} /></div>
          </div>
        </div>
      </Section>
    </>
  );
}

/* ---------- performance against the yardsticks ---------- */

function Performance({ d, a, twin }: { d: RunData; a: Agent; twin?: Agent }) {
  const theme = useChartTheme();
  const r = range("all", d);
  const spy = d.agents.find((x) => x.key === "benchmark");
  const monkey = d.agents.find((x) => x.key === "monkey");
  const others = [twin, spy, monkey].filter((x): x is Agent => !!x && x.id !== a.id);
  const lines: Line[] = [a, ...others].map((x) => ({
    id: x.id, points: curve(x, d, r, "return"), color: theme.series(x.key),
    style: x.id === a.id ? "solid" : x.key === "monkey" ? "dotted" : "dashed", width: x.id === a.id ? 3 : 1,
  }));
  return (
    <div className="card p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="eyebrow text-gold">Performance</div>
          <div className="mt-1 text-[13px] text-muted">Return since launch, against the yardsticks{twin ? " and its twin" : ""}</div>
        </div>
        <div className="flex flex-wrap gap-3 text-[12px] text-ink-2">
          {[a, ...others].map((x) => <span key={x.id} className="flex items-center gap-1.5"><Swatch agent={x} size={8} />{x.name}</span>)}
        </div>
      </div>
      <LineChart lines={lines} format={(v) => pct(v, 1)} height={320} zeroLine={0} />
    </div>
  );
}

/* ---------- what it holds ---------- */

function Holdings({ a, d }: { a: Agent; d: RunData }) {
  const eq = a.stats.final_equity_chf || 1;
  const rows = a.positions.slice().sort((x, y) => y.value_chf - x.value_chf);
  const max = Math.max(...rows.map((p) => p.value_chf / eq), 0.01);
  return (
    <div className="card p-7">
      <div className="mb-5 flex items-end justify-between">
        <div>
          <div className="eyebrow mb-2 text-gold">The book</div>
          <h2 className="display text-[2rem]">What it holds</h2>
        </div>
        <div className="text-right text-[12.5px] text-muted">{rows.length} positions<br />{chf(a.cash_chf)} CHF cash ({share(a.cash_chf / eq)})</div>
      </div>
      {rows.length ? (
        <div className="scroll-x">
          <table className="w-full min-w-[460px] text-[13.5px]">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-left text-[11px] uppercase tracking-[0.1em] text-muted">
                <th className="pb-2.5 font-medium">Market</th><th className="pb-2.5 font-medium">Share</th>
                <th className="pb-2.5 text-right font-medium">Value</th><th className="pb-2.5 text-right font-medium">Result</th><th className="pb-2.5 text-right font-medium">Since</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.ticker} className="border-b border-line last:border-0">
                  <td className="py-2.5"><span className="font-mono font-medium">{p.ticker}</span><div className="text-[11.5px] text-faint">{d.groups[p.ticker]}</div></td>
                  <td className="w-[28%] py-2.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full" style={{ width: `${(p.value_chf / eq / max) * 100}%`, background: color(a.key) }} /></div>
                      <span className="tabular w-11 text-right text-[12px] text-muted">{share(p.value_chf / eq, 1)}</span>
                    </div>
                  </td>
                  <td className="tabular py-2.5 text-right">{chf(p.value_chf)}</td>
                  <td className="py-2.5 text-right"><Delta value={p.pnl_chf}>{signedChf(p.pnl_chf)}</Delta> <Delta value={p.pnl_pct} className="text-[11.5px]">({pct(p.pnl_pct, 1)})</Delta></td>
                  <td className="py-2.5 text-right text-muted">{dateShort(p.entry_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>No positions: everything is in cash.</Empty>}
      <div className="mt-6 border-t border-line pt-5">
        <div className="eyebrow mb-3">Orders for the next open</div>
        {a.pending_orders.length ? (
          <ul className="grid gap-2 text-[13.5px]">
            {a.pending_orders.map((o, k) => (
              <li key={k} className="flex flex-wrap items-center gap-2">
                <span className={cx("text-[10.5px] font-semibold tracking-wider", o.side === "BUY" ? "text-up" : "text-down")}>{o.side}</span>
                <span className="font-mono">{o.ticker}</span><span className="tabular text-muted">{o.quantity} shares</span>
                <span className="text-muted">· {o.reason}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-[13.5px] text-muted">Nothing queued.</p>}
      </div>
    </div>
  );
}

/* ---------- how it learns ---------- */

function Learning({ a, d }: { a: Agent; d: RunData }) {
  if (a.team) {
    const rows = Object.entries(a.team.backing).sort((x, y) => y[1] - x[1]);
    return (
      <Panel eyebrow="Its team" title="Whom it backs">
        <p className="text-[14px] text-muted">{a.team.why}. Chosen {date(a.team.chosen)}; it chooses again on the first trading day of each month.</p>
        <ul className="mt-5 grid gap-3">
          {rows.map(([name, w]) => {
            const ag = d.agents.find((x) => x.name === name);
            return (
              <li key={name}>
                <div className="mb-1.5 flex justify-between text-[13.5px]"><span className="flex items-center gap-2">{ag && <Swatch agent={ag} size={8} />}{name}</span><span className="tabular text-muted">{share(w)}</span></div>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-gold" style={{ width: `${w * 100}%` }} /></div>
              </li>
            );
          })}
        </ul>
      </Panel>
    );
  }
  const ai = a.ai;
  if (ai && "kind" in ai && ai.kind === "news") return <NewsPanel ai={ai as NewsAI} />;
  if (ai) return <LearnerPanel ai={ai as LearnerAI} d={d} />;
  if (a.benchmark) {
    return (
      <Panel eyebrow="Yardstick" title={a.key === "monkey" ? "Pure chance" : "The bar to clear"}>
        <div className="prose-v3 text-[14.5px] leading-relaxed text-ink-2">{info(a).thinks.map((p, k) => <p key={k}>{p}</p>)}</div>
      </Panel>
    );
  }
  if (!a.learning) {
    return (
      <Panel eyebrow="Learning" title="It never changes">
        <p className="text-[14.5px] leading-relaxed text-ink-2">This twin keeps the settings it started with. Its learning twin replays the last three years every month and switches settings when another is clearly better. Comparing the two shows whether learning pays off.</p>
      </Panel>
    );
  }
  const log = (a.learning_log || []).slice().reverse();
  return (
    <Panel eyebrow="Learning" title="Monthly self-review">
      <p className="text-[14px] text-muted">On the first trading day of every month it replays its strategy over the last three years with every allowed setting, and switches only if another setting is clearly better.</p>
      {log.length ? (
        <ul className="mt-5 grid gap-2">
          {log.map((e, k) => (
            <li key={k} className="rounded-xl border border-line p-4 text-[13px]">
              <div className="flex items-center justify-between"><span>{date(e.date)}</span><Badge tone={e.switched ? "gold" : "neutral"}>{e.switched ? "Switched" : "Kept"}</Badge></div>
              <div className="mt-2 font-mono text-[11.5px] text-muted">{Object.entries(e.new).map(([k2, v]) => `${k2}=${v}`).join(" · ")}</div>
              <div className="mt-1 text-[12px] text-faint">Sharpe before {num(e.sharpe_old)} · best found {num(e.sharpe_best)}</div>
            </li>
          ))}
        </ul>
      ) : <div className="mt-5"><Empty>The first review is on the first trading day of next month.</Empty></div>}
    </Panel>
  );
}

function Panel({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <div className="card p-7">
      <div className="eyebrow mb-2 text-gold">{eyebrow}</div>
      <h2 className="display mb-4 text-[2rem]">{title}</h2>
      {children}
    </div>
  );
}

function NewsPanel({ ai }: { ai: NewsAI }) {
  const card = ai.report_card;
  const m = ai.midday && ai.midday.time.slice(0, 10) >= (ai.decided || "") ? ai.midday : null;
  const view = (m?.ok && m.view) || ai.market_view;
  return (
    <Panel eyebrow={`Claude · ${ai.model}`} title="Its view of the market">
      {view && <blockquote className="display border-l-2 border-gold pl-5 text-[1.45rem] italic leading-snug text-ink">“{view}”</blockquote>}
      <div className="mt-4 text-[12.5px] text-muted">
        {ai.status}.{m ? ` Midday check at ${swissTime(m.time)} Swiss time: ${m.ok ? (m.trades ? plural(m.trades, "trade") + " at live prices" : "no changes") : m.status}.` : ""}
        {ai.calls ? ` ${plural(ai.calls, "look")} at the news so far, about ${ai.est_cost_usd.toFixed(2)} USD of Claude usage (estimate).` : ""}
      </div>
      {card && card.calls.length > 0 && (
        <div className="mt-6 border-t border-line pt-5">
          <div className="eyebrow mb-2">Report card</div>
          <p className="text-[13px] text-muted">
            Each call is graded against the S&amp;P 500: a buy is right if the market then beat SPY. After 5 trading days:{" "}
            <b className="text-ink">{card.graded_5 ? `${share(card.hit_rate_5 ?? 0)} right of ${card.graded_5}` : "not graded yet"}</b>.
            After 20: <b className="text-ink">{card.graded_20 ? `${share(card.hit_rate_20 ?? 0)} right of ${card.graded_20}` : "not graded yet"}</b>. Claude sees this record every time it decides.
          </p>
          <ul className="mt-4 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {card.calls.slice().reverse().slice(0, 9).map((c, k) => (
              <li key={k} className="rounded-lg bg-surface-2 px-3 py-2 text-[12px]">
                <div className="flex justify-between"><span className="font-mono">{c.ticker}</span><span className={c.side === "BUY" ? "text-up" : "text-down"}>{c.side}</span></div>
                <div className="mt-0.5 flex justify-between text-muted"><span>{dateShort(c.date)}</span>
                  {c.edge_5 == null ? <span className="text-faint">pending</span> : <Delta value={c.edge_5}>{pct(c.edge_5, 1)}</Delta>}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-5 text-[11.5px] text-faint">The reasons shown are the model's own stated reasons, not a guaranteed account of how it reached its answer.</p>
    </Panel>
  );
}

function LearnerPanel({ ai, d }: { ai: LearnerAI; d: RunData }) {
  const W = ai.weights;
  const lean = W ? Object.keys(W.BUY).map((k) => [k, W.BUY[k] - (W.SELL[k] + W.HOLD[k] + W.BUY[k]) / 3] as const).sort((x, y) => y[1] - x[1]) : [];
  const max = Math.max(...lean.map(([, v]) => Math.abs(v)), 0.001);
  const shadow = d.last < ai.live_from;
  return (
    <Panel eyebrow={ai.kind === "learner_review" ? "Learning · reviewed by Claude Opus" : "Reinforcement learning"} title="What it has learned">
      <p className="text-[14px] text-muted">
        {shadow ? `Practice mode until ${date(ai.live_from)}: it decides and learns every day but places no orders yet. ` : "Trading with paper money and learning after every close. "}
        {ai.pretrain?.sessions ? `Practised on ${ai.pretrain.sessions.toLocaleString("en")} past sessions first. ` : ""}
        {plural(ai.days_learned, "live day")} learned, {ai.updates.toLocaleString("en")} updates in total, {share(ai.epsilon)} of decisions random so it keeps exploring.
      </p>
      {lean.length > 0 && (
        <div className="mt-5">
          <div className="eyebrow mb-3">Pull towards buying, by feature</div>
          <ul className="grid gap-2">
            {lean.map(([k, v]) => (
              <li key={k} className="grid grid-cols-[150px_1fr_52px] items-center gap-3 text-[12.5px]">
                <span className="truncate text-ink-2">{k}</span>
                <div className="relative h-2">
                  <div className="absolute left-1/2 top-0 h-full w-px bg-line-2" />
                  <div className={cx("absolute top-0 h-full rounded-full", v >= 0 ? "left-1/2 bg-up" : "right-1/2 bg-down")} style={{ width: `${(Math.abs(v) / max) * 50}%` }} />
                </div>
                <span className="tabular text-right text-muted">{(v >= 0 ? "+" : "") + v.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11.5px] text-faint">The model's own weights: positive means a high value of that feature makes it more likely to buy. A simplified view of a model that weighs all features together.</p>
        </div>
      )}
      {ai.kind === "learner_review" && ai.review && (
        <div className="mt-6 border-t border-line pt-5">
          <div className="eyebrow mb-2">Opus's verdicts, {dateShort(ai.review.date)}</div>
          <p className="text-[13px] italic text-ink-2">“{ai.review.view}”</p>
          <ul className="mt-4 grid gap-2">
            {ai.review.picks.map((p, k) => (
              <li key={k} className="grid grid-cols-[72px_64px_1fr] gap-3 text-[12.5px]">
                <span className="font-mono">{p.ticker}</span>
                <span className={p.approve ? "text-up" : "text-down"}>{p.approve ? "Approved" : "Turned down"}</span>
                <span className="text-muted">{p.action === "BUY" ? "Buy" : "Sell"}: {p.reason}</span>
              </li>
            ))}
          </ul>
          {ai.est_cost_usd != null && <p className="mt-3 text-[11.5px] text-faint">Estimated Claude cost so far: about {ai.est_cost_usd.toFixed(2)} USD.</p>}
        </div>
      )}
    </Panel>
  );
}

/* ---------- a market's price with this agent's trades ---------- */

function TradeChart({ d, a }: { d: RunData; a: Agent }) {
  const theme = useChartTheme();
  const tickers = useMemo(() => {
    const score = new Map<string, number>();
    a.trades.forEach((t) => score.set(t.ticker, (score.get(t.ticker) || 0) + 1));
    [...a.positions, ...a.pending_orders].forEach((p) => score.set(p.ticker, (score.get(p.ticker) || 0) + 100));
    return [...score].sort((x, y) => y[1] - x[1]).map(([t]) => t);
  }, [a]);
  const [ticker, setTicker] = useState(tickers[0] || Object.keys(d.prices)[0]);
  const [history, setHistory] = useState<"live" | "6m">("live");
  const back = useJSON<RunData>(history === "6m" ? "backtest" : null);
  const px: Point[] = history === "6m" && back?.prices[ticker] ? back.prices[ticker].slice(-130) : d.prices[ticker] || [];
  const mine = a.trades.filter((t) => t.ticker === ticker && px.some((p) => p[0] === t.date));
  const lines: Line[] = [{
    id: ticker, points: px, color: theme.series(a.key), width: 2,
    markers: mine.map((t) => ({ date: t.date, side: t.side, text: t.side === "BUY" ? "Buy" : "Sell" })),
  }];
  return (
    <div className="card p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-2 text-gold">On the chart</div>
          <h2 className="display text-[2rem]">Its trades in {ticker}</h2>
          <p className="mt-1 text-[13px] text-muted">Price in {d.currencies[ticker] || "USD"}. Arrows mark {a.name}'s buys and sells.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="History" value={history} options={[["live", "Since launch"], ["6m", "6 months"]]} onChange={setHistory} />
          <select value={ticker} onChange={(e) => setTicker(e.target.value)} aria-label="Market"
            className="rounded-full border border-line-2 bg-surface px-4 py-2 font-mono text-[13px] text-ink outline-none focus:border-gold">
            {tickers.length > 0 && <optgroup label="Traded or held">{tickers.map((t) => <option key={t}>{t}</option>)}</optgroup>}
            <optgroup label="All markets">{Object.keys(d.prices).filter((t) => !tickers.includes(t)).map((t) => <option key={t}>{t}</option>)}</optgroup>
          </select>
        </div>
      </div>
      {history === "6m" && back === undefined ? <div className="grid h-[320px] place-items-center text-muted"><History className="animate-pulse" /></div>
        : <LineChart lines={lines} format={(v) => num(v, 2)} height={320} />}
      {tickers.length === 0 && <p className="mt-3 text-[13px] text-muted">{a.name} has not traded yet. <Link to="/agents" className="text-gold">Other agents <ArrowRight className="inline" size={12} /></Link></p>}
    </div>
  );
}
