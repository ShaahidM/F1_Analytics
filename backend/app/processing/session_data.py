"""Session-level derived data with in-process memoisation (raw downloads are cached on disk by the sources)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from app.analysis.corners import Zone, build_zones, zone_metrics
from app.config import POSITION_UNITS_PER_M, TRACE_GRID_M
from app.processing.laps import build_lap_table
from app.processing.reference import ReferenceLine, build_reference, project
from app.processing.telemetry import lap_trace
from app.sources import multiviewer
from app.sources.base import DataUnavailable
from app.sources.registry import get_session, source_for_session

# If MultiViewer corner markers sit further than this from our reference line, its layout doesn't match.
CORNER_MATCH_MAX_M = 40.0


@lru_cache(maxsize=32)
def lap_table(session_id: str) -> pd.DataFrame:
    return build_lap_table(source_for_session(session_id), get_session(session_id))


def lap_row(session_id: str, driver: int, lap: int) -> pd.Series:
    laps = lap_table(session_id)
    m = laps[(laps["driver_number"] == driver) & (laps["lap_number"] == lap)]
    if m.empty:
        raise KeyError(f"lap {lap} of car {driver}")
    return m.iloc[0]


@lru_cache(maxsize=32)
def reference(session_id: str) -> tuple[ReferenceLine, dict]:
    """Reference = fastest lap in the session with a time, not deleted, not a pit lap."""
    s = get_session(session_id)
    src = source_for_session(session_id)
    caps = src.capabilities(s)
    if not caps.position:
        raise DataUnavailable("position data")
    laps = lap_table(session_id)
    cand = laps[laps["lap_time_s"].notna() & ~laps["deleted"] & ~laps["is_pit_out"] & ~laps["is_pit_in"]
                & laps["lap_start"].notna()].sort_values("lap_time_s")
    for row in cand.head(5).itertuples():  # fall back to the next fastest if a lap has telemetry gaps
        pos = src.position_data(s, int(row.driver_number))
        win = pos[(pos["date"] >= row.lap_start) & (pos["date"] <= row.lap_end)]
        if len(win) < 50 or win["date"].diff().dt.total_seconds().max() > 2.0:
            continue
        ref = build_reference(pos, row.lap_start, row.lap_end)
        return ref, {"driver_number": int(row.driver_number), "lap_number": int(row.lap_number),
                     "lap_time_s": float(row.lap_time_s), "length_m": round(ref.length_m, 1)}
    raise DataUnavailable("no lap with complete position data to build a reference line")


def _speed_minima_corners(session_id: str, ref: ReferenceLine, meta: dict) -> list[dict]:
    tr = trace(session_id, meta["driver_number"], meta["lap_number"])
    speed = np.array([v if v is not None else np.nan for v in tr["speed"]])
    peaks, _ = find_peaks(-np.nan_to_num(speed, nan=np.nanmax(speed)), prominence=15, distance=int(80 / TRACE_GRID_M))
    out = []
    for n, i in enumerate(peaks, start=1):
        out.append({"number": n, "letter": "", "angle": None, "x": tr["x"][i], "y": tr["y"][i],
                    "s": tr["s"][i], "source": "speed minimum (calculated)"})
    return out


@lru_cache(maxsize=32)
def track(session_id: str) -> dict:
    s = get_session(session_id)
    ref, meta = reference(session_id)
    info = multiviewer.circuit_info(s.circuit_key, s.year) if s.circuit_key is not None else None
    corners: list[dict] = []
    notes: list[str] = []
    if info and info["corners"]:
        cx = np.array([c["x"] for c in info["corners"]], float)
        cy = np.array([c["y"] for c in info["corners"]], float)
        cs, lat = project(ref, cx, cy)
        if np.median(np.abs(lat)) <= CORNER_MATCH_MAX_M:
            corners = [{**c, "s": round(float(si), 1), "source": "MultiViewer"} for c, si in zip(info["corners"], cs)]
        else:
            notes.append(f"MultiViewer corner layout ({info['layout_year']}) does not match this session's track; "
                         "corners detected from speed minima instead.")
    if not corners:
        corners = _speed_minima_corners(session_id, ref, meta)
    corners.sort(key=lambda c: c["s"])
    ref_trace = trace(session_id, meta["driver_number"], meta["lap_number"])
    return {
        "reference": {**meta, **ref.downsample(TRACE_GRID_M)},
        "corners": corners,
        "zones": [z.to_dict() for z in build_zones(ref_trace, corners)],
        "rotation": (info or {}).get("rotation", 0),
        "pit_loss_s": (info or {}).get("pit_loss"),
        "units_per_m": POSITION_UNITS_PER_M,
        "notes": notes,
    }


@lru_cache(maxsize=256)
def trace(session_id: str, driver: int, lap: int, include_raw: bool = True) -> dict:
    s = get_session(session_id)
    src = source_for_session(session_id)
    row = lap_row(session_id, driver, lap)
    if pd.isna(row["lap_start"]) or pd.isna(row["lap_end"]):
        raise DataUnavailable(f"lap {lap} of car {driver} has no timing window")
    ref, _ = reference(session_id)
    out = lap_trace(src.car_data(s, driver), src.position_data(s, driver), ref, row["lap_start"], row["lap_end"],
                    TRACE_GRID_M, include_raw)
    out["driver_number"] = driver
    out["lap_number"] = lap
    out["lap_time_s"] = None if pd.isna(row["lap_time_s"]) else float(row["lap_time_s"])
    return out


def zones(session_id: str) -> list[Zone]:
    return [Zone(**z) for z in track(session_id)["zones"]]


@lru_cache(maxsize=512)
def corner_metrics(session_id: str, driver: int, lap: int) -> list[dict]:
    tr = trace(session_id, driver, lap, True)
    return [zone_metrics(tr, z) for z in zones(session_id)]
