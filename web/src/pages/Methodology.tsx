/* How Vanguard3 works, written for a reader who wants to check the method:
 * the daily cycle, costs, data, the rules against look-ahead, how skill is
 * measured, and the limits of the experiment. */
import { Clock, Coins, Database, EyeOff, FlaskConical, Layers, Scale, ShieldAlert, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Container, Section } from "../components/ui";
import { useLive } from "../lib/data";
import { chf } from "../lib/format";

const SECTIONS: { id: string; title: string; icon: typeof Clock }[] = [
  { id: "question", title: "The question", icon: Sparkles },
  { id: "accounts", title: "The accounts", icon: Users },
  { id: "day", title: "A trading day", icon: Clock },
  { id: "costs", title: "Costs and fills", icon: Coins },
  { id: "lookahead", title: "No looking ahead", icon: EyeOff },
  { id: "data", title: "Data", icon: Database },
  { id: "learning", title: "How agents learn", icon: Layers },
  { id: "ai", title: "The Claude agents", icon: Sparkles },
  { id: "skill", title: "Measuring skill", icon: Scale },
  { id: "limits", title: "Limitations", icon: ShieldAlert },
  { id: "stack", title: "Under the hood", icon: FlaskConical },
];

function Part({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-line py-12 first:border-0 first:pt-0">
      <h2 className="display mb-5 text-[2.2rem]">{title}</h2>
      <div className="prose-v3 max-w-[680px] text-[16px] leading-[1.75] text-ink-2">{children}</div>
    </section>
  );
}

const Fact = ({ k, v }: { k: string; v: string }) => (
  <div className="flex justify-between gap-6 border-b border-line py-3 text-[14.5px] last:border-0"><span className="text-muted">{k}</span><span className="text-right text-ink">{v}</span></div>
);

