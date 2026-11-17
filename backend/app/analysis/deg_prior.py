"""Cross-race prior for field tyre degradation and fresh-tyre offsets (docs/TYRE_METHODOLOGY.md §10). ESTIMATED.

Learns, from every other dry race, what a compound's degradation slope (or its fresh-tyre offset vs Medium) is likely
to be at a given circuit, so `fit_race_model` has something better than "no idea" for compounds a race barely used.

    y = μ_compound + u_circuit + s_season + b·track_temp + ε,      y = 100 · value / typical lap time  (% of a lap)

- u_circuit and s_season are shrunk toward 0 (ridge = Gaussian random effects); μ_compound is not.
- Rows are weighted by 1 / (se² + τ²): se is the race fit's own standard error, τ² the race-to-race variance that
  no feature explains. Without τ² one tightly fitted race would dominate.
- The shrinkage strengths are chosen by leave-one-race-out error inside the training rows.
- The training table has only ~200 rows (one per race × compound), so this is deliberately a small model.

Targets are noisy and partly confounded (tyre age vs fuel burn within one race), so validation compares against
naive baselines on held-out races rather than against a ground truth: there is none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.analysis.race_model import MIN_COMPOUND_LAPS, MIN_DRIVERS

TARGETS = {"slope": ("slope", "slope_se"), "offset": ("offset_vs_medium", "offset_vs_medium_se")}
SHRINK_GRID = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0]  # prior precision of circuit / season effects, in units of 1/τ²
MIN_ROWS = 20


def training_rows(table: pd.DataFrame, target: str) -> pd.DataFrame:
    """Rows usable for a target, with y and se as % of the race's typical lap time. Compounds a race barely used
    (the same count thresholds as the simulator's reliability check) are left out: their fits are mostly noise.
    Negative slopes are kept, otherwise the prior would be biased upward."""
    value, se = TARGETS[target]
    df = table[(table["n_drivers"] >= MIN_DRIVERS) & (table["n_laps"] >= MIN_COMPOUND_LAPS)
               & table[value].notna() & table[se].notna()].copy()
    df["y"] = 100.0 * df[value].astype(float) / df["lap_time_s"]
    df["se"] = 100.0 * df[se].astype(float) / df["lap_time_s"]
    return df.reset_index(drop=True)


@dataclass
class PriorModel:
    target: str
    columns: list[str]
    coef: np.ndarray
    temp_mean: float
    temp_sd: float
    tau: float        # race-to-race SD not explained by se (% of lap)
    sd: float         # leave-one-race-out prediction error SD (% of lap): the prior's width
    shrink: float
    n_rows: int
    n_races: int
    feat_scale: dict[str, tuple[float, float]] = field(default_factory=dict)  # weekend feature → (mean, sd), % of lap

    def design(self, rows: pd.DataFrame) -> np.ndarray:
        return _design(rows, self.columns, self.temp_mean, self.temp_sd, self.feat_scale)

    def predict_pct(self, rows: pd.DataFrame) -> np.ndarray:
        return self.design(rows) @ self.coef

    def predict(self, compound: str, circuit_key, year: int, track_temp: float | None, lap_time_s: float,
                weekend: dict | None = None) -> dict | None:
        """Prior mean and SD in seconds (per lap of tyre age for slopes) for one compound at one race.
        weekend: this compound's pre-race features in seconds (missing ones count as average)."""
        if f"cmp:{compound}" not in self.columns:
            return None
        row = pd.DataFrame([{"compound": compound, "circuit_key": circuit_key, "year": year, "track_temp": track_temp,
                             "lap_time_s": lap_time_s, **{f: (weekend or {}).get(f) for f in self.feat_scale}}])
        scale = lap_time_s / 100.0
        return {"mean": float(self.predict_pct(row)[0]) * scale, "sd": self.sd * scale,
                "circuit_seen": f"cir:{circuit_key}" in self.columns}


def _pct(rows: pd.DataFrame, feature: str) -> pd.Series:
    return 100.0 * pd.to_numeric(rows[feature], errors="coerce") / rows["lap_time_s"].astype(float)


def _design(rows: pd.DataFrame, columns: list[str], temp_mean: float, temp_sd: float,
            feat_scale: dict[str, tuple[float, float]]) -> np.ndarray:
    X = np.zeros((len(rows), len(columns)))
    temp = ((rows["track_temp"].astype(float) - temp_mean) / temp_sd).fillna(0.0).to_numpy()
    keys = {"cmp": rows["compound"].astype(str).to_numpy(), "cir": rows["circuit_key"].astype(str).to_numpy(),
            "yr": rows["year"].astype(str).to_numpy()}
    for j, name in enumerate(columns):
        if name == "temp":
            X[:, j] = temp
        elif name.startswith("f:"):
            mean, sd = feat_scale[name[2:]]
            X[:, j] = ((_pct(rows, name[2:]) - mean) / sd).fillna(0.0).to_numpy()  # unknown → average
        else:
            kind, level = name.split(":", 1)
            X[:, j] = keys[kind] == level
    return X


def _solve(X: np.ndarray, y: np.ndarray, w: np.ndarray, penalty: np.ndarray) -> np.ndarray:
    A = (X * w[:, None]).T @ X + np.diag(penalty)
    return np.linalg.pinv(A) @ (X * w[:, None]).T @ y


def _loro(X: np.ndarray, y: np.ndarray, w: np.ndarray, penalty: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Leave-one-race-out predictions."""
    pred = np.empty(len(y))
    for g in np.unique(groups):
        test = groups == g
        pred[test] = X[test] @ _solve(X[~test], y[~test], w[~test], penalty)
    return pred


def fit_prior(table: pd.DataFrame, target: str = "slope", features: tuple[str, ...] = ()) -> PriorModel | None:
    """features: optional pre-race columns of the table (seconds), e.g. practice long-run slopes."""
    df = training_rows(table, target)
    if len(df) < MIN_ROWS or df["session_id"].nunique() < 5:
        return None
    y, se = df["y"].to_numpy(float), df["se"].to_numpy(float)
    groups = df["session_id"].to_numpy()

    # τ²: variance around the compound means beyond what the fits' own standard errors explain.
    resid = y - df.groupby("compound")["y"].transform("mean").to_numpy()
    tau2 = max(float(np.var(resid) - np.mean(se ** 2)), 0.25 * float(np.var(resid)), 1e-8)
    w = 1.0 / (se ** 2 + tau2)

    temp_mean = float(df["track_temp"].mean()) if df["track_temp"].notna().any() else 0.0
    temp_sd = float(df["track_temp"].std()) if df["track_temp"].notna().sum() > 2 else 1.0
    feat_scale = {}
    for f in features:
        v = _pct(df, f)
        if v.notna().sum() > 5 and v.std() > 0:
            feat_scale[f] = (float(v.mean()), float(v.std()))
    columns = ([f"cmp:{c}" for c in sorted(df["compound"].unique())] + ["temp"] + [f"f:{f}" for f in feat_scale]
               + [f"yr:{v}" for v in sorted(df["year"].unique())]
               + [f"cir:{k}" for k in sorted(df["circuit_key"].astype(str).unique())])
    X = _design(df, columns, temp_mean, temp_sd, feat_scale)
    shrunk = np.array([not n.startswith("cmp:") for n in columns], dtype=float)

    best = None
    for k in SHRINK_GRID:
        pred = _loro(X, y, w, shrunk * k / tau2, groups)
        err = float(np.sum(w * (y - pred) ** 2) / np.sum(w))
        if best is None or err < best[0]:
            best = (err, k, pred)
    _, k, pred = best
    coef = _solve(X, y, w, shrunk * k / tau2)
    return PriorModel(target=target, columns=columns, coef=coef, temp_mean=temp_mean, temp_sd=temp_sd,
                      tau=float(np.sqrt(tau2)), sd=float(np.sqrt(np.mean((y - pred) ** 2))), shrink=k,
                      n_rows=len(df), n_races=int(df["session_id"].nunique()), feat_scale=feat_scale)


# ---- validation ---------------------------------------------------------------------------------------------
def _baselines(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Naive predictions for the test rows: the compound's mean, and the same circuit's most recent earlier race."""
    means = train.groupby("compound")["y"].mean()
    overall = float(train["y"].mean())
    by_mean = np.array([means.get(c, overall) for c in test["compound"]])
    last = by_mean.copy()
    for i, r in enumerate(test.itertuples()):
        prev = train[(train["circuit_key"] == r.circuit_key) & (train["compound"] == r.compound) & (train["year"] < r.year)]
        if len(prev):
            last[i] = prev.sort_values("year")["y"].iloc[-1]
    return by_mean, last


def validate_prior(table: pd.DataFrame, target: str = "slope", scheme: str = "loro",
                   features: tuple[str, ...] = ()) -> pd.DataFrame:
    """Held-out predictions (in seconds) for the prior and both baselines.
    scheme "loro": each race predicted from every other race. "forward": each season from the seasons before it."""
    df = training_rows(table, target)
    if scheme == "loro":
        folds = [(df["session_id"] != g, df["session_id"] == g) for g in df["session_id"].unique()]
    else:
        folds = [(df["year"] < yr, df["year"] == yr) for yr in sorted(df["year"].unique())[1:]]
    out = []
    for train_mask, test_mask in folds:
        train, test = df[train_mask], df[test_mask].copy()
        # the model re-filters its rows, so hand it table-shaped rows of the training races only
        model = fit_prior(table[table["session_id"].isin(train["session_id"])], target, features)
        if model is None or test.empty:
            continue
        scale = test["lap_time_s"].to_numpy() / 100.0
        by_mean, last = _baselines(train, test)
        test["actual"] = test["y"].to_numpy() * scale
        test["actual_se"] = test["se"].to_numpy() * scale
        test["pred_model"] = model.predict_pct(test) * scale
        test["pred_compound_mean"] = by_mean * scale
        test["pred_last_year"] = last * scale
        test["prior_sd"] = model.sd * scale
        out.append(test)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def validation_summary(preds: pd.DataFrame, n_boot: int = 2000, seed: int = 7) -> dict:
    """Mean absolute error per method, and the model's improvement over each baseline with a 90% interval from
    resampling whole races (rows of one race aren't independent)."""
    methods = ["pred_model", "pred_compound_mean", "pred_last_year"]
    err = {m: np.abs(preds[m] - preds["actual"]).to_numpy() for m in methods}
    out = {"n_rows": int(len(preds)), "n_races": int(preds["session_id"].nunique()),
           "mae": {m.removeprefix("pred_"): round(float(err[m].mean()), 4) for m in methods}}
    rng = np.random.default_rng(seed)
    races = preds["session_id"].to_numpy()
    idx = {g: np.flatnonzero(races == g) for g in np.unique(races)}
    names = list(idx)
    gains = {m: [] for m in methods[1:]}
    for _ in range(n_boot):
        rows = np.concatenate([idx[g] for g in rng.choice(names, size=len(names))])
        for m in methods[1:]:
            gains[m].append(err[m][rows].mean() - err["pred_model"][rows].mean())
    out["gain_vs"] = {m.removeprefix("pred_"): {"mean": round(float(np.mean(g)), 4),
                                                 "low": round(float(np.percentile(g, 5)), 4),
                                                 "high": round(float(np.percentile(g, 95)), 4)}
                      for m, g in gains.items()}
    z = (preds["actual"] - preds["pred_model"]) / np.sqrt(preds["prior_sd"] ** 2)
    out["coverage_90"] = round(float((np.abs(z) < 1.645).mean()), 3)  # should be ≈ 0.90 if the prior width is honest
    return out
