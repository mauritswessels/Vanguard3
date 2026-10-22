/* Every position any agent has taken, from entry to exit, with the reasons
 * it gave at both ends. Filter by agent, status and market. */
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { TripCard } from "../components/agent";
import { Empty, Section, Segmented, Stat, cx } from "../components/ui";
import { ORDER } from "../lib/agents";
import { useLive } from "../lib/data";
import { share, signedChf } from "../lib/format";
import type { Agent, Trip } from "../lib/types";

type Status = "all" | "open" | "closed";
type Sort = "newest" | "best" | "worst";

export default function Trades() {
  const d = useLive();
  const [agent, setAgent] = useState("all");
  const [status, setStatus] = useState<Status>("all");
  const [sort, setSort] = useState<Sort>("newest");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(40);

  const rows = useMemo(() => {
    if (!d) return [];
    const out: { a: Agent; t: Trip }[] = [];
    d.agents.filter((a) => agent === "all" ? !a.fixed_twin : a.id === agent).forEach((a) => a.trips.forEach((t) => out.push({ a, t })));
    const query = q.trim().toUpperCase();
    return out
      .filter(({ t }) => status === "all" || t.status === status)
      .filter(({ t }) => !query || t.ticker.toUpperCase().includes(query))
      .sort((x, y) => sort === "best" ? y.t.pnl_chf - x.t.pnl_chf : sort === "worst" ? x.t.pnl_chf - y.t.pnl_chf
        : (y.t.exit_date || y.t.entry_date).localeCompare(x.t.exit_date || x.t.entry_date));
  }, [d, agent, status, sort, q]);

  if (d === undefined) return <Section><div className="h-[60vh] animate-pulse rounded-3xl bg-surface" /></Section>;
  if (!d) return <Section><Empty>No live data yet.</Empty></Section>;

  const closed = rows.filter((r) => r.t.status === "closed");
  const wins = closed.filter((r) => r.t.pnl_chf > 0).length;
  const total = rows.reduce((s, r) => s + r.t.pnl_chf, 0);
  const agents = d.agents.slice().sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key) || Number(a.fixed_twin) - Number(b.fixed_twin));

  return (
    <>
      <Section className="pb-6">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Trade explorer</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">Every position, and why</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            Each card is one position from the first buy to the last sell. Open it to read what the agent saw and said when it bought, and when it sold:
            the rule that fired, its score, and for the news agents the headlines they read.
          </p>
        </div>
      </Section>
      <Section className="pt-0">
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Positions" value={rows.length} sub={`${rows.length - closed.length} still open`} />
          <Stat label="Closed" value={closed.length} sub="sold at least once" />
          <Stat label="Win rate" value={closed.length ? share(wins / closed.length) : "–"} sub="of closed positions" />
          <Stat label="Result" value={<span className={cx(total > 0 ? "text-up" : total < 0 ? "text-down" : "")}>{signedChf(total)}</span>} sub="CHF, open positions at the last close" />
        </div>
        <div className="glass sticky top-16 z-30 mb-6 flex flex-wrap items-center gap-2 rounded-2xl p-2">
          <select value={agent} onChange={(e) => { setAgent(e.target.value); setShown(40); }} aria-label="Agent"
            className="rounded-full border border-line-2 bg-surface px-4 py-2 text-[13px] text-ink outline-none focus:border-gold">
            <option value="all">All agents (without twins)</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <Segmented label="Status" value={status} options={[["all", "All"], ["open", "Open"], ["closed", "Closed"]]} onChange={(v) => { setStatus(v); setShown(40); }} />
          <Segmented label="Sort" value={sort} options={[["newest", "Newest"], ["best", "Best"], ["worst", "Worst"]]} onChange={setSort} />
          <label className="ml-auto flex items-center gap-2 rounded-full border border-line-2 bg-surface px-4 py-2 text-[13px]">
            <Search size={14} className="text-muted" />
            <input value={q} onChange={(e) => { setQ(e.target.value); setShown(40); }} placeholder="Market, e.g. MSFT"
              className="w-36 bg-transparent font-mono text-ink outline-none placeholder:font-sans placeholder:text-faint" aria-label="Filter by market" />
          </label>
        </div>
        <div className="grid gap-3">
          {rows.length ? rows.slice(0, shown).map(({ a, t }) => <TripCard key={a.id + t.id} a={a} t={t} showAgent />) : <Empty>No positions match.</Empty>}
        </div>
        {rows.length > shown && (
          <div className="mt-6 text-center">
            <button type="button" onClick={() => setShown((n) => n + 40)} className="rounded-full border border-line-2 px-5 py-2.5 text-[13.5px] hover:border-gold/40 hover:text-gold">
              Show more ({rows.length - shown} left)
            </button>
          </div>
        )}
      </Section>
    </>
  );
}