export default function Methodology() {
  const d = useLive();
  const markets = d ? Object.keys(d.prices).length : 107;
  return (
    <>
      <Section className="pb-8">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Methodology</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">How the experiment works</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
            Vanguard3 is built to answer one question honestly, so most of its design is about not fooling itself: realistic costs, decisions that only
            see the past, yardsticks that expose luck, and every number recomputed from the raw record.
          </p>
        </div>
      </Section>
      <Container className="grid gap-12 pb-16 lg:grid-cols-[220px_1fr]">
        <nav className="hidden lg:block" aria-label="On this page">
          <ul className="sticky top-24 grid gap-1 text-[13.5px]">
            {SECTIONS.map(({ id, title, icon: Icon }) => (
              <li key={id}><a href={`#/methodology`} onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); }}
                className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-muted hover:bg-surface-2 hover:text-ink"><Icon size={14} className="text-gold" />{title}</a></li>
            ))}
          </ul>
        </nav>
        <article>
          <Part id="question" title="The question">
            <p>Can a trading agent beat the market, and beat luck? Not in a backtest tuned on the past, where almost anything can be made to look good, but live, day after day, with every cost paid and every decision recorded before the outcome is known.</p>
            <p>Thirteen accounts race on the same terms. Some follow classic hand-written rules, one teaches itself by reinforcement learning, and some ask a large language model (Claude) to read the news. Two yardsticks set the bar: the S&amp;P 500, and a monkey picking at random.</p>
          </Part>
          <Part id="accounts" title="The accounts">
            <p>Every account starts with {chf(d?.initial_capital_chf ?? 100000)} CHF of paper money, trades the same {markets} markets (large US, Swiss and euro-area shares, plus index, sector, bond and commodity funds, all tradable at Interactive Brokers) and pays the same costs. Only the way it decides differs.</p>
            <p>Each rule-based strategy runs twice: a <em>learning</em> version that re-tunes its settings every month, and a <em>fixed twin</em> that never changes. If learning helps, the learning versions should pull ahead of their twins over time.</p>
            <p><Link to="/agents" className="text-gold">Meet all the agents →</Link></p>
          </Part>
          <Part id="day" title="A trading day">
            <ol className="not-prose my-6 grid gap-0">
              {[
                ["After the New York close", "About 22:40 in Zurich, GitHub Actions downloads the day's closing prices and exchange rates. Every agent decides using only data up to that close, and its orders wait for the next open."],
                ["At each market's open", "Waiting orders fill at the next opening price, plus slippage. A market that does not open (a holiday) keeps its orders waiting, for up to a week."],
                ["Around midday", "The two news agents read the news again with live prices, while New York and Europe are both open. A change of mind fills at once at the live price, with the usual costs."],
                ["Every Saturday", "Claude is handed the week's facts (returns, trades and stated reasons) and writes the plain-language weekly report. It describes; it decides nothing."],
              ].map(([t, x], i) => (
                <li key={t} className="relative grid grid-cols-[28px_1fr] gap-4 pb-6 last:pb-0">
                  <span className="relative z-10 mt-1 grid size-7 place-items-center rounded-full border border-gold/40 bg-bg text-[12px] text-gold">{i + 1}</span>
                  {i < 3 && <span className="absolute left-[13.5px] top-8 h-[calc(100%-24px)] w-px bg-line-2" />}
                  <div><div className="text-[15px] font-medium text-ink">{t}</div><p className="mt-1 text-[15px] text-ink-2">{x}</p></div>
                </li>
              ))}
            </ol>
            <p>Everything runs in the cloud; nothing depends on a computer being switched on. Results are committed to the repository and published here automatically.</p>
          </Part>
          <Part id="costs" title="Costs and fills">
            <div className="not-prose card my-6 px-6 py-2">
              <Fact k="Commission" v={`${d?.costs.commission_chf ?? 2} CHF per fill`} />
              <Fact k="Slippage" v={`${d?.costs.slippage_bps ?? 5} basis points against the trade`} />
              <Fact k="Currency conversion" v={`${d?.costs.fx_bps ?? 2} basis point spread, CHF to USD or EUR`} />
              <Fact k="Smallest order" v="500 CHF (smaller buys are skipped: the fee would eat them)" />
              <Fact k="Cash" v="Never negative; buys are scaled down to the cash that is free" />
              <Fact k="Valuation" v="Every close, in CHF at that day's exchange rate" />
            </div>
            <p>The cost model follows Interactive Brokers' fixed pricing. Dividends are paid into cash (after foreign withholding tax) and share splits are followed, so the accounts behave like a real brokerage account rather than a price chart.</p>
          </Part>
          <Part id="lookahead" title="No looking ahead">
            <p>The most common way a trading study fools itself is by letting a decision see information from after the moment it was made. Here, an agent decides after the close of day <em>t</em> using data up to <em>t</em>, and its order can only fill at the open of day <em>t + 1</em>. Indicators are computed causally, using only past prices.</p>
            <p>Automated tests check this on every change: an indicator's value on a day must not change when later prices are removed, and an order must fill at the next open, never the same day. The live race is the strongest guard of all, because the future has not happened yet when the agents decide.</p>
          </Part>
          <Part id="data" title="Data">
            <p>Daily prices come from Yahoo Finance, with Stooq as a backup feed. The midday check uses real-time US prices from Finnhub and Yahoo's delayed quotes for Europe. Headlines come from Google News, and quarterly results from Yahoo Finance.</p>
            <p>Free data has gaps and occasional errors. The daily run checks for missing days (for example European prices that arrive late) and leaves an incomplete day for the next run instead of trading on it. If anything fails, a warning issue is opened automatically.</p>
          </Part>
          <Part id="learning" title="How agents learn">
            <p><b className="text-ink">Monthly self-review.</b> On the first trading day of each month, every learning strategy replays the last three years with each allowed setting and switches only if another setting is clearly better. Three optional safety rules (no new buys while SPY is below its 200-day average, a 12% stop loss, and skipping buys that move in step with a holding) can be switched on by the same review.</p>
            <p><b className="text-ink">Daily reinforcement learning.</b> The AI Learner scores sell, hold and buy for every market from ten price features with a linear model, and after every close updates its weights with what its last decisions earned (Q-learning). It practised on three years of history before its first live day.</p>
          </Part>
          <Part id="ai" title="The Claude agents">
            <p>The News Analysts read hundreds of headlines each evening, on every market and on politics and the economy, plus each company's latest quarterly results, and ask Claude for a target share of the account per market with a stated reason. Limits are fixed in code: at most 15% in one market and 90% invested. Two identical agents differ only in the model, Sonnet or Opus, to test whether a smarter model trades better.</p>
            <p>These agents <em>cannot be backtested</em>: the model already knows how past markets turned out, so any replay would be contaminated. They only decide for the newest session, and their record starts on their first live day.</p>
            <p>The reasons shown are the model's own stated reasons, not a guaranteed account of how it reached its answer. Each call is graded against the S&amp;P 500 after 5 and 20 trading days, and Claude sees this report card every time it decides.</p>
          </Part>
          <Part id="skill" title="Measuring skill">
            <p>With this many accounts, one will lead by luck alone. So every account is compared with 300 monkeys trading at random under the same rules and costs, over exactly the same days, and with buy-and-hold SPY.</p>
            <p>A lead counts as skill only when luck explains it less than 1 time in 20 <em>after allowing for the number of agents racing</em> (Holm's correction). It looks like luck when the results rule out an edge worth having (10% a year). Everything in between is honestly labelled “can't tell yet”, with an estimate of how many more weeks it would take to know. Ranges come from a block bootstrap of each account's own days.</p>
            <p><Link to="/research#skill" className="text-gold">See the current verdicts →</Link></p>
          </Part>
          <Part id="limits" title="Limitations">
            <ul className="not-prose my-4 grid gap-3">
              {[
                ["Paper money", "No real money is at risk, so there is no market impact and no emotion. Fills are simulated from public prices."],
                ["A short record", "A few weeks of results say almost nothing. The study above says how long it would take to know."],
                ["Survivorship bias", "The markets were chosen because they are large today, which flatters any replay of the past."],
                ["A simplified market", "End-of-day decisions, market orders at the open, no shorting and no leverage."],
                ["Free data", "Prices and news come from free sources that can be late, wrong or missing."],
              ].map(([t, x]) => (
                <li key={t} className="flex gap-3 text-[15px]"><span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-gold" /><span><b className="text-ink">{t}.</b> <span className="text-ink-2">{x}</span></span></li>
              ))}
            </ul>
            <p>Nothing on this site is investment advice.</p>
          </Part>
          <Part id="stack" title="Under the hood">
            <div className="not-prose card my-6 px-6 py-2">
              <Fact k="Simulation engine" v="Python, pandas and NumPy" />
              <Fact k="Scheduling" v="GitHub Actions, every weekday, plus midday and weekly runs" />
              <Fact k="Language models" v="Claude Sonnet and Claude Opus via the Anthropic API" />
              <Fact k="Broker link" v="Interactive Brokers paper account via IB Gateway on a cloud server" />
              <Fact k="This platform" v="React, TypeScript, Three.js, TradingView Lightweight Charts" />
              <Fact k="Hosting" v="GitHub Pages, rebuilt from the published results" />
              <Fact k="Tests" v="Accounting, no look-ahead, broker timing and full backtests on every change" />
            </div>
            <p>The full source code is public on <a className="text-gold" href="https://github.com/mauritswessels/Vanguard3">GitHub</a>.</p>
          </Part>
        </article>
      </Container>
    </>
  );
}
