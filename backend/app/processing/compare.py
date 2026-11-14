"""Lap selection for the four comparison modes + comparability report."""

from __future__ import annotations

import pandas as pd

MODES = ("fastest", "same_lap", "same_tyre_age", "custom")


class SelectionError(ValueError):
    pass


def _valid(laps: pd.DataFrame) -> pd.DataFrame:
    return laps[laps["lap_time_s"].notna() & ~laps["deleted"] & ~laps["is_pit_out"] & ~laps["is_pit_in"]]


def _pick(laps: pd.DataFrame, driver: int, mode: str, *, lap: int | None, tyre_age: int | None,
          compound: str | None, stint: int | None, custom_lap: int | None) -> pd.Series:
    d = laps[laps["driver_number"] == driver]
    if d.empty:
        raise SelectionError(f"car {driver} has no laps in this session")
    if mode == "fastest":
        v = _valid(d)
        if compound:
            v = v[v["compound"] == compound]
        if v.empty:
            raise SelectionError(f"car {driver}: no valid timed lap" + (f" on {compound}" if compound else ""))
        return v.loc[v["lap_time_s"].idxmin()]
    if mode == "same_lap":
        if lap is None:
            raise SelectionError("same_lap mode needs `lap`")
        m = d[d["lap_number"] == lap]
    elif mode == "same_tyre_age":
        if tyre_age is None:
            raise SelectionError("same_tyre_age mode needs `tyre_age`")
        m = d[d["tyre_age"] == tyre_age]
        if compound:
            m = m[m["compound"] == compound]
        if stint is not None:
            m = m[m["stint"] == stint]
        m = m.sort_values(["clean", "lap_number"], ascending=[False, True])
    elif mode == "custom":
        if custom_lap is None:
            raise SelectionError("custom mode needs a lap for each driver")
        m = d[d["lap_number"] == custom_lap]
    else:
        raise SelectionError(f"unknown mode {mode}; expected one of {MODES}")
    if m.empty:
        raise SelectionError(f"car {driver}: no lap matches the selection")
    return m.iloc[0]


QUALI_EVOLUTION_MIN = 5.0


def comparability(a: pd.Series, b: pd.Series, is_race: bool) -> list[dict]:
    diffs: list[dict] = []
    if a["compound"] is None or b["compound"] is None:
        diffs.append({"kind": "compound", "message": "Tyre compound unknown for at least one lap (not in the data source)"})
    elif a["compound"] != b["compound"]:
        diffs.append({"kind": "compound", "message": f"Different compounds: {a['compound']} vs {b['compound']}"})
    if pd.notna(a["tyre_age"]) and pd.notna(b["tyre_age"]) and a["tyre_age"] != b["tyre_age"]:
        diffs.append({"kind": "tyre_age", "message": f"Different tyre age: {a['tyre_age']} vs {b['tyre_age']} laps"})
    if a.get("tyre_age_assumed") or b.get("tyre_age_assumed"):
        diffs.append({"kind": "tyre_age_assumed",
                      "message": "Tyre age inferred from pit stops (assumes a new set at each stop); compound unknown"})
    if is_race and a["lap_number"] != b["lap_number"]:
        gap = abs(int(a["lap_number"]) - int(b["lap_number"]))
        diffs.append({"kind": "fuel", "message": f"Different race laps ({gap} apart): fuel load and track state differ"})
    if not is_race and pd.notna(a["lap_start"]) and pd.notna(b["lap_start"]):
        minutes = abs((a["lap_start"] - b["lap_start"]).total_seconds()) / 60
        if minutes > QUALI_EVOLUTION_MIN:
            diffs.append({"kind": "track_evolution",
                          "message": f"Laps set {minutes:.0f} min apart: track evolution and conditions may differ"})
    for tag, row in (("A", a), ("B", b)):
        for r in row["exclude_reasons"]:
            diffs.append({"kind": "lap_status", "message": f"Lap {tag} not clean: {r}"})
        for f in row["flags"]:
            diffs.append({"kind": "lap_flag", "message": f"Lap {tag}: {f}"})
    return diffs


def select_laps(laps: pd.DataFrame, a: int, b: int, mode: str, is_race: bool, **kw) -> dict:
    la = _pick(laps, a, mode, lap=kw.get("lap"), tyre_age=kw.get("tyre_age"), compound=kw.get("compound_a"),
               stint=kw.get("stint_a"), custom_lap=kw.get("lap_a"))
    lb = _pick(laps, b, mode, lap=kw.get("lap"), tyre_age=kw.get("tyre_age"), compound=kw.get("compound_b"),
               stint=kw.get("stint_b"), custom_lap=kw.get("lap_b"))
    diffs = comparability(la, lb, is_race)
    return {"a": la, "b": lb, "differences": diffs, "equivalent": not diffs}
