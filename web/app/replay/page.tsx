"use client";

import { useCallback, useEffect, useState } from "react";
import MatchCard from "@/components/MatchCard";
import { PlayerGate } from "@/components/BetSlip";
import { useApp } from "@/components/Providers";
import { api, MatchCard as M, money } from "@/lib/api";

type Day = { day: string; matches: number; revealed: boolean };

export default function Replay() {
  const { me, refreshMe, notify } = useApp();
  const [league, setLeague] = useState("MLS");
  const [seasons, setSeasons] = useState<{ season: string; matches: number }[]>([]);
  const [season, setSeason] = useState<string>("");
  const [days, setDays] = useState<Day[]>([]);
  const [day, setDay] = useState<string>("");
  const [matches, setMatches] = useState<M[]>([]);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    api<{ season: string; matches: number }[]>(`/api/replay/seasons?league=${league}`).then((s) => {
      setSeasons(s);
      setSeason(s[1]?.season ?? s[0]?.season ?? "");
    });
  }, [league]);

  const loadDays = useCallback(async () => {
    if (!season) return;
    const d = await api<Day[]>(`/api/replay/matchdays?league=${league}&season=${encodeURIComponent(season)}`);
    setDays(d);
    setDay((cur) => (d.some((x) => x.day === cur) ? cur : (d.find((x) => !x.revealed && x.matches >= 4) ?? d[0])?.day ?? ""));
  }, [league, season]);

  useEffect(() => {
    loadDays();
  }, [loadDays, me?.name]);

  const loadDay = useCallback(async () => {
    if (!day) return;
    const r = await api<{ matches: M[]; revealed: boolean }>(`/api/replay/day?league=${league}&day=${day}`);
    setMatches(r.matches);
    setRevealed(r.revealed);
  }, [league, day]);

  useEffect(() => {
    loadDay();
  }, [loadDay, me?.name]);

  const kickoff = async () => {
    const before = me?.bankroll ?? 0;
    const r = await api<{ settled_bets: number[]; bankroll: number }>("/api/replay/kickoff", {
      method: "POST",
      body: JSON.stringify({ league, day }),
    });
    await refreshMe();
    await loadDay();
    await loadDays();
    notify(
      r.settled_bets.length
        ? `Full time! ${r.settled_bets.length} bet(s) settled · bankroll ${money(before)} → ${money(r.bankroll)}`
        : "Full time! Results revealed (no bets on this matchday)",
    );
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Replay a matchday</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Every past match has the model&apos;s <b className="text-ink">walk-forward prediction</b>: made with only the data
          available the week before kickoff. Prices are real closing odds (market average). Scores stay hidden until you kick
          off. Replay is practice: it never counts on the live leaderboard.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {["MLS", "EPL"].map((l) => (
          <button
            key={l}
            onClick={() => setLeague(l)}
            className={`rounded-md px-3 py-1.5 text-sm ${league === l ? "bg-accent text-bg" : "border border-line text-muted"}`}
          >
            {l}
          </button>
        ))}
        <select
          value={season}
          onChange={(e) => setSeason(e.target.value)}
          className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
        >
          {seasons.map((s) => (
            <option key={s.season} value={s.season}>
              {s.season} ({s.matches})
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">
          {league === "EPL" ? "EPL replay has real closing 1X2, Asian handicap and O/U 2.5 prices." : "MLS replay: real closing 1X2; AH and totals at house prices."}
        </span>
      </div>

      <div className="no-scrollbar flex gap-1.5 overflow-x-auto pb-1">
        {days.map((d) => (
          <button
            key={d.day}
            onClick={() => setDay(d.day)}
            className={`whitespace-nowrap rounded-md border px-2.5 py-1 text-xs ${
              d.day === day ? "border-accent text-accent" : d.revealed ? "border-line text-muted line-through" : "border-line"
            }`}
          >
            {d.day.slice(5)} · {d.matches}
          </button>
        ))}
      </div>

      {!me && (
        <div className="card max-w-md">
          <PlayerGate />
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          {league} · {day}
        </h2>
        {me && !revealed && matches.length > 0 && (
          <button onClick={kickoff} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-bg">
            Kick off matchday ▶
          </button>
        )}
        {revealed && <span className="rounded bg-line px-2 py-1 text-xs text-muted">full time · revealed</span>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {matches.map((m) => (
          <MatchCard key={m.id} m={m} mode="replay" />
        ))}
      </div>
    </div>
  );
}
