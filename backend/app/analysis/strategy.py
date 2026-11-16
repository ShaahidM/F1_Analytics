"""Race strategy: stint timeline, gaps and positions by lap, pit-stop cost, undercut/overcut cycles.

Gaps use line-crossing times (OpenF1 lap start/end timestamps, or cumulative lap times for Jolpica), so every
number here is CALCULATED from timing. Pit loss uses the driver's own neighbouring clean laps as the baseline,
so it is an ESTIMATE (fuel, traffic and tyre state differ between those laps).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CYCLE_WINDOW_LAPS = 6
PIT_BASELINE_LAPS = 4
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def crossing_times(laps: pd.DataFrame) -> pd.DataFrame:
    """Seconds at which each driver completed each lap (absolute epoch seconds or race-relative for Jolpica)."""
    df = laps[["driver_number", "lap_number", "lap_end", "lap_time_s"]].copy() if "lap_end" in laps else \
        laps[["driver_number", "lap_number", "lap_time_s"]].assign(lap_end=pd.NaT)
    if df["lap_end"].notna().any():
        df["t"] = (df["lap_end"] - EPOCH).dt.total_seconds()
    else:
        df = df.sort_values(["driver_number", "lap_number"])
        df["t"] = df.groupby("driver_number")["lap_time_s"].cumsum()
    return df[["driver_number", "lap_number", "t"]].dropna()


def positions(cross: pd.DataFrame) -> pd.DataFrame:
    """Running order at each lap = rank of crossing time among drivers completing that lap."""
    out = cross.copy()
    out["position"] = out.groupby("lap_number")["t"].rank(method="first").astype(int)
    return out


def stints_table(laps: pd.DataFrame) -> list[dict]:
    rows = []
    for (drv, stint), g in laps[laps["stint"].notna()].groupby(["driver_number", "stint"]):
        rows.append({
            "driver_number": int(drv), "stint": int(stint), "compound": g["compound"].iloc[0],
            "lap_start": int(g["lap_number"].min()), "lap_end": int(g["lap_number"].max()),
            "tyre_age_start": None if pd.isna(g["tyre_age"].iloc[0]) else int(g["tyre_age"].iloc[0]),
            "tyre_age_assumed": bool(g["tyre_age_assumed"].iloc[0]) if "tyre_age_assumed" in g else False,
        })
    return rows


def pit_stops(laps: pd.DataFrame, pits: pd.DataFrame, driver: int) -> list[dict]:
    d = laps[laps["driver_number"] == driver].set_index("lap_number")
    lane = pits[pits["driver_number"] == driver].set_index("lap_number") if not pits.empty else pd.DataFrame()
    out = []
    for lap in d.index[d["is_pit_in"]]:
        if lap + 1 not in d.index:
            continue  # retired / finished in the pit lane
        in_t, out_t = d.at[lap, "lap_time_s"], d.at[lap + 1, "lap_time_s"]
        near = d[(abs(d.index - lap) <= PIT_BASELINE_LAPS + 1) & d["clean"] & ~d.index.isin([lap, lap + 1])]["lap_time_s"]
        base = float(near.median()) if len(near) >= 2 else None
        loss = None if base is None or pd.isna(in_t) or pd.isna(out_t) else round(float(in_t + out_t - 2 * base), 2)
        neutral = bool(d.loc[[lap, lap + 1], ["sc", "vsc", "red"]].to_numpy().any())
        row_lane = lane.loc[lap] if lap in lane.index else None
        if isinstance(row_lane, pd.DataFrame):
            row_lane = row_lane.iloc[0]
        out.append({
            "lap": int(lap),
            "from_compound": d.at[lap, "compound"], "to_compound": d.at[lap + 1, "compound"],
            "from_tyre_age": None if pd.isna(d.at[lap, "tyre_age"]) else int(d.at[lap, "tyre_age"]),
            "lane_s": None if row_lane is None or pd.isna(row_lane["lane_duration_s"]) else round(float(row_lane["lane_duration_s"]), 2),
            "stationary_s": None if row_lane is None or pd.isna(row_lane["stop_duration_s"]) else round(float(row_lane["stop_duration_s"]), 2),
            "in_lap_s": None if pd.isna(in_t) else round(float(in_t), 3),
            "out_lap_s": None if pd.isna(out_t) else round(float(out_t), 3),
            "baseline_lap_s": None if base is None else round(base, 3),
            "estimated_loss_s": loss,
            "under_neutralisation": neutral,
        })
    return out


def _gap(cross: pd.DataFrame, f: int, s: int, lap: int) -> float | None:
    """t_F − t_S at the end of `lap` (positive = F behind S)."""
    a = cross[(cross["driver_number"] == f) & (cross["lap_number"] == lap)]["t"]
    b = cross[(cross["driver_number"] == s) & (cross["lap_number"] == lap)]["t"]
    return None if a.empty or b.empty else round(float(a.iloc[0] - b.iloc[0]), 3)


def pit_cycles(cross: pd.DataFrame, stops: dict[int, list[dict]], laps: pd.DataFrame, a: int, b: int) -> list[dict]:
    """Pair each stop of A with B's nearest stop within CYCLE_WINDOW_LAPS and measure the gap across the cycle."""
    used: set[int] = set()
    out = []
    for sa in stops[a]:
        cand = [sb for sb in stops[b] if abs(sb["lap"] - sa["lap"]) <= CYCLE_WINDOW_LAPS and sb["lap"] not in used]
        if not cand:
            continue
        sb = min(cand, key=lambda x: abs(x["lap"] - sa["lap"]))
        used.add(sb["lap"])
        if sa["lap"] == sb["lap"]:
            first, second, f_stop, s_stop = a, b, sa, sb
        else:
            first, second, f_stop, s_stop = (a, b, sa, sb) if sa["lap"] < sb["lap"] else (b, a, sb, sa)
        before_lap, after_lap = f_stop["lap"] - 1, s_stop["lap"] + 1
        g0, g1 = _gap(cross, first, second, before_lap), _gap(cross, first, second, after_lap)
        net = None if g0 is None or g1 is None else round(g1 - g0, 3)
        lane_diff = None if f_stop["lane_s"] is None or s_stop["lane_s"] is None else round(f_stop["lane_s"] - s_stop["lane_s"], 2)
        window = laps[laps["driver_number"].isin([a, b]) & laps["lap_number"].between(f_stop["lap"], after_lap)]
        if sa["lap"] == sb["lap"]:
            outcome = "same-lap stops"
        elif g0 is None or g1 is None:
            outcome = "incomplete timing"
        elif g0 > 0 > g1:
            outcome = "undercut: first stopper moved ahead"
        elif g0 < 0 < g1:
            outcome = "overcut: second stopper moved ahead"
        else:
            outcome = "no change of order"
        out.append({
            "first_stopper": first, "second_stopper": second,
            "first_lap": f_stop["lap"], "second_lap": s_stop["lap"],
            "gap_before_s": g0, "gap_after_s": g1, "net_change_s": net,
            "lane_time_diff_s": lane_diff,
            "on_track_diff_s": None if net is None or lane_diff is None else round(net - lane_diff, 3),
            "compounds": {"first_to": f_stop["to_compound"], "second_from": s_stop["from_compound"], "second_to": s_stop["to_compound"]},
            "neutralised": bool(window[["sc", "vsc", "red"]].to_numpy().any()),
            "outcome": outcome,
        })
    return out


