export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Team = { id: string; name: string; short: string; conference: string };
export type Probs = { home: number; draw: number; away: number };
export type ValueRow = {
  market: "1x2" | "ah" | "ou";
  selection: string;
  line: number | null;
  price: number;
  book: string;
  model_prob: number;
  market_prob: number;
  fair_price: number | null;
  ev: number;
  verdict: "value" | "pass" | "caution" | "house";
  why: string;
  kelly_stake_pct: number;
};
export type MatchCard = {
  id: number;
  league: string;
  season: string;
  kickoff: string;
  day: string;
  status: string;
  stage: string;
  knockout: boolean;
  venue: string;
  home: Team;
  away: Team;
  score: { home: number; away: number; home_xg: number | null; away_xg: number | null } | null;
  prediction: { xg_home: number; xg_away: number; p: Probs } | null;
  prices_1x2: Record<string, { price: number; book: string }>;
  markets_available: string[];
  best_value: ValueRow | null;
};

export function token(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem("oddsforge_token");
  } catch {
    return null;
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const t = token();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(t ? { "X-Player-Token": t } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const j = await res.json();
      msg = j.detail ?? msg;
    } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export const pct = (x: number | null | undefined, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
export const signed = (x: number | null | undefined, d = 1) =>
  x == null ? "–" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
export const money = (x: number | null | undefined) => (x == null ? "–" : x.toFixed(2));

export function selectionLabel(market: string, selection: string, line: number | null, home?: string, away?: string) {
  if (market === "1x2") return selection === "home" ? home ?? "Home" : selection === "away" ? away ?? "Away" : "Draw";
  if (market === "ah") {
    const l = selection === "home" ? line ?? 0 : -(line ?? 0);
    return `${selection === "home" ? home ?? "Home" : away ?? "Away"} ${l > 0 ? "+" : ""}${l}`;
  }
  if (market === "ou") return `${selection === "over" ? "Over" : "Under"} ${line}`;
  return `${market} ${selection}`;
}

export function kickoffLabel(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function stageLabel(stage: string) {
  return stage
    .replace(/-+/g, " ")
    .replace(/\bplayoffs\b/i, "Playoffs ·")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}
