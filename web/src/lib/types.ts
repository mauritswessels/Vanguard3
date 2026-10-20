/* The shapes of the JSON files the bots write to docs/data/ (reporting.py,
 * daily_run.py, midday_news.py, weekly_report.py, walk_forward.py). Fields
 * the app does not read are left out; optional ones may be missing in older
 * files. */

export type Point = [date: string, value: number];

export interface Decision {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD";
  reason: string;
  ordered: boolean;
  score: number | null;
  stop: number | null;
  check: string | null;
  details: {
    target_weight?: number;
    market_view?: string;
    headlines?: string[];
    quarterly?: string;
    [k: string]: unknown;
  };
  date: string;
  time?: string;
  note?: string;
}

export interface Fill {
  id: number;
  date: string;
  decided: string;
  session: "open" | "midday" | string;
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  market_price: number;
  fx: number;
  value_chf: number;
  fees_chf: number;
  commission_chf: number;
  cash_flow_chf: number;
  pnl_chf: number | null;
  reason: string;
  decision: Decision | null;
}

export interface Trip {
  id: number;
  ticker: string;
  status: "open" | "closed";
  entry_date: string;
  exit_date: string | null;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  cost_chf: number;
  size_pct: number;
  holding_days: number;
  fills: number[];
  entry: Decision | null;
  exit: Decision | null;
  entry_fill?: number;
  exit_fill?: number;
  pnl_chf: number;
  pnl_pct: number;
}

export interface Position {
  ticker: string;
  quantity: number;
  entry_date: string;
  avg_cost_chf: number;
  price_chf: number;
  value_chf: number;
  pnl_chf: number;
  pnl_pct: number;
  stop: number | null;
}

export interface PendingOrder {
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  reason: string;
}

export interface DayFill {
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  pnl_chf?: number | null;
  at_open?: boolean;
}

export interface Rejected {
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  why: string;
}

export interface Corporate {
  kind: "dividend" | "split";
  ticker: string;
  chf?: number;
  per_share?: number;
  currency?: string;
  shares?: number;
  tax_pct?: number;
  ratio?: number;
  shares_before?: number;
}

export interface Activity {
  date: string;
  time?: "midday" | string;
  fills: DayFill[];
  signals: Decision[];
  rejected?: Rejected[];
  corporate?: Corporate[];
}

export interface Watch {
  ticker: string;
  held: boolean;
  progress: number | null;
  ready: boolean;
  note: string;
}

export interface LearningReview {
  date: string;
  switched: boolean;
  new: Record<string, number>;
  sharpe_old: number | null;
  sharpe_best: number | null;
}

export interface ReportCardCall {
  date: string;
  ticker: string;
  side: "BUY" | "SELL";
  edge_5?: number | null;
  edge_20?: number | null;
}

export interface NewsAI {
  kind: "news";
  model: string;
  status: string;
  decided: string;
  market_view?: string;
  calls: number;
  headlines?: number;
  tokens?: { input: number; output: number };
  est_cost_usd: number;
  midday?: {
    time: string;
    ok: boolean;
    status: string;
    view?: string;
    opening_fills: number;
    trades: number;
    waiting: unknown[];
    prices?: string;
  };
  report_card?: {
    calls: ReportCardCall[];
    graded_5: number;
    hit_rate_5: number | null;
    avg_edge_5: number | null;
    graded_20: number;
    hit_rate_20: number | null;
    avg_edge_20: number | null;
  };
}

export interface LearnerAI {
  kind?: "learner" | "learner_review";
  live_from: string;
  days_learned: number;
  updates: number;
  epsilon: number;
  pretrain?: { from: string; to: string; sessions: number; epochs: number; updates: number };
  td_recent?: number[];
  weights?: Record<"SELL" | "HOLD" | "BUY", Record<string, number>>;
  model?: string;
  status?: string;
  decided?: string;
  calls?: number;
  est_cost_usd?: number;
  review?: {
    date: string;
    view: string;
    picks: { ticker: string; action: "BUY" | "SELL"; approve: boolean; reason: string }[];
  };
}

export interface Team {
  backing: Record<string, number>;
  chosen: string;
  why: string;
}

export interface Stats {
  final_equity_chf: number;
  total_return: number;
  cagr: number;
  volatility: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number;
  calmar: number;
  trades: number;
  closed_trades: number;
  win_rate: number | null;
  realized_pnl_chf: number;
  commissions_chf: number;
  slippage_fx_chf: number;
  open_positions: number;
  cash_chf: number;
}

export interface Agent {
  id: string;
  key: string;
  name: string;
  style: string;
  learning: boolean;
  fixed_twin: boolean;
  benchmark: boolean;
  learning_log: LearningReview[];
  params: Record<string, number | string>;
  stats: Stats;
  equity: Point[];
  cash_chf: number;
  positions: Position[];
  trades: Fill[];
  trips: Trip[];
  activity: Activity[];
  pending_orders: PendingOrder[];
  watch: Watch[] | null;
  ai: NewsAI | LearnerAI | null;
  team: Team | null;
  scans: [string, Record<string, number>][] | null;
  events?: { date: string; chf?: number }[];
}

export interface RunData {
  mode: "paper" | "backtest";
  status?: "live" | "waiting";
  generated_utc: string;
  data_source: string;
  start: string;
  last: string;
  base_currency: string;
  initial_capital_chf: number;
  costs: { commission_chf: number; slippage_bps: number; fx_bps: number };
  currencies: Record<string, string>;
  groups: Record<string, string>;
  agents: Agent[];
  prices: Record<string, Point[]>;
  fx: Record<string, Point[]>;
}

export interface WeeklyData {
  reports: { week_start: string; week_end: string; generated_utc: string; text: string; model?: string }[];
}

export interface WalkForwardData {
  generated_utc: string;
  data_source: string;
  train_years: number;
  folds: [string, string][];
  agents: {
    key: string;
    name: string;
    folds: {
      test: [string, string];
      params: Record<string, number>;
      train_sharpe: number | null;
      test_return: number;
      test_sharpe: number;
      test_trades: number;
      default_test_return: number;
    }[];
    tuned: { return: number; sharpe: number; max_drawdown: number };
    default: { return: number; sharpe: number; max_drawdown: number };
    tuned_equity: Point[];
    default_equity: Point[];
  }[];
  benchmark: { name: string; return: number; sharpe: number; max_drawdown: number; equity: Point[] };
}
