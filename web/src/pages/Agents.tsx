/* Meet the agents: every account as a card, grouped by how it thinks. */
import { AgentCard } from "../components/agent";
import { Empty, Section, SectionHead } from "../components/ui";
import { info, ORDER, ranked, type Family } from "../lib/agents";
import { useJSON, useLive } from "../lib/data";
import { chf } from "../lib/format";
import type { SkillData } from "../lib/types";

const FAMILIES: { family: Family; title: string; text: string }[] = [
  { family: "Rules", title: "Rule-based strategies", text: "Classic trading rules written by hand. Each runs twice: a version that re-tunes its settings every month, and a fixed twin that never changes." },
  { family: "Reinforcement learning", title: "Learning machines", text: "A small model that teaches itself by trial and error, updating after every close." },
  { family: "Claude AI", title: "Claude, reading the world", text: "Large language models that read the news and company results, or check another model's picks, and explain every decision." },
  { family: "Manager", title: "The manager", text: "An agent that picks agents instead of markets." },
  { family: "Yardstick", title: "The yardsticks", text: "Not competitors but the bar to clear: the S&P 500, every market in equal shares, and a monkey picking at random to show how far luck alone goes." },
];

export default function Agents() {
  const d = useLive();
  const skill = useJSON<SkillData>("skill");
  if (d === undefined) return <Section><div className="h-[60vh] animate-pulse rounded-3xl bg-surface" /></Section>;
  if (!d) return <Section><Empty>No live data yet.</Empty></Section>;
  const order = ranked(d.agents.filter((a) => !a.benchmark));
  const rank = (id: string) => order.findIndex((a) => a.id === id) + 1 || undefined;
  const verdict = (id: string) => skill?.accounts.find((x) => x.id === id)?.verdict ?? null;
  return (
    <>
      <Section className="pb-4">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">The lineup</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">Meet the agents</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            {d.agents.length} accounts, {chf(d.initial_capital_chf)} CHF of paper money each, the same {Object.keys(d.prices).length} markets and the same costs.
            What differs is how they think. Open any agent to see its holdings, every decision with its reasons, and how it learns.
          </p>
        </div>
      </Section>
      {FAMILIES.map(({ family, title, text }) => {
        const list = d.agents.filter((a) => info(a).family === family)
          .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key) || Number(a.fixed_twin) - Number(b.fixed_twin));
        if (!list.length) return null;
        return (
          <Section key={family} className="py-8 sm:py-10">
            <SectionHead title={title} intro={text} />
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((a) => <AgentCard key={a.id} a={a} rank={a.benchmark ? undefined : rank(a.id)} verdict={verdict(a.id)} />)}
            </div>
          </Section>
        );
      })}
    </>
  );
}
