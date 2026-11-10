"use client";

import Link from "next/link";
import { kickoffLabel, MatchCard as M, pct, selectionLabel, signed, stageLabel } from "@/lib/api";
import { useApp } from "./Providers";

export function ProbBar({ p, compact = false }: { p: { home: number; draw: number; away: number }; compact?: boolean }) {
  return (
    <div className={`flex w-full overflow-hidden rounded ${compact ? "h-1.5" : "h-2.5"}`}>
      <div className="bg-accent" style={{ width: `${p.home * 100}%` }} title={`home ${pct(p.home)}`} />
      <div className="bg-[#5b6676]" style={{ width: `${p.draw * 100}%` }} title={`draw ${pct(p.draw)}`} />
      <div className="bg-sky" style={{ width: `${p.away * 100}%` }} title={`away ${pct(p.away)}`} />
    </div>
  );
}

export function PriceButton({
  m,
  market,
  selection,
  line,
  price,
  book,
  modelProb,
  mode,
  disabled,
}: {
  m: M;
  market: string;
  selection: string;
  line: number | null;
  price: number;
  book: string;
  modelProb?: number;
  mode: "live" | "replay";
  disabled?: boolean;
}) {
  const { toggleLeg, inSlip, setSlipOpen } = useApp();
  const active = inSlip(m.id, market, selection, line);
  const label = selectionLabel(market, selection, line, m.home.short, m.away.short);
  return (
    <button
      disabled={disabled}
      onClick={() => {
        toggleLeg({
          match_id: m.id,
          market,
          selection,
          line,
          price,
          book,
          label,
          matchLabel: `${m.home.short} v ${m.away.short}`,
          mode,
          model_prob: modelProb,
        });
        if (!active) setSlipOpen(false);
      }}
      className={`flex min-w-0 flex-1 flex-col items-center rounded-lg border px-2 py-1.5 transition disabled:opacity-40 ${
        active ? "border-accent bg-accent/15" : "border-line bg-bg hover:border-muted"
      }`}
      title={book === "house" ? "OddsForge house price (model + 5% margin)" : book}
    >
      <span className="w-full truncate text-center text-[11px] text-muted">{label}</span>
      <span className={`font-mono text-sm ${book === "house" ? "text-muted" : "text-ink"}`}>{price.toFixed(2)}</span>
    </button>
  );
}

export default function MatchCard({ m, mode }: { m: M; mode: "live" | "replay" }) {
  const p = m.prediction?.p;
  const closed = mode === "live" ? new Date(m.kickoff) <= new Date() : !!m.score;
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="mb-2 flex items-center justify-between text-xs text-muted">
        <span>
          {kickoffLabel(m.kickoff)}
          {m.stage && m.stage !== "regular season" && (
            <span className="ml-2 rounded bg-line px-1.5 py-0.5">{stageLabel(m.stage)}</span>
          )}
        </span>
        <Link href={`/match/${m.id}`} className="text-sky hover:underline">
          Analysis →
        </Link>
      </div>
      <Link href={`/match/${m.id}`} className="block">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <div className="truncate font-semibold">{m.home.name}</div>
          <div className="rounded-md bg-bg px-2 py-1 text-center font-mono text-sm">
            {m.score ? `${m.score.home} – ${m.score.away}` : "vs"}
          </div>
          <div className="truncate text-right font-semibold">{m.away.name}</div>
        </div>
        {m.score?.home_xg != null && (
          <div className="mt-0.5 text-center text-[11px] text-muted">
            xG {m.score.home_xg.toFixed(2)} – {m.score.away_xg?.toFixed(2)}
          </div>
        )}
      </Link>
      {p && m.prediction && (
        <div className="mt-3 space-y-1">
          <ProbBar p={p} />
          <div className="flex justify-between text-[11px] text-muted">
            <span>
              {pct(p.home)} · xG {m.prediction.xg_home.toFixed(2)}
            </span>
            <span>draw {pct(p.draw)}</span>
            <span>
              xG {m.prediction.xg_away.toFixed(2)} · {pct(p.away)}
            </span>
          </div>
        </div>
      )}
      <div className="mt-3 flex gap-2">
        {(["home", "draw", "away"] as const).map((sel) =>
          m.prices_1x2[sel] ? (
            <PriceButton
              key={sel}
              m={m}
              market="1x2"
              selection={sel}
              line={null}
              price={m.prices_1x2[sel].price}
              book={m.prices_1x2[sel].book}
              modelProb={p?.[sel]}
              mode={mode}
              disabled={closed}
            />
          ) : null,
        )}
      </div>
      <div className="mt-2 flex min-h-5 items-center justify-between text-[11px]">
        <span className="text-muted">
          {Object.values(m.prices_1x2)[0]?.book === "house" ? "house prices · no bookmaker line yet" : `prices: ${Object.values(m.prices_1x2)[0]?.book ?? "–"}`}
        </span>
        {m.best_value && (
          <span className="rounded bg-accent/15 px-1.5 py-0.5 text-accent">
            value: {selectionLabel(m.best_value.market, m.best_value.selection, m.best_value.line, m.home.short, m.away.short)}{" "}
            {signed(m.best_value.ev)}
          </span>
        )}
      </div>
    </div>
  );
}
