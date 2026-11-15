"""Offline tests for corner metrics, stint derivation and the Model A trend fit."""

import numpy as np
import pandas as pd

from app.analysis.corners import Zone, build_zones, zone_metrics
from app.analysis.degradation import stint_trends
from app.processing.laps import _derive_stints_from_pits

G = 9.80665


def _synthetic_trace(decel_g=3.0, brake_at=400.0, grid=5.0, L=1500.0):
    """Straight at 300 km/h → constant decel to 100 km/h → accelerate back. Raw samples every 4 m."""
    s = np.arange(0.0, L, grid)
    v_hi, v_lo = 300 / 3.6, 100 / 3.6
    brake_len = (v_hi**2 - v_lo**2) / (2 * decel_g * G)
    apex = brake_at + brake_len

    def speed(x):
        x = np.asarray(x, float)
        v = np.full_like(x, v_hi)
        braking = (x >= brake_at) & (x < apex)
        v[braking] = np.sqrt(v_hi**2 - 2 * decel_g * G * (x[braking] - brake_at))
        after = x >= apex
        v[after] = np.minimum(v_hi, np.sqrt(v_lo**2 + 2 * 1.0 * G * (x[after] - apex)))
        return v * 3.6

    t = np.r_[0, np.cumsum(grid / (speed(s)[1:] / 3.6))]
    rs = np.arange(0.0, L, 4.0)
    rv = speed(rs)
    tr = {
        "grid_m": grid, "length_m": L, "s": s.tolist(), "t": t.tolist(), "speed": speed(s).tolist(),
        "throttle": np.where((s >= brake_at) & (s < apex), 0, 100).tolist(),
        "brake": np.where((s >= brake_at) & (s < apex), 1, 0).tolist(),
        "gear": np.full_like(s, 5).tolist(), "accel_g": np.zeros_like(s).tolist(),
        "raw": {"car": {"s": rs.tolist(), "speed": rv.tolist(),
                        "throttle": np.where((rs >= brake_at) & (rs < apex), 0, 100).tolist(),
                        "brake": np.where((rs >= brake_at) & (rs < apex), 100, 0).tolist()}},
    }
    return tr, apex


def test_zone_and_braking_metrics():
    tr, apex = _synthetic_trace()
    zones = build_zones(tr, [{"number": 1, "letter": "", "s": apex}])
    assert len(zones) == 1 and zones[0].kind == "braking" and zones[0].label == "T1"
    m = zone_metrics(tr, zones[0])
    assert abs(m["brake_onset_before_apex_m"] - (zones[0].apex_s - 400.0)) <= m["brake_onset_resolution_m"] + 0.5
    assert abs(m["mean_decel_g"] + 3.0) < 0.15
    assert abs(m["min_speed_kmh"] - 100) < 3


def test_flat_zone_has_no_braking():
    tr, apex = _synthetic_trace()
    z = Zone(1, "T9", ["T9"], "flat", 50.0, 150.0, 250.0)
    m = zone_metrics(tr, z)
    assert m["min_throttle_pct"] == 100 and "mean_decel_g" not in m


def test_derive_stints_from_pits():
    laps = pd.DataFrame({"driver_number": 1, "lap_number": range(1, 9),
                         "is_pit_in": [False, False, True, False, False, False, True, False]})
    d = _derive_stints_from_pits(laps)
    assert d["stint"].tolist() == [1, 1, 1, 2, 2, 2, 2, 3]
    assert d["tyre_age"].tolist() == [0, 1, 2, 0, 1, 2, 3, 0]
    assert d["tyre_age_assumed"].all()


def test_stint_trend_recovers_slope_and_fuel_assumption():
    n = 15
    laps = pd.DataFrame({
        "driver_number": 1, "stint": 1, "compound": "HARD", "lap_number": np.arange(10, 10 + n),
        "tyre_age": np.arange(n), "lap_time_s": 90 + 0.05 * np.arange(n), "clean": True,
        "flags": [[] for _ in range(n)], "s1_s": np.nan, "s2_s": np.nan, "s3_s": np.nan,
    })
    (st,) = stint_trends(laps, [1], include_flagged=False, fuel_s_per_lap=0.06)
    assert abs(st["raw_trend"]["slope"] - 0.05) < 1e-6
    assert abs(st["fuel_corrected_trend"]["slope"] - 0.11) < 1e-6


def test_long_run_detection():
    from app.processing.laps import long_run_mask

    # Stint 1: push / cool-down pattern, 5 push laps (no long run). Stint 2: 8-lap run with one slow lap in the
    # middle. Stint 3: 6-lap run followed by slow laps at the end of the session (still a long run).
    t1 = [80.0, 95.0, 80.2, 96.0, 80.1, 95.5, 80.3, 96.2, 80.2]
    t2 = [85.0, 85.2, 85.1, 91.0, 85.4, 85.6, 85.5, 85.9]
    t3 = [86.0, 86.1, 86.3, 86.2, 86.5, 86.4, 120.0, 140.0, 130.0, 125.0]
    n1, n2, n3 = len(t1), len(t2), len(t3)
    rows = pd.DataFrame({"driver_number": 1, "stint": [1] * n1 + [2] * n2 + [3] * n3, "lap_time_s": t1 + t2 + t3,
                         "lap_number": range(1, n1 + n2 + n3 + 1)})
    mask = long_run_mask(rows, np.ones(len(rows), dtype=bool))
    assert not mask[:n1].any()
    assert mask[n1:n1 + n2].tolist() == [True, True, True, False, True, True, True, True]
    assert mask[n1 + n2:].tolist() == [True] * 6 + [False] * 4
