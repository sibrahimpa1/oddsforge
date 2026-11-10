"use client";

import { use, useCallback, useEffect, useState } from "react";
import { PriceButton, ProbBar } from "@/components/MatchCard";
import { api, kickoffLabel, pct, selectionLabel, signed, stageLabel, ValueRow } from "@/lib/api";

const FACTOR: Record<string, string> = {
  is_home: "Home advantage",
  rest_own: "Rest days",
  rest_opp: "Opponent rest",
  travel_km: "Travel distance (km)",
  tz_shift: "Time-zone shift (h)",
  venue_altitude: "Altitude above 1,000 m (km)",
  altitude_unaccustomed: "Altitude, sea-level visitor (km)",
  venue_turf: "Artificial turf",
  own_home_turf: "Plays home on turf",
  knockout: "Playoff knockout",
  season_progress: "Season phase",
  games_last_10d_own: "Games in last 10 days",
  games_last_10d_opp: "Opponent games in 10 days",
  midweek: "Midweek",
  cross_conference: "Cross-conference",
};

type Player = {
  player_id: string;
  name: string;
  position: string;
  minutes: number;
  minutes_share: number;
  attack_loss_pct: number;
  defence_loss: number;
  replacement: string;
};

export default function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [d, setD] = useState<any>(null);
  const [absent, setAbsent] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<any>(null);
  const [loadingAI, setLoadingAI] = useState(false);

  const load = useCallback(async () => {
    setD(await api(`/api/matches/${id}?absent=${absent.join(",")}`));
  }, [id, absent]);
  useEffect(() => {
    load();
  }, [load]);

  if (!d) return <p className="text-muted">Loading…</p>;
  const model = d.model;
  const lad = model?.ladder;
  const mode: "live" | "replay" = d.mode;
  const closed = mode === "live" ? new Date(d.kickoff) <= new Date() : !!d.score;
  const fair1x2: Record<string, any> = Object.fromEntries((d.board["1x2"] ?? []).map((r: any) => [r.selection, r]));
  const values: ValueRow[] = d.values ?? [];
  const hs = d.home.short;
  const as = d.away.short;

  const ask = async () => {
    setLoadingAI(true);
    try {
      setAnalysis(await api(`/api/matches/${id}/analysis`, { method: "POST", body: JSON.stringify({ absent }) }));
    } finally {
      setLoadingAI(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="card">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="rounded bg-line px-1.5 py-0.5">{d.league}</span>
          <span>{kickoffLabel(d.kickoff)}</span>
          {d.stage && <span>{stageLabel(d.stage)}</span>}
          {d.venue && <span>· {d.venue}</span>}
          <span className="ml-auto rounded bg-line px-1.5 py-0.5 uppercase">{mode === "live" ? "live · pregame" : "replay"}</span>
        </div>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <div className="text-lg font-bold sm:text-2xl">{d.home.name}</div>
          <div className="rounded-lg bg-bg px-3 py-2 font-mono text-lg">
            {d.score ? `${d.score.home} – ${d.score.away}` : "vs"}
          </div>
          <div className="text-right text-lg font-bold sm:text-2xl">{d.away.name}</div>
        </div>
        {d.score?.home_xg != null && (
          <div className="mt-1 text-center text-xs text-muted">
            match xG {d.score.home_xg.toFixed(2)} – {d.score.away_xg.toFixed(2)}
          </div>
        )}
        {mode === "replay" && !d.score && (
          <p className="mt-2 text-center text-xs text-muted">Score hidden until you kick off this matchday in Replay.</p>
        )}
      </div>

      {lad && (
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          {/* model vs market */}
          <div className="card space-y-4">
            <div className="flex items-baseline justify-between">
              <h2 className="font-semibold">Model vs market · 1X2</h2>
              <span className="text-xs text-muted">as of {model.as_of.slice(0, 10)}</span>
            </div>
            <ProbBar p={lad["1x2"]} />
            <table className="data">
              <thead>
                <tr>
                  <th>Outcome</th>
                  <th>Model</th>
                  <th>Market (no-vig)</th>
                  <th>Fair</th>
                  <th>Price</th>
                  <th>EV</th>
                </tr>
              </thead>
              <tbody>
                {(["home", "draw", "away"] as const).map((k) => {
                  const f = fair1x2[k];
                  const ev = f ? lad["1x2"][k] * f.price - 1 : null;
                  return (
                    <tr key={k}>
                      <td>{k === "home" ? hs : k === "away" ? as : "Draw"}</td>
                      <td className="font-mono">{pct(lad["1x2"][k], 1)}</td>
                      <td className="font-mono text-muted">{f ? pct(f.fair_prob, 1) : "–"}</td>
                      <td className="font-mono text-muted">{(1 / lad["1x2"][k]).toFixed(2)}</td>
                      <td className="font-mono">{f ? f.price.toFixed(2) : "–"}</td>
                      <td className={`font-mono ${ev != null && ev > 0.03 && f.book !== "house" ? "text-good" : "text-muted"}`}>
                        {f?.book === "house" ? "house" : signed(ev)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                ["xG " + hs, lad.xg_home],
                ["xG " + as, lad.xg_away],
                ["Total", lad.xg_total],
                ["BTTS", lad.btts.yes],
              ].map(([l, v], i) => (
                <div key={i} className="rounded-lg bg-bg p-2">
                  <div className="truncate text-[11px] text-muted">{l as string}</div>
                  <div className="font-mono text-lg">{i === 3 ? pct(v as number) : (v as number).toFixed(2)}</div>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted">
              Team strength alone: {model.base_lam_h.toFixed(2)} – {model.base_lam_a.toFixed(2)} xG. Context
              {model.lineup ? " and absences move" : " moves"} it to {model.lam_h.toFixed(2)} – {model.lam_a.toFixed(2)}. Dixon-Coles ρ ={" "}
              {model.rho.toFixed(3)}. Every market below is read from this one score distribution, so 1X2, handicaps and totals
              cannot contradict each other.
            </p>
          </div>

          {/* score matrix */}
          <div className="card">
            <h2 className="mb-3 font-semibold">Score distribution</h2>
            <div className="overflow-x-auto">
              <table className="mx-auto text-center font-mono text-[11px]">
                <thead>
                  <tr>
                    <th className="p-1 text-muted">
                      {hs.slice(0, 3)}↓ {as.slice(0, 3)}→
                    </th>
                    {lad.matrix[0].map((_: number, j: number) => (
                      <th key={j} className="p-1 text-muted">
                        {j}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {lad.matrix.map((row: number[], i: number) => (
                    <tr key={i}>
                      <td className="p-1 text-muted">{i}</td>
                      {row.map((p, j) => (
                        <td
                          key={j}
                          className="h-8 w-9 rounded"
                          style={{
                            background: `rgba(${i > j ? "163,230,53" : i < j ? "56,189,248" : "148,163,184"},${Math.min(p * 7, 0.9)})`,
                          }}
                          title={`${i}-${j}: ${(p * 100).toFixed(1)}%`}
                        >
                          {p >= 0.01 ? (p * 100).toFixed(0) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 text-xs text-muted">
              Most likely: {lad.top_scores.slice(0, 4).map((s: any) => `${s.score} (${pct(s.prob, 1)})`).join(" · ")}
            </div>
          </div>
        </div>
      )}

      {/* value table */}
      {values.length > 0 && (
        <div className="card">
          <div className="mb-3 flex items-baseline justify-between gap-2">
            <h2 className="font-semibold">Bettable markets</h2>
            <span className="text-xs text-muted">value = model EV ≥ 3% vs a real bookmaker price; edges &gt; 25% are flagged, not trusted</span>
          </div>
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>Selection</th>
                  <th>Book</th>
                  <th>Price</th>
                  <th>Model</th>
                  <th>Market</th>
                  <th>EV</th>
                  <th>Verdict</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {values.map((v, i) => (
                  <tr key={i}>
                    <td className="whitespace-nowrap">{selectionLabel(v.market, v.selection, v.line, hs, as)}</td>
                    <td className="text-muted">{v.book}</td>
                    <td className="font-mono">{v.price.toFixed(2)}</td>
                    <td className="font-mono">{pct(v.model_prob, 1)}</td>
                    <td className="font-mono text-muted">{pct(v.market_prob, 1)}</td>
                    <td className={`font-mono ${v.ev > 0 ? "text-good" : "text-bad"}`}>{signed(v.ev)}</td>
                    <td title={v.why}>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] ${
                          v.verdict === "value"
                            ? "bg-accent/15 text-accent"
                            : v.verdict === "caution"
                              ? "bg-warn/15 text-warn"
                              : "bg-line text-muted"
                        }`}
                      >
                        {v.verdict}
                      </span>
                    </td>
                    <td className="w-24">
                      <PriceButton
                        m={{ ...d, prediction: null } as any}
                        market={v.market}
                        selection={v.selection}
                        line={v.line}
                        price={v.price}
                        book={v.book}
                        modelProb={v.model_prob}
                        mode={mode}
                        disabled={closed}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {lad && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="card">
            <h2 className="mb-2 font-semibold">Asian handicap · model fair prices</h2>
            <table className="data">
              <thead>
                <tr>
                  <th>{hs} line</th>
                  <th>{hs}</th>
                  <th>{as}</th>
                  <th>P({hs})*</th>
                </tr>
              </thead>
              <tbody>
                {lad.asian_handicap
                  .filter((r: any) => Math.abs(r.home_prob - 0.5) < 0.3)
                  .map((r: any) => (
                    <tr key={r.line}>
                      <td className="font-mono">
                        {r.line > 0 ? "+" : ""}
                        {r.line}
                      </td>
                      <td className="font-mono">{r.home_fair.toFixed(2)}</td>
                      <td className="font-mono">{r.away_fair.toFixed(2)}</td>
                      <td className="font-mono text-muted">{pct(r.home_prob, 1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-muted">*push-adjusted: the win probability of an equivalent no-push bet.</p>
          </div>
          <div className="card">
            <h2 className="mb-2 font-semibold">Totals · model fair prices</h2>
            <table className="data">
              <thead>
                <tr>
                  <th>Line</th>
                  <th>Over</th>
                  <th>Under</th>
                  <th>P(over)*</th>
                </tr>
              </thead>
              <tbody>
                {lad.totals.map((r: any) => (
                  <tr key={r.line}>
                    <td className="font-mono">{r.line}</td>
                    <td className="font-mono">{r.over_fair.toFixed(2)}</td>
                    <td className="font-mono">{r.under_fair.toFixed(2)}</td>
                    <td className="font-mono text-muted">{pct(r.over_prob, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* lineup + context */}
      {(d.lineup_options || (model && Object.keys(model.context ?? {}).length > 0)) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {d.lineup_options && (
            <div className="card">
              <h2 className="font-semibold">Player availability</h2>
              <p className="mb-3 text-xs text-muted">
                Tick players who are out. Each is valued against his actual replacement (xG+xA per 90, goals-added defending,
                goalkeeper shot-stopping), scaled by how often he normally plays.
                {model?.lineup && (
                  <span className="text-ink">
                    {" "}
                    Now: {hs} {signed(model.lineup.delta_lh / model.base_lam_h, 0)} xG, {as}{" "}
                    {signed(model.lineup.delta_la / model.base_lam_a, 0)} xG.
                  </span>
                )}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {(["home", "away"] as const).map((side) => (
                  <div key={side}>
                    <div className="mb-1 text-xs font-semibold text-muted">{side === "home" ? d.home.name : d.away.name}</div>
                    <ul className="space-y-1">
                      {(d.lineup_options[side] as Player[]).map((p) => (
                        <li key={p.player_id}>
                          <label className="flex cursor-pointer items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={absent.includes(p.player_id)}
                              onChange={(e) =>
                                setAbsent((a) => (e.target.checked ? [...a, p.player_id] : a.filter((x) => x !== p.player_id)))
                              }
                              className="accent-[#a3e635]"
                              aria-label={`${p.name} unavailable`}
                            />
                            <span className="w-7 text-muted">{p.position}</span>
                            <span className="flex-1 truncate" title={`replacement: ${p.replacement}`}>
                              {p.name}
                            </span>
                            <span className="font-mono text-muted" title="share of own xG lost / goals conceded added">
                              {p.attack_loss_pct > 0 ? `-${p.attack_loss_pct}%` : ""}
                              {p.defence_loss > 0.005 ? ` +${p.defence_loss.toFixed(2)}ga` : ""}
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
          {model && Object.keys(model.context ?? {}).length > 0 && (
            <div className="card">
              <h2 className="font-semibold">Why: context effects on expected goals</h2>
              <p className="mb-3 text-xs text-muted">
                SHAP contributions from the LightGBM context model, which only adjusts the rating-based expected goals.
              </p>
              <table className="data">
                <thead>
                  <tr>
                    <th>Factor</th>
                    <th>{hs}</th>
                    <th>{as}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(model.context as Record<string, any>)
                    .sort((a, b) => Math.abs(b[1].home) + Math.abs(b[1].away) - Math.abs(a[1].home) - Math.abs(a[1].away))
                    .slice(0, 8)
                    .map(([f, c]) => (
                      <tr key={f}>
                        <td>{FACTOR[f] ?? f}</td>
                        {(["home", "away"] as const).map((s) => (
                          <td key={s} className={`font-mono ${c[s] > 0.005 ? "text-good" : c[s] < -0.005 ? "text-bad" : "text-muted"}`}>
                            {signed(Math.exp(c[s]) - 1)}
                            <span className="ml-1 text-[10px] text-muted">({Number(c[`value_${s}`]).toFixed(f.includes("altitude") ? 2 : 0)})</span>
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* AI analyst */}
      <div className="card">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">AI match analyst</h2>
          <button onClick={ask} disabled={loadingAI} className="rounded-lg border border-accent px-3 py-1.5 text-sm text-accent">
            {loadingAI ? "Thinking…" : analysis ? "Regenerate" : "Explain this prediction"}
          </button>
        </div>
        {analysis && (
          <div className="mt-3">
            <p className="whitespace-pre-line text-sm leading-relaxed">{analysis.text}</p>
            <p className="mt-2 text-[11px] text-muted">
              {analysis.source === "claude"
                ? `Written by Claude (${analysis.model}) from the model's fact sheet only.`
                : "Offline template (add ANTHROPIC_API_KEY for Claude-written analysis). Same facts, no AI."}
            </p>
          </div>
        )}
      </div>

      {/* form & h2h */}
      <div className="grid gap-4 md:grid-cols-3">
        {(["home", "away"] as const).map((side) => (
          <div key={side} className="card">
            <h2 className="mb-2 font-semibold">{side === "home" ? d.home.short : d.away.short} · last 5</h2>
            <table className="data">
              <tbody>
                {d.form[side].map((f: any, i: number) => (
                  <tr key={i}>
                    <td>
                      <span
                        className={`inline-block w-5 rounded text-center text-[11px] font-bold text-bg ${
                          f.result === "W" ? "bg-good" : f.result === "D" ? "bg-muted" : "bg-bad"
                        }`}
                      >
                        {f.result}
                      </span>
                    </td>
                    <td className="text-muted">{f.venue}</td>
                    <td className="truncate">{f.opponent}</td>
                    <td className="font-mono">
                      {f.gf}-{f.ga}
                    </td>
                    <td className="font-mono text-[11px] text-muted">
                      {f.xgf != null ? `${f.xgf.toFixed(1)}-${f.xga.toFixed(1)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        <div className="card">
          <h2 className="mb-2 font-semibold">Head to head</h2>
          <table className="data">
            <tbody>
              {d.h2h.map((h: any, i: number) => (
                <tr key={i}>
                  <td className="text-[11px] text-muted">{h.date.slice(0, 7)}</td>
                  <td className="truncate">
                    {h.home} <span className="font-mono">{h.score}</span> {h.away}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
