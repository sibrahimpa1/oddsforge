"""Database schema (SQLAlchemy 2.0). SQLite by default; set DATABASE_URL for Postgres.

Every odds row carries `timing` and `captured_at`, so a backtest can ask "what price was
available at decision time?" instead of silently using closing prices.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league: Mapped[str] = mapped_column(String(16), index=True)
    season: Mapped[str] = mapped_column(String(16), index=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, naive
    home_id: Mapped[str] = mapped_column(String(48), index=True)
    away_id: Mapped[str] = mapped_column(String(48), index=True)
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="final")  # scheduled | live | final
    knockout: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str] = mapped_column(String(64), default="")
    venue: Mapped[str] = mapped_column(String(128), default="")
    espn_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    asa_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    odds: Mapped[list[OddsQuote]] = relationship(back_populates="match", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("league", "kickoff", "home_id", "away_id"),)

    @property
    def is_final(self) -> bool:
        return self.status == "final" and self.home_goals is not None


class OddsQuote(Base):
    __tablename__ = "odds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market: Mapped[str] = mapped_column(String(8))  # 1x2 | ah | ou
    line: Mapped[float | None] = mapped_column(Float, nullable=True)  # AH line for home / total line
    book: Mapped[str] = mapped_column(String(24))  # pinnacle | best | avg | bet365 | betfair_ex | ...
    timing: Mapped[str] = mapped_column(String(12))  # open | close | snapshot
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    price_a: Mapped[float | None] = mapped_column(Float)  # home / over
    price_b: Mapped[float | None] = mapped_column(Float, nullable=True)  # draw (1x2) / away / under
    price_c: Mapped[float | None] = mapped_column(Float, nullable=True)  # away (1x2)
    match: Mapped[Match] = relationship(back_populates="odds")


class PlayerSeason(Base):
    """Per-player season aggregates from American Soccer Analysis, used for lineup adjustments."""

    __tablename__ = "player_seasons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(96))
    team_id: Mapped[str] = mapped_column(String(48), index=True)
    season: Mapped[str] = mapped_column(String(8), index=True)
    position: Mapped[str] = mapped_column(String(8))
    minutes: Mapped[int] = mapped_column(Integer)
    xg: Mapped[float] = mapped_column(Float, default=0.0)
    xa: Mapped[float] = mapped_column(Float, default=0.0)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    gplus: Mapped[float] = mapped_column(Float, default=0.0)  # goals added above average, season total
    gplus_def: Mapped[float] = mapped_column(Float, default=0.0)  # interrupting + fouling + receiving share
    gk_shots_faced: Mapped[int] = mapped_column(Integer, default=0)
    gk_goals_minus_xg: Mapped[float] = mapped_column(Float, default=0.0)


class Prediction(Base):
    """A point-in-time model output. `as_of` is the latest information time used; the backtest
    asserts as_of < kickoff for every row."""

    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    lam_h: Mapped[float] = mapped_column(Float)
    lam_a: Mapped[float] = mapped_column(Float)
    rho: Mapped[float] = mapped_column(Float)
    base_lam_h: Mapped[float] = mapped_column(Float)  # team-strength only, before context adjustments
    base_lam_a: Mapped[float] = mapped_column(Float)
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("match_id", "model"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    bankroll: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    bets: Mapped[list[Bet]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # single | acca
    mode: Mapped[str] = mapped_column(String(8))  # live | replay
    stake: Mapped[float] = mapped_column(Float)
    odds: Mapped[float] = mapped_column(Float)  # combined decimal odds at placement
    status: Mapped[str] = mapped_column(
        String(12), default="open"
    )  # open | won | lost | void | half_won | half_lost | settled
    payout: Mapped[float] = mapped_column(Float, default=0.0)
    model_ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship(back_populates="bets")
    legs: Mapped[list[BetLeg]] = relationship(back_populates="bet", cascade="all, delete-orphan")


class BetLeg(Base):
    __tablename__ = "bet_legs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market: Mapped[str] = mapped_column(String(8))  # 1x2 | ah | ou | btts
    selection: Mapped[str] = mapped_column(String(8))  # home|draw|away / over|under / yes|no
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str | None] = mapped_column(String(12), nullable=True)  # won|lost|void|half_won|half_lost
    factor: Mapped[float | None] = mapped_column(Float, nullable=True)  # payout multiplier for this leg
    bet: Mapped[Bet] = relationship(back_populates="legs")
    match: Mapped[Match] = relationship()


class KV(Base):
    """Small key/value store for cached artefacts (ratings snapshot, report metadata)."""

    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(settings.db_url, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
    return _engine


def session() -> Session:
    engine()
    assert _Session is not None
    return _Session()


def reset_engine(url: str | None = None) -> None:
    """Used by tests to point at a throwaway database."""
    global _engine, _Session
    _engine = create_engine(url or settings.db_url, future=True)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
