from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

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
    "deleted", "min_interval_s", "clean", "exclude_reasons", "flags",
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
