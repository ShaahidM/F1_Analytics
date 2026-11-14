"""Session-level derived data with in-process memoisation (raw downloads are cached on disk by the sources)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from app.analysis.corners import Zone, build_zones, zone_metrics
from app.analysis.degradation import _fit
from app.analysis.line import compare_line
from app.analysis.preservation import corner_rows, stint_zone_trends
from app.analysis.strategy import crossing_times, pit_cycles, pit_stops, positions, stints_table
from app.analysis.style import STYLE_METRICS, lap_style
from app.config import POSITION_UNITS_PER_M, TRACE_GRID_M
from app.processing import traffic
from app.processing.laps import build_lap_table
from app.processing.reference import ReferenceLine, build_reference, project
from app.processing.telemetry import lap_trace
from app.sources import multiviewer
from app.sources.base import DataUnavailable
from app.sources.registry import get_session, source_for_session
from app.storage.cache import parquet_path

# If MultiViewer corner markers sit further than this from our reference line, its layout doesn't match.
CORNER_MATCH_MAX_M = 40.0


@lru_cache(maxsize=32)
def base_lap_table(session_id: str) -> pd.DataFrame:
    """Lap table with the classification-interval traffic heuristic (no extra downloads)."""
    s = get_session(session_id)
    laps = build_lap_table(source_for_session(session_id), s)
    laps["traffic_source"] = "classification interval" if s.is_race and laps["min_interval_s"].notna().any() else "none"
    return laps


def lap_table(session_id: str) -> pd.DataFrame:
    """Base table, upgraded with on-track traffic once every car's positions have been processed."""
    return _lap_table(session_id, traffic.result(session_id) is not None)


@lru_cache(maxsize=64)
def _lap_table(session_id: str, traffic_ready: bool) -> pd.DataFrame:
    base = base_lap_table(session_id)
    if not traffic_ready:
        return base
    return traffic.apply(base, traffic.result(session_id), get_session(session_id).is_race)


def _invalidate_traffic_dependents(session_id: str) -> None:
    for cached in (style_rows, preservation, strategy):
        cached.cache_clear()


def ensure_traffic(session_id: str) -> dict:
    """Start (or load) on-track traffic detection for a session; returns its status."""
    s = get_session(session_id)
    src = source_for_session(session_id)
    if not src.capabilities(s).position:
        return {"state": "unavailable", "done": 0, "total": 0}
    if traffic.status(session_id)["state"] == "not_started":
        path = parquet_path(src.name, session_id, "traffic")
        if path.exists():
            traffic.preload(session_id, pd.read_parquet(path))
            _invalidate_traffic_dependents(session_id)
        else:
            def ready(sid: str) -> None:
                if s.is_settled():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    traffic.result(sid).to_parquet(path, index=False)
                _invalidate_traffic_dependents(sid)

            traffic.start(session_id, src, s, reference(session_id)[0], base_lap_table(session_id), ready)
    return traffic.status(session_id)


def lap_row(session_id: str, driver: int, lap: int) -> pd.Series:
    laps = base_lap_table(session_id)
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
    laps = base_lap_table(session_id)
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


def analysis_laps(session_id: str, driver: int, include_flagged: bool) -> pd.DataFrame:
    """Clean laps of one driver that have a timing window (and so telemetry)."""
    laps = lap_table(session_id)
    d = laps[(laps["driver_number"] == driver) & laps["clean"] & laps["lap_start"].notna() & laps["lap_end"].notna()]
    if not include_flagged:
        d = d[d["flags"].map(len) == 0]
    return d


def _metrics_by_lap(session_id: str, driver: int, laps: pd.DataFrame) -> dict[int, list[dict]]:
    out = {}
    for lap in laps["lap_number"].astype(int):
        try:
            out[lap] = corner_metrics(session_id, driver, lap)
        except (ValueError, DataUnavailable):
            continue  # lap without usable telemetry; reported via n_laps
    return out


