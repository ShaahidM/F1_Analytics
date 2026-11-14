"""Lap-level driving-style metrics (docs/TYRE_METHODOLOGY.md §5, P6/P7 and the style profile).

Every metric is CALCULATED from distance-aligned telemetry; nothing here measures tyre state.
"""

from __future__ import annotations

import numpy as np

from app.analysis.corners import COAST_MIN_SPEED, COAST_THROTTLE, EXIT_SPEED_OFFSET_M, FULL_THROTTLE, Zone, _arr

STYLE_METRICS = {
    "full_throttle_pct": ("% of lap", "C", f"Share of lap distance with throttle ≥ {FULL_THROTTLE:.0f}%"),
    "partial_throttle_pct": ("% of lap", "C", f"Share of lap distance with throttle between {COAST_THROTTLE:.0f}% and {FULL_THROTTLE:.0f}%"),
    "coast_m": ("m / lap", "C", f"Distance with throttle < {COAST_THROTTLE:.0f}%, brake off, above {COAST_MIN_SPEED:.0f} km/h (lift-and-coast)"),
    "braking_time_s": ("s / lap", "C", "Time with the brake on (binary signal, ~4 Hz)"),
    "braking_pct": ("% of lap", "C", "Share of lap distance with the brake on"),
    "gear_changes": ("per lap", "C", "Gear changes seen in ~4 Hz samples; very quick double shifts can be missed"),
    "mean_decel_g": ("g", "C", "Mean over braking zones of the kinematic deceleration during the brake application"),
    "mean_entry_kmh": ("km/h", "C", "Mean speed at brake onset over braking zones"),
    "mean_min_kmh": ("km/h", "C", "Mean minimum speed over braking zones"),
    "mean_exit_kmh": ("km/h", "C", f"Mean speed {EXIT_SPEED_OFFSET_M:.0f} m after the apex over braking zones"),
    "throttle_ramp_m": ("m", "C", "Mean distance from throttle pickup (> 20%) to full throttle; longer = more progressive"),
    "exit_accel_g": ("g", "C", f"Mean smoothed longitudinal acceleration in the {EXIT_SPEED_OFFSET_M:.0f} m after each apex"),
}


def _mean(values: list) -> float | None:
    v = [x for x in values if x is not None and np.isfinite(x)]
    return round(float(np.mean(v)), 3) if v else None


def lap_style(tr: dict, corner_rows: list[dict], zones: list[Zone]) -> dict:
    s = _arr(tr["s"])
    t = _arr(tr["t"])
    v = _arr(tr["speed"])
    thr = _arr(tr["throttle"])
    brk = _arr(tr["brake"])
    gear = _arr(tr["gear"])
    acc = _arr(tr["accel_g"])
    n = np.isfinite(thr).sum() or 1
    braking = brk > 0
    dt = np.r_[np.diff(t), 0.0]
    g = gear[np.isfinite(gear)]

    braking_zones = {z.id: z for z in zones if z.kind == "braking"}
    rows = [r for r in corner_rows if r["zone_id"] in braking_zones]
    ramps = [r["full_throttle_m"] - r["throttle_pickup_m"] for r in rows
             if r.get("full_throttle_m") is not None and r.get("throttle_pickup_m") is not None]
    exits = []
    for z in braking_zones.values():
        m = (s >= z.apex_s) & (s <= z.apex_s + EXIT_SPEED_OFFSET_M)
        if m.any():
            exits.append(float(np.nanmean(acc[m])))

    return {
        "full_throttle_pct": round(100 * float((thr >= FULL_THROTTLE).sum()) / n, 2),
        "partial_throttle_pct": round(100 * float(((thr > COAST_THROTTLE) & (thr < FULL_THROTTLE)).sum()) / n, 2),
        "coast_m": round(float(((thr < COAST_THROTTLE) & ~braking & (v > COAST_MIN_SPEED)).sum() * tr["grid_m"]), 0),
        "braking_time_s": round(float(np.nansum(dt[braking])), 2),
        "braking_pct": round(100 * float(braking.sum()) / n, 2),
        "gear_changes": int((np.diff(g) != 0).sum()) if g.size else None,
        "mean_decel_g": _mean([r.get("mean_decel_g") for r in rows]),
        "mean_entry_kmh": _mean([r.get("entry_speed_kmh") for r in rows]),
        "mean_min_kmh": _mean([r.get("min_speed_kmh") for r in rows]),
        "mean_exit_kmh": _mean([r.get("exit_speed_kmh") for r in rows]),
        "throttle_ramp_m": _mean(ramps),
        "exit_accel_g": _mean(exits),
    }
