export default function Responsible() {
  return (
    <div className="prose-invert max-w-3xl space-y-4 text-sm leading-relaxed">
      <h1 className="text-2xl font-bold">Responsible play</h1>
      <div className="card space-y-2">
        <p>
          <b>OddsForge uses fake credits only.</b> There are no deposits, no withdrawals, no prizes and no links to bookmakers.
          It exists to show how a pregame soccer model works and how hard it is to beat a betting market.
        </p>
        <p>
          The honest headline from our own backtest: across 2019–2026 MLS, betting the model&apos;s &quot;value&quot; picks
          against closing prices <b>lost about 4%</b> of turnover. Most people, and most models, lose to the bookmaker margin
          over time.
        </p>
      </div>
      <h2 className="text-lg font-semibold">Built-in guard rails</h2>
      <ul className="list-disc space-y-1 pl-5 text-muted">
        <li>One bet can risk at most 5% of your bankroll (and never more than 100 credits).</li>
        <li>A daily loss limit of 250 credits pauses play for 24 hours.</li>
        <li>Accumulators are capped at 6 legs, with one leg per match, and the slip warns that every extra leg adds margin.</li>
        <li>Live betting is pregame only: no in-play betting, no &quot;cash-out&quot;, no bonuses, no streaks, no push notifications.</li>
        <li>Edges above 25% are labelled &quot;caution&quot;: a huge edge usually means the model is missing news.</li>
      </ul>
      <h2 className="text-lg font-semibold">If gambling is a problem</h2>
      <p className="text-muted">
        If betting with real money is affecting your finances, relationships or mood, talk to someone. US: 1-800-GAMBLER
        (National Council on Problem Gambling). UK: GamCare 0808 8020 133 or the NHS National Gambling Clinic. Bosnia and
        Herzegovina and the wider region: contact your local mental-health centre (centar za mentalno zdravlje).
      </p>
    </div>
  );
}
