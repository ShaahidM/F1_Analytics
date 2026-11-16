"""Lap-time model for the strategy simulator (docs/TYRE_METHODOLOGY.md §7).

    lap_time = α_driver + κ_compound + γ·lap_number + β_c·age + q_c·age² [if it improves AIC]
               + δ_{d,c}·min(age, own_max_{d,c})

- α_driver: pace offset; κ: fresh-tyre offset per compound; γ: fuel burn + track evolution (common to all drivers).
- β_c, q_c: field degradation per compound. Beyond the oldest tyre seen in the race, the quadratic continues along
  its tangent (no invented acceleration).
- δ_{d,c}: a driver's deviation from the field slope, only within the ages they actually ran (beyond that the
  field slope carries on). Deviations are ridge-shrunk toward 0 with a Gaussian prior of SD DRIVER_SLOPE_PRIOR_SD,
  which keeps the model identifiable (every driver having a deviation is otherwise collinear with β_c) and stops a
  5-lap stint producing a wild slope. The prior SD is an ASSUMPTION.

Residuals get a lap-to-lap AR(1) estimate so the Monte Carlo noise is realistic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DRIVER_SLOPE_PRIOR_SD = 0.02  # s/lap: how far a driver's degradation typically differs from the field (assumption)
MIN_OWN_AGES = 4
QUAD_AIC_GAIN = 2.0
QUAD_MIN_LAPS = 100
# A compound is "reliable" for simulation only with enough independent data and a non-negative degradation slope.
# Hungary 2025 Softs (a few cars, early laps, heavy fuel) fitted −0.19 s/lap: tyres "getting faster" is confounding.
MIN_DRIVERS = 3
MIN_COMPOUND_LAPS = 40


@dataclass
class RaceModel:
    columns: list[str]
    theta: np.ndarray
    cov: np.ndarray
    sigma: float
    rho: float
    ref_compound: str
    compounds: list[str]
    drivers: list[int]
    quad: dict[str, bool]
    own_max: dict[tuple[int, str], int]
    field_max: dict[str, int]
    n: int
    r2: float
    reliability: dict[str, str | None] = field(default_factory=dict)  # compound → None if reliable, else the reason
    index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.index = {c: i for i, c in enumerate(self.columns)}

    # ---- design rows -----------------------------------------------------------------------------
    def _age_q(self, c: str, age: float) -> float:
        fmax = self.field_max.get(c, 0)
        if age <= fmax:
            return age * age
        return fmax * fmax + 2 * fmax * (age - fmax)  # tangent continuation beyond the data

    def row(self, driver: int, compound: str, age: float, lap: int) -> np.ndarray:
        x = np.zeros(len(self.columns))
        x[self.index[f"drv:{driver}"]] = 1.0
        if compound != self.ref_compound:
            x[self.index[f"cmp:{compound}"]] = 1.0
        x[self.index["lap"]] = lap
        x[self.index[f"slope:{compound}"]] = age
        if self.quad.get(compound):
            x[self.index[f"quad:{compound}"]] = self._age_q(compound, age)
        dev = f"dev:{driver}:{compound}"
        if dev in self.index:
            x[self.index[dev]] = min(age, self.own_max[(driver, compound)])
        return x

    def predict(self, rows: np.ndarray, thetas: np.ndarray | None = None) -> np.ndarray:
        """rows: (laps, p). thetas: (draws, p) or None for the point estimate. Returns (draws, laps) or (laps,)."""
        return rows @ self.theta if thetas is None else thetas @ rows.T

    def draw(self, k: int, rng: np.random.Generator) -> np.ndarray:
        return rng.multivariate_normal(self.theta, self.cov, size=k, method="eigh")

    def summary(self) -> dict:
        get = lambda name: float(self.theta[self.index[name]]) if name in self.index else None  # noqa: E731
        se = lambda name: float(np.sqrt(self.cov[self.index[name], self.index[name]])) if name in self.index else None  # noqa: E731
        return {
            "n_laps": self.n, "r2": round(self.r2, 3), "residual_sd": round(self.sigma, 3), "residual_ar1": round(self.rho, 3),
            "fuel_track_per_lap": {"estimate": round(get("lap"), 4), "se": round(se("lap"), 4)},
            "compounds": {c: {"offset": round(get(f"cmp:{c}") or 0.0, 3), "slope": round(get(f"slope:{c}"), 4),
                              "slope_se": round(se(f"slope:{c}"), 4), "quadratic": self.quad.get(c, False),
                              "oldest_tyre": self.field_max.get(c), "unreliable": self.reliability.get(c)}
                          for c in self.compounds},
            "driver_slope_prior_sd": DRIVER_SLOPE_PRIOR_SD,
        }


def _ols_aic(X: np.ndarray, y: np.ndarray) -> float:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    rss = float(np.sum((y - X @ beta) ** 2))
    rank = np.linalg.matrix_rank(X)
    return len(y) * np.log(rss / len(y)) + 2 * rank


def fit_race_model(laps: pd.DataFrame) -> RaceModel:
    """Fit on clean laps (traffic-flagged laps included, as in Model B) with known compound and tyre age."""
    df = laps[laps["clean"] & laps["compound"].notna() & laps["tyre_age"].notna() & laps["lap_time_s"].notna()].copy()
    df["tyre_age"] = df["tyre_age"].astype(float)
    df["driver_number"] = df["driver_number"].astype(int)
    if len(df) < 50:
        raise ValueError(f"only {len(df)} clean laps with tyre data; need 50+ to model the race")
    counts = df["compound"].value_counts()
    ref = counts.index[0]
    compounds = sorted(df["compound"].unique())
    drivers = sorted(df["driver_number"].unique())
    field_max = {c: int(df.loc[df["compound"] == c, "tyre_age"].max()) for c in compounds}
    own_ages = df.groupby(["driver_number", "compound"])["tyre_age"]
    own_max = {k: int(v) for k, v in own_ages.max().items()}
    devs = [k for k, n in own_ages.nunique().items() if n >= MIN_OWN_AGES]

    y = df["lap_time_s"].to_numpy(float)
    age = df["tyre_age"].to_numpy(float)
    comp = df["compound"].to_numpy()
    drv = df["driver_number"].to_numpy()

    base_cols: dict[str, np.ndarray] = {f"drv:{d}": (drv == d).astype(float) for d in drivers}
    for c in compounds:
        if c != ref:
            base_cols[f"cmp:{c}"] = (comp == c).astype(float)
    base_cols["lap"] = df["lap_number"].to_numpy(float)
    for c in compounds:
        base_cols[f"slope:{c}"] = np.where(comp == c, age, 0.0)

    # Quadratic per compound only if it lowers AIC (pooled OLS, no driver deviations).
    X0 = np.column_stack(list(base_cols.values()))
    quad = {}
    for c in compounds:
        q = np.where(comp == c, age * age, 0.0)
        rich = (comp == c).sum() >= QUAD_MIN_LAPS and len(set(drv[comp == c])) >= MIN_DRIVERS
        quad[c] = bool(rich and _ols_aic(np.column_stack([X0, q]), y) < _ols_aic(X0, y) - QUAD_AIC_GAIN)
        if quad[c]:
            base_cols[f"quad:{c}"] = q

    cols = dict(base_cols)
    for d, c in devs:
        cols[f"dev:{d}:{c}"] = np.where((drv == d) & (comp == c), np.minimum(age, own_max[(d, c)]), 0.0)
    names = list(cols)
    X = np.column_stack([cols[n] for n in names])
    keep = X.any(axis=0)
    X, names = X[:, keep], [n for n, k in zip(names, keep) if k]

    # Ridge on driver deviations only: λ = σ² / τ² (Gaussian prior on deviations).
    X_base = np.column_stack([v for n, v in zip(names, X.T) if not n.startswith("dev:")])
    b0, *_ = np.linalg.lstsq(X_base, y, rcond=None)
    sigma0 = float(np.std(y - X_base @ b0, ddof=X_base.shape[1]))
    lam = sigma0 ** 2 / DRIVER_SLOPE_PRIOR_SD ** 2
    D = np.diag([1.0 if n.startswith("dev:") else 0.0 for n in names])
    XtX = X.T @ X
    A = XtX + lam * D
    A_inv = np.linalg.pinv(A)
    theta = A_inv @ X.T @ y
    resid = y - X @ theta
    dof = len(y) - float(np.trace(X @ A_inv @ X.T))
    sigma = float(np.sqrt(np.sum(resid ** 2) / dof))
    cov = sigma ** 2 * A_inv @ XtX @ A_inv
    cov = (cov + cov.T) / 2

    # Lap-to-lap AR(1) of residuals within each driver's stint.
    df["resid"] = resid
    df = df.sort_values(["driver_number", "lap_number"])
    prev = df.groupby(["driver_number", "stint"])["resid"].shift(1)
    pair = df["resid"].notna() & prev.notna()
    rho = float(np.clip(np.corrcoef(df.loc[pair, "resid"], prev[pair])[0, 1], 0.0, 0.9)) if pair.sum() > 20 else 0.0

    r2 = 1 - float(np.sum(resid ** 2)) / float(np.sum((y - y.mean()) ** 2))
    reliability = {}
    for c in compounds:
        n_c, d_c = int((comp == c).sum()), len(set(drv[comp == c]))
        slope = float(theta[names.index(f"slope:{c}")])
        if d_c < MIN_DRIVERS or n_c < MIN_COMPOUND_LAPS:
            reliability[c] = f"only {d_c} driver(s) and {n_c} clean laps on {c}: too little data to model it"
        elif slope < 0:
            reliability[c] = (f"{c} appears to get faster with age ({slope:+.3f} s/lap), which signals confounding "
                              "(fuel or track evolution), not real tyre behaviour")
        else:
            reliability[c] = None
    return RaceModel(columns=names, theta=theta, cov=cov, sigma=sigma, rho=rho, ref_compound=ref, compounds=compounds,
                     drivers=drivers, quad=quad, own_max=own_max, field_max=field_max, n=len(y), r2=r2,
                     reliability=reliability)
