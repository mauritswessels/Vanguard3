/* Who the agents are, in plain words: colour, family, a one-line tagline and
 * how each one thinks. The numbers come from the data; this file only holds
 * the descriptions, written from the agents' code (models/*.py, config.py). */
import type { Agent } from "./types";

export type Family = "Rules" | "Reinforcement learning" | "Claude AI" | "Manager" | "Yardstick";

export interface AgentInfo {
  tagline: string;
  family: Family;
  /** How it decides, in a few plain sentences. */
  thinks: string[];
  /** Its rules in short, for the profile page. */
  rules: string[];
}

export const INFO: Record<string, AgentInfo> = {
  trend: {
    tagline: "Rides markets that are already rising.",
    family: "Rules",
    thinks: [
      "The Trend Follower believes that what is going up tends to keep going up for a while. It watches two moving averages of each market's price: a fast one (20 days) and a slow one (50 days).",
      "When the fast average climbs above the slow one and the trend is strong (measured by the ADX indicator), it buys. When the trend breaks, it sells.",
    ],
    rules: ["Buy: 20-day average crosses above the 50-day, ADX above 25", "Sell: the cross reverses", "Each position: 10% of the account"],
  },
  reversion: {
    tagline: "Buys what has fallen too far, too fast.",
    family: "Rules",
    thinks: [
      "The Bargain Hunter bets that sharp drops overshoot. It looks for markets whose RSI (a measure of recent selling pressure) is low and whose price has fallen below the lower Bollinger band.",
      "It sells when the price snaps back to its 20-day average, or after 20 days if the bounce never comes.",
    ],
    rules: ["Buy: RSI below 40 and price under the lower Bollinger band", "Sell: back at the 20-day average, or after 20 days", "Each position: 10% of the account"],
  },
  volatility: {
    tagline: "Chases breakouts, guarded by a trailing stop.",
    family: "Rules",
    thinks: [
      "Volatility Protected buys a market when it breaks out to its highest price in 55 days, a classic Donchian-channel signal.",
      "Every position gets a trailing stop 3.5 times the market's average daily range (ATR) below the price, and its size is set so that hitting the first stop would cost about 1% of the account. Calm markets get bigger positions, wild ones smaller.",
    ],
    rules: ["Buy: a new 55-day high", "Sell: a 20-day low or the trailing stop", "Size: 1% of the account at risk, at most 15% per market"],
  },
  learner: {
    tagline: "Teaches itself by trial and error, every day.",
    family: "Reinforcement learning",
    thinks: [
      "The AI Learner is a small reinforcement-learning model. For each market it scores three choices (sell, hold, buy) from ten price features such as momentum, RSI and volatility.",
      "After every close it checks what its last decisions earned and nudges its weights (Q-learning). It practised on three years of history before its first live day, and 5% of its choices are random so it keeps exploring.",
    ],
    rules: ["Learns after every close", "Up to 8 positions of 10%", "5% of decisions random, to keep learning"],
  },
  learner_opus: {
    tagline: "The AI Learner, with Claude Opus checking its picks.",
    family: "Claude AI",
    thinks: [
      "The Opus Learner runs the same learning model as the AI Learner, but every evening Claude Opus reviews the model's proposed buys and sells, with recent price moves and a few headlines for each.",
      "Opus approves or turns down every pick, and only approved trades are placed. The race against the AI Learner shows whether an AI reviewer improves a simple model.",
    ],
    rules: ["Model proposes, Opus approves or rejects", "At most 12 buy picks reviewed per evening", "Only trades on the newest session"],
  },
  news: {
    tagline: "Claude reads the news and sets the portfolio.",
    family: "Claude AI",
    thinks: [
      "Every evening the News Analyst gathers hundreds of headlines on every market, on politics and the economy, plus each company's latest quarterly results, and asks Claude (Sonnet) for a target share of the account per market, with a stated reason.",
      "It buys new targets, sells markets set to zero and leaves the rest alone to save fees. Around midday it reads the news again with live prices and can trade at once.",
    ],
    rules: ["At most 15% in one market, 90% invested", "Evening decision plus a midday check", "Grades its own calls against SPY after 5 and 20 days"],
  },
  news_opus: {
    tagline: "The same news, read by a stronger model.",
    family: "Claude AI",
    thinks: [
      "The News Analyst (Opus) reads exactly the same news under the same rules and limits as the News Analyst, but asks Claude Opus, a stronger and pricier model.",
      "The race between the two answers a simple question: does a smarter model make a better trader?",
    ],
    rules: ["Same brief and limits as the News Analyst", "Model: Claude Opus", "Evening decision plus a midday check"],
  },
  manager: {
    tagline: "Picks agents, not markets.",
    family: "Manager",
    thinks: [
      "The Team Manager does not choose markets. It backs other agents and owns its share of whatever they own.",
      "Until there are 35 days of results it backs every racing agent equally. After that, on the first trading day of each month, it backs the three agents with the best return over the last three months.",
    ],
    rules: ["Backs the top 3 agents by 3-month return", "Re-chooses monthly", "Only trades a market more than 2% off target"],
  },
  benchmark: {
    tagline: "The yardstick: buy the S&P 500 and hold.",
    family: "Yardstick",
    thinks: [
      "Buy & Hold SPY puts the whole account into the S&P 500 index fund on day one and never trades again. It pays the same costs as everyone else.",
      "Any agent that cannot beat it over time is not worth its trading fees.",
    ],
    rules: ["100% in SPY from day one", "Never trades", "Same costs as the agents"],
  },
  monkey: {
    tagline: "The luck yardstick: picks at random.",
    family: "Yardstick",
    thinks: [
      "The Monkey picks markets at random under the same rules as the agents: up to 10 positions of 10%, same costs. Each evening every holding has a 1 in 20 chance of being sold.",
      "With this many accounts racing, one will lead by luck alone. An agent shows skill only if it keeps beating the Monkey over many weeks.",
    ],
    rules: ["Random picks, 10 positions of 10%", "Each holding: 1 in 20 chance of a sale each evening", "Same costs as the agents"],
  },
};

export const info = (a: Pick<Agent, "key">): AgentInfo => INFO[a.key] || INFO.trend;

/** CSS colour of an agent's series (fixed twins share their learner's). */
export const color = (key: string) => `var(--s-${key}, var(--muted))`;

/** Resolved hex for canvases (charts, the 3D scene) that cannot read CSS variables. */
export function hex(key: string, el: Element = document.documentElement) {
  return getComputedStyle(el).getPropertyValue(`--s-${key}`).trim() || "#8f897b";
}

/** The order agents are listed in when not ranked. */
export const ORDER = ["trend", "reversion", "volatility", "learner", "learner_opus", "news", "news_opus", "manager", "benchmark", "monkey"];

export const isYardstick = (a: Agent) => a.benchmark;
export const learns = (a: Agent) => a.learning || !!a.ai;

/** A short label for the profile header and cards. */
export function badge(a: Agent): string {
  if (a.fixed_twin) return "Fixed twin";
  if (a.benchmark) return "Yardstick";
  if (a.ai && "kind" in a.ai && a.ai.kind === "news") return "Claude · evening + midday";
  if (a.ai && "kind" in a.ai && a.ai.kind === "learner_review") return "Learns daily · Opus reviews";
  if (a.ai) return "Learns daily";
  if (a.learning) return "Re-tunes monthly";
  if (a.team) return "Backs the best agents";
  return info(a).family;
}

export const ranked = (agents: Agent[]) =>
  agents.slice().sort((a, b) => (b.stats.final_equity_chf ?? 0) - (a.stats.final_equity_chf ?? 0));
