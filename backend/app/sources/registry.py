"""Chooses the source for a season or session. Preference order, not hardcoded year ranges:
the first source whose catalog has the season wins."""

from __future__ import annotations

from functools import lru_cache

from app.sources.base import SessionRef, SessionSource
from app.sources.jolpica import JolpicaSource
from app.sources.openf1 import OpenF1Source

# Richest first. A FastF1 (authenticated) source could be inserted here later.
SOURCES: list[SessionSource] = [OpenF1Source(), JolpicaSource()]
BY_PREFIX = {s.prefix: s for s in SOURCES}


def source_for_season(year: int) -> SessionSource:
    for src in SOURCES:
        if src.has_season(year):
            return src
    raise KeyError(f"No source has season {year}")


def source_for_session(session_id: str) -> SessionSource:
    prefix = session_id.split("-", 1)[0]
    if prefix not in BY_PREFIX:
        raise KeyError(session_id)
    return BY_PREFIX[prefix]


@lru_cache(maxsize=256)
def get_session(session_id: str) -> SessionRef:
    return source_for_session(session_id).session(session_id)
