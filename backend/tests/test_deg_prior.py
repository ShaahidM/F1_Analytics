"""Cross-race degradation prior on a synthetic table with known compound, circuit and temperature effects."""

import numpy as np
import pandas as pd

from app.analysis.deg_prior import fit_prior, training_rows, validate_prior, validation_summary

LAP = 90.0
MU = {"SOFT": 0.12, "MEDIUM": 0.08, "HARD": 0.04}  # s/lap
TEMP = 0.002                                        # s/lap per °C


def table(n_circuits=20, years=(2023, 2024, 2025), circuit_sd=0.03, noise=0.01, seed=0):
    rng = np.random.default_rng(seed)
    effect = rng.normal(0, circuit_sd, n_circuits)
    rows = []
    for year in years:
        for k in range(n_circuits):
            temp = 35 + rng.normal(0, 8)
            for c in MU:
                slope = MU[c] + effect[k] + TEMP * (temp - 35) + rng.normal(0, noise)
                rows.append({"session_id": f"s-{year}-{k}", "year": year, "round": k + 1, "circuit_key": k,
                             "compound": c, "slope": slope, "slope_se": noise, "n_laps": 300, "n_drivers": 15,
                             "offset_vs_medium": None if c == "MEDIUM" else (-0.5 if c == "SOFT" else 0.4) + rng.normal(0, 0.05),
                             "offset_vs_medium_se": None if c == "MEDIUM" else 0.05,
                             "lap_time_s": LAP, "track_temp": temp})
    return pd.DataFrame(rows)


def test_recovers_compound_means_and_temperature():
    m = fit_prior(table(), "slope")
    coef = dict(zip(m.columns, m.coef * LAP / 100))
    for c, mu in MU.items():
        assert abs(coef[f"cmp:{c}"] - mu) < 0.02
    assert abs(coef["temp"] / m.temp_sd - TEMP) < 0.001


def test_beats_compound_mean_when_circuits_differ():
    preds = validate_prior(table(), "slope", "loro")
    s = validation_summary(preds, n_boot=200)
    assert s["mae"]["model"] < 0.6 * s["mae"]["compound_mean"]
    assert s["gain_vs"]["compound_mean"]["low"] > 0
    assert 0.8 < s["coverage_90"] <= 1.0


def test_no_circuit_signal_means_no_gain_and_no_harm():
    preds = validate_prior(table(circuit_sd=0.0, noise=0.03), "slope", "loro")
    s = validation_summary(preds, n_boot=200)
    assert s["mae"]["model"] < 1.1 * s["mae"]["compound_mean"]


def test_predict_for_unseen_circuit_falls_back_to_compound_mean():
    m = fit_prior(table(), "slope")
    p = m.predict("HARD", 999, 2025, 35.0, LAP)
    assert not p["circuit_seen"] and abs(p["mean"] - MU["HARD"]) < 0.02 and p["sd"] > 0
    assert m.predict("INTERMEDIATE", 1, 2025, 35.0, LAP) is None


def test_thin_compounds_are_not_training_rows_and_offsets_exclude_medium():
    t = table()
    t.loc[0, "n_drivers"] = 2
    assert len(training_rows(t, "slope")) == len(t) - 1
    assert set(training_rows(t, "offset")["compound"]) == {"SOFT", "HARD"}
    assert fit_prior(t.head(10), "slope") is None
