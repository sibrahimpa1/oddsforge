"use client";

import { useEffect, useState } from "react";
import { api, money, signed } from "@/lib/api";

export default function Leaderboard() {
  const [mode, setMode] = useState("live");
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    api<any[]>(`/api/leaderboard?mode=${mode}`).then(setRows);
  }, [mode]);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Leaderboard</h1>
      <p className="max-w-2xl text-sm text-muted">
        Ranked by profit on settled bets. Live only counts real upcoming fixtures. Replay is a separate practice table,
        because past results can be looked up. With a few dozen bets, luck dominates: a 95% interval on ROI is ±20 points or
        wider.
      </p>
      <div className="flex gap-2">
        {["live", "replay"].map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1.5 text-sm capitalize ${mode === m ? "bg-accent text-bg" : "border border-line text-muted"}`}
          >
            {m}
          </button>
        ))}
      </div>
      <div className="card overflow-x-auto">
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Bets</th>
              <th>Staked</th>
              <th>Profit</th>
              <th>ROI</th>
              <th>Bankroll</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.name}>
                <td className="text-muted">{i + 1}</td>
                <td className="font-medium">{r.name}</td>
                <td>{r.bets}</td>
                <td className="font-mono">{money(r.staked)}</td>
                <td className={`font-mono ${r.profit >= 0 ? "text-good" : "text-bad"}`}>{money(r.profit)}</td>
                <td className="font-mono">{signed(r.roi)}</td>
                <td className="font-mono text-muted">{money(r.bankroll)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="text-muted">
                  No settled {mode} bets yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
