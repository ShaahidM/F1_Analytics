"""Model A — per-stint robust pace trend (docs/TYRE_METHODOLOGY.md §4).

The slope combines fuel burn, track evolution and tyre degradation (collinear within a stint), so it is
reported as a "raw pace trend", not degradation. An optional fuel-correction ASSUMPTION (s per lap of
fuel burned) lets the user see how sensitive the trend is to that assumption.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

MIN_LAPS_FOR_FIT = 4
CI_LEVEL = 0.90


def _fit(x: np.ndarray, y: np.ndarray) -> dict | None:
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < MIN_LAPS_FOR_FIT or np.ptp(x) == 0:
        return None
    slope, intercept, lo, hi = theilslopes(y, x, alpha=CI_LEVEL)
    resid = y - (intercept + slope * x)
    return {
        "slope": round(float(slope), 4),
        "ci_low": round(float(lo), 4),
        "ci_high": round(float(hi), 4),
        "intercept": round(float(intercept), 3),
        "residual_sd": round(float(np.std(resid, ddof=1)), 3),
        "n": int(len(x)),
    }


def stint_trends(laps: pd.DataFrame, drivers: list[int], include_flagged: bool, fuel_s_per_lap: float) -> list[dict]:
    out = []
    sub = laps[laps["driver_number"].isin(drivers) & laps["stint"].notna()]
    for (drv, stint), g in sub.groupby(["driver_number", "stint"], sort=True):
        g = g.sort_values("lap_number")
        usable = g["clean"] & (include_flagged | (g["flags"].map(len) == 0))
        u = g[usable]
        x = u["tyre_age"].astype(float).to_numpy()
        y = u["lap_time_s"].to_numpy(float)
        # Fuel-burn ASSUMPTION: later laps are lighter, so add back the time the lost fuel would have cost.
        y_corr = y + fuel_s_per_lap * (u["lap_number"].to_numpy(float) - float(g["lap_number"].min()))
        sectors = {}
        for col in ("s1_s", "s2_s", "s3_s"):
            if u[col].notna().sum() >= MIN_LAPS_FOR_FIT:
                sectors[col] = _fit(x, u[col].to_numpy(float))
        out.append({
            "driver_number": int(drv),
            "stint": int(stint),
            "compound": g["compound"].iloc[0],
            "lap_start": int(g["lap_number"].min()),
            "lap_end": int(g["lap_number"].max()),
            "tyre_age_start": None if pd.isna(g["tyre_age"].iloc[0]) else int(g["tyre_age"].iloc[0]),
            "tyre_age_assumed": bool(g.get("tyre_age_assumed", pd.Series([False])).iloc[0]),
            "n_laps": int(len(g)),
            "n_used": int(usable.sum()),
            "median_lap_s": round(float(np.median(y)), 3) if len(y) else None,
            "raw_trend": _fit(x, y),
            "fuel_corrected_trend": _fit(x, y_corr) if fuel_s_per_lap else None,
            "sector_trends": sectors,
        })
    return out
