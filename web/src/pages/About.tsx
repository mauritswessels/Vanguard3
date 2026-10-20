/* About the project and its builder (content/about.ts), with credits. */
import { ArrowUpRight, FolderGit2 } from "lucide-react";
import { Link } from "react-router";
import { Section, Stat } from "../components/ui";
import { BUILDER } from "../content/about";
import { useLive } from "../lib/data";
import { date } from "../lib/format";

const CREDITS: [string, string, string][] = [
  ["Prices", "Yahoo Finance, with Stooq as a backup and Finnhub for real-time US prices", "https://finance.yahoo.com"],
  ["News", "Google News, and quarterly results from Yahoo Finance", "https://news.google.com"],
  ["Language models", "Claude Sonnet and Claude Opus by Anthropic", "https://www.anthropic.com"],
  ["Broker", "Interactive Brokers paper trading, through IB Gateway", "https://www.interactivebrokers.com"],
  ["Charts", "TradingView Lightweight Charts™, Copyright (c) 2025 TradingView, Inc.", "https://www.tradingview.com/"],
  ["Type", "Instrument Serif and Geist", "https://fonts.google.com/specimen/Instrument+Serif"],
];

export default function About() {
  const d = useLive();
  const fills = d ? d.agents.reduce((n, a) => n + a.trades.length, 0) : null;
  return (
    <>
      <Section className="pb-8">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">About</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">An open experiment in machine investing</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            Vanguard3 pits trading agents against each other, against the market and against pure chance, in public, with every decision and its reasons on
            the record. It is a research project, not a product: there is nothing to buy and no advice to follow, only an honest attempt to find out what works.
          </p>
        </div>
      </Section>

      {d && (
        <Section className="pt-0">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Accounts racing" value={d.agents.length} sub="including two yardsticks" />
            <Stat label="Markets watched" value={Object.keys(d.prices).length} sub="US, Swiss, European, funds" />
            <Stat label="Trades recorded" value={fills?.toLocaleString("en")} sub="each with its stated reason" />
            <Stat label="Live since" value={<span className="text-[1.2rem]">{date(d.start)}</span>} sub={`${d.agents[0]?.equity.length ?? 0} trading days so far`} />
          </div>
        </Section>
      )}

      {BUILDER.name && (
        <Section className="pt-0">
          <div className="card grid gap-8 p-8 md:grid-cols-[1fr_1.6fr] md:p-10">
            <div>
              <div className="eyebrow mb-3 text-gold">The builder</div>
              <h2 className="display text-[2.4rem]">{BUILDER.name}</h2>
              {BUILDER.role && <p className="mt-2 text-[15px] text-muted">{BUILDER.role}</p>}
              <div className="mt-6 flex flex-wrap gap-2">
                {BUILDER.links.map((l) => (
                  <a key={l.href} href={l.href} className="inline-flex items-center gap-1.5 rounded-full border border-line-2 px-4 py-2 text-[13px] hover:border-gold/40 hover:text-gold">
                    {l.label} <ArrowUpRight size={13} />
                  </a>
                ))}
              </div>
            </div>
            <div className="prose-v3 text-[16px] leading-[1.75] text-ink-2">{BUILDER.bio.map((p, i) => <p key={i}>{p}</p>)}</div>
          </div>
        </Section>
      )}

      <Section className="pt-0">
        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div className="card p-8">
            <div className="eyebrow mb-4 text-gold">Credits</div>
            <ul className="grid gap-4">
              {CREDITS.map(([k, v, href]) => (
                <li key={k} className="grid gap-1 border-b border-line pb-4 last:border-0 last:pb-0 sm:grid-cols-[140px_1fr]">
                  <span className="text-[13px] text-muted">{k}</span>
                  <a href={href} className="link-underline w-fit text-[14.5px] hover:text-gold">{v}</a>
                </li>
              ))}
            </ul>
          </div>
          <div className="grid gap-6">
            <a href="https://github.com/mauritswessels/Vanguard3" className="card group flex items-center justify-between p-7 hover:border-gold/30">
              <span className="flex items-center gap-4"><FolderGit2 size={22} className="text-gold" /><span><span className="block text-[16px] font-medium">Source code</span><span className="text-[13px] text-muted">Every line is public on GitHub</span></span></span>
              <ArrowUpRight size={18} className="text-gold transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
            </a>
            <div className="card p-7 text-[13.5px] leading-relaxed text-muted">
              <div className="eyebrow mb-3 text-gold">Fine print</div>
              Paper money only: no real orders are placed by this site, and the broker link uses a paper account. Nothing here is investment advice.
              Vanguard3 is an independent project and is not affiliated with The Vanguard Group. <Link to="/methodology" className="text-gold">Read the methodology →</Link>
            </div>
          </div>
        </div>
      </Section>
    </>
  );
}
