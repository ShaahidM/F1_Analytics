"""Offline tests for gaps, positions, pit-loss estimates and undercut detection."""

import pandas as pd

from app.analysis.strategy import crossing_times, pit_cycles, pit_stops, positions


def _laps(driver, times, pit_in=()):
    rows = []
    for i, t in enumerate(times, start=1):
        rows.append({"driver_number": driver, "lap_number": i, "lap_time_s": t, "lap_end": pd.NaT,
                     "is_pit_in": i in pit_in, "clean": i not in pit_in and (i - 1) not in pit_in,
                     "compound": "MEDIUM" if not pit_in or i <= min(pit_in) else "HARD", "tyre_age": i,
                     "sc": False, "vsc": False, "red": False})
    return rows


def test_undercut_detected_and_pit_loss_estimated():
    # Car 1 runs 0.5 s behind car 2, pits on lap 5 and gains 1.5 s/lap on fresh tyres while car 2 stays out to lap 7.
    base = 90.0
    t1 = [base + 0.1, base, base, base, base + 5, base + 20 - 1.5, base - 1.5, base - 1.5, base - 1.0, base]
    t2 = [base, base, base, base, base, base, base + 5, base + 20, base, base]
    laps = pd.DataFrame(_laps(1, t1, pit_in=(5,)) + _laps(2, t2, pit_in=(7,)))
    pits = pd.DataFrame({"driver_number": [1, 2], "lap_number": [5, 7], "lane_duration_s": [20.0, 20.0], "stop_duration_s": [2.5, 2.5]})
    cross = crossing_times(laps)
    stops = {1: pit_stops(laps, pits, 1), 2: pit_stops(laps, pits, 2)}
    assert abs(stops[2][0]["estimated_loss_s"] - 25.0) < 1e-6
    (cyc,) = pit_cycles(cross, stops, laps, 1, 2)
    assert cyc["first_stopper"] == 1 and cyc["gap_before_s"] > 0 > cyc["gap_after_s"]
    assert cyc["outcome"].startswith("undercut")
    assert cyc["lane_time_diff_s"] == 0.0


def test_positions_rank_crossing_order():
    laps = pd.DataFrame(_laps(1, [91, 90]) + _laps(2, [90, 92]))
    pos = positions(crossing_times(laps))
    p = pos.set_index(["driver_number", "lap_number"])["position"]
    assert p[(2, 1)] == 1 and p[(1, 2)] == 1
