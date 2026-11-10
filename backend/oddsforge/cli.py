"""Command line: `oddsforge fetch | load | backtest | refresh | serve | all`."""

from __future__ import annotations

import argparse
import logging


def main() -> None:
    p = argparse.ArgumentParser(prog="oddsforge")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download fresh raw snapshots from all public sources")
    sub.add_parser("load", help="load raw snapshots into the database")
    sub.add_parser("backtest", help="tune, walk forward, evaluate, write data/reports/backtest.json")
    sub.add_parser("refresh", help="fixtures/results/odds only (ESPN + The Odds API), then settle bets")
    sub.add_parser("all", help="load + backtest (offline-safe: uses the bundled raw data)")
    sv = sub.add_parser("serve", help="run the API")
    sv.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if a.cmd == "fetch":
        from .etl.sources import fetch_all

        fetch_all()
    elif a.cmd == "load":
        from .etl.load import load_all

        load_all()
    elif a.cmd == "backtest":
        from .backtest.report import run_all

        run_all()
    elif a.cmd == "refresh":
        from .betting.service import settle_live
        from .db import session
        from .etl.load import load_espn, load_odds_api
        from .etl.sources import _client, fetch_espn, fetch_odds_api

        with _client() as c:
            fetch_espn(c)
            fetch_odds_api(c)
        with session() as s:
            load_espn(s)
            load_odds_api(s)
            s.commit()
            print("settled", settle_live(s))
    elif a.cmd == "all":
        from .backtest.report import run_all
        from .etl.load import load_all

        load_all()
        run_all()
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("oddsforge.api:app", host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
