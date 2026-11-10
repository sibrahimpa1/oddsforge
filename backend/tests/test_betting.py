from datetime import timedelta

import pytest

from oddsforge import db
from oddsforge.betting import service as bets
from oddsforge.db import Match, OddsQuote, Prediction, utcnow


@pytest.fixture()
def s(tmp_path):
    db.reset_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        yield s


def _match(s, status="final", hg=2, ag=1, days=-30, league="MLS"):
    m = Match(
        league=league,
        season="2025",
        kickoff=utcnow() + timedelta(days=days),
        home_id="sea",
        away_id="por",
        home_goals=hg if status == "final" else None,
        away_goals=ag if status == "final" else None,
        status=status,
    )
    m.odds.append(
        OddsQuote(market="1x2", book="avg", timing="close", price_a=2.10, price_b=3.40, price_c=3.60)
    )
    m.odds.append(
        OddsQuote(
            market="1x2",
            book="bet365",
            timing="snapshot",
            captured_at=utcnow(),
            price_a=2.20,
            price_b=3.30,
            price_c=3.50,
        )
    )
    s.add(m)
    s.flush()
    s.add(
        Prediction(
            match_id=m.id,
            model="mls_v1",
            as_of=m.kickoff - timedelta(days=2),
            lam_h=1.6,
            lam_a=1.1,
            rho=-0.05,
            base_lam_h=1.6,
            base_lam_a=1.1,
            p_home=0.48,
            p_draw=0.26,
            p_away=0.26,
            features={},
        )
    )
    s.commit()
    return m


def test_replay_single_bet_settles_on_kickoff(s):
    u = bets.create_user(s, "tester")
    m = _match(s)
    b = bets.place_bet(s, u, [{"match_id": m.id, "market": "1x2", "selection": "home"}], 40, "replay")
    assert b.odds == 2.10  # server price, never the client's
    assert u.bankroll == 960
    assert b.legs[0].model_prob == pytest.approx(0.48, abs=0.05)
    res = bets.replay_kickoff(s, u, "MLS", bets.local_day(m))
    assert b.id in res["settled_bets"]
    assert b.status == "won" and b.payout == pytest.approx(84.0)
    assert u.bankroll == pytest.approx(1044.0)
    with pytest.raises(bets.BetError, match="already revealed"):
        bets.place_bet(s, u, [{"match_id": m.id, "market": "1x2", "selection": "home"}], 10, "replay")


def test_stake_and_slip_limits(s):
    u = bets.create_user(s, "limits")
    m1, m2 = _match(s), _match(s, hg=0, ag=0, days=-29)
    with pytest.raises(bets.BetError, match="stake limit"):
        bets.place_bet(s, u, [{"match_id": m1.id, "market": "1x2", "selection": "home"}], 51, "replay")
    with pytest.raises(bets.BetError, match="one leg per match"):
        bets.place_bet(
            s,
            u,
            [
                {"match_id": m1.id, "market": "1x2", "selection": "home"},
                {"match_id": m1.id, "market": "1x2", "selection": "draw"},
            ],
            10,
            "replay",
        )
    acca = bets.place_bet(
        s,
        u,
        [
            {"match_id": m1.id, "market": "1x2", "selection": "home"},
            {"match_id": m2.id, "market": "1x2", "selection": "draw"},
        ],
        10,
        "replay",
    )
    assert acca.kind == "acca" and acca.odds == pytest.approx(2.10 * 3.40)
    bets.replay_kickoff(s, u, "MLS", bets.local_day(m1))
    assert acca.status == "open"  # second leg's day not revealed yet
    bets.replay_kickoff(s, u, "MLS", bets.local_day(m2))
    assert acca.status == "won" and acca.payout == pytest.approx(10 * 2.10 * 3.40, abs=0.01)


def test_live_bet_needs_upcoming_match_and_settles_when_final(s):
    u = bets.create_user(s, "live")
    old = _match(s)
    with pytest.raises(bets.BetError, match="pregame only"):
        bets.place_bet(s, u, [{"match_id": old.id, "market": "1x2", "selection": "home"}], 10, "live")
    m = _match(s, status="scheduled", days=2)
    b = bets.place_bet(s, u, [{"match_id": m.id, "market": "1x2", "selection": "away"}], 20, "live")
    assert b.odds == 3.50
    assert bets.settle_live(s) == 0
    m.status, m.home_goals, m.away_goals = "final", 0, 1
    s.commit()
    assert bets.settle_live(s) == 1
    assert b.status == "won" and u.bankroll == pytest.approx(1000 - 20 + 70)


def test_daily_loss_limit(s):
    u = bets.create_user(s, "tilt")
    lost = 0.0
    with pytest.raises(bets.BetError, match="daily loss limit"):
        for i in range(20):  # keep losing max stakes until the guard rail stops play
            m = _match(s, hg=0, ag=3, days=-60 + i)
            stake = bets.stake_limit(u)
            bets.place_bet(s, u, [{"match_id": m.id, "market": "1x2", "selection": "home"}], stake, "replay")
            bets.replay_kickoff(s, u, "MLS", bets.local_day(m))
            lost += stake
    assert lost <= 250
    assert bets.leaderboard(s, "replay")[0]["profit"] == pytest.approx(-lost)
