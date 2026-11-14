"""Per-lap trace on a common distance grid (see docs/ARCHITECTURE.md "Lap alignment")."""

from __future__ import annotations

import numpy as np
import pandas as pd

from scipy.ndimage import uniform_filter1d

from app.config import POSITION_UNITS_PER_M
from app.processing.reference import ReferenceLine, project

PAD = pd.Timedelta(seconds=2)
GAP_WARN_S = 1.5
G = 9.80665
ACCEL_WINDOW = 7
TIME_CORRECTION_WINDOW_M = 400.0
DRIVEN_DT = 0.02  # s, integration step for distance driven


def _secs(dates: pd.Series, origin: pd.Timestamp) -> np.ndarray:
    return (dates - origin).dt.total_seconds().to_numpy(float)


def _step(grid: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Previous-value interpolation for discrete channels (gear, brake, DRS)."""
    i = np.clip(np.searchsorted(s, grid, side="right") - 1, 0, len(v) - 1)
    return v[i]


def _accel_time_domain(t: np.ndarray, speed_kmh: np.ndarray, window: int = ACCEL_WINDOW) -> np.ndarray:
    """Longitudinal acceleration (g) from a local quadratic fit over `window` raw samples.

    Raw car_data timestamps jitter (gaps up to ~1 s, impossible 30 km/h jumps in 0.3 s), so a
    point derivative is meaningless; this smooths over ~1.7 s and therefore UNDERESTIMATES peaks.
    """
    v = speed_kmh / 3.6
    half = window // 2
    out = np.full(len(t), np.nan)
    for i in range(len(t)):
        lo, hi = max(0, i - half), min(len(t), i + half + 1)
        if hi - lo < 3:
            continue
        tt = t[lo:hi] - t[i]
        out[i] = np.polyfit(tt, v[lo:hi], 2)[1] / G  # derivative of the fit at t[i]
    return out


def _r(a: np.ndarray, nd: int = 1) -> list:
    return [None if not np.isfinite(v) else round(float(v), nd) for v in a]


def lap_trace(car: pd.DataFrame, pos: pd.DataFrame, ref: ReferenceLine, lap_start: pd.Timestamp,
              lap_end: pd.Timestamp, grid_m: float, include_raw: bool = True) -> dict:
    p = pos[(pos["date"] >= lap_start - PAD) & (pos["date"] <= lap_end + PAD)].reset_index(drop=True)
    c = car[(car["date"] >= lap_start - PAD) & (car["date"] <= lap_end + PAD)].reset_index(drop=True)
    if len(p) < 10 or len(c) < 10:
        raise ValueError("insufficient telemetry for this lap")

    tp = _secs(p["date"], lap_start)
    tc = _secs(c["date"], lap_start)
    px, py = p["x"].to_numpy(float), p["y"].to_numpy(float)

    # Sequential guess = own path length since the timing line; disambiguates nearby track sections.
    path = np.r_[0.0, np.cumsum(np.hypot(np.diff(px), np.diff(py)))] / POSITION_UNITS_PER_M
    guess = path - np.interp(0.0, tp, path)
    s_raw, lat = project(ref, px, py, s_guess=np.mod(guess, ref.length_m))
    L = ref.length_m
    s_cont = s_raw + L * np.round((guess - s_raw) / L)
    s_cont = np.maximum.accumulate(s_cont)

    grid = np.arange(0.0, L, grid_m)
    s_car = np.interp(tc, tp, s_cont)
    # np.interp needs strictly increasing x; nudge ties (stationary samples).
    s_car_u = s_car + np.arange(len(s_car)) * 1e-6
    s_pos_u = s_cont + np.arange(len(s_cont)) * 1e-6

    speed = np.interp(grid, s_car_u, c["speed"].to_numpy(float))
    accel_g = np.interp(grid, s_car_u, _accel_time_domain(tc, c["speed"].to_numpy(float)))

    # Elapsed time t(s): position timestamps are accurate on average but jitter ±~0.05 s locally;
    # integrating speed is smooth locally but drifts. Combine: integral + low-passed correction.
    t_pos = np.interp(grid, s_pos_u, tp)
    v = np.maximum(speed / 3.6, 1.0)
    t_int = t_pos[0] + np.r_[0.0, np.cumsum(grid_m / ((v[1:] + v[:-1]) / 2))]
    corr_n = max(1, int(TIME_CORRECTION_WINDOW_M / grid_m))
    t_grid = t_int + uniform_filter1d(t_pos - t_int, size=corr_n, mode="nearest")

    # Distance actually driven = ∫ wheel speed dt, mapped onto track distance. Positions are snapped to one line,
    # so (driven − track) through a corner reflects a longer/shorter line OR tyre slip (indistinguishable).
    tf = np.arange(tc[0], tc[-1], DRIVEN_DT)
    vf = np.interp(tf, tc, c["speed"].to_numpy(float)) / 3.6
    driven_t = np.r_[0.0, np.cumsum((vf[1:] + vf[:-1]) / 2 * DRIVEN_DT)]
    s_f = np.interp(tf, tp, s_cont) + np.arange(len(tf)) * 1e-9
    driven = np.interp(grid, s_f, driven_t) - np.interp(0.0, s_f, driven_t)
    speed_scale = (np.interp(L, s_f, driven_t) - np.interp(0.0, s_f, driven_t)) / L

    spacing = np.diff(s_car)
    sample_spacing = np.interp(grid, s_car_u[1:], spacing) if len(spacing) else np.full_like(grid, np.nan)
    gaps = np.diff(tp[(tp >= 0) & (tp <= (lap_end - lap_start).total_seconds())])

    out = {
        "grid_m": grid_m,
        "length_m": round(L, 1),
        "s": _r(grid, 1),
        "t": _r(t_grid, 3),
        "speed": _r(speed, 1),
        "throttle": _r(np.interp(grid, s_car_u, c["throttle"].to_numpy(float)), 0),
        "brake": _r(_step(grid, s_car_u, c["brake"].to_numpy(float)), 0),
        "gear": _r(_step(grid, s_car_u, c["gear"].to_numpy(float)), 0),
        "rpm": _r(np.interp(grid, s_car_u, c["rpm"].to_numpy(float)), 0),
        "drs": _r(_step(grid, s_car_u, c["drs"].to_numpy(float)), 0),
        "x": _r(np.interp(grid, s_pos_u, px), 1),
        "y": _r(np.interp(grid, s_pos_u, py), 1),
        "lateral_m": _r(np.interp(grid, s_pos_u, lat), 2),
        "accel_g": _r(accel_g, 2),
        "driven_m": _r(driven, 2),
        "sample_spacing_m": _r(sample_spacing, 1),
        "quality": {
            "car_samples": int(((tc >= 0) & (tc <= (lap_end - lap_start).total_seconds())).sum()),
            "pos_samples": int(len(gaps) + 1),
            "max_pos_gap_s": round(float(gaps.max()), 2) if len(gaps) else None,
            "has_gaps": bool(len(gaps) and gaps.max() > GAP_WARN_S),
            "trace_time_s": round(float(np.interp(L, s_pos_u, tp)), 3),
            "speed_scale": round(float(speed_scale), 4),
        },
    }
    if include_raw:
        in_car = (s_car >= 0) & (s_car < L)
        in_pos = (s_cont >= 0) & (s_cont < L)
        out["raw"] = {
            "car": {
                "s": _r(s_car[in_car], 1),
                "speed": _r(c["speed"].to_numpy(float)[in_car], 0),
                "throttle": _r(c["throttle"].to_numpy(float)[in_car], 0),
                "brake": _r(c["brake"].to_numpy(float)[in_car], 0),
            },
            "pos": {"s": _r(s_cont[in_pos], 1), "x": _r(px[in_pos], 0), "y": _r(py[in_pos], 0)},
        }
    return out
