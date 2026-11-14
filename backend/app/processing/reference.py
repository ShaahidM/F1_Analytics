"""Reference line and projection: maps any x/y sample to track distance `s` (m) and lateral offset (m).

See docs/ARCHITECTURE.md "Lap alignment". Coordinates stay in source units (0.1 m) for display;
distances are returned in metres.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import splev, splprep
from scipy.spatial import cKDTree

from app.config import POSITION_UNITS_PER_M

RESAMPLE_M = 1.0
SEARCH_K = 16
# Max disagreement between the projected s and the sequential guess before a candidate is rejected.
# Guards against self-crossing / adjacent track sections (e.g. Suzuka's crossover).
MAX_S_JUMP_M = 150.0


@dataclass
class ReferenceLine:
    x: np.ndarray       # source units
    y: np.ndarray
    s: np.ndarray       # metres from the timing line
    length_m: float
    tree: cKDTree

    def downsample(self, step_m: float) -> dict:
        idx = np.arange(0, len(self.s), max(1, int(step_m / RESAMPLE_M)))
        return {"s": self.s[idx].round(1).tolist(), "x": self.x[idx].round(1).tolist(), "y": self.y[idx].round(1).tolist()}


def _interp_xy(pos: pd.DataFrame, t: pd.Timestamp) -> tuple[float, float]:
    ts = (pos["date"] - t).dt.total_seconds().to_numpy()
    return float(np.interp(0.0, ts, pos["x"])), float(np.interp(0.0, ts, pos["y"]))


def build_reference(pos: pd.DataFrame, lap_start: pd.Timestamp, lap_end: pd.Timestamp) -> ReferenceLine:
    """Closed periodic spline through one lap's position samples, anchored at the timing line (s=0)."""
    inside = pos[(pos["date"] > lap_start) & (pos["date"] < lap_end)]
    x0, y0 = _interp_xy(pos, lap_start)
    pts_x = np.concatenate([[x0], inside["x"].to_numpy(float)])
    pts_y = np.concatenate([[y0], inside["y"].to_numpy(float)])
    # Drop consecutive duplicates (stationary samples break the spline parameterisation).
    keep = np.r_[True, (np.diff(pts_x) != 0) | (np.diff(pts_y) != 0)]
    pts_x, pts_y = pts_x[keep], pts_y[keep]
    # Light smoothing only: positions are map-matched (low noise) and heavier smoothing biases curves inward.
    tck, _ = splprep([pts_x, pts_y], s=len(pts_x) * 0.25, per=1)

    dense_u = np.linspace(0, 1, 20000, endpoint=False)
    dx, dy = splev(dense_u, tck)
    seg = np.hypot(np.diff(np.r_[dx, dx[0]]), np.diff(np.r_[dy, dy[0]])) / POSITION_UNITS_PER_M
    cum = np.r_[0.0, np.cumsum(seg)]
    length = float(cum[-1])
    s = np.arange(0.0, length, RESAMPLE_M)
    u = np.interp(s, cum, np.r_[dense_u, 1.0])
    rx, ry = splev(u, tck)
    rx, ry = np.asarray(rx), np.asarray(ry)
    return ReferenceLine(x=rx, y=ry, s=s, length_m=length, tree=cKDTree(np.c_[rx, ry]))


def project(ref: ReferenceLine, x: np.ndarray, y: np.ndarray, s_guess: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return (s in m, signed lateral offset in m; +left of travel direction) for each point.

    With `s_guess`, candidates far from the guess (modulo lap length) are skipped so that nearby but
    different parts of the track are not confused.
    """
    pts = np.c_[x, y]
    k = min(SEARCH_K, len(ref.s))
    dist, idx = ref.tree.query(pts, k=k)
    n = len(ref.s)
    if s_guess is None:
        chosen = idx[:, 0]
    else:
        cand_s = ref.s[idx]
        diff = np.abs((cand_s - s_guess[:, None] + ref.length_m / 2) % ref.length_m - ref.length_m / 2)
        ok = diff < MAX_S_JUMP_M
        # First (nearest) acceptable candidate; fall back to the nearest overall.
        first_ok = np.where(ok.any(axis=1), ok.argmax(axis=1), 0)
        chosen = idx[np.arange(len(idx)), first_ok]

    # Refine on the segment [i, i+1] (or [i-1, i]) for sub-metre precision.
    i0 = chosen
    i1 = (chosen + 1) % n
    ip = (chosen - 1) % n
    best_s = np.empty(len(pts))
    best_lat = np.empty(len(pts))
    best_d = np.full(len(pts), np.inf)
    for a, b, base in ((i0, i1, ref.s[i0]), (ip, i0, ref.s[ip])):
        ax, ay, bx, by = ref.x[a], ref.y[a], ref.x[b], ref.y[b]
        vx, vy = bx - ax, by - ay
        seg2 = vx * vx + vy * vy
        t = np.clip(((pts[:, 0] - ax) * vx + (pts[:, 1] - ay) * vy) / np.where(seg2 == 0, 1, seg2), 0, 1)
        px, py = ax + t * vx, ay + t * vy
        d = np.hypot(pts[:, 0] - px, pts[:, 1] - py)
        cross = vx * (pts[:, 1] - ay) - vy * (pts[:, 0] - ax)
        better = d < best_d
        best_d = np.where(better, d, best_d)
        best_s = np.where(better, base + t * np.sqrt(seg2) / POSITION_UNITS_PER_M, best_s)
        best_lat = np.where(better, np.sign(cross) * d / POSITION_UNITS_PER_M, best_lat)
    return best_s % ref.length_m, best_lat
