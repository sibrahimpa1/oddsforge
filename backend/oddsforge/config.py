"""Runtime configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("ODDSFORGE_DATA_DIR", str(ROOT / "data"))))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5-5"))
    odds_api_key: str = field(default_factory=lambda: _env("ODDS_API_KEY"))
    offline: bool = field(default_factory=lambda: _env("ODDSFORGE_OFFLINE", "0") == "1")
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "http://localhost:3000"))

    # Paper-betting guard rails (fake money, but the habits should be healthy ones).
    starting_bankroll: float = 1000.0
    max_stake_fraction: float = 0.05  # one bet can risk at most 5% of the current bankroll
    max_stake_abs: float = 100.0
    daily_loss_limit: float = 250.0
    max_acca_legs: int = 6

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'oddsforge.db'}"


settings = Settings()
