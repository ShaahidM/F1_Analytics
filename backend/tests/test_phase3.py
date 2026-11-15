"""Offline tests for the preservation pattern rules and Model B."""

import numpy as np
import pandas as pd

from app.analysis.model import fit_session_model
from app.analysis.preservation import classify


def _fit(slope, lo, hi):
    return {"slope": slope, "ci_low": lo, "ci_high": hi, "intercept": 0, "residual_sd": 0, "n": 10}


FLAT = _fit(0.0, -0.1, 0.1)


def _fits(**over):
    base = {k: FLAT for k in ("brake_onset_before_apex_m", "mean_decel_g", "min_speed_kmh", "exit_speed_kmh",
                              "throttle_ramp_m", "coast_m", "time_in_zone_s")}
    return {**base, **over}


def test_coasting_increase_reads_as_management():
    label, ev = classify(_fits(coast_m=_fit(2.0, 1.0, 3.0)), span=20)
    assert label == "consistent_with_management" and "coasting" in ev[0]


def test_falling_min_speed_reads_as_grip_loss():
    label, _ = classify(_fits(min_speed_kmh=_fit(-0.3, -0.5, -0.1)), span=20)
    assert label == "consistent_with_grip_loss"


def test_earlier_braking_with_falling_speed_is_not_management():
    label, _ = classify(_fits(brake_onset_before_apex_m=_fit(1.0, 0.5, 1.5), min_speed_kmh=_fit(-0.3, -0.5, -0.1)), span=20)
    assert label == "consistent_with_grip_loss"


def test_statistically_significant_but_tiny_change_is_ignored():
    # 0.05 km/h per lap over 10 laps = 0.5 km/h, below the 2 km/h practical threshold.
    label, _ = classify(_fits(min_speed_kmh=_fit(-0.05, -0.08, -0.02)), span=10)
    assert label == "no_clear_pattern"


def test_insufficient_fits():
    label, _ = classify({"coast_m": None, "min_speed_kmh": None}, span=10)
    assert label == "insufficient_data"


def test_model_b_recovers_fuel_and_tyre_effects():
    rng = np.random.default_rng(1)
    rows = []
    for d in range(1, 13):
        pit = 18 + d  # staggered stops identify the lap effect separately from tyre age
        for lap in range(2, 51):
            stint, start, comp = (1, 1, "MEDIUM") if lap <= pit else (2, pit + 1, "HARD")
            age = lap - start
            beta = 0.08 if comp == "MEDIUM" else 0.04
            if d == 1 and comp == "HARD":
                beta = 0.07  # driver A degrades faster on hards
            t = 90 + 0.1 * d - 0.06 * lap + beta * age + rng.normal(0, 0.05)
            rows.append({"driver_number": d, "lap_number": lap, "lap_time_s": t, "compound": comp, "tyre_age": age,
                         "stint": stint, "clean": True, "flags": [], "lap_start": pd.NaT})
    res = fit_session_model(pd.DataFrame(rows), 1, 2, include_flagged=True, weather=None)
    assert res["ok"]
    assert abs(res["lap_effect"]["estimate"] + 0.06) < 0.01
    assert abs(res["field_tyre_slopes"]["MEDIUM"]["estimate"] - 0.08) < 0.01
    a_hard = res["driver_tyre_slopes"]["A"]["compounds"]["HARD"]
    assert a_hard["ci_low"] < 0.07 < a_hard["ci_high"]


def test_session_conditions():
    from app.analysis.model import session_conditions

    dry = pd.DataFrame({"clean": True, "compound": ["MEDIUM"] * 10})
    inters = pd.DataFrame({"clean": True, "compound": ["INTERMEDIATE"] * 8 + ["MEDIUM"] * 2})
    rain = pd.DataFrame({"rainfall": [0] * 8 + [1] * 2})
    assert session_conditions(dry, None) == "dry"
    assert session_conditions(dry, rain) == "mixed"
    assert session_conditions(inters, None) == "wet"


def test_season_metric_rows_and_duckdb_aggregate(tmp_path, monkeypatch):
    from app.processing import season

    monkeypatch.setattr(season, "SEASON_DIR", tmp_path)
    for i, (cond, coast) in enumerate((("dry", 10.0), ("dry", 30.0), ("wet", 500.0)), start=1):
        summary = {"session_id": f"of-{i}", "round": i, "conditions": cond, "status": "ok",
                   "style": {"a": {"coast_m": coast}, "b": {"coast_m": 2 * coast}},
                   "model": {"a": {"HARD": {"estimate": 0.05}}, "b": {"HARD": {"estimate": 0.03}}},
                   "patterns": {"a": {"consistent_with_management": 1, "consistent_with_grip_loss": 3}},
                   "pace_gap": {"median_s": 0.2}}
        season._store(2024, "AAA", "BBB", summary)
    agg = {(r["driver"], r["metric"]): r for r in season.aggregate(2024, "AAA", "BBB", include_wet=False)}
    assert agg[("AAA", "coast_m")]["median"] == 20.0 and agg[("AAA", "coast_m")]["races"] == 2
    assert agg[("BBB", "coast_m")]["median"] == 40.0
    assert agg[("AAA", "management_share")]["median"] == 0.25
    assert agg[("BBB", "pace_gap_vs_a")]["races"] == 2
    wet = {(r["driver"], r["metric"]): r for r in season.aggregate(2024, "AAA", "BBB", include_wet=True)}
    assert wet[("AAA", "coast_m")]["races"] == 3
