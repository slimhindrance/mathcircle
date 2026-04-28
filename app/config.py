"""Runtime configuration with sensible local-first defaults."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
DATA_DIR = ROOT_DIR / "data"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
SEED_FILE = DATA_DIR / "seed_problems.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "MATHCIRCLE_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'mathcircle.db').as_posix()}",
)

# Reseed on every startup if the DB is empty. Set to "1" to force re-seed.
FORCE_RESEED = os.getenv("MATHCIRCLE_FORCE_RESEED", "0") == "1"

# Daily session shape — counts per kind, configurable.
SESSION_SHAPE = {
    "warm_up": 3,
    "rich_puzzle": 1,
    "visual": 1,
    "story": 1,
    "explain": 1,
    "parent_extension": 1,
}

# Strand keys (canonical order).
STRAND_KEYS = [
    "number_sense",
    "add_sub_structures",
    "missing_number_stories",
    "equality_balance",
    "patterns",
    "logic_classification",
    "geometry_spatial",
    "measurement",
    "combinatorics_counting",
    "math_games",
]
