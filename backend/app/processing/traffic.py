"""On-track traffic from every car's position (replaces the classification-interval heuristic when available).

Each car's snapped x/y is projected onto the reference line and unwrapped into cumulative race distance D(t)
(lap k starts at (k−1)·L). Every second, for each car we find the nearest car physically ahead on track
(smallest positive (D_other − D_self) mod L) and convert that distance to a time gap with the car's own speed.
Lap relation n = (D_other − D_self − gap) / L classifies the car ahead:
  n = 0  → racing car on the same lap (dirty air, battle)
  n ≤ −1 → lapped backmarker (blue-flag traffic)
  n ≥ 1  → a car laps ahead in the race (still dirty air)
A car physically behind within BEING_LAPPED_S that is ≥ 1 lap ahead in the race means this car is being lapped.
Cars in the pit lane (lateral offset > PIT_LATERAL_M) are ignored. Qualifying has no lap relation, so any car
ahead counts as traffic there.

Downloading every car's positions costs one request per driver (~20, ≈ 30–60 s cold), so it runs in a
background thread; until it finishes the lap table uses the interval heuristic and says so.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from app.processing.reference import ReferenceLine, project
from app.sources.base import DataUnavailable, SessionRef, SessionSource

log = logging.getLogger(__name__)

GAP_S = 1.5
BEING_LAPPED_S = 1.0
PIT_LATERAL_M = 8.0
GRID_DT_S = 1.0
MAX_SAMPLE_GAP_S = 5.0
MIN_SPEED_MS = 10.0
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")

_state: dict[str, dict] = {}
_lock = threading.Lock()


def status(session_id: str) -> dict:
    with _lock:
        st = _state.get(session_id)
        return dict(st) if st else {"state": "not_started", "done": 0, "total": 0}


def preload(session_id: str, df: pd.DataFrame) -> None:
    with _lock:
        _state[session_id] = {"state": "ready", "done": 0, "total": 0, "result": df}


def result(session_id: str) -> pd.DataFrame | None:
    with _lock:
        st = _state.get(session_id)
        return st.get("result") if st and st["state"] == "ready" else None


def _secs(dates: pd.Series) -> np.ndarray:
    return (dates - EPOCH).dt.total_seconds().to_numpy()


def _cumulative_distance(pos: pd.DataFrame, ref: ReferenceLine, laps: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    L = ref.length_m
    t = _secs(pos["date"])
    s, lat = project(ref, pos["x"].to_numpy(float), pos["y"].to_numpy(float))
    ds = np.diff(s)
    wraps = np.r_[0, np.cumsum((ds < -L / 2).astype(int) - (ds > L / 2).astype(int))]
    cum = s + L * wraps
    # Anchor lap counting on the driver's own lap starts: at the start of lap k, D ≈ (k−1)·L.
    starts = laps.dropna(subset=["lap_start"])
    if len(starts):
        at = np.interp(_secs(starts["lap_start"]), t, cum)
        offset = np.median((starts["lap_number"].to_numpy(float) - 1) * L - at)
        cum = cum + L * np.round(offset / L)
    return t, cum, np.abs(lat)


def compute(src: SessionSource, s: SessionRef, ref: ReferenceLine, laps: pd.DataFrame, progress=None) -> pd.DataFrame:
    drivers = sorted(int(d) for d in laps["driver_number"].unique())
    t0 = laps["lap_start"].min()
    t1 = laps["lap_end"].max()
    if pd.isna(t0) or pd.isna(t1):
        raise DataUnavailable("lap timing windows")
    grid = np.arange(_secs(pd.Series([t0]))[0] - 5, _secs(pd.Series([t1]))[0] + 5, GRID_DT_S)
    L = ref.length_m

    def load(d):
        try:
            return d, src.position_data(s, d)
        finally:
            if progress:
                progress()

    with ThreadPoolExecutor(max_workers=3) as pool:
        positions = dict(pool.map(load, drivers))

    D = np.full((len(drivers), len(grid)), np.nan)
    pit = np.zeros_like(D, dtype=bool)
    for i, d in enumerate(drivers):
        pos = positions[d]
        pos = pos[(pos["date"] >= t0 - pd.Timedelta(seconds=60)) & (pos["date"] <= t1 + pd.Timedelta(seconds=10))]
        if len(pos) < 10:
            continue
        t, cum, lat = _cumulative_distance(pos, ref, laps[laps["driver_number"] == d])
        D[i] = np.interp(grid, t, cum)
        idx = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
        near = np.minimum(np.abs(t[idx] - grid), np.abs(t[idx - 1] - grid))
        D[i, (near > MAX_SAMPLE_GAP_S) | (grid < t[0]) | (grid > t[-1])] = np.nan
        pit[i] = np.interp(grid, t, lat) > PIT_LATERAL_M

    v = np.gradient(D, GRID_DT_S, axis=1)
    valid = ~np.isnan(D) & ~pit
    rows = []
    for i, d in enumerate(drivers):
        rel = D - D[i]
        ahead = np.where(valid, np.mod(rel, L), np.inf)
        ahead[i] = np.inf
        ahead[ahead < 0.5] = np.inf  # same position = same car / data artefact
        j = np.argmin(ahead, axis=0)
        g = ahead[j, np.arange(len(grid))]
        laps_rel = np.round((rel[j, np.arange(len(grid))] - g) / L)
        gap_s = g / np.maximum(v[i], MIN_SPEED_MS)
        gap_s[~np.isfinite(gap_s)] = np.inf  # NaN speed at data edges must not win argmin
        behind = np.where(valid, np.mod(-rel, L), np.inf)
        behind[i] = np.inf
        behind[behind < 0.5] = np.inf
        jb = np.argmin(behind, axis=0)
        hb = behind[jb, np.arange(len(grid))]
        laps_rel_b = np.round((rel[jb, np.arange(len(grid))] + hb) / L)
        gap_b = hb / np.maximum(v[jb, np.arange(len(grid))], MIN_SPEED_MS)
        gap_b[~np.isfinite(gap_b)] = np.inf
        ok = valid[i]

        own = laps[(laps["driver_number"] == d) & laps["lap_start"].notna() & laps["lap_end"].notna()]
        for lap in own.itertuples():
            m = ok & (grid >= _secs(pd.Series([lap.lap_start]))[0]) & (grid < _secs(pd.Series([lap.lap_end]))[0])
            if not m.any():
                continue
            gm = np.where(m, gap_s, np.inf)
            k = int(np.argmin(gm))
            close = m & (gap_s < GAP_S)
            if not s.is_race:
                kind = "car ahead"
            elif laps_rel[k] == 0:
                kind = "racing"
            elif laps_rel[k] < 0:
                kind = "backmarker"
            else:
                kind = "lapping car ahead"
            rows.append({
                "driver_number": d, "lap_number": int(lap.lap_number),
                "track_gap_ahead_s": round(float(gm[k]), 2) if np.isfinite(gm[k]) else None,
                "track_car_ahead": int(drivers[j[k]]) if np.isfinite(gm[k]) else None,
                "traffic_kind": kind if np.isfinite(gm[k]) else None,
                "traffic_share": round(float(close.sum() / m.sum()), 2),
                "being_lapped": bool(s.is_race and (m & (gap_b < BEING_LAPPED_S) & (laps_rel_b >= 1)).any()),
            })
    return pd.DataFrame(rows)


def start(session_id: str, src: SessionSource, s: SessionRef, ref: ReferenceLine, laps: pd.DataFrame, on_ready) -> None:
    with _lock:
        if session_id in _state and _state[session_id]["state"] in ("downloading", "ready"):
            return
        _state[session_id] = {"state": "downloading", "done": 0, "total": int(laps["driver_number"].nunique())}

    def tick():
        with _lock:
            _state[session_id]["done"] += 1

    def run():
        try:
            df = compute(src, s, ref, laps, tick)
            with _lock:
                _state[session_id].update(state="ready", result=df)
            on_ready(session_id)
        except Exception as exc:  # keep the interval heuristic if anything fails
            log.exception("on-track traffic failed for %s", session_id)
            with _lock:
                _state[session_id].update(state="failed", error=str(exc))

    threading.Thread(target=run, daemon=True, name=f"traffic-{session_id}").start()


def apply(laps: pd.DataFrame, traffic: pd.DataFrame, is_race: bool) -> pd.DataFrame:
    """Swap the interval-based traffic flag for on-track flags."""
    laps = laps.merge(traffic, on=["driver_number", "lap_number"], how="left")
    interval_flag = [f for f in laps["flags"].explode().dropna().unique() if str(f).startswith("within ") and "car ahead" in str(f)]
    flags = []
    for r in laps.itertuples():
        f = [x for x in r.flags if x not in interval_flag]
        gap = r.track_gap_ahead_s
        if gap is not None and not pd.isna(gap) and gap < GAP_S:
            label = {"racing": "racing car", "backmarker": "lapped backmarker", "lapping car ahead": "faster car a lap up",
                     "car ahead": "car"}.get(r.traffic_kind, "car")
            f.append(f"within {GAP_S}s of a {label} ahead on track")
        if is_race and r.being_lapped:
            f.append("being lapped (blue flags)")
        flags.append(f)
    laps["flags"] = flags
    laps["traffic_source"] = "on-track positions"
    return laps
