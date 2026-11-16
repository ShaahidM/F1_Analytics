"""Strategy simulator Stage B: traffic and overtaking (docs/TYRE_METHODOLOGY.md §9).

Every car that isn't being simulated keeps its real crossing times. A simulated driver's free lap is their REAL lap
plus the modelled difference between the plan and their real strategy (Stage A), so the real plan replays the real
race exactly. When a what-if brings them past a car they did not pass at that point in reality, an overtaking trial
decides whether they get by; if not, they're held FOLLOW_GAP_S behind that car (running at its pace).

Pass probability comes from this race's own data: every time a car started a lap within 1 s of another on the same
lap (no pit stops, not neutralised), the pace advantage (model free-air lap time of the car ahead minus the car
behind) is paired with whether a pass happened by the line. A logistic curve is fitted with a weak Gaussian prior
(MAP + Laplace), so races with almost no passes (Monaco) still give a sensible, uncertain curve.

Not modelled (shown in the UI): cars behind being held up by the simulated car, other drivers reacting
strategically, DRS trains as a distinct effect, and tyre wear from following.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from app.analysis.simulator import RaceContext, Scenario, Stint, _interval, _noise, simulate, validate

FOLLOW_GAP_S = 0.3        # ASSUMPTION: how close behind a car you cross the line when you can't pass it
PASS_COST_S = 0.2         # ASSUMPTION: time lost making a pass
SC_TRAIN_GAP_S = 0.6      # ASSUMPTION: car-to-car gap when a hypothetical safety car bunches the field
BATTLE_GAP_S = 1.0
PRIOR_MEAN = np.array([-2.5, 2.0])  # logit P(pass) = a + b·advantage: ~8% at no advantage, rising ~2/s (weak prior)
PRIOR_SD = np.array([1.5, 1.5])


@dataclass
class Overtaking:
    a: float
    b: float
    cov: np.ndarray
    n_battles: int
    n_passes: int

    def p(self, adv: np.ndarray, a: np.ndarray | float | None = None, b: np.ndarray | float | None = None) -> np.ndarray:
        a = self.a if a is None else a
        b = self.b if b is None else b
        return 1.0 / (1.0 + np.exp(-(a + b * adv)))

    def advantage_for(self, prob: float) -> float | None:
        """Pace advantage (s/lap) needed for a given pass probability."""
        if self.b <= 0:
            return None
        return float((np.log(prob / (1 - prob)) - self.a) / self.b)

    def summary(self) -> dict:
        return {"n_battles": self.n_battles, "n_passes": self.n_passes, "a": round(self.a, 3), "b": round(self.b, 3),
                "pass_chance_no_advantage": round(float(self.p(0.0)), 3),
                "advantage_for_50pct_s": None if self.advantage_for(0.5) is None else round(self.advantage_for(0.5), 2),
                "prior": {"mean": PRIOR_MEAN.tolist(), "sd": PRIOR_SD.tolist()}}


def _free_pace(ctx: RaceContext, d: int, lap: int) -> float | None:
    """Model free-air lap time for car d on its real tyres at `lap` (point estimate)."""
    stints = ctx.actual.get(d)
    if not stints or d not in ctx.model.drivers:
        return None
    k = lap
    for s in stints:
        if k <= s.laps:
            return float(ctx.model.predict(ctx.model.row(d, s.compound, s.start_age + k - 1, lap)[None, :])[0])
        k -= s.laps
    return None


def _real_stop_laps(ctx: RaceContext, d: int) -> set[int]:
    """In-laps and out-laps of a driver's real stops (these laps aren't battles: time is lost in the pits)."""
    out, lap = set(), 0
    for s in ctx.actual.get(d, [])[:-1]:
        lap += s.laps
        out |= {lap, lap + 1}
    return out


def estimate_overtaking(ctx: RaceContext) -> Overtaking:
    drivers = [d for d in ctx.real_cross if d in ctx.actual]
    pit = {d: _real_stop_laps(ctx, d) for d in drivers}
    adv, y = [], []
    for lap in range(3, ctx.total_laps + 1):
        if lap in ctx.neutral_time or lap - 1 in ctx.neutral_time or lap in ctx.red_laps:
            continue
        prev = {d: ctx.real_cross[d][lap - 2] for d in drivers}
        now = {d: ctx.real_cross[d][lap - 1] for d in drivers}
        order = sorted((t, d) for d, t in prev.items() if np.isfinite(t))
        for (t_ahead, ahead), (t_behind, behind) in zip(order, order[1:]):
            gap = t_behind - t_ahead
            if not 0 < gap < BATTLE_GAP_S or lap in pit[ahead] or lap in pit[behind]:
                continue
            if not (np.isfinite(now[ahead]) and np.isfinite(now[behind])):
                continue
            pa, pb = _free_pace(ctx, ahead, lap), _free_pace(ctx, behind, lap)
            if pa is None or pb is None:
                continue
            adv.append(pa - pb)  # positive = car behind is faster in free air
            y.append(1.0 if now[behind] < now[ahead] else 0.0)
    x, yy = np.array(adv), np.array(y)

    def nll(w):
        z = w[0] + w[1] * x
        ll = np.sum(yy * z - np.logaddexp(0, z)) if len(x) else 0.0
        return -ll + 0.5 * np.sum(((w - PRIOR_MEAN) / PRIOR_SD) ** 2)

    res = minimize(nll, PRIOR_MEAN, method="BFGS")
    w = res.x
    p = 1 / (1 + np.exp(-(w[0] + w[1] * x))) if len(x) else np.array([])
    X = np.column_stack([np.ones_like(x), x]) if len(x) else np.zeros((0, 2))
    H = (X.T * (p * (1 - p))) @ X + np.diag(1 / PRIOR_SD ** 2)  # Laplace approximation
    return Overtaking(a=float(w[0]), b=float(w[1]), cov=np.linalg.inv(H), n_battles=len(x), n_passes=int(yy.sum()))


def _compress_after_sc(times: dict[int, np.ndarray], sc_laps: list[int]) -> dict[int, np.ndarray]:
    """Hypothetical SC: at the end of each SC block, close every car on the lead lap up to SC_TRAIN_GAP_S apart."""
    if not sc_laps:
        return times
    out = {d: t.copy() for d, t in times.items()}
    ends = [l for l in sorted(sc_laps) if l + 1 not in sc_laps]
    for end in ends:
        col = end - 1
        draws = next(iter(out.values())).shape[0]
        for k in range(draws):
            row = sorted((t[k, col], d) for d, t in out.items() if np.isfinite(t[k, col]))
            if not row:
                continue
            leader = row[0][0]
            for rank, (t, d) in enumerate(row):
                shift = t - (leader + rank * SC_TRAIN_GAP_S)
                if shift > 0:
                    out[d][k, col:] -= shift
    return out


def run_with_traffic(ctx: RaceContext, ov: Overtaking, plans: dict[int, list[Stint]], scenario: Scenario,
                     draws: int = 400, seed: int = 7) -> dict:
    """Stage B: like simulator.run, but simulated drivers can be held up by (and must overtake) the real field."""
    rng = np.random.default_rng(seed)
    thetas = ctx.model.draw(draws, rng)
    w = rng.multivariate_normal([ov.a, ov.b], ov.cov, size=draws)  # overtaking-curve uncertainty per draw
    n = ctx.total_laps
    field = {d: np.tile(t, (draws, 1)) for d, t in ctx.real_cross.items() if d not in plans and np.isfinite(t[-1])}
    field = _compress_after_sc(field, scenario.sc)
    real_lap = {d: np.diff(ctx.real_cross[d]) for d in plans}
    free = {}
    for d, stints in plans.items():
        validate(ctx, d, stints)
        noise = _noise(ctx, draws, np.random.default_rng(seed + d))
        loss_noise = np.random.default_rng(seed + 1000 + d).normal(0, ctx.loss_sd, (draws, 3))
        sim = simulate(ctx, d, stints, scenario, thetas, noise, loss_noise)
        base = simulate(ctx, d, ctx.actual[d], scenario, thetas, noise, loss_noise)
        free[d] = real_lap[d][None, :] + (np.diff(sim, axis=1) - np.diff(base, axis=1))  # anchored free laps 2..n
    plan_pits = {d: _stop_laps(stints) for d, stints in plans.items()}
    real_pits = {d: _real_stop_laps(ctx, d) for d in ctx.real_cross}
    neutral = set(ctx.neutral_time) | set(scenario.sc) | set(scenario.vsc) | ctx.red_laps
    u = np.random.default_rng(seed + 99).random((draws, n, len(ctx.real_cross) + 2))

    T = {d: np.full((draws, n), np.nan) for d in plans}
    for d in plans:
        T[d][:, 0] = ctx.real_cross[d][0]
    held = {d: np.zeros(draws) for d in plans}
    passes = {d: np.zeros(draws) for d in plans}
    car_idx = {d: i for i, d in enumerate(ctx.real_cross)}
    for lap in range(2, n + 1):
        c = lap - 1
        # Process the simulated drivers front to back so the one ahead acts as an obstacle for the other.
        order = sorted(plans, key=lambda d: float(np.nanmedian(T[d][:, c - 1])))
        for d in order:
            prev = T[d][:, c - 1]
            t = prev + free[d][:, c - 1]
            blocked = np.zeros(draws, bool)
            obstacles = [(o, field[o]) for o in field] + [(o, T[o]) for o in plans if o != d and o in order[:order.index(d)]]
            for o, R in sorted(obstacles, key=lambda x: -float(np.nanmedian(x[1][:, c]))):
                ahead_prev, ahead_now = R[:, c - 1], R[:, c]
                trying = ~blocked & (prev > ahead_prev) & (t < ahead_now)
                if o in ctx.real_cross and d in ctx.real_cross:
                    really_passed = (ctx.real_cross[d][c - 1] > ctx.real_cross[o][c - 1]) and (ctx.real_cross[d][c] < ctx.real_cross[o][c])
                    if really_passed:
                        trying &= False  # the real race already contains this pass (field car or the other driver)
                if not trying.any():
                    continue
                if lap in neutral:
                    ok = np.zeros(draws, bool)
                elif lap in real_pits.get(o, set()) or lap in plan_pits.get(o, set()) or lap in plan_pits[d]:
                    ok = np.ones(draws, bool)  # position changes through the pits aren't overtakes
                else:
                    adv = (ahead_now - ahead_prev) - free[d][:, c - 1]
                    ok = u[:, c, car_idx.get(o, len(ctx.real_cross)) % u.shape[2]] < ov.p(adv, w[:, 0], w[:, 1])
                fail = trying & ~ok
                t = np.where(fail, np.maximum(t, ahead_now + FOLLOW_GAP_S), t)
                t = np.where(trying & ok & (lap not in neutral), t + PASS_COST_S, t)
                held[d] += fail
                passes[d] += trying & ok
                blocked |= fail
            T[d][:, c] = t
        if lap in scenario.sc and lap + 1 not in scenario.sc:
            # Bunch the simulated drivers with the field at the end of a hypothetical SC.
            merged = _compress_after_sc({**{o: R[:, :] for o, R in field.items()}, **T}, [lap])
            for d in plans:
                T[d][:, c:] = merged[d][:, c:]

    out = {"drivers": {}, "overtaking": ov.summary(), "assumptions": ctx.assumptions + [
        "Lap 1 is each driver's real lap 1; starts aren't modelled",
        "The rest of the field keeps its real race and isn't held up by the simulated driver",
        f"A car that can't pass crosses the line {FOLLOW_GAP_S} s behind the car ahead; a pass costs {PASS_COST_S} s",
        "Pass chance follows a curve fitted to this race's on-track battles (pace advantage vs passes)",
        "Drivers are assumed to drive the same way on a different strategy",
    ] + ([f"A hypothetical safety car bunches the field to {SC_TRAIN_GAP_S} s gaps; other drivers don't change strategy"]
         if scenario.sc else [])}
    finals = {d: T[d][:, -1] for d in plans}
    for d, stints in plans.items():
        others = np.column_stack([R[:, -1] for R in field.values()]) if field else np.zeros((draws, 0))
        pos = 1 + (others < finals[d][:, None]).sum(axis=1)
        for o in plans:
            if o != d:
                pos = pos + (finals[o] < finals[d]).astype(int)
        vals, counts = np.unique(pos, return_counts=True)
        out["drivers"][str(d)] = {
            "code": ctx.codes.get(d), "stints": [s.__dict__ for s in stints],
            "delta_vs_actual_strategy": _interval(finals[d] - ctx.real_cross[d][-1]),
            "position": {"median": int(np.median(pos)),
                         "distribution": {int(v): round(float(k) / draws, 3) for v, k in zip(vals, counts)},
                         "actual": int(1 + sum(t < ctx.finish[d][1] for o, (m, t) in ctx.finish.items()
                                               if o != d and m >= ctx.total_laps))},
            "traffic": {"laps_held_median": float(np.median(held[d])), "passes_median": float(np.median(passes[d]))},
            "warnings": [], "extrapolation": [],
        }
    if len(plans) == 2:
        a, b = list(plans)
        out["p_first_ahead"] = round(float(np.mean(finals[a] < finals[b])), 3)
        gap = T[b] - T[a]
        out["gap_by_lap"] = {"median": np.round(np.median(gap, axis=0), 3).tolist(),
                             "low": np.round(np.percentile(gap, 5, axis=0), 3).tolist(),
                             "high": np.round(np.percentile(gap, 95, axis=0), 3).tolist(),
                             "actual": np.round(ctx.real_cross[b] - ctx.real_cross[a], 3).tolist()}
    return out


def _stop_laps(stints: list[Stint]) -> set[int]:
    out, lap = set(), 0
    for s in stints[:-1]:
        lap += s.laps
        out |= {lap, lap + 1}
    return out
