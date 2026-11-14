"""Corner zones (defined once per session on the reference lap) and per-lap corner metrics.

Zones are shared by every lap in the session so "time in zone" compares identical stretches of track.
Brake onset uses the raw ~4 Hz car samples: onset lies between the last brake-off and first brake-on
sample, so it is reported as the midpoint ± half that spacing. See docs/TYRE_METHODOLOGY.md §2, §5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import find_peaks

G = 9.80665
ZONE_MIN_PROMINENCE_KMH = 10.0
MIN_ZONE_SEPARATION_M = 60.0
APPROACH_SEARCH_M = 700.0
EXIT_SEARCH_M = 500.0
EXIT_SPEED_OFFSET_M = 150.0
APEX_SEARCH_M = 100.0
CORNER_ASSIGN_M = 250.0
FLAT_WINDOW_M = (150.0, 100.0)
PICKUP_THROTTLE = 20.0
FULL_THROTTLE = 98.0
COAST_THROTTLE = 5.0
COAST_MIN_SPEED = 150.0

# Unit, evidence tier and caveat for every metric — returned to the UI so labels never drift from the code.
METRICS = {
    "time_in_zone_s": ("s", "C", "Elapsed time between the shared zone start and end distances"),
    "approach_max_kmh": ("km/h", "M", "Highest speed before the apex within the zone"),
    "brake_onset_before_apex_m": ("m", "C", "Distance before the reference apex; midpoint between last brake-off and first brake-on sample"),
    "brake_onset_resolution_m": ("± m", "C", "Half the raw sample spacing at the brake onset"),
    "entry_speed_kmh": ("km/h", "C", "Speed at the estimated brake onset"),
    "braking_distance_m": ("m", "C", "Brake onset to brake release (each ± half the local sample spacing)"),
    "mean_decel_g": ("g", "C", "Kinematic mean over the brake application: (v_on² − v_release²) / 2d; distance-based, so robust to timestamp jitter"),
    "peak_decel_g": ("g", "C", "Smoothed acceleration minimum; underestimates true peak braking"),
    "min_speed_kmh": ("km/h", "M", "Lowest speed within ±100 m of the reference apex"),
    "min_speed_offset_m": ("m", "C", "Own minimum-speed point relative to the reference apex (+ = later)"),
    "throttle_pickup_m": ("m", "C", f"First throttle > {PICKUP_THROTTLE:.0f}% after the minimum, relative to the reference apex"),
    "full_throttle_m": ("m", "C", f"First throttle ≥ {FULL_THROTTLE:.0f}% after the minimum, relative to the reference apex"),
    "coast_m": ("m", "C", f"Throttle < {COAST_THROTTLE:.0f}%, brake off, speed > {COAST_MIN_SPEED:.0f} km/h before the apex (lift-and-coast)"),
    "exit_speed_kmh": ("km/h", "M", f"Speed {EXIT_SPEED_OFFSET_M:.0f} m after the reference apex"),
    "min_gear": ("", "M", "Lowest gear in the zone"),
    "min_throttle_pct": ("%", "M", "Lowest throttle in the zone (flat-out corners)"),
    "path_excess_m": ("m", "E", "EXPERIMENTAL: distance driven (∫ wheel speed, calibrated per lap) minus track distance, "
                      "relative to the reference lap. Higher = longer line OR more tyre slip (inseparable). "
                      "Per-lap noise ~5 m: use race averages"),
}


@dataclass
class Zone:
    id: int
    label: str
    corners: list[str]
    kind: str          # "braking" | "flat"
    start_s: float
    apex_s: float
    end_s: float

    def to_dict(self) -> dict:
        return asdict(self)


def _arr(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def build_zones(ref_trace: dict, corners: list[dict]) -> list[Zone]:
    s = _arr(ref_trace["s"])
    v = _arr(ref_trace["speed"])
    grid = float(ref_trace["grid_m"])
    filled = np.where(np.isnan(v), np.nanmax(v), v)
    minima, _ = find_peaks(-filled, prominence=ZONE_MIN_PROMINENCE_KMH, distance=max(1, int(MIN_ZONE_SEPARATION_M / grid)))

    raw: list[tuple[float, float, float]] = []
    for k, m in enumerate(minima):
        lo = minima[k - 1] if k else 0
        hi = minima[k + 1] if k + 1 < len(minima) else len(s) - 1
        a0 = max(lo, m - int(APPROACH_SEARCH_M / grid))
        e1 = min(hi, m + int(EXIT_SEARCH_M / grid))
        approach = a0 + int(np.nanargmax(filled[a0:m + 1]))
        exit_peak = m + int(np.nanargmax(filled[m:e1 + 1]))
        raw.append((s[approach], s[m], s[exit_peak]))

    # Attach each corner marker to the braking zone with the nearest apex; leftovers become flat-out zones.
    assigned: dict[int, list[dict]] = {i: [] for i in range(len(raw))}
    flat: list[dict] = []
    for c in corners:
        if raw:
            i = int(np.argmin([abs(c["s"] - apex) for _, apex, _ in raw]))
            start, apex, end = raw[i]
            if start <= c["s"] <= end and abs(c["s"] - apex) <= CORNER_ASSIGN_M:
                assigned[i].append(c)
                continue
        flat.append(c)

    name = lambda c: f"T{c['number']}{c.get('letter') or ''}"  # noqa: E731
    zones: list[Zone] = []
    for i, (start, apex, end) in enumerate(raw):
        names = [name(c) for c in sorted(assigned[i], key=lambda c: c["s"])]
        label = (names[0] if len(names) == 1 else f"{names[0]}–{names[-1]}") if names else f"Zone @ {apex:.0f} m"
        zones.append(Zone(0, label, names, "braking", round(start, 1), round(apex, 1), round(end, 1)))
    L = float(ref_trace["length_m"])
    for c in flat:
        zones.append(Zone(0, name(c), [name(c)], "flat", round(max(0.0, c["s"] - FLAT_WINDOW_M[0]), 1), round(c["s"], 1),
                          round(min(L, c["s"] + FLAT_WINDOW_M[1]), 1)))
    zones.sort(key=lambda z: z.apex_s)
    for i, z in enumerate(zones, start=1):
        z.id = i
    return zones


def _first_crossing(s: np.ndarray, y: np.ndarray, level: float, after: float) -> float | None:
    """Distance where y first rises to `level` after `after`, linearly interpolated between raw samples."""
    idx = np.flatnonzero((s > after) & (y >= level))
    if not idx.size:
        return None
    j = idx[0]
    if j == 0 or y[j - 1] >= level:
        return float(s[j])
    f = (level - y[j - 1]) / (y[j] - y[j - 1])
    return float(s[j - 1] + f * (s[j] - s[j - 1]))


def zone_metrics(tr: dict, z: Zone) -> dict:
    s = _arr(tr["s"])
    v = _arr(tr["speed"])
    t = _arr(tr["t"])
    thr = _arr(tr["throttle"])
    brk = _arr(tr["brake"])
    gear = _arr(tr["gear"])
    acc = _arr(tr["accel_g"])
    in_zone = (s >= z.start_s) & (s <= z.end_s)
    at = lambda arr, x: float(np.interp(x, s, arr))  # noqa: E731
    out: dict = {"zone_id": z.id, "time_in_zone_s": round(at(t, z.end_s) - at(t, z.start_s), 3)}
    out["min_gear"] = float(np.nanmin(gear[in_zone])) if in_zone.any() else None
    scale = tr.get("quality", {}).get("speed_scale")
    if "driven_m" in tr and scale:
        d = _arr(tr["driven_m"])
        out["path_excess_m"] = round((at(d, z.end_s) - at(d, z.start_s)) / scale - (z.end_s - z.start_s), 2)

    if z.kind == "flat":
        out["min_speed_kmh"] = round(float(np.nanmin(v[in_zone])), 1)
        out["min_throttle_pct"] = float(np.nanmin(thr[in_zone]))
        return out

    near = (s >= z.apex_s - APEX_SEARCH_M) & (s <= z.apex_s + APEX_SEARCH_M)
    i_min = np.flatnonzero(near)[int(np.nanargmin(v[near]))]
    s_min, v_min = float(s[i_min]), float(v[i_min])
    out["min_speed_kmh"] = round(v_min, 1)
    out["min_speed_offset_m"] = round(s_min - z.apex_s, 1)
    out["approach_max_kmh"] = round(float(np.nanmax(v[(s >= z.start_s) & (s <= s_min)])), 1)
    out["exit_speed_kmh"] = round(at(v, min(z.apex_s + EXIT_SPEED_OFFSET_M, z.end_s)), 1)

    pre = (s >= z.start_s) & (s <= s_min)
    coast = pre & (thr < COAST_THROTTLE) & (brk == 0) & (v > COAST_MIN_SPEED)
    out["coast_m"] = round(float(coast.sum() * tr["grid_m"]), 0)
    out["peak_decel_g"] = round(float(np.nanmin(acc[pre])), 2) if pre.any() else None

    raw = tr.get("raw", {}).get("car")
    if raw:
        rs = _arr(raw["s"])
        rb = _arr(raw["brake"])
        rt = _arr(raw["throttle"])
        win = np.flatnonzero((rs >= z.start_s - 100) & (rs <= s_min))
        onset = next((j for j in win if j > 0 and rb[j] > 0 and rb[j - 1] == 0), None)
        if onset is not None:
            s_on = (rs[onset - 1] + rs[onset]) / 2
            v_on = at(v, s_on)
            out["brake_onset_before_apex_m"] = round(z.apex_s - s_on, 1)
            out["brake_onset_resolution_m"] = round((rs[onset] - rs[onset - 1]) / 2, 1)
            out["entry_speed_kmh"] = round(v_on, 1)
            release = next((j for j in range(onset + 1, len(rb)) if rb[j] == 0), None)
            if release is not None:
                s_rel = (rs[release - 1] + rs[release]) / 2
                v_rel = at(v, s_rel)
                out["braking_distance_m"] = round(s_rel - s_on, 1)
                if s_rel > s_on:
                    out["mean_decel_g"] = round(-((v_on / 3.6) ** 2 - (v_rel / 3.6) ** 2) / (2 * (s_rel - s_on)) / G, 2)
        pickup = _first_crossing(rs, rt, PICKUP_THROTTLE, s_min)
        full = _first_crossing(rs, rt, FULL_THROTTLE, s_min)
        out["throttle_pickup_m"] = None if pickup is None else round(pickup - z.apex_s, 1)
        out["full_throttle_m"] = None if full is None or full > z.end_s + 200 else round(full - z.apex_s, 1)
    return out
