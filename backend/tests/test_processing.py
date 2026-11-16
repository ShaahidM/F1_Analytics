"""Offline unit tests for the pure processing functions (no network)."""

import numpy as np
import pandas as pd
import pytest

from app.processing.compare import SelectionError, select_laps
from app.processing.reference import build_reference, project
from app.processing.telemetry import _accel_time_domain
from app.processing.track_status import deleted_laps, neutralisation_windows

T0 = pd.Timestamp("2024-01-01T12:00:00Z")


def _circle_pos(radius_units=5000.0, n=400, laps=1.0):
    th = np.linspace(0, 2 * np.pi * laps, int(n * laps), endpoint=False)
    dates = T0 + pd.to_timedelta(np.arange(len(th)) * 0.25, unit="s")
    return pd.DataFrame({"date": dates, "x": radius_units * np.cos(th), "y": radius_units * np.sin(th), "z": 0.0})


def test_reference_length_and_projection():
    pos = _circle_pos()
    ref = build_reference(pos, T0, T0 + pd.Timedelta(seconds=100))
    expected = 2 * np.pi * 500.0  # radius 5000 units = 500 m
    assert abs(ref.length_m - expected) / expected < 0.005
    # A point 2 m (20 units) outside the circle at a quarter lap: s ≈ L/4, lateral ≈ -2 m (right of CCW travel).
    s, lat = project(ref, np.array([0.0]), np.array([5020.0]))
    assert abs(s[0] - expected / 4) < 2.0
    assert abs(abs(lat[0]) - 2.0) < 0.2


def test_projection_guess_disambiguates():
    pos = _circle_pos()
    ref = build_reference(pos, T0, T0 + pd.Timedelta(seconds=100))
    s, _ = project(ref, np.array([5000.0]), np.array([0.0]), s_guess=np.array([3.0]))
    assert s[0] < 5 or s[0] > ref.length_m - 5


def _rc(rows):
    df = pd.DataFrame(rows, columns=["date", "category", "flag", "scope", "sector", "message"])
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def test_neutralisation_windows_and_deleted():
    rc = _rc([
        ("2024-01-01T12:00:00Z", "Flag", "YELLOW", "Sector", 5, "YELLOW IN TRACK SECTOR 5"),
        ("2024-01-01T12:00:30Z", "SafetyCar", None, None, None, "SAFETY CAR DEPLOYED"),
        ("2024-01-01T12:05:00Z", "SafetyCar", None, None, None, "SAFETY CAR IN THIS LAP"),
        ("2024-01-01T12:05:10Z", "Flag", "CLEAR", "Track", None, "TRACK CLEAR"),
        ("2024-01-01T12:10:00Z", "SafetyCar", None, None, None, "VIRTUAL SAFETY CAR DEPLOYED"),
        ("2024-01-01T12:11:00Z", "SafetyCar", None, None, None, "VIRTUAL SAFETY CAR ENDING"),
        ("2024-01-01T12:20:00Z", "Other", None, None, None, "CAR 1 (VER) TIME 1:24.107 DELETED - TRACK LIMITS AT TURN 13 LAP 47 16:29:18"),
        ("2024-01-01T12:21:00Z", "Other", None, None, None, "CAR 44 (HAM) TIME 1:25.000 DELETED - TRACK LIMITS AT TURN 4 LAP 10 16:30:00"),
        ("2024-01-01T12:22:00Z", "Other", None, None, None, "CAR 44 (HAM) TIME 1:25.000 REINSTATED LAP 10"),
    ])
    w = {x.kind: x for x in neutralisation_windows(rc, pd.Timedelta(seconds=90), T0 + pd.Timedelta(hours=2))}
    assert w["sc"].end == pd.Timestamp("2024-01-01T12:06:30Z")
    assert w["vsc"].end == pd.Timestamp("2024-01-01T12:11:20Z")
    assert w["yellow"].end == pd.Timestamp("2024-01-01T12:05:10Z")
    assert deleted_laps(rc) == {(1, 47)}


def test_accel_time_domain_constant():
    t = np.cumsum(np.r_[0, np.random.default_rng(0).uniform(0.16, 0.44, 40)])
    v = 100 + 3.6 * 9.80665 * 1.0 * t  # exactly +1 g
    a = _accel_time_domain(t, v)
    assert np.allclose(a[3:-3], 1.0, atol=1e-6)


def _laps():
    base = dict(lap_time_s=90.0, deleted=False, is_pit_out=False, is_pit_in=False, exclude_reasons=[], flags=[],
                clean=True, lap_start=T0, stint=1)
    rows = [
        {**base, "driver_number": 1, "lap_number": 5, "compound": "MEDIUM", "tyre_age": 4, "lap_time_s": 89.0},
        {**base, "driver_number": 1, "lap_number": 6, "compound": "MEDIUM", "tyre_age": 5},
        {**base, "driver_number": 2, "lap_number": 5, "compound": "HARD", "tyre_age": 10},
        {**base, "driver_number": 2, "lap_number": 20, "compound": "HARD", "tyre_age": 5, "lap_time_s": 88.0},
    ]
    return pd.DataFrame(rows)


def test_select_modes_and_comparability():
    laps = _laps()
    r = select_laps(laps, 1, 2, "fastest", True)
    assert (r["a"]["lap_number"], r["b"]["lap_number"]) == (5, 20)
    kinds = {d["kind"] for d in r["differences"]}
    assert {"compound", "fuel", "tyre_age"} <= kinds
    r = select_laps(laps, 1, 2, "same_tyre_age", True, tyre_age=5)
    assert (r["a"]["lap_number"], r["b"]["lap_number"]) == (6, 20)
    assert "tyre_age" not in {d["kind"] for d in r["differences"]}
    with pytest.raises(SelectionError):
        select_laps(laps, 1, 2, "same_lap", True)


def test_red_flag_closes_on_session_restart():
    rc = _rc([
        ("2024-01-01T12:00:00Z", "Flag", "RED", "Track", None, "RED FLAG"),
        ("2024-01-01T12:40:00Z", "SessionStatus", None, None, None, "SESSION STARTED"),
    ])
    (w,) = neutralisation_windows(rc, pd.Timedelta(seconds=90), T0 + pd.Timedelta(hours=3))
    assert w.kind == "red" and w.end == pd.Timestamp("2024-01-01T12:41:30Z")


def test_vsc_upgraded_to_safety_car_closes_vsc():
    rc = _rc([
        ("2024-01-01T12:00:00Z", "SafetyCar", None, None, None, "VIRTUAL SAFETY CAR DEPLOYED"),
        ("2024-01-01T12:04:00Z", "SafetyCar", None, None, None, "SAFETY CAR DEPLOYED"),
        ("2024-01-01T12:10:00Z", "SafetyCar", None, None, None, "SAFETY CAR IN THIS LAP"),
    ])
    w = {x.kind: x for x in neutralisation_windows(rc, pd.Timedelta(seconds=90), T0 + pd.Timedelta(hours=3))}
    assert w["vsc"].end == pd.Timestamp("2024-01-01T12:04:00Z")
    assert w["sc"].end == pd.Timestamp("2024-01-01T12:11:30Z")
