"""Model B — session-wide fixed-effects regression (docs/TYRE_METHODOLOGY.md §4).

    lap_time = α_driver + γ·lap_number + Σ_c β_c·tyre_age·[compound=c]
               + Σ_c δ_{c,A}·tyre_age·[compound=c, driver=A] + (same for B) + θ·track_temp + ε

Within one stint tyre age and lap number rise together, so γ (fuel burn + track evolution, combined) is
identified only because tyre age resets at pit stops across the whole field. γ is ASSUMED common to all
drivers. Standard errors are heteroskedasticity-robust (HC3) but ignore lap-to-lap autocorrelation, so the
intervals are, if anything, too narrow.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

CI_LEVEL = 0.90
MIN_LAPS = 30

ASSUMPTIONS = [
    "Fuel-burn and track-evolution effect (γ) is linear in lap number and identical for every driver",
    "Tyre-age effect is linear within a compound",
    "Driver differences in pace are constant offsets except for the two selected drivers' tyre slopes",
    "Clean-lap filter removes SC/VSC/red, pit laps, lap 1, deleted laps and outliers; residual traffic effects remain",
]


def _attach_track_temp(laps: pd.DataFrame, weather: pd.DataFrame | None) -> pd.DataFrame:
    laps = laps.copy()
    laps["track_temp"] = np.nan
    if weather is None or weather.empty or "track_temperature" not in weather or laps["lap_start"].isna().all():
        return laps
    w = weather[["date", "track_temperature"]].dropna().sort_values("date")
    have = laps.loc[laps["lap_start"].notna(), ["lap_start"]].sort_values("lap_start").reset_index()
    merged = pd.merge_asof(have, w, left_on="lap_start", right_on="date", direction="nearest")
    laps.loc[merged["index"], "track_temp"] = merged["track_temperature"].to_numpy()
    return laps


def _combo(res, names: list[str]) -> tuple[float, float, float]:
    """Point estimate and CI of a sum of coefficients."""
    vec = np.zeros(len(res.params))
    for n in names:
        vec[list(res.params.index).index(n)] = 1.0
    est = float(vec @ res.params.to_numpy())
    se = float(np.sqrt(vec @ res.cov_params().to_numpy() @ vec))
    z = 1.6448536269514722  # 90% two-sided normal quantile
    return est, est - z * se, est + z * se


def fit_session_model(laps: pd.DataFrame, a: int, b: int, include_flagged: bool, weather: pd.DataFrame | None) -> dict:
    df = laps[laps["clean"] & laps["tyre_age"].notna() & laps["lap_time_s"].notna()].copy()
    if not include_flagged:
        df = df[df["flags"].map(len) == 0]
    df["compound"] = df["compound"].fillna("UNKNOWN")
    df["tyre_age"] = df["tyre_age"].astype(float)
    df["driver"] = df["driver_number"].astype(str)
    df["isA"] = (df["driver_number"] == a).astype(float)
    df["isB"] = (df["driver_number"] == b).astype(float)
    df = _attach_track_temp(df, weather)
    use_temp = df["track_temp"].notna().mean() > 0.9 and df["track_temp"].std() > 0.2
    if use_temp:
        df = df[df["track_temp"].notna()]
    if len(df) < MIN_LAPS:
        return {"ok": False, "reason": f"only {len(df)} clean laps in the session (need {MIN_LAPS})"}

    # Compounds with too little tyre-age spread can't support a slope.
    compounds = [c for c, g in df.groupby("compound") if g["tyre_age"].nunique() >= 4]
    df = df[df["compound"].isin(compounds)]
    terms = ["C(driver)", "lap_number"]
    terms += [f"I(tyre_age * (compound == '{c}'))" for c in compounds]
    driver_terms = {}
    for tag in ("A", "B"):
        for c in compounds:
            sub = df[(df[f"is{tag}"] == 1) & (df["compound"] == c)]
            if sub["tyre_age"].nunique() >= 4:
                name = f"I(tyre_age * (compound == '{c}') * is{tag})"
                terms.append(name)
                driver_terms[(tag, c)] = name
    if use_temp:
        terms.append("track_temp")
    res = smf.ols("lap_time_s ~ " + " + ".join(terms), data=df).fit(cov_type="HC3")
    ci = res.conf_int(alpha=1 - CI_LEVEL)

    def coef(name: str) -> dict:
        return {"estimate": round(float(res.params[name]), 4), "ci_low": round(float(ci.loc[name, 0]), 4),
                "ci_high": round(float(ci.loc[name, 1]), 4)}

    field = {c: coef(f"I(tyre_age * (compound == '{c}'))") for c in compounds}
    per_driver = {}
    for tag, drv in (("A", a), ("B", b)):
        per_driver[tag] = {"driver_number": drv, "compounds": {}}
        for c in compounds:
            base = f"I(tyre_age * (compound == '{c}'))"
            if (tag, c) in driver_terms:
                est, lo, hi = _combo(res, [base, driver_terms[(tag, c)]])
                per_driver[tag]["compounds"][c] = {"estimate": round(est, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                                                   "n_laps": int(((df[f"is{tag}"] == 1) & (df["compound"] == c)).sum())}
    warnings = []
    if res.condition_number > 1e5:
        warnings.append("High collinearity (condition number %.0e): estimates may be unstable" % res.condition_number)
    stints_per_driver = laps[laps["driver_number"].isin([a, b])].groupby("driver_number")["stint"].nunique()
    for d, n in stints_per_driver.items():
        if n < 2:
            warnings.append(f"Car {d} ran a single stint: its tyre slope relies entirely on the field-wide γ")
    if (df["compound"] == "UNKNOWN").any():
        warnings.append("Compound unknown for this season: all laps treated as one compound; tyre age inferred from pit stops")
    return {
        "ok": True,
        "ci_level": CI_LEVEL,
        "n_laps": int(res.nobs),
        "n_drivers": int(df["driver"].nunique()),
        "r2": round(float(res.rsquared), 3),
        "residual_sd": round(float(np.sqrt(res.scale)), 3),
        "lap_effect": coef("lap_number"),
        "track_temp_effect": coef("track_temp") if use_temp else None,
        "field_tyre_slopes": field,
        "driver_tyre_slopes": per_driver,
        "warnings": warnings,
        "assumptions": ASSUMPTIONS,
    }
