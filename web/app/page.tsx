"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import MatchCard from "@/components/MatchCard";
import { api, kickoffLabel, MatchCard as M } from "@/lib/api";

type Upcoming = { upcoming: M[]; recent_results: { id: number; kickoff: string; home: any; away: any; score: string }[] };

export default function Home() {
  const [data, setData] = useState<Upcoming | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<Upcoming>("/api/matches/upcoming").then(setData).catch((e) => setErr(e.message));
  }, []);

  return (
    <div className="space-y-8">
      <section className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">MLS pregame model vs the market</h1>
          <p className="mt-2 max-w-2xl text-muted">
            Expected goals from xG-weighted team ratings, MLS context (travel, altitude, turf, rest) and player availability,
            turned into one coherent score distribution for 1X2, Asian handicap and totals. Bet on it with fake credits and see
            if you can beat the closing line. The{" "}
            <Link href="/model" className="text-sky underline">
              backtest
            </Link>{" "}
            says that is hard.
          </p>
        </div>
        <div className="card text-sm">
          <div className="mb-2 font-semibold">How to play</div>
          <ol className="list-decimal space-y-1 pl-4 text-muted">
            <li>Tap a price to add it to your slip (singles or accumulators).</li>
            <li>
              <b className="text-ink">Live</b>: real upcoming MLS fixtures, settled automatically from results.
            </li>
            <li>
              <b className="text-ink">
                <Link href="/replay" className="underline">
                  Replay
                </Link>
              </b>
              : bet on any past matchday (MLS 2014–2026, EPL 2016–2026), then kick it off.
            </li>
            <li>Max 5% of bankroll per bet, daily loss limit 250. Fake credits only.</li>
          </ol>
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <h2 className="text-lg font-semibold">Upcoming MLS fixtures</h2>
          <span className="text-xs text-muted">priced by the live model · odds: ESPN/Bet365, The Odds API (optional) or house</span>
        </div>
        {err && <p className="text-bad">API not reachable: {err}. Start the backend with `oddsforge serve`.</p>}
        {!data && !err && <p className="text-muted">Loading fixtures…</p>}
        {data && data.upcoming.length === 0 && (
          <div className="card text-muted">
            No upcoming MLS fixtures in the current data snapshot. Run <code>oddsforge refresh</code>, or play{" "}
            <Link href="/replay" className="text-sky underline">
              Replay
            </Link>
            .
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data?.upcoming.map((m) => <MatchCard key={m.id} m={m} mode="live" />)}
        </div>
      </section>

      {data && data.recent_results.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Recent results</h2>
          <div className="card grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {data.recent_results.map((r) => (
              <Link key={r.id} href={`/match/${r.id}`} className="flex justify-between gap-2 py-1 hover:text-sky">
                <span className="truncate">
                  {r.home.short} <span className="font-mono">{r.score}</span> {r.away.short}
                </span>
                <span className="whitespace-nowrap text-xs text-muted">{kickoffLabel(r.kickoff)}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
