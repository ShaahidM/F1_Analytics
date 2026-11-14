"""Line-length proxy: extra distance driven per corner zone, averaged over a session (EXPERIMENTAL, tier E).

Positions are snapped to one track line, but the wheel-speed integral measures the distance the car actually
covered. Its excess over track distance through a zone means a longer line OR more tyre slip; the two can't be
separated. Per-lap noise is ~4–7 m, so only session averages are meaningful. A difference is reported as
"replicated" when it has the same sign and ≥ REPLICATE_MIN_M in both halves of the session (validated on
Monza 2024 and São Paulo 2026: large differences replicated, small ones flipped sign).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OUTLIER_MADS = 3.0
REPLICATE_MIN_M = 1.0
SIGNIFICANT_Z = 2.0


def _robust(values: pd.Series) -> pd.Series:
    v = values.dropna()
    if len(v) < 3:
        return v
    med = v.median()
    mad = (v - med).abs().median() * 1.4826
    return v if mad == 0 else v[(v - med).abs() <= OUTLIER_MADS * mad]


def _stats(v: pd.Series) -> dict | None:
    if len(v) < 3:
        return None
    return {"mean": round(float(v.mean()), 2), "sd": round(float(v.std(ddof=1)), 2), "n": int(len(v)),
            "se": round(float(v.std(ddof=1) / np.sqrt(len(v))), 2)}


def compare_line(rows_a: pd.DataFrame, rows_b: pd.DataFrame, zone_ids: list[int]) -> list[dict]:
    out = []
    if rows_a.empty or rows_b.empty or "path_excess_m" not in rows_a or "path_excess_m" not in rows_b:
        return out
    mid = float(pd.concat([rows_a["lap_number"], rows_b["lap_number"]]).median())
    for zid in zone_ids:
        va = _robust(rows_a.loc[rows_a["zone_id"] == zid, "path_excess_m"])
        vb = _robust(rows_b.loc[rows_b["zone_id"] == zid, "path_excess_m"])
        sa, sb = _stats(va), _stats(vb)
        row = {"zone_id": zid, "a": sa, "b": sb, "diff_m": None, "se_m": None, "z": None, "halves": None,
               "replicated": False, "significant": False}
        if sa and sb:
            diff = sa["mean"] - sb["mean"]
            se = float(np.hypot(sa["se"], sb["se"])) or 1e-9
            lap_a = rows_a.loc[va.index, "lap_number"]
            lap_b = rows_b.loc[vb.index, "lap_number"]
            halves = []
            for sel_a, sel_b in ((lap_a <= mid, lap_b <= mid), (lap_a > mid, lap_b > mid)):
                if sel_a.sum() >= 3 and sel_b.sum() >= 3:
                    halves.append(round(float(va[sel_a].mean() - vb[sel_b].mean()), 2))
            replicated = len(halves) == 2 and all(abs(h) >= REPLICATE_MIN_M for h in halves) and np.sign(halves[0]) == np.sign(halves[1])
            row.update({"diff_m": round(diff, 2), "se_m": round(se, 2), "z": round(diff / se, 2), "halves": halves,
                        "replicated": bool(replicated), "significant": bool(abs(diff / se) >= SIGNIFICANT_Z and replicated)})
        out.append(row)
    return out
