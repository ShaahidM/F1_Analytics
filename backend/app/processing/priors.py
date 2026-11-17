"""Training table for the cross-race degradation prior (docs/TYRE_METHODOLOGY.md §10).

One row per dry Grand Prix × compound: the field degradation slope and fresh-tyre offset from a linear-only
`fit_race_model`, with the race-level features the prior is allowed to use (circuit, season, track temperature,
typical lap time). Sprints are left out: with no pit stops, tyre age and fuel burn can't be separated.

Each race is summarised once and cached as JSON in `data/priors/races/`; the table is those files concatenated.
Needs laps, stints, pits, race control, intervals and weather only (~6 OpenF1 requests per race, no telemetry), so a
first build of every season takes roughly 20–30 minutes at the free rate limit. Runs in a background thread.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

from app.analysis.model import _attach_track_temp, session_conditions
from app.analysis.race_model import RaceModel, fit_race_model
from app.config import DATA_DIR, FIRST_SUPPORTED_SEASON
from app.processing import session_data as sd
from app.sources.base import DataUnavailable
from app.sources.registry import source_for_season

log = logging.getLogger(__name__)
PRIORS_DIR = DATA_DIR / "priors"
RACES_DIR = PRIORS_DIR / "races"
WEEKENDS_DIR = PRIORS_DIR / "weekends"
BASE_COMPOUND = "MEDIUM"  # fresh-tyre offsets are stored relative to it (it's raced almost everywhere)

_job: dict = {"state": "not_started"}
_lock = threading.Lock()


def weekends() -> list[tuple]:
    """(race, [practice and sprint sessions run before it]) for every finished Grand Prix of every season whose
    source has tyre compounds, oldest first."""
    now = datetime.now(timezone.utc)
    out = []
    for year in range(FIRST_SUPPORTED_SEASON, now.year + 1):
        try:
            src = source_for_season(year)
        except KeyError:
            continue
        for e in src.events(year):
            for s in e["sessions"]:
                if s.session_name == "Race" and s.date_end and s.date_end < now and src.capabilities(s).compounds:
                    before = [p for p in e["sessions"] if p.date_end and s.date_start and p.date_end < s.date_start
                              and (p.session_type == "Practice" or p.session_name == "Sprint")]
                    out.append((s, before))
    return out


def races() -> list:
    return [race for race, _ in weekends()]


# ---- pre-race running (practice long runs, sprint stints, practice push laps) ---------------------------------
RUN_MIN_LAPS = 5
RUN_MIN_AGES = 4
SPRINT_MIN_LAPS = 8


def _session_runs(s) -> tuple[list[dict], list[dict]]:
    """Long runs (one dict per driver × tyre set) and best laps per driver × compound of one pre-race session."""
    laps = sd.base_lap_table(s.id)
    if laps.empty or "compound" not in laps or laps["compound"].isna().all():
        return [], []
    try:
        drivers = source_for_season(s.year).drivers(s)
        teams = dict(zip(drivers["driver_number"].astype(int), drivers["team"]))
    except DataUnavailable:
        teams = {}
    runs = []
    clean = laps[laps["clean"] & laps["compound"].notna() & laps["tyre_age"].notna()]
    min_laps = SPRINT_MIN_LAPS if s.is_race else RUN_MIN_LAPS
    for (d, _), g in clean.groupby(["driver_number", "stint"]):
        age, t = g["tyre_age"].to_numpy(float), g["lap_time_s"].to_numpy(float)
        if len(g) < min_laps or len(np.unique(age)) < RUN_MIN_AGES:
            continue
        runs.append({"session_id": s.id, "driver": int(d), "team": teams.get(int(d)), "compound": g["compound"].iloc[0],
                     "slope": float(theilslopes(t, age)[0]), "pace": float(np.median(t)), "n": int(len(g))})
    best = []
    if not s.is_race:
        timed = laps[laps["lap_time_s"].notna() & laps["compound"].notna() & ~laps["is_pit_in"] & ~laps["is_pit_out"]
                     & ~laps["deleted"]]
        for (d, c), g in timed.groupby(["driver_number", "compound"]):
            best.append({"session_id": s.id, "driver": int(d), "compound": c, "best": float(g["lap_time_s"].min())})
    return runs, best


def _paired_delta(df: pd.DataFrame, by: list[str], value: str, c: str) -> tuple[float | None, int]:
    """Median over `by` groups (same session) of value on compound c minus value on the base compound."""
    if df.empty:
        return None, 0
    wide = df.groupby(by + ["compound"])[value].median().unstack("compound")
    if c not in wide or BASE_COMPOUND not in wide:
        return None, 0
    diff = (wide[c] - wide[BASE_COMPOUND]).dropna()
    return (round(float(diff.median()), 4), int(len(diff))) if len(diff) else (None, 0)


def weekend_rows(race, before: list) -> dict:
    """Per compound: what practice and the sprint showed before the race (all in seconds).
    lr_slope: median lap-time trend of long runs (tyre wear and fuel burn together, so it sits below the race slope).
    lr_pace_vs_medium: long-run pace vs Medium within the same team and session (fuel loads unknown).
    push_vs_medium: a driver's best lap on the compound vs their best on Medium in the same practice session."""
    runs, best = [], []
    for s in before:
        try:
            r, b = _session_runs(s)
        except DataUnavailable:
            continue
        runs += r
        best += b
    runs, best = pd.DataFrame(runs), pd.DataFrame(best)
    rows = []
    compounds = set(runs["compound"]) if len(runs) else set()
    compounds |= set(best["compound"]) if len(best) else set()
    for c in sorted(compounds):
        own = runs[runs["compound"] == c] if len(runs) else runs
        pace, pace_n = _paired_delta(runs, ["session_id", "team"], "pace", c)
        push, push_n = _paired_delta(best, ["session_id", "driver"], "best", c)
        rows.append({"session_id": race.id, "compound": c,
                     "lr_slope": round(float(own["slope"].median()), 4) if len(own) else None, "lr_n": int(len(own)),
                     "lr_pace_vs_medium": pace, "lr_pace_n": pace_n, "push_vs_medium": push, "push_n": push_n})
    return {"session_id": race.id, "status": "ok", "n_sessions": len(before), "rows": rows}


