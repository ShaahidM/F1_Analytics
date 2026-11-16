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
    "deleted", "min_interval_s", "clean", "exclude_reasons", "flags", "tyre_age_assumed", "track_gap_ahead_s",
    "track_car_ahead", "traffic_kind", "traffic_share", "being_lapped", "traffic_source",
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
            src = source_for_season(year)
            out.append({"year": year, "source": src.name, "limited": not src.provides_telemetry})
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


def _race_only(s, what: str) -> None:
    """Tyre-age analyses need long runs: races, sprints and practice, not qualifying."""
    if s.session_type == "Qualifying":
        raise HTTPException(422, f"{what} needs a race or practice long runs: qualifying has only 1–3 push laps per tyre set")


@router.get("/sessions/{session_id}/degradation")
def degradation(session_id: str, drivers: str, include_flagged: bool = False, fuel_s_per_lap: float = 0.0):
    s, _ = _session(session_id)
    _race_only(s, "Tyre-age analysis")
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
    _race_only(s, "Tyre-age analysis")
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
        raise HTTPException(422, "The session-wide model needs a race: practice fuel loads are unknown and differ "
                                 "between teams, and qualifying has no stints")
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


@router.get("/sessions/{session_id}/traffic")
def traffic_status(session_id: str):
    """Starts on-track traffic detection on first call (background), then reports progress."""
    _session(session_id)
    st = _guard(lambda: session_data.ensure_traffic(session_id))
    return {k: v for k, v in st.items() if k != "result"}


@router.get("/sessions/{session_id}/line")
def line(session_id: str, drivers: str, include_flagged: bool = True):
    _session(session_id)
    a, b = _two_drivers(drivers)
    return _guard(lambda: session_data.line_comparison(session_id, a, b, include_flagged))


@router.get("/sessions/{session_id}/longruns")
def long_runs(session_id: str, include_flagged: bool = True):
    """Every driver's long runs in the session (practice long runs, or race/sprint stints)."""
    s, src = _session(session_id)
    _race_only(s, "Long-run analysis")
    df = _guard(lambda: session_data.lap_table(session_id))
    drivers = _guard(lambda: src.drivers(s))
    code = dict(zip(drivers["driver_number"], drivers["code"]))
    team = dict(zip(drivers["driver_number"], drivers["team"]))
    runs = [r for r in stint_trends(df, sorted(df["driver_number"].unique()), include_flagged, 0.0) if r["n_used"] >= 5]
    for r in runs:
        r["code"] = code.get(r["driver_number"])
        r["team"] = team.get(r["driver_number"])
    return {"ci_level": CI_LEVEL, "runs": runs}


@router.get("/seasons/{year}/drivers")
def season_drivers(year: int):
    from app.processing import season
    try:
        return season.season_drivers(year)
    except KeyError:
        raise HTTPException(404, f"no data source covers {year}")


@router.get("/seasons/{year}/compare")
def season_compare(year: int, a: str, b: str, include_wet: bool = False):
    """Starts (or reports) the background season comparison for two driver codes; returns races done so far."""
    from app.processing import season
    a, b = a.upper(), b.upper()
    if a == b:
        raise HTTPException(422, "pick two different drivers")
    try:
        if not source_for_season(year).provides_telemetry:
            raise HTTPException(422, "season comparison needs telemetry seasons (2023+)")
    except KeyError:
        raise HTTPException(404, f"no data source covers {year}")
    st = season.start(year, a, b)
    races = sorted(st.get("races", []), key=lambda r: r.get("round") or 0)
    return {**{k: v for k, v in st.items() if k != "races"}, "races": races,
            "aggregate": season.aggregate(year, a, b, include_wet)}


# ---- strategy what-if simulator (Stage A: lap-time maths, no traffic) ----------------------------------
from pydantic import BaseModel, Field  # noqa: E402


class StintIn(BaseModel):
    compound: str
    laps: int = Field(ge=1)
    start_age: int = Field(0, ge=0)


class DriverPlanIn(BaseModel):
    driver: int
    stints: list[StintIn] = Field(min_length=1, max_length=6)


class ScenarioIn(BaseModel):
    sc: list[int] = []
    vsc: list[int] = []


