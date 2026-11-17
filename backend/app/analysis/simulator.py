"""Strategy what-if simulator, Stage A: lap-time maths (no traffic or overtaking).

A driver's race is rebuilt lap by lap: lap 1 is their real lap 1 (starts aren't modelled); every later lap comes
from the race model (analysis/race_model.py) for the compound and tyre age the chosen strategy implies; each stop
adds a pit loss. Laps that were neutralised in the real race (SC/VSC/red) keep the field's real lap time on that lap,
and scenario SC/VSC laps are slowed by the ratio measured in this race (or an assumed one).

Uncertainty is Monte Carlo over the model coefficients (their covariance), AR(1) lap noise and pit-loss spread.
Comparisons reuse the same draws (common random numbers), so deltas between strategies aren't inflated by noise that
affects both equally. Positions rank the simulated finish time against the rest of the field's real finish times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd

from app.analysis.race_model import RaceModel

DRAWS = 2000
MIN_STINT = 5
EXTRAP_TOLERANCE = 2  # laps: in/out laps aren't in the clean-lap fit, so real stints run slightly past it
TOP_N = 10
# Used only when this race had no neutralised laps to measure from (ASSUMPTIONS, shown in the UI).
ASSUMED_SC_RATIO = 1.40
ASSUMED_VSC_RATIO = 1.30
ASSUMED_SC_LOSS_FACTOR = 0.60
ASSUMED_VSC_LOSS_FACTOR = 0.70
DRY = {"SOFT", "MEDIUM", "HARD"}
# Flag a plan when compound offsets supply at least this much of its time difference, and at least this share of it
# (analyst choices: ~1 s is a few times the lap-time noise accumulated over a stint comparison).
OFFSET_WARN_S = 1.0
OFFSET_WARN_SHARE = 0.5


@dataclass
class Stint:
    compound: str
    laps: int
    start_age: int = 0


@dataclass
class Scenario:
    sc: list[int] = field(default_factory=list)
    vsc: list[int] = field(default_factory=list)


@dataclass
class RaceContext:
    model: RaceModel
    total_laps: int
    codes: dict[int, str]
    lap1_cross: dict[int, float]          # time each car completed lap 1 (s, any common origin)
    finish: dict[int, tuple[int, float]]  # (laps completed, crossing time of last lap)
    neutral_time: dict[int, float]        # real neutralised laps → field median lap time
    own_neutral: dict[tuple[int, int], float]  # (driver, lap) → the driver's own real time on a neutralised lap, ex-stop
    red_laps: set[int]                    # laps under a red flag: tyre changes are free (sporting regulations)
    in_share: float                       # share of a stop's time loss that falls on the in-lap (rest on the out-lap)
    actual: dict[int, list[Stint]]
    real_cross: dict[int, np.ndarray]     # real crossing time at the end of laps 1..N (NaN where missing)
    pit_loss: dict[int, float]
    field_loss: float
    loss_sd: float
    mv_loss: dict[str, float] | None
    sc_ratio: float
    vsc_ratio: float
    ratio_measured: bool
    assumptions: list[str] = field(default_factory=list)


class StrategyError(ValueError):
    pass


def _model_pit_losses(model: RaceModel, laps: pd.DataFrame, stops: dict[int, list[dict]]) -> tuple[dict[int, list[float]], float]:
    """Pit loss = (real in-lap + out-lap) − (model's normal lap on those tyres for both laps).

    Measured against the model rather than neighbouring laps (which ran on other tyres and fuel), so it's exactly
    the time the simulator must add back for a stop. Stops under SC/VSC/red are skipped."""
    by_lap = laps.set_index(["driver_number", "lap_number"])
    out: dict[int, list[float]] = {}
    shares: list[float] = []
    for d, v in stops.items():
        for s in v:
            lap = s["lap"]
            if s["under_neutralisation"] or (d, lap) not in by_lap.index or (d, lap + 1) not in by_lap.index:
                continue
            rows, total, times = [], 0.0, []
            for k in (lap, lap + 1):
                r = by_lap.loc[(d, k)]
                if pd.isna(r["lap_time_s"]) or pd.isna(r["tyre_age"]) or r["compound"] not in model.compounds \
                        or d not in model.drivers:
                    break
                rows.append(model.row(d, r["compound"], float(r["tyre_age"]), k))
                total += float(r["lap_time_s"])
                times.append(float(r["lap_time_s"]))
            else:
                pred = model.predict(np.array(rows))
                loss = total - float(pred.sum())
                out.setdefault(d, []).append(loss)
                if loss > 5:
                    shares.append(float(np.clip((times[0] - pred[0]) / loss, 0, 1)))
    return out, (float(np.median(shares)) if shares else 0.5)


def build_context(model: RaceModel, laps: pd.DataFrame, cross: pd.DataFrame, stops: dict[int, list[dict]],
                  stints: list[dict], codes: dict[int, str], mv_loss: dict | None) -> RaceContext:
    total = int(cross["lap_number"].max())
    pit_laps = laps["is_pit_in"] | laps["is_pit_out"]
    neutral_flag = laps[["sc", "vsc", "red"]].any(axis=1)
    by_lap = laps.assign(neutral=neutral_flag, pit=pit_laps).groupby("lap_number")
    share = by_lap["neutral"].mean()
    neutral_laps = [int(n) for n, v in share.items() if v > 0.5 and 1 < n <= total]
    red_laps = {int(n) for n, v in by_lap["red"].mean().items() if v > 0.5}
    restart_laps = {n + 1 for n in red_laps if n + 1 not in red_laps and n + 1 <= total}
    neutral_laps = sorted(set(neutral_laps) | {n for n in restart_laps if n > 1})
    # Neutralised laps take the field's median crossing-to-crossing time, which (unlike lap_time_s) always exists and
    # includes red-flag stoppages. Pit laps are left out of the median.
    wide = cross.pivot_table(index="lap_number", columns="driver_number", values="t")
    step = wide.diff()
    pitting = set(zip(laps.loc[pit_laps, "lap_number"], laps.loc[pit_laps, "driver_number"]))
    neutral_time = {}
    for n in neutral_laps:
        if n in step.index:
            vals = [v for d, v in step.loc[n].items() if (n, d) not in pitting and np.isfinite(v)]
            if vals:
                neutral_time[n] = float(np.median(vals))

    clean_med = float(laps.loc[laps["clean"], "lap_time_s"].median())
    sc_l = [v for n, v in neutral_time.items() if laps[(laps["lap_number"] == n)]["sc"].mean() > 0.5]
    vsc_l = [v for n, v in neutral_time.items() if laps[(laps["lap_number"] == n)]["vsc"].mean() > 0.5]
    assumptions = []
    sc_ratio = float(np.median(sc_l)) / clean_med if sc_l else ASSUMED_SC_RATIO
    vsc_ratio = float(np.median(vsc_l)) / clean_med if vsc_l else ASSUMED_VSC_RATIO
    if not sc_l:
        assumptions.append(f"Safety-car laps assumed {ASSUMED_SC_RATIO:.2f}× a normal lap (no SC in this race to measure)")
    if not vsc_l:
        assumptions.append(f"VSC laps assumed {ASSUMED_VSC_RATIO:.2f}× a normal lap (no VSC in this race to measure)")

    losses, in_share = _model_pit_losses(model, laps, stops)
    every = [x for v in losses.values() for x in v]
    field_loss = float(np.median(every)) if every else (mv_loss or {}).get("normal", 22.0)
    if not every and not mv_loss:
        assumptions.append("Pit loss assumed 22 s (no measurable stops in this race)")
    loss_sd = float(np.std(every, ddof=1)) if len(every) >= 3 else 1.0

    lap1, finish = {}, {}
    for d, g in cross.groupby("driver_number"):
        g = g.sort_values("lap_number")
        if (g["lap_number"] == 1).any():
            lap1[int(d)] = float(g.loc[g["lap_number"] == 1, "t"].iloc[0])
        finish[int(d)] = (int(g["lap_number"].iloc[-1]), float(g["t"].iloc[-1]))

    actual = {}
    for s in sorted(stints, key=lambda x: (x["driver_number"], x["stint"])):
        actual.setdefault(s["driver_number"], []).append(
            Stint(s["compound"], s["lap_end"] - s["lap_start"] + 1, int(s["tyre_age_start"] or 0)))
    real_cross = {}
    for d, g in cross.groupby("driver_number"):
        arr = np.full(total, np.nan)
        for lap, tt in zip(g["lap_number"].astype(int), g["t"]):
            if 1 <= lap <= total:
                arr[lap - 1] = tt
        real_cross[int(d)] = arr
    ctx = RaceContext(model=model, total_laps=total, codes=codes, lap1_cross=lap1, finish=finish, neutral_time=neutral_time,
                      own_neutral={}, red_laps=red_laps, in_share=in_share, actual=actual, real_cross=real_cross,
                      pit_loss={d: float(np.median(v)) for d, v in losses.items() if v}, field_loss=field_loss,
                      loss_sd=loss_sd, mv_loss=mv_loss, sc_ratio=sc_ratio, vsc_ratio=vsc_ratio,
                      ratio_measured=bool(sc_l or vsc_l), assumptions=assumptions)
    for d, arr in real_cross.items():
        real_stops = set(_plan(ctx, actual[d])[2]) if d in actual and sum(s.laps for s in actual[d]) == total else set()
        for n in neutral_laps:
            step = arr[n - 1] - arr[n - 2]
            if np.isfinite(step):
                ctx.own_neutral[(d, n)] = float(step) - (_loss_for(ctx, d, n, Scenario()) if n in real_stops else 0.0)
    return ctx


# ---- validation and flags ---------------------------------------------------------------------------
def validate(ctx: RaceContext, driver: int, stints: list[Stint]) -> list[str]:
    """Raises StrategyError for impossible plans; returns warnings for allowed-but-questionable ones."""
    laps_done = ctx.finish.get(driver, (0, 0))[0]
    if driver not in ctx.model.drivers or driver not in ctx.lap1_cross:
        raise StrategyError(f"car {driver} has no modelled laps in this race")
    if laps_done < ctx.total_laps:
        raise StrategyError(f"car {driver} didn't complete the race distance ({laps_done}/{ctx.total_laps} laps)")
    if sum(s.laps for s in stints) != ctx.total_laps:
        raise StrategyError(f"stints cover {sum(s.laps for s in stints)} laps; the race was {ctx.total_laps}")
    if any(s.laps < 1 for s in stints):
        raise StrategyError("every stint needs at least one lap")
    unknown = {s.compound for s in stints} - set(ctx.model.compounds)
    if unknown:
        raise StrategyError(f"{', '.join(sorted(unknown))} wasn't raced here, so there's no data to model it")
    if all(s.compound in DRY for s in stints) and len({s.compound for s in stints}) < 2:
        raise StrategyError("dry races require at least two different compounds (sporting regulations)")
    warnings = [f"{c}: {ctx.model.reliability[c]}" for c in {s.compound for s in stints} if ctx.model.reliability.get(c)]
    used = pd.Series([s.compound for s in stints]).value_counts()
    most = pd.Series([s.compound for st in ctx.actual.values() for s in st]).value_counts()
    for c, n in used.items():
        if n > most.get(c, 0):
            warnings.append(f"{n} sets of {c}: more than any driver used in this race; the real tyre allocation isn't public")
    return warnings


def extrapolation_flags(ctx: RaceContext, driver: int, stints: list[Stint]) -> list[str]:
    code = ctx.codes.get(driver, str(driver))
    out = []
    for i, s in enumerate(stints, start=1):
        oldest = s.start_age + s.laps - 1
        own = ctx.model.own_max.get((driver, s.compound))
        fmax = ctx.model.field_max.get(s.compound, 0)
        if oldest > fmax + EXTRAP_TOLERANCE:
            out.append(f"Stint {i}: {s.compound} to {oldest} laps old is beyond any {s.compound} run in this race "
                       f"({fmax} laps): pure extrapolation")
        elif own is None:
            out.append(f"Stint {i}: {code} didn't run {s.compound} in this race, so the field's degradation is used")
        elif oldest > own + EXTRAP_TOLERANCE:
            out.append(f"Stint {i}: {s.compound} to {oldest} laps old; {code}'s longest {s.compound} run was {own} laps, "
                       "so the field's rate is used beyond that")
    return out


def offset_dependence(ctx: RaceContext, driver: int, stints: list[Stint], scenario: Scenario) -> dict:
    """How much of a plan's difference to the real strategy comes from the fitted compound offsets κ (point estimate).

    The offsets are the weakest part of the lap-time model: across 76 dry 2023–26 races they don't track practice pace
    (docs/TYRE_METHODOLOGY.md §10), so a plan that wins mostly because of them should not be trusted."""
    m = ctx.model
    plain = m.theta.copy()
    for name, i in m.index.items():
        if name.startswith("cmp:"):
            plain[i] = 0.0
    zero, no_loss = np.zeros((1, ctx.total_laps)), np.zeros((1, 3))

    def delta(theta: np.ndarray) -> float:
        a = simulate(ctx, driver, stints, scenario, theta[None, :], zero, no_loss)[0, -1]
        b = simulate(ctx, driver, ctx.actual[driver], scenario, theta[None, :], zero, no_loss)[0, -1]
        return float(a - b)

    full, without = delta(m.theta), delta(plain)
    effect = full - without
    flagged = abs(effect) >= OFFSET_WARN_S and abs(effect) >= OFFSET_WARN_SHARE * abs(full)
    return {"effect_s": round(effect, 2), "delta_without_offsets_s": round(without, 2), "flagged": bool(flagged),
            "message": (f"{effect:+.1f} s of this plan's {full:+.1f} s comes from fitted compound offsets, which don't "
                        f"match practice pace and aren't validated; without them it is {without:+.1f} s") if flagged else None}


# ---- simulation -------------------------------------------------------------------------------------
def _plan(ctx: RaceContext, stints: list[Stint]):
    """Per-lap compound and tyre age (index 0 = lap 1) and the in-laps where stops happen."""
    comp, age, stops = [], [], []
    lap = 1
    for i, s in enumerate(stints):
        for k in range(s.laps):
            comp.append(s.compound)
            age.append(s.start_age + k)
        lap += s.laps
        if i < len(stints) - 1:
            stops.append(lap - 1)
    return comp, age, stops


def _loss_for(ctx: RaceContext, driver: int, in_lap: int, scenario: Scenario) -> float:
    if in_lap in ctx.red_laps:
        return 0.0  # tyres may be changed for free while the race is suspended
    base = ctx.pit_loss.get(driver, ctx.field_loss)
    mv = ctx.mv_loss or {}
    if in_lap in scenario.sc or in_lap in ctx.neutral_time:
        return mv.get("sc", base * ASSUMED_SC_LOSS_FACTOR)
    if in_lap in scenario.vsc:
        return mv.get("vsc", base * ASSUMED_VSC_LOSS_FACTOR)
    return base


def simulate(ctx: RaceContext, driver: int, stints: list[Stint], scenario: Scenario,
             thetas: np.ndarray, noise: np.ndarray, loss_noise: np.ndarray) -> np.ndarray:
    """Cumulative race time at the end of every lap, shape (draws, laps). Column 0 is the real lap-1 crossing."""
    m = ctx.model
    comp, age, stops = _plan(ctx, stints)
    n = ctx.total_laps
    rows = np.array([m.row(driver, comp[i], age[i], i + 1) for i in range(1, n)])
    lap_t = m.predict(rows, thetas) + noise[:, 1:n]  # laps 2..n
    for idx in range(1, n):
        lap = idx + 1
        if (driver, lap) in ctx.own_neutral:
            lap_t[:, idx - 1] = ctx.own_neutral[(driver, lap)]
        elif lap in ctx.neutral_time:
            lap_t[:, idx - 1] = ctx.neutral_time[lap]
        elif lap in scenario.sc:
            lap_t[:, idx - 1] *= ctx.sc_ratio
        elif lap in scenario.vsc:
            lap_t[:, idx - 1] *= ctx.vsc_ratio
    for j, in_lap in enumerate(stops):
        loss = _loss_for(ctx, driver, in_lap, scenario) + loss_noise[:, j % loss_noise.shape[1]]
        share = ctx.in_share if in_lap + 1 <= n else 1.0
        if in_lap >= 2:
            lap_t[:, in_lap - 2] += loss * share
        if in_lap + 1 <= n:
            lap_t[:, in_lap - 1] += loss * (1 - share if in_lap >= 2 else 1.0)
    start = np.full((thetas.shape[0], 1), ctx.lap1_cross[driver])
    return np.concatenate([start, start + np.cumsum(lap_t, axis=1)], axis=1)


def _noise(ctx: RaceContext, draws: int, rng: np.random.Generator) -> np.ndarray:
    """AR(1) lap noise with the model's residual SD and autocorrelation."""
    rho, sd = ctx.model.rho, ctx.model.sigma
    e = np.empty((draws, ctx.total_laps))
    e[:, 0] = rng.normal(0, sd, draws)
    innov = rng.normal(0, sd * np.sqrt(1 - rho * rho), (draws, ctx.total_laps))
    for t in range(1, ctx.total_laps):
        e[:, t] = rho * e[:, t - 1] + innov[:, t]
    return e


def _interval(x: np.ndarray) -> dict:
    return {"median": round(float(np.median(x)), 2), "low": round(float(np.percentile(x, 5)), 2),
            "high": round(float(np.percentile(x, 95)), 2)}


def run(ctx: RaceContext, plans: dict[int, list[Stint]], scenario: Scenario, draws: int = DRAWS, seed: int = 7) -> dict:
    """Simulate one or two drivers' plans.

    Results are ANCHORED to the real race: what-if crossing time = real crossing time + (simulated plan − simulated
    real strategy), on the same random draws. The real strategy therefore reproduces the real race exactly, the
    model's own bias cancels, and the uncertainty shown is that of the modelled difference.
    """
    rng = np.random.default_rng(seed)
    thetas = ctx.model.draw(draws, rng)
    out = {"drivers": {}, "assumptions": ctx.assumptions + [
        "Lap 1 is each driver's real lap 1; starts aren't modelled",
        "No traffic, dirty air or overtaking (Stage A): a clean-air time comparison",
        "Drivers are assumed to drive the same way on a different strategy",
        "The rest of the field keeps its real race",
    ] + ([
        "A hypothetical safety car or VSC costs every car the same time, and other drivers don't change strategy for it",
    ] if scenario.sc or scenario.vsc else [])}
    anchored = {}
    for d, stints in plans.items():
        warnings = validate(ctx, d, stints)
        noise = _noise(ctx, draws, np.random.default_rng(seed + d))
        loss_noise = np.random.default_rng(seed + 1000 + d).normal(0, ctx.loss_sd, (draws, 3))
        sim = simulate(ctx, d, stints, scenario, thetas, noise, loss_noise)
        # A hypothetical SC/VSC slows everyone, so the plan is compared with the real strategy under the SAME scenario.
        base = simulate(ctx, d, ctx.actual[d], scenario, thetas, noise, loss_noise)
        anchored[d] = ctx.real_cross[d][None, :] + (sim - base)
        out["drivers"][str(d)] = {
            "code": ctx.codes.get(d), "stints": [s.__dict__ for s in stints],
            "delta_vs_actual_strategy": _interval(sim[:, -1] - base[:, -1]),
            "laps": np.round(np.diff(np.median(sim, axis=0)), 3).tolist(),
            "warnings": warnings, "extrapolation": extrapolation_flags(ctx, d, stints),
            "offset_dependence": offset_dependence(ctx, d, stints, scenario),
        }
    for d in plans:
        mine = anchored[d][:, -1]
        others = np.array([t for o, (n, t) in ctx.finish.items() if o not in plans and n >= ctx.total_laps])
        pos = 1 + (others[None, :] < mine[:, None]).sum(axis=1)
        for o in plans:
            if o != d:
                pos = pos + (anchored[o][:, -1] < mine).astype(int)
        vals, counts = np.unique(pos, return_counts=True)
        out["drivers"][str(d)]["position"] = {
            "median": int(np.median(pos)),
            "distribution": {int(v): round(float(c) / len(pos), 3) for v, c in zip(vals, counts)},
            "actual": int(1 + sum(t < ctx.finish[d][1] for o, (n, t) in ctx.finish.items() if o != d and n >= ctx.total_laps)),
        }
    if len(plans) == 2:
        a, b = list(plans)
        out["p_first_ahead"] = round(float(np.mean(anchored[a][:, -1] < anchored[b][:, -1])), 3)
        gap = anchored[b] - anchored[a]  # + = second driver behind
        out["gap_by_lap"] = {"median": np.round(np.median(gap, axis=0), 3).tolist(),
                             "low": np.round(np.percentile(gap, 5, axis=0), 3).tolist(),
                             "high": np.round(np.percentile(gap, 95, axis=0), 3).tolist(),
                             "actual": np.round(ctx.real_cross[b] - ctx.real_cross[a], 3).tolist()}
    return out


def backtest(ctx: RaceContext) -> dict:
    """Predicted (point estimate) vs real finish for every driver who completed the distance on their real strategy."""
    errors = {}
    zero = np.zeros((1, ctx.total_laps))
    for d, stints in ctx.actual.items():
        try:
            validate(ctx, d, stints)
        except StrategyError:
            continue
        sim = simulate(ctx, d, stints, Scenario(), ctx.model.theta[None, :], zero, np.zeros((1, 3)))
        errors[ctx.codes.get(d, str(d))] = round(float(sim[0, -1] - ctx.finish[d][1]), 2)
    vals = np.abs(list(errors.values()))
    return {"errors_s": errors, "median_abs_error_s": round(float(np.median(vals)), 2) if len(vals) else None,
            "n_drivers": len(errors)}


# ---- optimiser ------------------------------------------------------------------------------------------
def optimise(ctx: RaceContext, driver: int, max_stops: int, scenario: Scenario, top_n: int = TOP_N) -> dict:
    """Enumerate 1..max_stops-stop plans on new tyres, rank by expected race time (closed form), then Monte Carlo
    the best TOP_N. Stints are at least MIN_STINT laps."""
    m = ctx.model
    n = ctx.total_laps
    comps = [c for c in m.compounds if c in DRY and not m.reliability.get(c)]
    if len(comps) < 2:
        raise StrategyError("fewer than two compounds have reliable data in this race, so no valid plan can be ranked")
    laps_idx = np.arange(1, n + 1)
    fixed = np.array([lap == 1 or lap in ctx.neutral_time for lap in laps_idx])
    scale = np.where(np.isin(laps_idx, scenario.sc), ctx.sc_ratio, np.where(np.isin(laps_idx, scenario.vsc), ctx.vsc_ratio, 1.0))

    # Expected lap time for compound c at age k on lap l (driver-specific); stint cost S[c][a, b], laps a..b, new tyres.
    S = {}
    for c in comps:
        cost = np.full((n + 2, n + 2), np.inf)
        for a in range(1, n + 1):
            ages = np.arange(0, n - a + 1)
            rows = np.array([m.row(driver, c, k, a + k) for k in ages])
            t = m.predict(rows) * scale[a - 1:]
            t = np.where(fixed[a - 1:], 0.0, t)  # lap 1 and real neutralised laps cost the same on any plan
            cost[a, a:n + 1] = np.cumsum(t)
        S[c] = cost
    loss = np.array([_loss_for(ctx, driver, lap, scenario) for lap in range(0, n + 1)])

    cands: list[tuple[float, tuple, tuple]] = []
    for k in range(1, max_stops + 1):
        for seq in product(comps, repeat=k + 1):
            if len(set(seq)) < 2:
                continue
            ends = _stop_grid(n, k)
            if not len(ends):
                continue
            total = np.zeros(len(ends))
            starts = np.column_stack([np.ones(len(ends), int), ends + 1])
            finish = np.column_stack([ends, np.full(len(ends), n)])
            for i, c in enumerate(seq):
                total += S[c][starts[:, i], finish[:, i]]
            total += loss[ends].sum(axis=1)
            best = np.argsort(total)[:top_n]
            cands += [(float(total[j]), seq, tuple(int(x) for x in ends[j])) for j in best]
    cands.sort(key=lambda x: x[0])
    plans = []
    seen = set()
    for _, seq, ends in cands:
        edges = (0,) + ends + (n,)
        key = tuple(sorted((c, edges[i + 1] - edges[i]) for i, c in enumerate(seq)))
        if key in seen:
            continue
        seen.add(key)
        edges = (0,) + ends + (n,)
        plans.append([Stint(c, edges[i + 1] - edges[i]) for i, c in enumerate(seq)])
        if len(plans) >= top_n:
            break

    rng = np.random.default_rng(11)
    thetas = m.draw(DRAWS, rng)
    noise = _noise(ctx, DRAWS, np.random.default_rng(11 + driver))
    loss_noise = np.random.default_rng(1011 + driver).normal(0, ctx.loss_sd, (DRAWS, 3))
    base = simulate(ctx, driver, ctx.actual[driver], scenario, thetas, noise, loss_noise)[:, -1]
    ranked = []
    for p in plans:
        sim = simulate(ctx, driver, p, scenario, thetas, noise, loss_noise)[:, -1]
        ranked.append({"stints": [s.__dict__ for s in p], "stops": len(p) - 1,
                       "delta_vs_actual_strategy": _interval(sim - base),
                       "extrapolation": extrapolation_flags(ctx, driver, p),
                       "offset_dependence": offset_dependence(ctx, driver, p, scenario)})
    ranked.sort(key=lambda r: r["delta_vs_actual_strategy"]["median"])
    return {"driver": driver, "code": ctx.codes.get(driver), "max_stops": max_stops, "plans": ranked,
            "actual": [s.__dict__ for s in ctx.actual[driver]]}


def _stop_grid(n: int, k: int) -> np.ndarray:
    """All in-lap tuples (x1 < … < xk) with every stint ≥ MIN_STINT laps."""
    lo, hi = MIN_STINT, n - MIN_STINT
    if k == 1:
        return np.arange(lo, hi + 1).reshape(-1, 1)
    grids = np.meshgrid(*[np.arange(lo, hi + 1)] * k, indexing="ij")
    g = np.stack([x.ravel() for x in grids], axis=1)
    ok = np.all(np.diff(g, axis=1) >= MIN_STINT, axis=1) & (g[:, 0] >= MIN_STINT) & (n - g[:, -1] >= MIN_STINT)
    return g[ok]
