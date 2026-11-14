"""Central configuration. Only infrastructure settings live here — no F1 data is hardcoded."""

from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_CACHE_DIR = DATA_DIR / "raw"
PARQUET_DIR = DATA_DIR / "parquet"

OPENF1_BASE = "https://api.openf1.org/v1"
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
MULTIVIEWER_BASE = "https://api.multiviewer.app/api/v1"

# Scope agreed with the user (2019 → present). Not a data-availability claim.
FIRST_SUPPORTED_SEASON = 2019

# Published / observed rate limits, as (max_requests, window_seconds) pairs per host.
RATE_LIMITS: dict[str, list[tuple[int, float]]] = {
    "api.openf1.org": [(3, 1.0), (30, 60.0)],
    "api.jolpi.ca": [(4, 1.0), (500, 3600.0)],
    "api.multiviewer.app": [(2, 1.0)],
}

# Catalog data for a season still in progress can change; finished seasons are immutable.
CURRENT_SEASON_TTL = timedelta(hours=6)

# Distance grid spacing (m) for aligned lap traces. Raw samples are ~7–20 m apart.
TRACE_GRID_M = 5.0
# OpenF1 / F1 position units are 1/10 metre.
POSITION_UNITS_PER_M = 10.0

HTTP_TIMEOUT_S = 60.0