class SimulateIn(BaseModel):
    drivers: list[DriverPlanIn] = Field(min_length=1, max_length=2)
    scenario: ScenarioIn = ScenarioIn()
    traffic: bool = True  # Stage B (traffic + overtaking); False = Stage A clean-air comparison


class OptimiseIn(BaseModel):
    driver: int
    max_stops: int = Field(2, ge=1, le=3)
    scenario: ScenarioIn = ScenarioIn()
    traffic: bool = True


def _whatif(session_id: str):
    _session(session_id)
    return _guard(lambda: session_data.whatif_context(session_id))


def _sim_guard(fn):
    from app.analysis.simulator import StrategyError
    try:
        return fn()
    except StrategyError as exc:
        raise HTTPException(422, str(exc))


@router.get("/sessions/{session_id}/whatif/model")
def whatif_model(session_id: str):
    from app.analysis.simulator import backtest
    ctx = _whatif(session_id)
    return {
        "total_laps": ctx.total_laps, "model": ctx.model.summary(), "backtest": backtest(ctx),
        "pit_loss": {"by_driver": {ctx.codes.get(d, str(d)): round(v, 2) for d, v in ctx.pit_loss.items()},
                     "field_median": round(ctx.field_loss, 2), "spread_sd": round(ctx.loss_sd, 2), "multiviewer": ctx.mv_loss},
        "actual": {str(d): [s.__dict__ for s in st] for d, st in ctx.actual.items()},
        "own_max": [{"driver": d, "compound": c, "laps": n} for (d, c), n in ctx.model.own_max.items()],
        "neutralised_laps": sorted(ctx.neutral_time), "assumptions": ctx.assumptions,
        "overtaking": session_data.whatif_overtaking(session_id).summary(),
    }


@router.post("/sessions/{session_id}/whatif/simulate")
def whatif_simulate(session_id: str, body: SimulateIn):
    from app.analysis.simulator import Scenario, Stint, run
    from app.analysis.traffic_sim import run_with_traffic
    ctx = _whatif(session_id)
    plans = {p.driver: [Stint(s.compound.upper(), s.laps, s.start_age) for s in p.stints] for p in body.drivers}
    if len(plans) != len(body.drivers):
        raise HTTPException(422, "each driver can appear only once")
    scenario = Scenario(body.scenario.sc, body.scenario.vsc)
    clean = _sim_guard(lambda: run(ctx, plans, scenario))
    if not body.traffic:
        return {**clean, "mode": "clean_air"}
    res = _sim_guard(lambda: run_with_traffic(ctx, session_data.whatif_overtaking(session_id), plans, scenario))
    for d, r in res["drivers"].items():  # validation messages and the clean-air figure come from Stage A
        c = clean["drivers"][d]
        r.update(warnings=c["warnings"], extrapolation=c["extrapolation"], laps=c["laps"],
                 clean_air_delta=c["delta_vs_actual_strategy"])
    return {**res, "mode": "traffic"}


@router.post("/sessions/{session_id}/whatif/optimise")
def whatif_optimise(session_id: str, body: OptimiseIn):
    from app.analysis.simulator import Scenario, Stint, optimise, validate
    from app.analysis.traffic_sim import run_with_traffic
    ctx = _whatif(session_id)
    _sim_guard(lambda: validate(ctx, body.driver, ctx.actual.get(body.driver, [])))
    scenario = Scenario(body.scenario.sc, body.scenario.vsc)
    res = _sim_guard(lambda: optimise(ctx, body.driver, body.max_stops, scenario))
    if body.traffic:
        # Clean-air ranking first (fast, exhaustive), then re-rank the shortlist with traffic and overtaking.
        ov = session_data.whatif_overtaking(session_id)
        for p in res["plans"]:
            stints = [Stint(**s) for s in p["stints"]]
            r = run_with_traffic(ctx, ov, {body.driver: stints}, scenario, draws=200)
            p["delta_with_traffic"] = r["drivers"][str(body.driver)]["delta_vs_actual_strategy"]
            p["laps_held"] = r["drivers"][str(body.driver)]["traffic"]["laps_held_median"]
        res["plans"].sort(key=lambda p: p["delta_with_traffic"]["median"])
    return {**res, "mode": "traffic" if body.traffic else "clean_air"}
