"""Builds the enriched lap table: tyre info, pit flags, track status, traffic and the clean-lap filter.

Rules are documented in docs/TYRE_METHODOLOGY.md §3. Hard exclusions go in `exclude_reasons`;
soft conditions (traffic, yellow) go in `flags` so the UI can toggle them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.processing.track_status import deleted_laps, neutralisation_windows
from app.sources.base import DataUnavailable, SessionRef, SessionSource

TRAFFIC_GAP_S = 1.5
OUTLIER_MADS = 5.0
QUALI_PUSH_RATIO = 1.07
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _attach_stints(laps: pd.DataFrame, stints: pd.DataFrame) -> pd.DataFrame:
    laps = laps.copy()
    laps["stint"] = pd.array([pd.NA] * len(laps), dtype="Int64")
    laps["compound"] = pd.Series([None] * len(laps), dtype="object")
    # Laps completed on this tyre set *before* this lap (0 on the first lap of a new set).
    laps["tyre_age"] = pd.array([pd.NA] * len(laps), dtype="Int64")
    if stints.empty:
        return laps
    for st in stints.itertuples(index=False):
        end = st.lap_end if pd.notna(st.lap_end) else laps["lap_number"].max()
        m = (laps["driver_number"] == st.driver_number) & laps["lap_number"].between(st.lap_start, end)
        laps.loc[m, "stint"] = st.stint
        laps.loc[m, "compound"] = st.compound
        if pd.notna(st.tyre_age_at_start):
            laps.loc[m, "tyre_age"] = (laps.loc[m, "lap_number"] - st.lap_start + st.tyre_age_at_start).astype("Int64")
    return laps


def _derive_stints_from_pits(laps: pd.DataFrame) -> pd.DataFrame:
    """Sources without stint data (Jolpica): stint = 1 + pit stops completed before this lap.

    Tyre age then ASSUMES a new set at the start and at every stop (`tyre_age_assumed`); compound stays unknown.
    """
    laps = laps.sort_values(["driver_number", "lap_number"]).copy()
    prior_stops = laps.groupby("driver_number")["is_pit_in"].transform(lambda s: s.astype(int).shift(1, fill_value=0).cumsum())
    laps["stint"] = (prior_stops + 1).astype("Int64")
    first = laps.groupby(["driver_number", "stint"])["lap_number"].transform("min")
    laps["tyre_age"] = (laps["lap_number"] - first).astype("Int64")
    laps["tyre_age_assumed"] = True
    return laps


def _lap_windows(laps: pd.DataFrame) -> pd.Series:
    """Lap end time: start + duration, falling back to the next lap's start for laps without a time."""
    nxt = laps.groupby("driver_number")["lap_start"].shift(-1)
    return (laps["lap_start"] + pd.to_timedelta(laps["lap_time_s"], unit="s")).fillna(nxt)


def _min_interval(laps: pd.DataFrame, intervals: pd.DataFrame) -> np.ndarray:
    out = np.full(len(laps), np.nan)
    if intervals.empty:
        return out
    for drv, idx in laps.groupby("driver_number").groups.items():
        iv = intervals[intervals["driver_number"] == drv].sort_values("date")
        if iv.empty:
            continue
        t = (iv["date"] - EPOCH).dt.total_seconds().to_numpy()
        v = iv["interval_s"].to_numpy(dtype=float)
        for i in idx:
            s, e = laps.at[i, "lap_start"], laps.at[i, "lap_end"]
            if pd.isna(s) or pd.isna(e):
                continue
            lo, hi = np.searchsorted(t, (s - EPOCH).total_seconds()), np.searchsorted(t, (e - EPOCH).total_seconds())
            seg = v[lo:hi]
            if seg.size and np.isfinite(seg).any():
                out[i] = np.nanmin(seg)
    return out


