"""Model B — session-wide fixed-effects regression (docs/TYRE_METHODOLOGY.md §4).

    lap_time = α_driver + κ_compound + γ·lap_number + Σ_c β_c·tyre_age·[compound=c]
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
PHASE_SPREAD = 0.3  # warn when compounds' median laps differ by > 30% of race distance

ASSUMPTIONS = [
    "Fuel-burn and track-evolution effect (γ) is linear in lap number and identical for every driver",
    "Tyre-age effect is linear within a compound",
    "Driver differences in pace are constant offsets except for the two selected drivers' tyre slopes",
    "Each compound has one fresh-tyre pace offset shared by all drivers",
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
    if len(compounds) > 1:
        terms.append(f"C(compound, Treatment('{compounds[0]}'))")  # fresh-tyre pace offset per compound
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
    offsets = {compounds[0]: {"estimate": 0.0, "ci_low": 0.0, "ci_high": 0.0}}
    for c in compounds[1:]:
        offsets[c] = coef(f"C(compound, Treatment('{compounds[0]}'))[T.{c}]")

    # Predicted pace vs tyre age per driver × compound at a common reference lap and temperature, so compounds
    # can be compared at equal fuel and conditions (the cross-compound view).
    ref_lap = float(df["lap_number"].median())
    ref_temp = float(df["track_temp"].median()) if use_temp else None
    curves = []
    for tag, drv in (("A", a), ("B", b)):
        for c in compounds:
            seen = df[(df["compound"] == c)]["tyre_age"]
            ages = np.arange(0, int(seen.max()) + 1)
            grid = pd.DataFrame({"driver": str(drv), "compound": c, "tyre_age": ages.astype(float), "lap_number": ref_lap,
                                 "isA": 1.0 if tag == "A" else 0.0, "isB": 1.0 if tag == "B" else 0.0})
            if use_temp:
                grid["track_temp"] = ref_temp
            if str(drv) not in set(df["driver"]):
                continue
            pred = res.get_prediction(grid).summary_frame(alpha=1 - CI_LEVEL)
            own = df[(df["driver_number"] == drv) & (df["compound"] == c)]["tyre_age"]
            curves.append({"tag": tag, "driver_number": drv, "compound": c, "tyre_age": ages.tolist(),
                           "lap_time": pred["mean"].round(3).tolist(), "ci_low": pred["mean_ci_lower"].round(3).tolist(),
                           "ci_high": pred["mean_ci_upper"].round(3).tolist(),
                           "driver_used_ages": [int(own.min()), int(own.max())] if len(own) else None})

    warnings = []
    phase = df.groupby("compound")["lap_number"].median()
    if len(phase) > 1 and phase.max() - phase.min() > PHASE_SPREAD * df["lap_number"].max():
        early, late = phase.idxmin(), phase.idxmax()
        warnings.append(f"{early} was mostly run early (median lap {phase[early]:.0f}) and {late} late (median lap "
                        f"{phase[late]:.0f}): compound offsets are partly confounded with any non-linear fuel/track effect")
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
        "compound_offsets": offsets,
        "reference": {"compound": compounds[0], "lap_number": ref_lap, "track_temp": ref_temp},
        "pace_curves": curves,
        "driver_tyre_slopes": per_driver,
        "warnings": warnings,
        "assumptions": ASSUMPTIONS,
    }
