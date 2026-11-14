from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.analysis.corners import METRICS
from app.analysis.degradation import CI_LEVEL, stint_trends
from app.analysis.model import fit_session_model
from app.analysis.preservation import CONFOUNDERS, INDICATORS, MIN_CHANGE
from app.analysis.style import STYLE_METRICS
from app.api.serialize import frame, row, value
from app.config import FIRST_SUPPORTED_SEASON
from app.processing import session_data
from app.processing.compare import SelectionError, select_laps
from app.sources.base import DataUnavailable
from app.sources.registry import get_session, source_for_season, source_for_session

router = APIRouter(prefix="/api")

LAP_FIELDS = [
    "driver_number", "lap_number", "lap_start", "lap_time_s", "s1_s", "s2_s", "s3_s", "i1_speed", "i2_speed",
    "st_speed", "is_pit_out", "is_pit_in", "stint", "compound", "tyre_age", "sc", "vsc", "red", "yellow",
    "deleted", "min_interval_s", "clean", "exclude_reasons", "flags", "tyre_age_assumed",
]


def _session(session_id: str):
    try:
        return get_session(session_id), source_for_session(session_id)
    except KeyError:
        raise HTTPException(404, f"unknown session {session_id}")


def _guard(fn):
    try:
        return fn()
    except DataUnavailable as exc:
        raise HTTPException(422, f"Not available for this session: {exc}")
    except (KeyError, SelectionError) as exc:
        raise HTTPException(404, str(exc).strip("'\""))


@router.get("/seasons")
def seasons():
    out = []
    for year in range(datetime.now(timezone.utc).year, FIRST_SUPPORTED_SEASON - 1, -1):
        try:
            out.append({"year": year, "source": source_for_season(year).name})
        except KeyError:
            continue
    return out


@router.get("/seasons/{year}/events")
def events(year: int):
    try:
        src = source_for_season(year)
    except KeyError:
        raise HTTPException(404, f"no data source covers {year}")
    evs = src.events(year)
    return [{
        **{k: value(v) for k, v in e.items() if k != "sessions"},
        "sessions": [{**sr.to_dict(), "capabilities": src.capabilities(sr).to_dict()} for sr in e["sessions"]],
    } for e in evs]


@router.get("/sessions/{session_id}")
def session(session_id: str):
    s, src = _session(session_id)
    drivers = _guard(lambda: src.drivers(s))
    return {**s.to_dict(), "capabilities": src.capabilities(s).to_dict(), "drivers": frame(drivers)}


@router.get("/sessions/{session_id}/laps")
def laps(session_id: str, drivers: str | None = Query(None, description="comma-separated car numbers")):
    _session(session_id)
    df = _guard(lambda: session_data.lap_table(session_id))
    if drivers:
        df = df[df["driver_number"].isin([int(d) for d in drivers.split(",")])]
    return frame(df, LAP_FIELDS)


@router.get("/sessions/{session_id}/stints")
def stints(session_id: str):
    s, src = _session(session_id)
    return frame(_guard(lambda: src.stints(s)))


@router.get("/sessions/{session_id}/track")
def track(session_id: str):
    _session(session_id)
    return _guard(lambda: session_data.track(session_id))


