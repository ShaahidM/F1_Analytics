"""Source-independent types. Every adapter returns these shapes so analysis code never sees raw API fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.config import CURRENT_SEASON_TTL

# Normalized column sets (see docs/ARCHITECTURE.md "Normalized data model").
DRIVER_COLUMNS = ["driver_number", "code", "full_name", "team", "team_colour"]
LAP_COLUMNS = [
    "driver_number", "lap_number", "lap_start", "lap_time_s", "s1_s", "s2_s", "s3_s",
    "i1_speed", "i2_speed", "st_speed", "is_pit_out", "is_pit_in",
]
STINT_COLUMNS = ["driver_number", "stint", "lap_start", "lap_end", "compound", "tyre_age_at_start"]
PIT_COLUMNS = ["driver_number", "lap_number", "date", "lane_duration_s", "stop_duration_s"]
CAR_COLUMNS = ["date", "speed", "throttle", "brake", "gear", "rpm", "drs"]
POS_COLUMNS = ["date", "x", "y", "z"]


@dataclass
class Capabilities:
    lap_times: bool = False
    sectors: bool = False
    compounds: bool = False
    pit: bool = False
    telemetry: bool = False
    position: bool = False
    weather: bool = False
    race_control: bool = False
    intervals: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionRef:
    id: str               # "<source prefix>-<source key>", stable across restarts
    source: str
    year: int
    round: int | None
    meeting_name: str
    country: str
    location: str
    circuit_key: int | None
    circuit_name: str
    session_name: str     # "Race", "Qualifying", "Sprint", "Sprint Qualifying", …
    session_type: str     # "Race" | "Qualifying"
    date_start: datetime | None
    date_end: datetime | None

    @property
    def is_race(self) -> bool:
        return self.session_type == "Race"

    def has_started(self) -> bool:
        return self.date_start is not None and self.date_start <= datetime.now(timezone.utc)

    def cache_ttl(self) -> timedelta | None:
        """Permanent cache once data has settled (1 day after the session), short TTL before that."""
        end = self.date_end or self.date_start
        if end is None or datetime.now(timezone.utc) - end < timedelta(days=1):
            return timedelta(minutes=30)
        return None

    def is_settled(self) -> bool:
        return self.cache_ttl() is None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date_start"] = self.date_start.isoformat() if self.date_start else None
        d["date_end"] = self.date_end.isoformat() if self.date_end else None
        d["available"] = self.has_started()
        return d


def season_ttl(year: int) -> timedelta | None:
    return CURRENT_SEASON_TTL if year >= datetime.now(timezone.utc).year else None


def empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


class DataUnavailable(Exception):
    """Requested data type is not provided by the session's source."""


class SessionSource:
    """Base adapter. Methods a source can't provide raise DataUnavailable."""

    name: str = "base"
    prefix: str = ""
    provides_telemetry: bool = False  # used to mark seasons as "limited data" in the catalog

    def has_season(self, year: int) -> bool:
        raise NotImplementedError

    def events(self, year: int) -> list[dict]:
        """[{meeting_name, country, location, round, circuit_key, date_start, sessions: [SessionRef]}]"""
        raise NotImplementedError

    def session(self, session_id: str) -> SessionRef:
        raise NotImplementedError

    def capabilities(self, s: SessionRef) -> Capabilities:
        raise NotImplementedError

    def drivers(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("drivers")

    def laps(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("lap times")

    def stints(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("stints / compounds")

    def pits(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("pit stops")

    def race_control(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("race control")

    def intervals(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("intervals")

    def weather(self, s: SessionRef) -> pd.DataFrame:
        raise DataUnavailable("weather")

    def car_data(self, s: SessionRef, driver_number: int) -> pd.DataFrame:
        raise DataUnavailable("car telemetry")

    def position_data(self, s: SessionRef, driver_number: int) -> pd.DataFrame:
        raise DataUnavailable("position data")
