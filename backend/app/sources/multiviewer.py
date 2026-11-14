"""MultiViewer circuit info: corner positions, track outline, map rotation, pit loss.

Unofficial third-party API — treated as optional enrichment (callers must handle None).
Coordinates share the F1/OpenF1 frame (verified on Monza: identical x/y extents).
"""

from __future__ import annotations

import logging

from app.config import MULTIVIEWER_BASE
from app.sources.http import NotFound, http

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "FastF1/3.9"}


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def circuit_info(circuit_key: int, year: int) -> dict | None:
    try:
        data = http.get_json(f"{MULTIVIEWER_BASE}/circuits/{circuit_key}/{year}", headers=HEADERS)
    except NotFound:
        return None
    except Exception as exc:  # network / schema problems must not break the session view
        log.warning("MultiViewer unavailable for circuit %s/%s: %s", circuit_key, year, exc)
        return None
    corners = [
        {
            "number": c.get("number"),
            "letter": c.get("letter") or "",
            "angle": c.get("angle"),
            "x": c["trackPosition"]["x"],
            "y": c["trackPosition"]["y"],
        }
        for c in data.get("corners", [])
        if c.get("trackPosition")
    ]
    return {
        "corners": corners,
        "rotation": data.get("rotation", 0),
        # {"normal": s, "sc": s, "vsc": s}: MultiViewer's own estimates of total time lost to a stop.
        "pit_loss": {k: float(v) for k, v in (data.get("pitLoss") or {}).items() if _is_number(v)} or None,
        "layout_year": data.get("year"),
        "outline_x": data.get("x", []),
        "outline_y": data.get("y", []),
    }
