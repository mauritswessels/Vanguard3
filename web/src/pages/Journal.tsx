/* The project journal: a timeline of how Vanguard3 grew (content/journal.ts). */
import { Badge, Section } from "../components/ui";
import { JOURNAL, NEXT } from "../content/journal";
import { date } from "../lib/format";

export default function Journal() {
  const months = [...new Set(JOURNAL.map((e) => e.date.slice(0, 7)))];
  return (
    <>
      <Section className="pb-6">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Project journal</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">How Vanguard3 grew</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">From three hand-written trading rules to Claude reading the news, a broker connection and a study of luck. Every step is in the public code history.</p>
        </div>
      </Section>
      <Section className="pt-4">
        <div className="mx-auto max-w-3xl">
          {months.map((m) => (
            <div key={m}>
              <div className="display mb-6 text-[1.6rem] text-gold">{new Date(m + "-01T00:00:00Z").toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</div>
              <ol className="relative mb-12 grid gap-8 border-l border-line-2 pl-8">
                {JOURNAL.filter((e) => e.date.startsWith(m)).map((e) => (
                  <li key={e.date + e.title} className="relative">
                    <span className="absolute -left-[38px] top-1.5 grid size-[19px] place-items-center rounded-full border border-gold/50 bg-bg"><span className="size-[7px] rounded-full bg-gold" /></span>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                      {date(e.date)} <Badge tone="gold">{e.tag}</Badge>{e.pending && <Badge>in progress</Badge>}
                    </div>
                    <h2 className="text-[19px] font-medium">{e.title}</h2>
                    <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{e.text}</p>
                  </li>
                ))}
              </ol>
            </div>
          ))}
          <div className="card p-7">
            <div className="eyebrow mb-3 text-gold">What's next</div>
            <ul className="grid gap-3 text-[15px] text-ink-2">
              {NEXT.map((n) => <li key={n} className="flex gap-3"><span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-gold" />{n}</li>)}
            </ul>
          </div>
        </div>
      </Section>
    </>
  );
}