@router.get("/sessions/{session_id}/trace")
def trace(session_id: str, driver: int, lap: int, raw: bool = True):
    _session(session_id)
    try:
        return _guard(lambda: session_data.trace(session_id, driver, lap, raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/sessions/{session_id}/compare")
def compare(
    session_id: str, a: int, b: int, mode: Literal["fastest", "same_lap", "same_tyre_age", "custom"] = "fastest",
    lap: int | None = None, tyre_age: int | None = None,
    compound_a: str | None = None, compound_b: str | None = None,
    stint_a: int | None = None, stint_b: int | None = None,
    lap_a: int | None = None, lap_b: int | None = None,
):
    s, _ = _session(session_id)
    laps_df = _guard(lambda: session_data.lap_table(session_id))
    sel = _guard(lambda: select_laps(
        laps_df, a, b, mode, s.is_race, lap=lap, tyre_age=tyre_age, compound_a=compound_a, compound_b=compound_b,
        stint_a=stint_a, stint_b=stint_b, lap_a=lap_a, lap_b=lap_b))
    pick = lambda r: {k: v for k, v in row(r).items() if k in LAP_FIELDS}  # noqa: E731
    return {"mode": mode, "a": pick(sel["a"]), "b": pick(sel["b"]),
            "differences": sel["differences"], "equivalent": sel["equivalent"]}


@router.get("/sessions/{session_id}/corners")
def corners(session_id: str, driver: int, lap: int):
    _session(session_id)
    try:
        metrics = _guard(lambda: session_data.corner_metrics(session_id, driver, lap))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"driver_number": driver, "lap_number": lap, "metrics": metrics,
            "definitions": {k: {"unit": u, "tier": tier, "note": note} for k, (u, tier, note) in METRICS.items()}}


@router.get("/sessions/{session_id}/degradation")
def degradation(session_id: str, drivers: str, include_flagged: bool = False, fuel_s_per_lap: float = 0.0):
    _session(session_id)
    df = _guard(lambda: session_data.lap_table(session_id))
    ids = [int(d) for d in drivers.split(",")]
    return {
        "ci_level": CI_LEVEL,
        "fuel_s_per_lap": fuel_s_per_lap,
        "stints": stint_trends(df, ids, include_flagged, fuel_s_per_lap),
        "laps": frame(df[df["driver_number"].isin(ids)], LAP_FIELDS),
    }


def _two_drivers(drivers: str) -> list[int]:
    ids = [int(d) for d in drivers.split(",") if d]
    if len(ids) != 2:
        raise HTTPException(422, "pass exactly two car numbers, e.g. drivers=16,81")
    return ids


@router.get("/sessions/{session_id}/style")
def style(session_id: str, drivers: str, include_flagged: bool = True):
    _session(session_id)
    ids = _two_drivers(drivers)
    return {
        "definitions": {k: {"unit": u, "tier": tier, "note": note} for k, (u, tier, note) in STYLE_METRICS.items()},
        "drivers": {str(d): _guard(lambda d=d: session_data.style_rows(session_id, d, include_flagged)) for d in ids},
    }


@router.get("/sessions/{session_id}/preservation")
def preservation(session_id: str, drivers: str, include_flagged: bool = True):
    s, src = _session(session_id)
    ids = _two_drivers(drivers)
    out = {}
    for d in ids:
        p = _guard(lambda d=d: session_data.preservation(session_id, d, include_flagged))
        out[str(d)] = {**p, "rows": frame(p["rows"]) if len(p["rows"]) else []}
    return {
        "indicators": {k: {"label": lab, "unit": u, "increase_means": inc, "min_change": MIN_CHANGE.get(k)}
                       for k, (lab, u, inc) in INDICATORS.items()},
        "style_metrics": {k: {"unit": u, "tier": tier, "note": note} for k, (u, tier, note) in STYLE_METRICS.items()},
        "confounders": CONFOUNDERS + src.capabilities(s).notes,
        "zones": [z.to_dict() for z in _guard(lambda: session_data.zones(session_id))],
        "drivers": out,
    }


@router.get("/sessions/{session_id}/model")
def session_model(session_id: str, drivers: str, include_flagged: bool = True):
    s, src = _session(session_id)
    if not s.is_race:
        raise HTTPException(422, "Model B needs a race: qualifying has no stints or fuel burn to separate")
    a, b = _two_drivers(drivers)
    laps_df = _guard(lambda: session_data.lap_table(session_id))
    try:
        weather = src.weather(s)
    except DataUnavailable:
        weather = None
    return fit_session_model(laps_df, a, b, include_flagged, weather)


@router.get("/sessions/{session_id}/strategy")
def strategy(session_id: str, drivers: str):
    _session(session_id)
    a, b = _two_drivers(drivers)
    return _guard(lambda: session_data.strategy(session_id, a, b))
