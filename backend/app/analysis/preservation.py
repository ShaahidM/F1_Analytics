"""Preservation indicators trended against tyre age, and rule-based pattern labels (INTERPRETATION tier).

See docs/TYRE_METHODOLOGY.md §5. Trends are per (driver, stint, zone): Theil–Sen slope of the indicator
against tyre age with a 90% CI. A trend counts as a "change" only when its CI excludes zero.
The labels describe what the data is *consistent with*; they never assert intent or tyre state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.degradation import _fit

# key → (label, unit, what an increase means physically)
INDICATORS = {
    "brake_onset_before_apex_m": ("P1 Brake point before apex", "m", "braking earlier"),
    "mean_decel_g": ("P2 Mean deceleration", "g", "gentler braking (less negative)"),
    "entry_speed_kmh": ("P3 Entry speed", "km/h", "faster entry"),
    "min_speed_kmh": ("P3 Minimum speed", "km/h", "faster through the apex"),
    "exit_speed_kmh": ("P3 Exit speed", "km/h", "faster exit"),
    "throttle_pickup_m": ("P4 Throttle pickup after apex", "m", "later throttle"),
    "throttle_ramp_m": ("P5 Pickup → full throttle", "m", "more progressive throttle"),
    "coast_m": ("P6 Coasting before the corner", "m", "more lift-and-coast"),
    "path_excess_m": ("P8 Extra distance driven (experimental)", "m", "a longer line or more tyre slip"),
    "time_in_zone_s": ("Time in zone", "s", "slower through the zone"),
}

CONFOUNDERS = [
    "Fuel burn: a lighter car brakes later and carries more speed, which can mask grip loss and opposes 'braking earlier'",
    "Track evolution (rubbering-in, temperature) changes grip independently of tyre age",
    "Traffic / dirty air and DRS change speeds and lift points",
    "Brake temperature and energy-recovery strategy (strongly in 2026+) can cause lifts unrelated to tyres",
    "Different car performance: compare trends within a driver, not absolute values between teams",
]


# Smallest change across a stint that counts as real: roughly the measurement resolution. Requiring this
# as well as a CI that excludes zero limits false positives from testing many zones × indicators.
MIN_CHANGE = {
    "brake_onset_before_apex_m": 10.0,
    "mean_decel_g": 0.15,
    "entry_speed_kmh": 3.0,
    "min_speed_kmh": 2.0,
    "exit_speed_kmh": 2.0,
    "throttle_pickup_m": 10.0,
    "throttle_ramp_m": 10.0,
    "coast_m": 10.0,
    "path_excess_m": 3.0,
    "time_in_zone_s": 0.05,
}


def _sig(f: dict | None, key: str = "", span: float = 0.0) -> int:
    """+1 / -1 when the CI excludes zero AND the change over the stint span reaches MIN_CHANGE; else 0."""
    if not f:
        return 0
    if key and abs(f["slope"]) * span < MIN_CHANGE.get(key, 0.0):
        return 0
    if f["ci_low"] > 0:
        return 1
    if f["ci_high"] < 0:
        return -1
    return 0


def classify(fits: dict[str, dict | None], span: float) -> tuple[str, list[str]]:
    """Pattern label from indicator trends. Grip loss *forces* lower corner speeds; management is a *choice*
    to lift or apply throttle progressively while corner speed is maintained. Braking earlier alone is
    ambiguous (it also happens when grip is lost), so it only counts alongside maintained corner speed."""
    s = {k: _sig(f, k, span) for k, f in fits.items()}
    n_fit = sum(f is not None for f in fits.values())
    if n_fit < 3:
        return "insufficient_data", []
    speeds_held = s.get("min_speed_kmh", 0) >= 0 and s.get("exit_speed_kmh", 0) >= 0
    management = []
    if s.get("coast_m") == 1:
        management.append("coasting increases with tyre age")
    if s.get("throttle_ramp_m") == 1 and speeds_held:
        management.append("throttle applied more progressively while min/exit speed held")
    if s.get("brake_onset_before_apex_m") == 1 and speeds_held:
        management.append("braking earlier while min/exit speed held")
    grip = []
    if s.get("min_speed_kmh") == -1 and s.get("coast_m", 0) <= 0:
        grip.append("minimum speed falls with tyre age without extra coasting")
    if s.get("exit_speed_kmh") == -1 and s.get("throttle_ramp_m", 0) <= 0:
        grip.append("exit speed falls without a more progressive throttle")
    if management and grip:
        return "mixed", management + grip
    if management:
        return "consistent_with_management", management
    if grip:
        return "consistent_with_grip_loss", grip
    return "no_clear_pattern", []


def corner_rows(metrics_by_lap: dict[int, list[dict]], laps: pd.DataFrame) -> pd.DataFrame:
    rows = []
    info = laps.set_index("lap_number")
    for lap, metrics in metrics_by_lap.items():
        li = info.loc[lap]
        for m in metrics:
            r = {"lap_number": lap, "stint": li["stint"], "compound": li["compound"], "tyre_age": li["tyre_age"], **m}
            if m.get("full_throttle_m") is not None and m.get("throttle_pickup_m") is not None:
                r["throttle_ramp_m"] = m["full_throttle_m"] - m["throttle_pickup_m"]
            rows.append(r)
    return pd.DataFrame(rows)


def stint_zone_trends(rows: pd.DataFrame, zone_ids: list[int]) -> list[dict]:
    out = []
    if rows.empty:
        return out
    for (stint, zone_id), g in rows.groupby(["stint", "zone_id"]):
        if zone_id not in zone_ids:
            continue
        x = g["tyre_age"].astype(float).to_numpy()
        fits = {k: (_fit(x, g[k].astype(float).to_numpy()) if k in g else None) for k in INDICATORS}
        span = float(np.ptp(x)) if len(x) else 0.0
        label, evidence = classify(fits, span)
        out.append({"stint": int(stint), "zone_id": int(zone_id), "compound": g["compound"].iloc[0],
                    "n_laps": int(len(g)), "tyre_age_span": span, "trends": fits,
                    "significant": {k: _sig(f, k, span) for k, f in fits.items()},
                    "pattern": label, "evidence": evidence})
    return out
