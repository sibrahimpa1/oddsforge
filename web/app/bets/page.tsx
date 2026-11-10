"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PlayerGate } from "@/components/BetSlip";
import { useApp } from "@/components/Providers";
import { api, money, pct, selectionLabel, signed } from "@/lib/api";

const STATUS: Record<string, string> = {
  won: "text-good",
  half_won: "text-good",
  lost: "text-bad",
  half_lost: "text-bad",
  void: "text-muted",
  open: "text-warn",
};

export default function Bets() {
  const { me } = useApp();
  const [bets, setBets] = useState<any[]>([]);
  useEffect(() => {
    if (me) api<any[]>("/api/bets").then(setBets);
  }, [me]);

  if (!me)
    return (
      <div className="card mx-auto max-w-md">
        <h1 className="mb-3 text-xl font-bold">Your fake-money account</h1>
        <PlayerGate />
      </div>
    );

  const curve = me.pnl_curve.map((p, i) => ({ i: i + 1, pnl: p.pnl }));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-bold">{me.name}</h1>
        <div className="text-right">
          <div className="text-xs text-muted">Bankroll (fake credits)</div>
          <div className="font-mono text-2xl text-accent">{money(me.bankroll)}</div>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(["live", "replay"] as const).map((k) => (
          <div key={k} className="card">
            <div className="text-xs uppercase text-muted">{k === "live" ? "Live (counts on leaderboard)" : "Replay (practice)"}</div>
            <div className={`mt-1 font-mono text-xl ${me[k].profit >= 0 ? "text-good" : "text-bad"}`}>
              {me[k].profit >= 0 ? "+" : ""}
              {money(me[k].profit)}
            </div>
            <div className="text-xs text-muted">
              {me[k].settled} settled · {me[k].open} open · ROI {me[k].roi == null ? "–" : signed(me[k].roi)}
            </div>
          </div>
        ))}
        <div className="card">
          <div className="text-xs uppercase text-muted">Limits</div>
          <div className="mt-1 text-sm">
            Max stake <span className="font-mono">{money(me.stake_limit)}</span>
          </div>
          <div className="text-sm">
            Lost last 24h <span className="font-mono">{money(me.lost_last_24h)}</span> / {money(me.daily_loss_limit)}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-muted">Model EV of your bets</div>
          <div className="mt-1 font-mono text-xl">{signed(me.live.avg_model_ev ?? me.replay.avg_model_ev)}</div>
          <div className="text-xs text-muted">average at placement, per the model</div>
        </div>
      </div>

      {curve.length > 1 && (
        <div className="card h-64">
          <div className="mb-2 text-sm font-semibold">Profit and loss by settled bet</div>
          <ResponsiveContainer width="100%" height="85%">
            <LineChart data={curve}>
              <CartesianGrid stroke="#1e2935" />
              <XAxis dataKey="i" stroke="#8794a3" fontSize={11} />
              <YAxis stroke="#8794a3" fontSize={11} />
              <ReferenceLine y={0} stroke="#8794a3" />
              <Tooltip contentStyle={{ background: "#111821", border: "1px solid #1e2935" }} />
              <Line type="stepAfter" dataKey="pnl" stroke="#a3e635" dot={false} strokeWidth={2} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Bet history</h2>
        {bets.length === 0 ? (
          <p className="text-sm text-muted">
            No bets yet. Try <Link href="/replay" className="text-sky underline">Replay</Link> for instant results.
          </p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Placed</th>
                <th>Mode</th>
                <th>Selections</th>
                <th>Odds</th>
                <th>Stake</th>
                <th>Model EV</th>
                <th>Status</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {bets.map((b) => (
                <tr key={b.id}>
                  <td className="whitespace-nowrap text-muted">{b.placed_at.slice(5, 16).replace("T", " ")}</td>
                  <td className="text-muted">{b.mode}</td>
                  <td>
                    {b.legs.map((l: any, i: number) => (
                      <div key={i} className="whitespace-nowrap">
                        <Link href={`/match/${l.match_id}`} className="hover:text-sky">
                          {selectionLabel(l.market, l.selection, l.line, l.home.toUpperCase(), l.away.toUpperCase())}
                        </Link>{" "}
                        <span className="text-[11px] text-muted">
                          {l.home.toUpperCase()} v {l.away.toUpperCase()} @ {l.odds.toFixed(2)}
                          {l.score && ` · ${l.score}`}
                          {l.model_prob != null && ` · model ${pct(l.model_prob)}`}
                        </span>
                      </div>
                    ))}
                  </td>
                  <td className="font-mono">{b.odds.toFixed(2)}</td>
                  <td className="font-mono">{money(b.stake)}</td>
                  <td className="font-mono text-muted">{signed(b.model_ev)}</td>
                  <td className={STATUS[b.status] ?? ""}>{b.status.replace("_", " ")}</td>
                  <td className={`font-mono ${b.profit > 0 ? "text-good" : b.profit < 0 ? "text-bad" : ""}`}>
                    {b.profit == null ? "–" : `${b.profit > 0 ? "+" : ""}${money(b.profit)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
