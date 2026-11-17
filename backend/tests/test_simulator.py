"""Strategy simulator on a synthetic race with known fuel, tyre and pit-loss effects."""

import numpy as np
import pandas as pd
import pytest

from app.analysis.race_model import fit_race_model
from app.analysis.simulator import Scenario, Stint, StrategyError, backtest, build_context, optimise, run, simulate
from app.analysis.strategy import crossing_times, pit_stops, stints_table

N = 50
SLOPE = {"MEDIUM": 0.08, "HARD": 0.04}
OFFSET = {"MEDIUM": -0.3, "HARD": 0.0}
GAMMA = -0.05
IN_LOSS, OUT_LOSS = 8.0, 12.0  # pit loss = 20 s


def lap_time(d, comp, age, lap, rng, noise):
    return 90 + 0.1 * d + GAMMA * lap + OFFSET[comp] + SLOPE[comp] * age + (rng.normal(0, noise) if noise else 0.0)


def race(noise=0.0, one_compound_driver=False, seed=0):
    rng = np.random.default_rng(seed)
    rows, pits = [], []
    for d in range(1, 13):
        stop = 14 + d  # staggered stops identify fuel separately from tyre age
        for lap in range(1, N + 1):
            stint = 1 if lap <= stop else 2
            comp = "MEDIUM" if stint == 1 else "HARD"
            if one_compound_driver and d == 12:
                comp = "HARD"
            age = lap - 1 if stint == 1 else lap - stop - 1
            t = lap_time(d, comp, age, lap, rng, noise)
            t += IN_LOSS if lap == stop else OUT_LOSS if lap == stop + 1 else 0.0
            rows.append({"driver_number": d, "lap_number": lap, "lap_time_s": t, "compound": comp, "tyre_age": age,
                         "stint": stint, "is_pit_in": lap == stop, "is_pit_out": lap == stop + 1, "sc": False, "vsc": False,
                         "red": False, "lap_end": pd.NaT, "tyre_age_assumed": False, "flags": [[]][0]})
        pits.append({"driver_number": d, "lap_number": stop, "lane_duration_s": 18.0, "stop_duration_s": None})
    laps = pd.DataFrame(rows)
    laps["clean"] = ~(laps["is_pit_in"] | laps["is_pit_out"]) & (laps["lap_number"] > 1)
    pits = pd.DataFrame(pits)
    stops = {d: pit_stops(laps, pits, d) for d in range(1, 13)}
    model = fit_race_model(laps)
    ctx = build_context(model, laps, crossing_times(laps), stops, stints_table(laps), {d: f"D{d:02d}" for d in range(1, 13)}, None)
    return laps, ctx


def test_model_recovers_known_effects():
    _, ctx = race(noise=0.05)
    s = ctx.model.summary()
    assert abs(s["fuel_track_per_lap"]["estimate"] - GAMMA) < 0.01
    assert abs(s["compounds"]["MEDIUM"]["slope"] - SLOPE["MEDIUM"]) < 0.01
    assert abs(s["compounds"]["HARD"]["slope"] - SLOPE["HARD"]) < 0.01


def test_backtest_and_pit_loss_without_noise():
    _, ctx = race(noise=0.0)
    assert abs(ctx.field_loss - (IN_LOSS + OUT_LOSS)) < 0.5
    bt = backtest(ctx)
    assert bt["n_drivers"] == 12 and bt["median_abs_error_s"] < 0.5


def test_actual_strategy_reproduces_reality_and_delta_matches_maths():
    _, ctx = race(noise=0.0)
    d = 5
    r = run(ctx, {d: ctx.actual[d]}, Scenario(), draws=200)
    assert r["drivers"][str(d)]["delta_vs_actual_strategy"]["median"] == 0.0
    # Stopping 5 laps later swaps 5 laps of fresh hards for 5 extra laps of old mediums: compute it by hand.
    stop = 14 + d
    alt = [Stint("MEDIUM", stop + 5), Stint("HARD", N - stop - 5)]
    zero = np.zeros((1, N))
    sim_alt = simulate(ctx, d, alt, Scenario(), ctx.model.theta[None, :], zero, np.zeros((1, 3)))[0, -1]
    sim_act = simulate(ctx, d, ctx.actual[d], Scenario(), ctx.model.theta[None, :], zero, np.zeros((1, 3)))[0, -1]
    expected = 0.0
    for lap in range(2, N + 1):
        a_comp, a_age = ("MEDIUM", lap - 1) if lap <= stop + 5 else ("HARD", lap - stop - 6)
        b_comp, b_age = ("MEDIUM", lap - 1) if lap <= stop else ("HARD", lap - stop - 1)
        expected += (OFFSET[a_comp] + SLOPE[a_comp] * a_age) - (OFFSET[b_comp] + SLOPE[b_comp] * b_age)
    assert abs((sim_alt - sim_act) - expected) < 0.3


