"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, pct, signed } from "@/lib/api";

const NAMES: Record<string, string> = {
  goals_only: "Goals-only Dixon-Coles",
  xg_blend: "xG-blend ratings",
  xg_blend_context: "xG-blend + MLS context (final)",
  market_pinnacle_close: "Pinnacle closing line (no-vig)",
  market_average_close: "Market average close",
};
const tip = { contentStyle: { background: "#111821", border: "1px solid #1e2935", fontSize: 12 } };

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="card">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${tone ?? ""}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export default function ModelPage() {
  const [r, setR] = useState<any>(null);
  const [outcome, setOutcome] = useState<"home" | "draw" | "away">("draw");
  useEffect(() => {
    api("/api/backtest").then(setR);
  }, []);
  if (!r) return <p className="text-muted">Loading backtest report…</p>;
  const m = r.mls;
  const e = r.epl;
  const final = m.models.xg_blend_context;
  const mkt = m.models.market_pinnacle_close;
  const shop = m.betting.find((b: any) => b.strategy.book === "best" && b.strategy.min_edge === 0.03 && b.strategy.staking === "flat");
  const leakHonest = m.leakage_audit.walk_forward.betting;
  const leak = m.leakage_audit.in_sample_leak.betting;
  const epl1x2 = e.betting.find((b: any) => b.strategy.market === "1x2" && b.strategy.name.includes("model"));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Model &amp; backtest</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Real numbers from <code>oddsforge backtest</code>, generated {r.generated_at.slice(0, 10)}. Hyperparameters were tuned on
          MLS {m.tuning.period.join("–")} using log-loss only, then frozen. Everything below is the untouched {m.test_period} holdout,
          predicted walk-forward: each week the model only sees matches that kicked off before that week.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={`MLS log-loss, model (n=${final.n})`} value={final.log_loss.toFixed(4)} sub={`Pinnacle close: ${mkt.log_loss.toFixed(4)}`} />
        <Stat
          label="Best-price betting, edge ≥ 3%"
          value={signed(shop.roi)}
          tone={shop.roi >= 0 ? "text-good" : "text-bad"}
          sub={`${shop.bets} bets · 95% CI ${signed(shop.roi_ci95[0])} to ${signed(shop.roi_ci95[1])}`}
        />
        <Stat
          label="Leakage audit: in-sample ROI"
          value={signed(leak.roi)}
          tone="text-warn"
          sub={`same bets, honest walk-forward: ${signed(leakHonest.roi)}`}
        />
        <Stat
          label="EPL closing-line value (1X2)"
          value={signed(epl1x2.clv_mean)}
          tone={epl1x2.clv_mean >= 0 ? "text-good" : "text-bad"}
          sub={`${pct(epl1x2.clv_positive_share)} of ${epl1x2.bets} bets beat the close`}
        />
      </div>

      <div className="card border-warn/40 text-sm">
        <b>Verdict.</b> The model is well calibrated and clearly better than a goals-only baseline, but the closing market is
        still {((final.log_loss - mkt.log_loss) / mkt.log_loss * 100).toFixed(1)}% better on log-loss. Betting its edges against
        closing prices loses money, and the confidence intervals include zero. On the EPL, where opening prices exist, its bets
        are beaten by the close {pct(1 - epl1x2.clv_positive_share)} of the time. That is the expected result for a public-data
        model: the honest value is in the pipeline, the calibration and the audit, not in a promised ROI.
      </div>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card overflow-x-auto">
          <h2 className="mb-2 font-semibold">Probability quality · MLS {m.test_period}</h2>
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th>Log-loss</th>
                <th>Brier</th>
                <th>RPS</th>
                <th>ECE</th>
                <th>Acc.</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.models)
                .filter(([, v]) => v)
                .map(([k, v]: any) => (
                  <tr key={k} className={k.startsWith("market") ? "text-muted" : ""}>
                    <td>{NAMES[k] ?? k}</td>
                    <td className="font-mono">{v.log_loss.toFixed(4)}</td>
                    <td className="font-mono">{v.brier.toFixed(4)}</td>
                    <td className="font-mono">{v.rps.toFixed(4)}</td>
                    <td className="font-mono">{v.ece.toFixed(3)}</td>
                    <td className="font-mono">{pct(v.accuracy, 1)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">
            Lower is better except accuracy. Same {m.n_compare} games in every row. Draws: predicted {pct(m.draws.predicted, 1)} vs
            observed {pct(m.draws.observed, 1)} (Dixon-Coles ρ {m.draws.rho.toFixed(3)}). Expected goals: mean predicted total{" "}
            {m.goals.mean_pred_total.toFixed(2)} vs actual {m.goals.mean_actual_total.toFixed(2)}; MAE per team vs goals{" "}
            {m.goals.mae_goals_per_team.toFixed(2)}, vs match xG {m.goals.mae_vs_xg_per_team.toFixed(2)}.
          </p>
        </div>

        <div className="card">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-semibold">Calibration (reliability)</h2>
            <div className="flex gap-1">
              {(["home", "draw", "away"] as const).map((o) => (
                <button
                  key={o}
                  onClick={() => setOutcome(o)}
                  className={`rounded px-2 py-0.5 text-xs capitalize ${outcome === o ? "bg-accent text-bg" : "border border-line text-muted"}`}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer>
              <ScatterChart margin={{ left: -10, right: 10 }}>
                <CartesianGrid stroke="#1e2935" />
                <XAxis type="number" dataKey="pred" domain={[0, 0.8]} stroke="#8794a3" fontSize={11} tickFormatter={(v) => pct(v)} name="predicted" />
                <YAxis type="number" dataKey="obs" domain={[0, 0.8]} stroke="#8794a3" fontSize={11} tickFormatter={(v) => pct(v)} name="observed" />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 0.8, y: 0.8 }]} stroke="#8794a3" strokeDasharray="4 4" />
                <Tooltip {...tip} formatter={(v: any) => pct(v, 1)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Scatter name="Model" data={m.calibration[outcome].model} fill="#a3e635" line={{ stroke: "#a3e635", strokeWidth: 2 }} isAnimationActive={false} />
                <Scatter name="Pinnacle close" data={m.calibration[outcome].market} fill="#38bdf8" isAnimationActive={false} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-muted">Predicted probability (x) vs observed frequency (y), 10 equal-count bins. On the diagonal = calibrated.</p>
        </div>
      </section>

      <section className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Betting simulation · MLS {m.test_period} · 1X2, one bet per match</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Bets</th>
              <th>Hit rate</th>
              <th>Avg price</th>
              <th>Model EV</th>
              <th>Realised ROI</th>
              <th>95% CI</th>
            </tr>
          </thead>
          <tbody>
            {m.betting.map((b: any) => (
              <tr key={b.strategy.name}>
                <td>{b.strategy.name}</td>
                <td>{b.bets}</td>
                <td className="font-mono">{pct(b.hit_rate, 1)}</td>
                <td className="font-mono">{b.avg_price.toFixed(2)}</td>
                <td className="font-mono text-muted">{signed(b.avg_model_ev)}</td>
                <td className={`font-mono ${b.roi >= 0 ? "text-good" : "text-bad"}`}>{signed(b.roi)}</td>
                <td className="font-mono text-muted">
                  {signed(b.roi_ci95[0])} … {signed(b.roi_ci95[1])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">
          The gap between &quot;model EV&quot; (what the model believed) and realised ROI is the model&apos;s overconfidence against
          the market. Free MLS data has closing prices only, so these bets are placed at the close: the hardest benchmark there is.
        </p>
        <div className="mt-4 h-56">
          <ResponsiveContainer>
            <LineChart data={shop.curve} margin={{ left: -10, right: 10 }}>
              <CartesianGrid stroke="#1e2935" />
              <XAxis dataKey="t" stroke="#8794a3" fontSize={11} minTickGap={40} />
              <YAxis stroke="#8794a3" fontSize={11} />
              <ReferenceLine y={0} stroke="#8794a3" />
              <Tooltip {...tip} />
              <Line dataKey="cum" name="Cumulative units (best price, edge ≥ 3%)" stroke="#a3e635" dot={false} strokeWidth={2} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-semibold">ROI by model edge (best price)</h2>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart
                data={m.edge_buckets.map((b: any) => ({ ...b, err: [b.roi - b.roi_ci95[0], b.roi_ci95[1] - b.roi] }))}
                margin={{ left: -10, right: 10 }}
              >
                <CartesianGrid stroke="#1e2935" />
                <XAxis dataKey="bucket" stroke="#8794a3" fontSize={10} />
                <YAxis stroke="#8794a3" fontSize={11} tickFormatter={(v) => pct(v)} />
                <ReferenceLine y={0} stroke="#8794a3" />
                <Tooltip {...tip} formatter={(v: any, n: any) => (n === "roi" ? signed(v) : v)} />
                <Bar dataKey="roi" fill="#38bdf8" isAnimationActive={false}>
                  <ErrorBar dataKey="err" stroke="#e8edf2" width={4} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-muted">
            If the model had real edge, ROI would rise with the predicted edge. Bars: {m.edge_buckets.map((b: any) => b.bets).join(" / ")} bets.
          </p>
        </div>
        <div className="card overflow-x-auto">
          <h2 className="mb-2 font-semibold">ROI by odds range (edge ≥ 3%)</h2>
          <table className="data">
            <thead>
              <tr>
                <th>Price</th>
                <th>Bets</th>
                <th>ROI</th>
                <th>95% CI</th>
              </tr>
            </thead>
            <tbody>
              {m.odds_buckets.map((b: any) => (
                <tr key={b.bucket}>
                  <td>{b.bucket}</td>
                  <td>{b.bets}</td>
                  <td className={`font-mono ${b.roi >= 0 ? "text-good" : "text-bad"}`}>{signed(b.roi)}</td>
                  <td className="font-mono text-muted">
                    {signed(b.roi_ci95[0])} … {signed(b.roi_ci95[1])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2 className="mb-2 font-semibold">Leakage audit: what a leaky backtest would have claimed</h2>
        <p className="mb-3 text-sm text-muted">
          Same model, same games, same staking. The only difference: ratings refitted once per season <i>including that
          season&apos;s own results</i>, the most common backtest mistake. It turns a losing strategy into a &quot;profitable&quot; one.
        </p>
        <table className="data max-w-2xl">
          <thead>
            <tr>
              <th />
              <th>Log-loss</th>
              <th>Bets</th>
              <th>ROI</th>
              <th>95% CI</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["Honest walk-forward", m.leakage_audit.walk_forward],
              ["In-sample (leaky)", m.leakage_audit.in_sample_leak],
            ].map(([n, a]: any) => (
              <tr key={n}>
                <td>{n}</td>
                <td className="font-mono">{a.metrics.log_loss.toFixed(4)}</td>
                <td>{a.betting.bets}</td>
                <td className={`font-mono ${a.betting.roi >= 0 ? "text-warn" : "text-bad"}`}>{signed(a.betting.roi)}</td>
                <td className="font-mono text-muted">
                  {signed(a.betting.roi_ci95[0])} … {signed(a.betting.roi_ci95[1])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">EPL {e.test_period}: opening prices, CLV against the Pinnacle close</h2>
        <p className="mb-3 text-sm text-muted">
          football-data.co.uk has opening and closing prices for the EPL, so here bets are placed at the opening price (known at
          decision time) and judged by closing-line value. Model weight in log-linear pooling with the opening market, tuned on{" "}
          {e.tuning.period.join(" to ")}: <b className="text-ink">{e.pool_weight_model}</b>. The model adds no information the
          opening market doesn&apos;t already have.
        </p>
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <table className="data">
            <thead>
              <tr>
                <th>Source</th>
                <th>Log-loss</th>
                <th>RPS</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(e.models).map(([k, v]: any) => (
                <tr key={k}>
                  <td>{k.replaceAll("_", " ")}</td>
                  <td className="font-mono">{v.log_loss.toFixed(4)}</td>
                  <td className="font-mono">{v.rps.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="data">
            <thead>
              <tr>
                <th>Market / probabilities</th>
                <th>Bets</th>
                <th>ROI</th>
                <th>CLV</th>
                <th>Beat close</th>
              </tr>
            </thead>
            <tbody>
              {e.betting
                .filter((b: any) => b.bets > 0)
                .map((b: any) => (
                  <tr key={b.strategy.name}>
                    <td>
                      {b.strategy.market.toUpperCase()} · {b.strategy.name.includes("pooled") ? "pooled" : "model"}
                    </td>
                    <td>{b.bets}</td>
                    <td className={`font-mono ${b.roi >= 0 ? "text-good" : "text-bad"}`}>{signed(b.roi)}</td>
                    <td className={`font-mono ${b.clv_mean >= 0 ? "text-good" : "text-bad"}`}>{signed(b.clv_mean)}</td>
                    <td className="font-mono">{pct(b.clv_positive_share)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-semibold">Log-loss by season (model vs Pinnacle close)</h2>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={m.by_season} margin={{ left: -5, right: 10 }}>
                <CartesianGrid stroke="#1e2935" />
                <XAxis dataKey="season" stroke="#8794a3" fontSize={11} />
                <YAxis domain={["auto", "auto"]} stroke="#8794a3" fontSize={11} />
                <Tooltip {...tip} formatter={(v: any) => Number(v).toFixed(4)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="model_log_loss" name="Model" stroke="#a3e635" strokeWidth={2} isAnimationActive={false} />
                <Line dataKey="market_log_loss" name="Pinnacle close" stroke="#38bdf8" strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {m.seasons_without_pinnacle.length > 0 && (
            <p className="text-xs text-muted">
              {m.seasons_without_pinnacle.join(", ")}: no Pinnacle prices in the free data (other books only).
            </p>
          )}
        </div>
        <div className="card text-sm">
          <h2 className="mb-2 font-semibold">Method and known gaps</h2>
          <ul className="list-disc space-y-1 pl-5 text-muted">
            <li>
              Ratings: Poisson GLM, attack/defence per team, home term, target = {m.params.xg_weight} × xG + {1 - m.params.xg_weight} × goals,
              half-life {m.params.half_life_days} days, ridge {m.params.ridge}. Tuned over {m.tuning.combos} combinations.
            </li>
            <li>Context: LightGBM Poisson on the rating offset, retrained each season on out-of-sample rows only.</li>
            <li>Score model: Dixon-Coles; 1X2, AH, totals and BTTS all come from the same matrix.</li>
            <li>Vig removed with the power method (Shin and multiplicative are available and tested).</li>
            <li className="text-ink">Not in the backtest: lineups and injuries. Free data has no timestamped historical lineups, so player-availability adjustments run live only.</li>
            <li className="text-ink">MLS opening odds are not in the free data, so MLS CLV cannot be measured. That is why the EPL section exists.</li>
            <li className="text-ink">Rest and congestion ignore cup and CONCACAF games (league games only in the data).</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
