/* The project journal: how Vanguard3 grew. Every pull request that changes
 * what the agents do or what the website shows adds an entry here (or
 * updates one), newest at the top: a date (YYYY-MM-DD), a title, a short
 * plain-English text and a tag. Work that is merged but not live yet gets
 * pending: true; take it off once it is. The flaw scan flags a journal
 * that falls more than a week behind the merged pull requests. */

export type Tag = "Agents" | "Research" | "Infrastructure" | "Platform";

export interface Entry {
  date: string;
  title: string;
  text: string;
  tag: Tag;
  /** Shown as "in progress" until it is part of the live race. */
  pending?: boolean;
}

export const JOURNAL: Entry[] = [
  {
    date: "2026-10-28", tag: "Infrastructure", title: "A message for every trade",
    text: "Every weekday morning a Telegram message lists each trade the accounts made the day before, with the reason in plain words, and the orders waiting for the next open, so the race can be followed from a phone without opening the website.",
  },
  {
    date: "2026-10-28", tag: "Platform", title: "The research lab gets the platform's look", pending: true,
    text: "The 3D Research Lab, where a separate agent practises on past prices, gets the same colours, fonts and gold V3 logo as the rest of the platform, with a warm gold 3D scene.",
  },
  {
    date: "2026-10-28", tag: "Platform", title: "Its own address",
    text: "The platform now lives at vanguard3.xyz. The old github.io address forwards there by itself.",
  },
  {
    date: "2026-10-22", tag: "Infrastructure", title: "A full audit, and a scan that keeps looking",
    text: "An audit of the whole project fixed six flaws and four smaller gaps. A flaw scan now checks every change and runs every Sunday: accounts that must add up, the broker's paper-only lock, secrets, and scheduled jobs that fail without telling anyone.",
  },
  {
    date: "2026-10-22", tag: "Infrastructure", title: "Orders the broker accepts",
    text: "US shares now go to Interactive Brokers as limit orders, because the paper account has no US price feed and was cancelling plain market orders.",
  },
  {
    date: "2026-10-22", tag: "Research", title: "Fair comparisons and report cards",
    text: "Every account is compared with the yardsticks over exactly the same days, with an equal mix of all markets as a new yardstick. Every trade is graded against the S&P 500, the News Analysts say how sure they are and are checked on it, and the real IBKR paper account is shown next to the simulated Team Manager.",
  },
  {
    date: "2026-10-21", tag: "Agents", title: "Learners that learn from what they did",
    text: "The AI Learner stops buying and selling the same market a day apart, and both learners now learn from the trades their account really made, not from picks that were turned down or never placed.",
  },
  {
    date: "2026-10-20", tag: "Platform", title: "A new home for the race",
    text: "This platform: a 3D network of every account and market, a profile for every agent with its reasoning, a trade explorer, analytics, research and a written methodology. Built with React, TypeScript and Three.js on the same published results.",
  },
  {
    date: "2026-10-20", tag: "Research", title: "Skill or luck?",
    text: "A study that compares every account with 300 monkeys trading at random under the same rules, and with the S&P 500, and says plainly whether a lead is skill, luck, or too early to tell.",
  },
  {
    date: "2026-10-20", tag: "Infrastructure", title: "Getting the details right",
    text: "Dividends paid into cash and share splits followed, cash kept aside for orders still waiting for their market, every failed order reported, and European prices taken before Yahoo drops them at midnight.",
  },
  {
    date: "2026-10-15", tag: "Agents", title: "An AI reviewer",
    text: "The Opus Learner: the same learning model as the AI Learner, but Claude Opus approves or turns down every pick before it is placed. Does a reviewer improve a simple model?",
  },
  {
    date: "2026-10-14", tag: "Agents", title: "A smarter model, and a weekly report",
    text: "A second News Analyst running on Claude Opus races the Sonnet version on identical news. Every Saturday, Claude now writes a plain-language report of the week from the facts.",
  },
  {
    date: "2026-10-12", tag: "Infrastructure", title: "A real broker",
    text: "A bridge copies one agent into an Interactive Brokers paper account every weekday morning, first from a Mac and then from a small cloud server running IB Gateway, with a message to the phone after every run.",
  },
  {
    date: "2026-10-11", tag: "Research", title: "Keeping it honest",
    text: "The Monkey joins as a yardstick for luck. Learning agents gain optional safety rules, the News Analyst gets a report card graded against the S&P 500, the Team Manager starts backing the best agents, and failed or missed runs raise an alert.",
  },
  {
    date: "2026-10-08", tag: "Agents", title: "Claude reads the news",
    text: "The News Analyst asks Claude for a portfolio after reading hundreds of headlines and every company's quarterly results, and checks again at midday with live prices. The watchlist grows to 108 markets.",
  },
  {
    date: "2026-10-08", tag: "Agents", title: "A machine that teaches itself",
    text: "The AI Learner, a reinforcement-learning account, scores every market from ten price features and updates itself after every close.",
  },
  {
    date: "2026-10-07", tag: "Research", title: "Launch",
    text: "Three rule-based strategies and buy-and-hold SPY start trading 100,000 CHF of paper money each. A walk-forward study picks their settings, each strategy gets a learning version and a fixed twin, and a 3D research lab lets a separate agent practise on past prices.",
  },
];

export const NEXT: string[] = [
  "A longer record: the luck study estimates how many weeks each agent needs before skill can be told from chance.",
  "New agents and new questions as the project continues into university research.",
];
