"""Season comparison: two drivers analysed race by race, then aggregated with DuckDB.

Drivers are identified by their three-letter code because car numbers change between seasons (VER: 1 → 3).
Each race is summarised once (race-wide model tyre costs, like-for-like pace gap, driving-style medians, behaviour
patterns, line-length differences), cached as JSON + a long-format Parquet of metrics, and the season aggregate is a
DuckDB query over those Parquet files. Runs in a background thread because a full season needs ~300 OpenF1 requests
(~10–15 min at the free rate limit); finished races are visible while the rest download.

Traffic uses the classification-interval fallback here (on-track traffic for 20 cars × 24 races would add ~500
requests). Mixed/wet races are summarised but excluded from season aggregates by default.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from app.analysis.model import fit_session_model
from app.config import DATA_DIR
from app.processing import session_data as sd
from app.sources.base import DataUnavailable
from app.sources.registry import source_for_season

log = logging.getLogger(__name__)
SEASON_DIR = DATA_DIR / "season"
STYLE_KEYS = ["full_throttle_pct", "partial_throttle_pct", "coast_m", "braking_time_s", "mean_decel_g",
              "throttle_ramp_m", "exit_accel_g", "mean_min_kmh"]
PATTERNS = ["consistent_with_management", "consistent_with_grip_loss", "mixed", "no_clear_pattern", "insufficient_data"]

_jobs: dict[tuple, dict] = {}
_lock = threading.Lock()


def _pair_dir(year: int, a: str, b: str) -> Path:
    return SEASON_DIR / str(year) / f"{a}_{b}"


def races(year: int) -> list:
    """Grand Prix race sessions of a season that have finished (sprints excluded)."""
    src = source_for_season(year)
    now = datetime.now(timezone.utc)
    out = []
    for e in src.events(year):
        for s in e["sessions"]:
            if s.session_name == "Race" and s.date_end and s.date_end < now:
                out.append(s)
    return out


def season_drivers(year: int) -> list[dict]:
    """Every driver code that started a race this season, with names, teams and race counts."""
    src = source_for_season(year)
    seen: dict[str, dict] = {}
    for s in races(year):
        try:
            d = src.drivers(s)
        except DataUnavailable:
            continue
        for r in d.itertuples():
            row = seen.setdefault(r.code, {"code": r.code, "full_name": r.full_name, "teams": [], "races": 0,
                                           "team_colour": r.team_colour})
            row["races"] += 1
            if r.team not in row["teams"]:
                row["teams"].append(r.team)
    return sorted(seen.values(), key=lambda r: (-r["races"], r["code"]))


def _paired_pace_gap(laps: pd.DataFrame, a: int, b: int) -> dict | None:
    """Median of (B − A) over laps both drivers completed cleanly on the same lap number: same fuel and track state."""
    la = laps[(laps["driver_number"] == a) & laps["clean"]].set_index("lap_number")["lap_time_s"]
    lb = laps[(laps["driver_number"] == b) & laps["clean"]].set_index("lap_number")["lap_time_s"]
    both = la.index.intersection(lb.index)
    if len(both) < 5:
        return None
    d = (lb[both] - la[both]).to_numpy(float)
    boot = np.median(np.random.default_rng(0).choice(d, size=(1000, len(d))), axis=1)
    return {"median_s": round(float(np.median(d)), 3), "ci_low": round(float(np.percentile(boot, 5)), 3),
            "ci_high": round(float(np.percentile(boot, 95)), 3), "n_laps": int(len(d))}


def race_summary(year: int, s, a_code: str, b_code: str) -> dict:
    src = source_for_season(year)
    base = {"session_id": s.id, "round": s.round, "meeting_name": s.meeting_name, "location": s.location,
            "date": s.date_start.isoformat() if s.date_start else None}
    drivers = src.drivers(s)
    num = dict(zip(drivers["code"], drivers["driver_number"]))
    if a_code not in num or b_code not in num:
        missing = [c for c in (a_code, b_code) if c not in num]
        return {**base, "status": "absent", "message": f"{', '.join(missing)} did not start"}
    a, b = int(num[a_code]), int(num[b_code])
    laps = sd.base_lap_table(s.id)
    try:
        weather = src.weather(s)
    except DataUnavailable:
        weather = None
    model = fit_session_model(laps, a, b, True, weather)
    st = sd.strategy(s.id, a, b)
    order = st["order"]
    out = {**base, "status": "ok", "a_number": a, "b_number": b,
           "conditions": model.get("conditions", "dry") if model.get("ok") else "unknown",
           "finish": {"a": order.index(a) + 1 if a in order else None, "b": order.index(b) + 1 if b in order else None},
           "stops": {"a": len(st["pit_stops"][str(a)]), "b": len(st["pit_stops"][str(b)])},
           "pace_gap": _paired_pace_gap(laps, a, b),
           "clean_laps": {"a": int(laps[(laps["driver_number"] == a) & laps["clean"]].shape[0]),
                          "b": int(laps[(laps["driver_number"] == b) & laps["clean"]].shape[0])},
           "model": None, "style": {}, "patterns": {}, "line": None}
    if model.get("ok"):
        out["model"] = {"lap_effect": model["lap_effect"], "field": model["field_tyre_slopes"],
                        "a": model["driver_tyre_slopes"]["A"]["compounds"], "b": model["driver_tyre_slopes"]["B"]["compounds"],
                        "warnings": model["warnings"]}
    caps = src.capabilities(s)
    if caps.telemetry and caps.position:
        for tag, d in (("a", a), ("b", b)):
            rows = pd.DataFrame(sd.style_rows(s.id, d, True))
            out["style"][tag] = {k: (round(float(rows[k].median()), 3) if k in rows and rows[k].notna().any() else None)
                                 for k in STYLE_KEYS}
            trends = sd.preservation(s.id, d, True)["zone_trends"]
            out["patterns"][tag] = {p: sum(t["pattern"] == p for t in trends) for p in PATTERNS}
        line = sd.line_comparison(s.id, a, b, True)
        sig = [r for r in line["rows"] if r["significant"]]
        labels = {z["id"]: z["label"] for z in line["zones"]}
        out["line"] = {"significant": [{"zone": labels[r["zone_id"]], "diff_m": r["diff_m"]} for r in sig],
                       "n_zones": len(line["rows"])}
    return out


def _metric_rows(summary: dict, a_code: str, b_code: str) -> pd.DataFrame:
    """Long-format metrics (one row per driver × metric) for the DuckDB season aggregate."""
    rows = []
    common = {"session_id": summary["session_id"], "round": summary["round"], "conditions": summary["conditions"]}
    for tag, code in (("a", a_code), ("b", b_code)):
        for k, v in (summary.get("style", {}).get(tag) or {}).items():
            if v is not None:
                rows.append({**common, "driver": code, "metric": k, "value": float(v)})
        for comp, c in ((summary.get("model") or {}).get(tag) or {}).items():
            rows.append({**common, "driver": code, "metric": f"tyre_cost_{comp}", "value": float(c["estimate"])})
        pats = (summary.get("patterns") or {}).get(tag) or {}
        decided = pats.get("consistent_with_management", 0) + pats.get("consistent_with_grip_loss", 0)
        if decided:
            rows.append({**common, "driver": code, "metric": "management_share",
                         "value": pats.get("consistent_with_management", 0) / decided})
    if summary.get("pace_gap"):
        rows.append({**common, "driver": b_code, "metric": "pace_gap_vs_a", "value": float(summary["pace_gap"]["median_s"])})
    return pd.DataFrame(rows)


def aggregate(year: int, a_code: str, b_code: str, include_wet: bool) -> list[dict]:
    """Season medians per driver and metric, computed by DuckDB over the per-race Parquet files."""
    files = sorted(_pair_dir(year, a_code, b_code).glob("*.parquet"))
    if not files:
        return []
    cond = "" if include_wet else "WHERE conditions = 'dry'"
    q = f"""
        SELECT driver, metric, median(value) AS median, avg(value) AS mean, count(*) AS races
        FROM read_parquet({[str(f) for f in files]!r}, union_by_name = true)
        {cond}
        GROUP BY driver, metric
        ORDER BY metric, driver
    """
    df = duckdb.sql(q).df()
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in df.to_dict("records")]


def _load_cached(year: int, a_code: str, b_code: str, s) -> dict | None:
    path = _pair_dir(year, a_code, b_code) / f"{s.id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _store(year: int, a_code: str, b_code: str, summary: dict) -> None:
    d = _pair_dir(year, a_code, b_code)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{summary['session_id']}.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = _metric_rows(summary, a_code, b_code) if summary["status"] == "ok" else pd.DataFrame()
    if not rows.empty:
        rows.to_parquet(d / f"{summary['session_id']}.parquet", index=False)


def status(year: int, a_code: str, b_code: str) -> dict:
    with _lock:
        job = _jobs.get((year, a_code, b_code))
        return {k: v for k, v in job.items() if k != "thread"} if job else {"state": "not_started"}


def start(year: int, a_code: str, b_code: str) -> dict:
    key = (year, a_code, b_code)
    with _lock:
        if key in _jobs and _jobs[key]["state"] in ("running", "done"):
            return {k: v for k, v in _jobs[key].items() if k != "thread"}
        _jobs[key] = {"state": "running", "done": 0, "total": 0, "current": None, "races": []}

    def run():
        try:
            sessions = races(year)
            with _lock:
                _jobs[key]["total"] = len(sessions)
            for s in sessions:
                with _lock:
                    _jobs[key]["current"] = s.meeting_name
                summary = _load_cached(year, a_code, b_code, s)
                if summary is None:
                    try:
                        summary = race_summary(year, s, a_code, b_code)
                    except Exception as exc:  # one bad race must not stop the season
                        log.exception("season summary failed for %s", s.id)
                        summary = {"session_id": s.id, "round": s.round, "meeting_name": s.meeting_name,
                                   "status": "error", "message": str(exc)[:200]}
                    if s.is_settled() and summary["status"] != "error":
                        _store(year, a_code, b_code, summary)
                with _lock:
                    _jobs[key]["races"].append(summary)
                    _jobs[key]["done"] += 1
            with _lock:
                _jobs[key].update(state="done", current=None)
        except Exception as exc:
            log.exception("season job failed")
            with _lock:
                _jobs[key].update(state="failed", error=str(exc)[:200])

    t = threading.Thread(target=run, daemon=True, name=f"season-{year}-{a_code}-{b_code}")
    with _lock:
        _jobs[key]["thread"] = t
    t.start()
    return status(year, a_code, b_code)
