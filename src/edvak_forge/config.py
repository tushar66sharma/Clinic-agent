"""Application settings, read from environment variables (and `.env` for local runs).

Only non-secret settings live here. Provider API keys are read by the LLM layer at call time
so they never end up in logs or in objects that get serialised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Project folder (holds data/, reports/, runs/). Override with EDVAK_HOME when the package is
# installed somewhere else, e.g. inside a container.
REPO_ROOT = Path(os.getenv("EDVAK_HOME") or Path(__file__).resolve().parents[2])
DEFAULT_DATA_DIR = REPO_ROOT / "data"

# The brief fixes "today" as 9 November 2026. It is configurable so new scenarios can be tested.
DEFAULT_TODAY = "2026-11-09"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    today: date


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env", override=False)
    data_dir = Path(os.getenv("CLINIC_DATA_DIR", str(DEFAULT_DATA_DIR)))
    today = date.fromisoformat(os.getenv("CLINIC_TODAY", DEFAULT_TODAY))
    return Settings(data_dir=data_dir, today=today)