def weekend_table() -> pd.DataFrame:
    rows = []
    for p in sorted(WEEKENDS_DIR.glob("*.json")) if WEEKENDS_DIR.exists() else []:
        rows.extend(json.loads(p.read_text(encoding="utf-8"))["rows"])
    return pd.DataFrame(rows)


def build_weekends(progress=None) -> int:
    """Pre-race features for every race that has training rows (blocking). Returns the number of weekends done."""
    wanted = set(table()["session_id"]) if RACES_DIR.exists() else set()
    todo = [(race, before) for race, before in weekends() if race.id in wanted]
    for i, (race, before) in enumerate(todo):
        path = WEEKENDS_DIR / f"{race.id}.json"
        if progress:
            progress(i, len(todo), race)
        if path.exists():
            continue
        try:
            res = weekend_rows(race, before)
        except Exception:  # one bad weekend must not stop the build
            log.exception("weekend rows failed for %s", race.id)
            continue
        sd.base_lap_table.cache_clear()
        WEEKENDS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res), encoding="utf-8")
    return len(todo)


def _offset_vs(model: RaceModel, c: str, base: str) -> tuple[float | None, float | None]:
    """Fresh-tyre pace of compound c relative to `base` in this race (s), with its standard error."""
    if base not in model.compounds or c == base:
        return None, None
    vec = np.zeros(len(model.columns))
    for name, sign in ((f"cmp:{c}", 1.0), (f"cmp:{base}", -1.0)):
        if name in model.index:  # the model's reference compound has no column (offset 0)
            vec[model.index[name]] = sign
    return round(float(vec @ model.theta), 4), round(float(np.sqrt(vec @ model.cov @ vec)), 4)