def strategy_offset(cross: pd.DataFrame, stops: dict[int, list[dict]], cycles: list[dict], a: int, b: int,
                    total: int) -> dict | None:
    """Different strategies (e.g. 1-stop vs 2-stop) that the stop-pairing in `pit_cycles` can't capture.

    Gaps are B − A in seconds (positive = B behind), measured before the first stop by either driver, after the last
    one, and at the finish."""
    paired = {(c["first_lap"], c["second_lap"]) for c in cycles}
    paired_laps = {lap for pair in paired for lap in pair}
    la, lb = [s["lap"] for s in stops[a]], [s["lap"] for s in stops[b]]
    if len(la) == len(lb) and all(lap in paired_laps for lap in la + lb):
        return None
    if not la and not lb:
        return None
    first, last = min(la + lb), max(la + lb)
    loss = lambda d: round(sum(s["estimated_loss_s"] or 0.0 for s in stops[d]), 1)  # noqa: E731
    before = _gap(cross, b, a, first - 1)
    finish = _gap(cross, b, a, total)
    return {
        "stops": {"a": len(la), "b": len(lb)}, "stop_laps": {"a": la, "b": lb},
        "gap_before_first_stop_s": before, "gap_after_last_stop_s": _gap(cross, b, a, min(last + 1, total)),
        "gap_at_finish_s": finish, "net_change_s": None if before is None or finish is None else round(finish - before, 3),
        "pit_loss_s": {"a": loss(a), "b": loss(b)},
    }