def test_rules_and_flags():
    _, ctx = race()
    with pytest.raises(StrategyError, match="two different compounds"):
        run(ctx, {3: [Stint("HARD", 20), Stint("HARD", 30)]}, Scenario(), draws=50)
    with pytest.raises(StrategyError, match="race was 50"):
        run(ctx, {3: [Stint("MEDIUM", 10), Stint("HARD", 10)]}, Scenario(), draws=50)
    r = run(ctx, {3: [Stint("MEDIUM", 45), Stint("HARD", 5)]}, Scenario(), draws=50)
    assert any("longest MEDIUM run" in f or "beyond any MEDIUM" in f for f in r["drivers"]["3"]["extrapolation"])


def test_optimiser_matches_brute_force_one_stop():
    _, ctx = race(noise=0.0)
    d = 4
    zero = np.zeros((1, N))
    best = None
    for stop in range(5, N - 4):
        for seq in (("MEDIUM", "HARD"), ("HARD", "MEDIUM")):
            plan = [Stint(seq[0], stop), Stint(seq[1], N - stop)]
            t = simulate(ctx, d, plan, Scenario(), ctx.model.theta[None, :], zero, np.zeros((1, 3)))[0, -1]
            if best is None or t < best[0]:
                best = (t, plan)
    top = optimise(ctx, d, 1, Scenario())["plans"][0]["stints"]
    assert [(s["compound"], s["laps"]) for s in top] == [(s.compound, s.laps) for s in best[1]]


def test_cheaper_stop_under_safety_car():
    _, ctx = race(noise=0.0)
    d = 6
    stop = 14 + d
    later = [Stint("MEDIUM", stop + 10), Stint("HARD", N - stop - 10)]
    sc = Scenario(sc=[stop + 10])
    with_sc = run(ctx, {d: later}, sc, draws=100)["drivers"][str(d)]["delta_vs_actual_strategy"]["median"]
    without = run(ctx, {d: later}, Scenario(), draws=100)["drivers"][str(d)]["delta_vs_actual_strategy"]["median"]
    assert with_sc < without  # pitting under the safety car is cheaper


def test_rank_deficiency_guard_single_compound_driver():
    _, ctx = race(noise=0.05, one_compound_driver=True)
    assert np.all(np.isfinite(ctx.model.theta)) and np.all(np.isfinite(ctx.model.cov))


def test_offset_dependence_isolates_the_compound_offsets(monkeypatch):
    import app.analysis.simulator as sim_mod
    _, ctx = race(noise=0.0)
    d = 5
    stop = 14 + d
    act = sim_mod.offset_dependence(ctx, d, ctx.actual[d], Scenario())
    assert act["effect_s"] == 0.0 and not act["flagged"] and act["message"] is None
    # 5 more Medium laps instead of Hard: the offset part is 5 × (MEDIUM − HARD offset), whatever the tyre-age part is.
    alt = [Stint("MEDIUM", stop + 5), Stint("HARD", N - stop - 5)]
    dep = sim_mod.offset_dependence(ctx, d, alt, Scenario())
    assert abs(dep["effect_s"] - 5 * (OFFSET["MEDIUM"] - OFFSET["HARD"])) < 0.3
    monkeypatch.setattr(sim_mod, "OFFSET_WARN_SHARE", 0.0)
    flagged = sim_mod.offset_dependence(ctx, d, alt, Scenario())
    assert flagged["flagged"] and "compound offsets" in flagged["message"]
    r = run(ctx, {d: alt}, Scenario(), draws=50)["drivers"][str(d)]
    assert "offset_dependence" in r
    assert "offset_dependence" in optimise(ctx, d, 1, Scenario())["plans"][0]
