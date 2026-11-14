"""Neutralisation windows (SC / VSC / red / yellow) and deleted laps reconstructed from OpenF1 race_control.

Message formats verified on 2023 Australian GP (session 7787), see docs/DATA_SOURCES.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

VSC_GRACE = pd.Timedelta(seconds=20)  # VSC "ENDING" → green typically within 10–15 s
DELETED_RE = re.compile(r"CAR (\d+) \(\w+\)(?: TIME [\d:.]+)? (DELETED|REINSTATED).*?\bLAP (\d+)\b")


@dataclass
class Window:
    kind: str  # "sc" | "vsc" | "red" | "yellow"
    start: pd.Timestamp
    end: pd.Timestamp


def neutralisation_windows(rc: pd.DataFrame, typical_lap: pd.Timedelta, session_end: pd.Timestamp) -> list[Window]:
    """SC ends one typical lap after "IN THIS LAP" and red ends one lap after the next green light, so the
    restart lap is covered conservatively."""
    if rc.empty:
        return []
    windows: list[Window] = []
    open_: dict[str, pd.Timestamp] = {}
    yellow_sectors: dict[int | str, pd.Timestamp] = {}

    def close(kind: str, end: pd.Timestamp) -> None:
        if kind in open_:
            windows.append(Window(kind, open_.pop(kind), end))

    for row in rc.itertuples(index=False):
        msg = str(row.message).upper()
        date = row.date
        if row.category == "SafetyCar":
            if "VIRTUAL SAFETY CAR DEPLOYED" in msg:
                open_.setdefault("vsc", date)
            elif "VIRTUAL SAFETY CAR ENDING" in msg:
                close("vsc", date + VSC_GRACE)
            elif "SAFETY CAR DEPLOYED" in msg:
                open_.setdefault("sc", date)
            elif "SAFETY CAR IN THIS LAP" in msg:
                close("sc", date + typical_lap)
        elif row.category == "Flag":
            flag = str(row.flag or "").upper()
            scope = str(row.scope or "")
            if flag == "RED":
                open_.setdefault("red", date)
            elif flag == "GREEN" and "red" in open_:
                close("red", date + typical_lap)
            elif flag in ("YELLOW", "DOUBLE YELLOW") and scope == "Sector":
                yellow_sectors.setdefault(row.sector, date)
            elif flag == "CLEAR" and scope == "Sector" and row.sector in yellow_sectors:
                windows.append(Window("yellow", yellow_sectors.pop(row.sector), date))
            elif flag in ("CLEAR", "CHEQUERED") and scope == "Track":
                for start in yellow_sectors.values():
                    windows.append(Window("yellow", start, date))
                yellow_sectors.clear()
    for kind in list(open_):
        close(kind, session_end)
    for start in yellow_sectors.values():
        windows.append(Window("yellow", start, session_end))
    return windows


def deleted_laps(rc: pd.DataFrame) -> set[tuple[int, int]]:
    """{(driver_number, lap_number)} deleted by race control (later reinstatements are honoured)."""
    out: set[tuple[int, int]] = set()
    if rc.empty:
        return out
    for msg in rc["message"].astype(str):
        m = DELETED_RE.search(msg.upper())
        if not m:
            continue
        key = (int(m.group(1)), int(m.group(3)))
        if m.group(2) == "DELETED":
            out.add(key)
        else:
            out.discard(key)
    return out
