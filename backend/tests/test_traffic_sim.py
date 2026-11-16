"""Stage B traffic simulation on the synthetic race from test_simulator (known effects)."""

import numpy as np

from app.analysis.simulator import Scenario, Stint
from app.analysis.traffic_sim import Overtaking, estimate_overtaking, run_with_traffic
from tests.test_simulator import N, race

NEVER = Overtaking(a=-50.0, b=0.0, cov=np.eye(2) * 1e-9, n_battles=0, n_passes=0)
ALWAYS = Overtaking(a=50.0, b=0.0, cov=np.eye(2) * 1e-9, n_battles=0, n_passes=0)


def test_actual_strategy_replays_real_race_exactly():
    _, ctx = race(noise=0.05)
    d = 5
    r = run_with_traffic(ctx, NEVER, {d: ctx.actual[d]}, Scenario(), draws=50)
    delta = r["drivers"][str(d)]["delta_vs_actual_strategy"]
    assert abs(delta["median"]) < 1e-6 and abs(delta["low"]) < 1e-6 and abs(delta["high"]) < 1e-6


def test_two_drivers_on_real_strategies_replay_exactly():
    _, ctx = race(noise=0.05)
    r = run_with_traffic(ctx, NEVER, {3: ctx.actual[3], 4: ctx.actual[4]}, Scenario(), draws=30)
    for d in ("3", "4"):
        assert abs(r["drivers"][d]["delta_vs_actual_strategy"]["median"]) < 1e-6
    assert np.allclose(r["gap_by_lap"]["median"][1:], r["gap_by_lap"]["actual"][1:], atol=1e-6)


def test_faster_plan_is_held_when_passing_is_impossible():
    _, ctx = race(noise=0.0)
    d = 12  # slowest driver (highest base time) starting at the back
    faster = [Stint("MEDIUM", 20), Stint("HARD", N - 20)]
    clean = run_with_traffic(ctx, ALWAYS, {d: faster}, Scenario(), draws=20)["drivers"][str(d)]
    stuck = run_with_traffic(ctx, NEVER, {d: faster}, Scenario(), draws=20)["drivers"][str(d)]
    # With passing impossible the driver can't gain more than the clean-air plan allows, and never gains places.
    assert stuck["delta_vs_actual_strategy"]["median"] >= clean["delta_vs_actual_strategy"]["median"] - 1e-6
    assert stuck["position"]["median"] >= clean["position"]["median"]


def test_overtaking_estimate_is_finite_and_monotone():
    _, ctx = race(noise=0.1)
    ov = estimate_overtaking(ctx)
    assert np.isfinite(ov.a) and np.isfinite(ov.b) and ov.b > 0  # weak prior keeps the slope positive
    assert ov.p(1.0) > ov.p(0.0)