@lru_cache(maxsize=64)
def style_rows(session_id: str, driver: int, include_flagged: bool) -> list[dict]:
    laps = analysis_laps(session_id, driver, include_flagged)
    zs = zones(session_id)
    rows = []
    for lap, metrics in _metrics_by_lap(session_id, driver, laps).items():
        li = laps[laps["lap_number"] == lap].iloc[0]
        rows.append({
            "lap_number": lap, "stint": None if pd.isna(li["stint"]) else int(li["stint"]), "compound": li["compound"],
            "tyre_age": None if pd.isna(li["tyre_age"]) else int(li["tyre_age"]), "lap_time_s": float(li["lap_time_s"]),
            **lap_style(trace(session_id, driver, lap, True), metrics, zs),
        })
    return rows


@lru_cache(maxsize=64)
def preservation(session_id: str, driver: int, include_flagged: bool) -> dict:
    laps = analysis_laps(session_id, driver, include_flagged)
    rows = corner_rows(_metrics_by_lap(session_id, driver, laps), laps)
    braking = [z.id for z in zones(session_id) if z.kind == "braking"]
    style = pd.DataFrame(style_rows(session_id, driver, include_flagged))
    lap_trends = []
    if not style.empty:
        for stint, g in style.dropna(subset=["stint", "tyre_age"]).groupby("stint"):
            x = g["tyre_age"].astype(float).to_numpy()
            lap_trends.append({"stint": int(stint), "compound": g["compound"].iloc[0], "n_laps": int(len(g)),
                               "trends": {k: _fit(x, g[k].astype(float).to_numpy()) for k in STYLE_METRICS}})
    keep = ["lap_number", "stint", "compound", "tyre_age", "zone_id", "time_in_zone_s", "brake_onset_before_apex_m",
            "brake_onset_resolution_m", "mean_decel_g", "entry_speed_kmh", "min_speed_kmh", "exit_speed_kmh",
            "throttle_pickup_m", "throttle_ramp_m", "coast_m", "path_excess_m"]
    return {
        "driver_number": driver,
        "zone_trends": stint_zone_trends(rows, braking),
        "lap_trends": lap_trends,
        "rows": rows[[c for c in keep if c in rows]] if not rows.empty else rows,
    }


@lru_cache(maxsize=32)
def strategy(session_id: str, a: int, b: int) -> dict:
    s = get_session(session_id)
    src = source_for_session(session_id)
    if not s.is_race:
        raise DataUnavailable("strategy analysis (races and sprints only)")
    laps = lap_table(session_id)
    try:
        pits = src.pits(s)
    except DataUnavailable:
        pits = pd.DataFrame(columns=["driver_number", "lap_number", "lane_duration_s", "stop_duration_s"])
    cross = crossing_times(laps)
    pos = positions(cross)
    last = pos.sort_values("lap_number").groupby("driver_number").tail(1)
    order = last.sort_values(["lap_number", "t"], ascending=[False, True])["driver_number"].astype(int).tolist()
    stops = {d: pit_stops(laps, pits, d) for d in (a, b)}
    ta = cross[cross["driver_number"] == a].set_index("lap_number")["t"]
    tb = cross[cross["driver_number"] == b].set_index("lap_number")["t"]
    common = ta.index.intersection(tb.index)
    info = multiviewer.circuit_info(s.circuit_key, s.year) if s.circuit_key is not None else None
    return {
        "order": order,
        "total_laps": int(laps["lap_number"].max()),
        "stints": stints_table(laps),
        "pit_stops": {str(d): v for d, v in stops.items()},
        "pit_loss_reference": (info or {}).get("pit_loss"),
        "gap": [{"lap": int(n), "gap_s": round(float(tb[n] - ta[n]), 3)} for n in sorted(common)],
        "positions": {str(d): [{"lap": int(r.lap_number), "position": int(r.position)}
                               for r in pos[pos["driver_number"] == d].sort_values("lap_number").itertuples()] for d in (a, b)},
        "cycles": pit_cycles(cross, stops, laps, a, b),
        "timing_basis": "line-crossing timestamps" if laps["lap_end"].notna().any() else "cumulative lap times",
    }


def line_comparison(session_id: str, a: int, b: int, include_flagged: bool) -> dict:
    ra = preservation(session_id, a, include_flagged)["rows"]
    rb = preservation(session_id, b, include_flagged)["rows"]
    zs = zones(session_id)
    return {"zones": [z.to_dict() for z in zs], "rows": compare_line(ra, rb, [z.id for z in zs])}