def race_rows(s) -> dict:
    """{"session_id", "status": "ok" | "skipped", "message"?, "rows": [one dict per compound]}"""
    src = source_for_season(s.year)
    base = {"session_id": s.id, "year": s.year, "round": s.round, "meeting_name": s.meeting_name,
            "circuit_key": s.circuit_key, "circuit_name": s.circuit_name}
    laps = sd.base_lap_table(s.id)
    if laps.empty:
        return {**base, "status": "skipped", "message": "no laps", "rows": []}
    try:
        weather = src.weather(s)
    except DataUnavailable:
        weather = None
    conditions = session_conditions(laps, weather)
    if conditions != "dry":
        return {**base, "status": "skipped", "message": f"{conditions} race", "rows": []}
    try:
        model = fit_race_model(laps, allow_quad=False)
    except ValueError as exc:
        return {**base, "status": "skipped", "message": str(exc), "rows": []}

    clean = _attach_track_temp(laps[laps["clean"] & laps["lap_time_s"].notna()], weather)
    lap_s = float(clean["lap_time_s"].median())
    temp = float(clean["track_temp"].median()) if clean["track_temp"].notna().any() else None
    summary = model.summary()
    per = clean.groupby("compound")
    rows = []
    for c, m in summary["compounds"].items():
        g = per.get_group(c)
        off, off_se = _offset_vs(model, c, BASE_COMPOUND)
        rows.append({**base, "compound": c, "slope": m["slope"], "slope_se": m["slope_se"],
                     "offset_vs_medium": off, "offset_vs_medium_se": off_se,
                     "n_laps": int(len(g)), "n_drivers": int(g["driver_number"].nunique()),
                     "oldest_tyre": m["oldest_tyre"], "median_lap_number": float(g["lap_number"].median()),
                     "unreliable": m["unreliable"] is not None,
                     "lap_time_s": round(lap_s, 3), "track_temp": temp, "total_laps": int(laps["lap_number"].max()),
                     "fuel_track_per_lap": summary["fuel_track_per_lap"]["estimate"],
                     "residual_sd": summary["residual_sd"]})
    return {**base, "status": "ok", "rows": rows}


def _path(session_id: str):
    return RACES_DIR / f"{session_id}.json"


def _load_cached(s) -> dict | None:
    return json.loads(_path(s.id).read_text(encoding="utf-8")) if _path(s.id).exists() else None


def table() -> pd.DataFrame:
    """Every cached race × compound row (empty frame if nothing has been built yet)."""
    rows = []
    for p in sorted(RACES_DIR.glob("*.json")) if RACES_DIR.exists() else []:
        rows.extend(json.loads(p.read_text(encoding="utf-8"))["rows"])
    df = pd.DataFrame(rows)
    if not df.empty:
        df["track_temp"] = df["track_temp"].astype(float)
        df = df.sort_values(["year", "round", "compound"]).reset_index(drop=True)
    return df


def status() -> dict:
    with _lock:
        return {k: v for k, v in _job.items() if k != "thread"}


def build(progress=None) -> dict:
    """Summarise every race not cached yet (blocking). Returns counts by status."""
    sessions = races()
    counts = {"ok": 0, "skipped": 0, "error": 0}
    for i, s in enumerate(sessions):
        if progress:
            progress(i, len(sessions), s)
        res = _load_cached(s)
        if res is None:
            try:
                res = race_rows(s)
            except Exception as exc:  # one bad race must not stop the build
                log.exception("prior rows failed for %s", s.id)
                res = {"session_id": s.id, "status": "error", "message": str(exc)[:200], "rows": []}
            if s.is_settled() and res["status"] != "error":
                RACES_DIR.mkdir(parents=True, exist_ok=True)
                _path(s.id).write_text(json.dumps(res), encoding="utf-8")
        counts[res["status"]] += 1
    return counts


def start() -> dict:
    with _lock:
        if _job["state"] == "running":
            return {k: v for k, v in _job.items() if k != "thread"}
        _job.clear()
        _job.update(state="running", done=0, total=0, current=None)

    def progress(i, total, s):
        with _lock:
            _job.update(done=i, total=total, current=f"{s.year} {s.meeting_name}")

    def run():
        try:
            counts = build(progress)
            with _lock:
                _job.update(state="done", current=None, done=_job["total"], counts=counts)
        except Exception as exc:
            log.exception("prior build failed")
            with _lock:
                _job.update(state="failed", error=str(exc)[:200])

    t = threading.Thread(target=run, daemon=True, name="prior-build")
    with _lock:
        _job["thread"] = t
    t.start()
    return status()