def build_lap_table(src: SessionSource, s: SessionRef) -> pd.DataFrame:
    laps = src.laps(s)
    if laps.empty:
        return laps
    try:
        stints = src.stints(s)
    except DataUnavailable:
        stints = pd.DataFrame()
    laps = _attach_stints(laps, stints)

    try:
        pits = src.pits(s)
    except DataUnavailable:
        pits = pd.DataFrame(columns=["driver_number", "lap_number"])
    pit_in = set(zip(pits["driver_number"], pits["lap_number"]))
    if not stints.empty:  # a stint change also implies an in-lap, even if the pit record is missing
        nxt = stints.groupby("driver_number")["stint"].shift(-1)
        pit_in |= set(zip(stints.loc[nxt.notna(), "driver_number"], stints.loc[nxt.notna(), "lap_end"].astype(int)))
    laps["is_pit_in"] = laps["is_pit_in"].to_numpy(dtype=bool) | np.array(
        [(d, n) in pit_in for d, n in zip(laps["driver_number"], laps["lap_number"])], dtype=bool)
    laps["tyre_age_assumed"] = False
    if stints.empty and laps["is_pit_in"].any():
        laps = _derive_stints_from_pits(laps).reset_index(drop=True)

    laps["lap_end"] = _lap_windows(laps)
    for col in ("sc", "vsc", "red", "yellow", "deleted"):
        laps[col] = False
    try:
        rc = src.race_control(s)
    except DataUnavailable:
        rc = pd.DataFrame()
    if not rc.empty and laps["lap_start"].notna().any():
        typical = pd.Timedelta(seconds=float(np.nanmedian(laps["lap_time_s"])) if laps["lap_time_s"].notna().any() else 90)
        session_end = pd.Timestamp(s.date_end) if s.date_end else laps["lap_end"].max()
        for w in neutralisation_windows(rc, typical, session_end):
            laps.loc[(laps["lap_start"] < w.end) & (laps["lap_end"] > w.start), w.kind] = True
        dels = deleted_laps(rc)
        laps["deleted"] = [(d, n) in dels for d, n in zip(laps["driver_number"], laps["lap_number"])]

    laps["min_interval_s"] = np.nan
    if s.is_race:
        try:
            laps["min_interval_s"] = _min_interval(laps.reset_index(drop=True), src.intervals(s))
        except DataUnavailable:
            pass

    return _classify(laps, s)


def _classify(laps: pd.DataFrame, s: SessionRef) -> pd.DataFrame:
    reasons: list[list[str]] = [[] for _ in range(len(laps))]
    flags: list[list[str]] = [[] for _ in range(len(laps))]
    rows = laps.reset_index(drop=True)

    def add(mask, label, target):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            target[i].append(label)

    add(rows["lap_time_s"].isna(), "no lap time", reasons)
    add(rows["is_pit_out"], "pit out-lap", reasons)
    add(rows["is_pit_in"], "pit in-lap", reasons)
    add(rows["deleted"], "deleted by race control", reasons)
    add(rows["sc"], "safety car", reasons)
    add(rows["vsc"], "virtual safety car", reasons)
    add(rows["red"], "red flag", reasons)
    add(rows["yellow"], "yellow flag", flags)
    if s.is_race:
        add(rows["lap_number"] == 1, "race start lap", reasons)
        add(rows["min_interval_s"] < TRAFFIC_GAP_S, f"within {TRAFFIC_GAP_S}s of car ahead", flags)
        # Robust outlier test against the stint median among otherwise-eligible laps.
        ok = np.array([not r for r in reasons])
        grp = rows["stint"].astype("float").fillna(-1)
        for _, idx in rows[ok].groupby([rows["driver_number"][ok], grp[ok]]).groups.items():
            t = rows.loc[idx, "lap_time_s"]
            med = t.median()
            mad = (t - med).abs().median() or 0.0
            if mad > 0:
                add(rows.index.isin(idx) & ((rows["lap_time_s"] - med).abs() > OUTLIER_MADS * mad * 1.4826), "lap-time outlier", reasons)
    else:
        best = rows.groupby("driver_number")["lap_time_s"].transform("min")
        add(rows["lap_time_s"] > best * QUALI_PUSH_RATIO, "not a push lap (>107% of own best)", reasons)

    rows["exclude_reasons"] = reasons
    rows["flags"] = flags
    rows["clean"] = [not r for r in reasons]
    return rows
