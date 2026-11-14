"""Synthetic on-track traffic: a fast car catches, then laps, a slow car on a circular track."""

import numpy as np
import pandas as pd

from app.processing import traffic
from app.processing.reference import build_reference
from app.sources.base import SessionRef, SessionSource

R_UNITS = 5000.0  # 500 m radius
T0 = pd.Timestamp("2024-01-01T12:00:00Z")


class FakeSource(SessionSource):
    def __init__(self, pos):
        self.pos = pos

    def position_data(self, s, driver_number):
        return self.pos[driver_number]


def _car(speed_ms, start_m, duration_s=400.0, dt=0.25):
    L = 2 * np.pi * 500.0
    t = np.arange(0, duration_s, dt)
    d = start_m + speed_ms * t
    th = 2 * np.pi * (d % L) / L
    pos = pd.DataFrame({"date": T0 + pd.to_timedelta(t, unit="s"), "x": R_UNITS * np.cos(th), "y": R_UNITS * np.sin(th), "z": 0.0})
    laps = []
    k = 1
    while True:  # lap k starts when d crosses (k-1)·L
        ts = ((k - 1) * L - start_m) / speed_ms
        te = (k * L - start_m) / speed_ms
        if te > duration_s:
            break
        if ts >= 0:
            laps.append({"lap_number": k, "lap_start": T0 + pd.Timedelta(seconds=ts), "lap_end": T0 + pd.Timedelta(seconds=te)})
        k += 1
    return pos, laps


def test_catch_then_lap_a_backmarker():
    fast, fast_laps = _car(60.0, 0.0)
    slow, slow_laps = _car(40.0, 300.0)
    ref = build_reference(fast, T0, T0 + pd.Timedelta(seconds=2 * np.pi * 500 / 60))
    laps = pd.DataFrame([{"driver_number": 1, **l} for l in fast_laps] + [{"driver_number": 2, **l} for l in slow_laps])
    s = SessionRef("x-1", "fake", 2024, 1, "", "", "", None, "", "Race", "Race", T0, T0)
    out = traffic.compute(FakeSource({1: fast, 2: slow}), s, ref, laps).set_index(["driver_number", "lap_number"])
    kinds = out.loc[1]["traffic_kind"]
    # Same lap at first ("racing"); after the pass the slow car is a lap down ("backmarker").
    assert "racing" in set(kinds) and "backmarker" in set(kinds)
    first_bm = kinds[kinds == "backmarker"].index.min()
    assert (kinds[kinds.index < first_bm] == "racing").all()
    assert out.loc[2]["being_lapped"].any()
