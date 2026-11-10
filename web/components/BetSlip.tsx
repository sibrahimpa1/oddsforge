"use client";

import { useState } from "react";
import { api, money, signed } from "@/lib/api";
import { useApp } from "./Providers";

export function PlayerGate({ onDone }: { onDone?: () => void }) {
  const { setToken } = useApp();
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const r = await api<{ token: string }>("/api/players", { method: "POST", body: JSON.stringify({ name }) });
          setToken(r.token);
          onDone?.();
        } catch (e: any) {
          setErr(e.message);
        }
      }}
    >
      <p className="text-sm text-muted">
        Pick a player name to get <b className="text-ink">1,000 fake credits</b>. No email, no payment, no real money. Ever.
      </p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Player name"
        className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-ink outline-none focus:border-accent"
      />
      {err && <p className="text-sm text-bad">{err}</p>}
      <button className="w-full rounded-lg bg-accent px-3 py-2 font-semibold text-bg">Start playing</button>
    </form>
  );
}

export default function BetSlip() {
  const { slip, removeLeg, clearSlip, me, refreshMe, slipOpen, setSlipOpen, notify } = useApp();
  const [stake, setStake] = useState("10");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const odds = slip.reduce((a, l) => a * l.price, 1);
  const modelEv = slip.every((l) => l.model_prob != null)
    ? slip.reduce((a, l) => a * (l.model_prob! * l.price), 1) - 1
    : null;
  const s = parseFloat(stake) || 0;

  const place = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api("/api/bets", {
        method: "POST",
        body: JSON.stringify({
          legs: slip.map((l) => ({ match_id: l.match_id, market: l.market, selection: l.selection, line: l.line })),
          stake: s,
          mode: slip[0].mode,
        }),
      });
      notify(`Bet placed: ${money(s)} credits at ${odds.toFixed(2)}`);
      clearSlip();
      await refreshMe();
      setSlipOpen(false);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {slip.length > 0 && !slipOpen && (
        <button
          onClick={() => setSlipOpen(true)}
          className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full bg-accent px-5 py-3 font-semibold text-bg shadow-lg shadow-black/40"
        >
          Bet slip <span className="rounded-full bg-bg px-2 text-xs text-accent">{slip.length}</span>
          <span className="tabular-nums">@ {odds.toFixed(2)}</span>
        </button>
      )}
      {slipOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setSlipOpen(false)}>
          <aside
            onClick={(e) => e.stopPropagation()}
            className="flex h-full w-full max-w-md flex-col border-l border-line bg-panel p-5"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                Bet slip{" "}
                <span className="ml-1 rounded bg-line px-2 py-0.5 text-xs uppercase text-muted">
                  {slip[0]?.mode === "replay" ? "replay · practice" : "live · pregame"}
                </span>
              </h2>
              <button onClick={() => setSlipOpen(false)} className="text-muted hover:text-ink" aria-label="Close">
                ✕
              </button>
            </div>
            {!me ? (
              <PlayerGate />
            ) : slip.length === 0 ? (
              <p className="text-muted">Tap any price to add it here.</p>
            ) : (
              <>
                <ul className="flex-1 space-y-2 overflow-y-auto">
                  {slip.map((l) => (
                    <li key={l.match_id} className="rounded-lg border border-line bg-bg p-3">
                      <div className="flex justify-between gap-2">
                        <div>
                          <div className="font-medium">{l.label}</div>
                          <div className="text-xs text-muted">{l.matchLabel}</div>
                          <div className="text-xs text-muted">
                            {l.book === "house" ? "OddsForge house price" : l.book}
                            {l.model_prob != null && ` · model ${(l.model_prob * 100).toFixed(1)}%`}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="font-mono text-accent">{l.price.toFixed(2)}</div>
                          <button onClick={() => removeLeg(l.match_id)} className="text-xs text-muted hover:text-bad">
                            remove
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="mt-4 space-y-3 border-t border-line pt-4">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted">{slip.length > 1 ? `Accumulator (${slip.length} legs)` : "Single"}</span>
                    <span className="font-mono">@ {odds.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      step="1"
                      value={stake}
                      onChange={(e) => setStake(e.target.value)}
                      className="w-28 rounded-lg border border-line bg-bg px-3 py-2 font-mono outline-none focus:border-accent"
                    />
                    <span className="text-sm text-muted">credits · max {money(me.stake_limit)} per bet</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted">Potential return</span>
                    <span className="font-mono">{money(s * odds)}</span>
                  </div>
                  {modelEv != null && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted">Model expected value</span>
                      <span className={`font-mono ${modelEv > 0 ? "text-good" : "text-bad"}`}>{signed(modelEv)}</span>
                    </div>
                  )}
                  {slip.length > 1 && (
                    <p className="text-xs text-muted">
                      Accumulators multiply the bookmaker margin: every extra leg makes the expected loss larger.
                    </p>
                  )}
                  {err && <p className="text-sm text-bad">{err}</p>}
                  <button
                    disabled={busy || s <= 0}
                    onClick={place}
                    className="w-full rounded-lg bg-accent py-3 font-semibold text-bg disabled:opacity-50"
                  >
                    {busy ? "Placing…" : `Place ${money(s)} fake credits`}
                  </button>
                  <p className="text-center text-xs text-muted">Bankroll {money(me.bankroll)} · fake credits only</p>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
