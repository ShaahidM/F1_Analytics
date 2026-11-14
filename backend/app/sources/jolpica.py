"""Jolpica-F1 (Ergast successor) adapter — results, lap times and pit stops only (no telemetry, sectors or compounds).

Used for seasons OpenF1 doesn't cover (2019–2022 within the current scope).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.config import JOLPICA_BASE
from app.sources.base import (
    DRIVER_COLUMNS, LAP_COLUMNS, PIT_COLUMNS, Capabilities, DataUnavailable, SessionRef, SessionSource, empty,
    season_ttl,
)
from app.sources.http import NotFound, http

# Jolpica session keys → (session_name, session_type, results endpoint, results table key).
SESSION_KINDS = {
    "R": ("Race", "Race", "results", "Results"),
    "Q": ("Qualifying", "Qualifying", "qualifying", "QualifyingResults"),
    "S": ("Sprint", "Race", "sprint", "SprintResults"),
}
SCHEDULE_KEYS = {"R": None, "Q": "Qualifying", "S": "Sprint"}
PAGE = 100


def _parse_dt(block: dict | None) -> datetime | None:
    if not block or not block.get("date"):
        return None
    t = block.get("time", "00:00:00Z").replace("Z", "+00:00")
    return datetime.fromisoformat(f"{block['date']}T{t}").astimezone(timezone.utc)


def _lap_seconds(text: str | None) -> float | None:
    if not text:
        return None
    parts = text.split(":")
    try:
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    except ValueError:
        return None


class JolpicaSource(SessionSource):
    name = "jolpica"
    prefix = "jp"

    def _get(self, path: str, ttl: timedelta | None, offset: int = 0) -> dict:
        return http.get_json(f"{JOLPICA_BASE}/{path}", {"limit": PAGE, "offset": offset}, ttl=ttl)["MRData"]

    def _paged_races(self, path: str, ttl: timedelta | None) -> list[dict]:
        """Jolpica paginates by inner rows (laps/stops), splitting one race across pages — merge them."""
        races: list[dict] = []
        offset = 0
        while True:
            data = self._get(path, ttl, offset)
            races.extend(data["RaceTable"]["Races"])
            offset += PAGE
            if offset >= int(data["total"]):
                return races

    @staticmethod
    def _parse_id(session_id: str) -> tuple[int, int, str]:
        _, year, rnd, kind = session_id.split("-")
        return int(year), int(rnd), kind

    def _schedule(self, year: int) -> list[dict]:
        return self._get(f"{year}/races/", season_ttl(year))["RaceTable"]["Races"]

    def _ref(self, race: dict, kind: str) -> SessionRef:
        name, stype, _, _ = SESSION_KINDS[kind]
        block = race if kind == "R" else race.get(SCHEDULE_KEYS[kind])
        start = _parse_dt(block)
        circuit = race["Circuit"]
        return SessionRef(
            id=f"{self.prefix}-{race['season']}-{int(race['round']):02d}-{kind}",
            source=self.name,
            year=int(race["season"]),
            round=int(race["round"]),
            meeting_name=race["raceName"],
            country=circuit["Location"].get("country", ""),
            location=circuit["Location"].get("locality", ""),
            circuit_key=None,
            circuit_name=circuit.get("circuitName", ""),
            session_name=name,
            session_type=stype,
            date_start=start,
            date_end=start + timedelta(hours=2) if start else None,
        )

    def has_season(self, year: int) -> bool:
        return bool(self._schedule(year))

    def events(self, year: int) -> list[dict]:
        events = []
        for race in self._schedule(year):
            sessions = [self._ref(race, k) for k in ("Q", "S", "R") if k == "R" or race.get(SCHEDULE_KEYS[k])]
            sessions.sort(key=lambda r: r.date_start or datetime.max.replace(tzinfo=timezone.utc))
            events.append({
                "meeting_key": f"{race['season']}-{race['round']}",
                "meeting_name": race["raceName"],
                "country": sessions[-1].country,
                "location": sessions[-1].location,
                "circuit_key": None,
                "date_start": sessions[0].date_start,
                "round": int(race["round"]),
                "sessions": sessions,
            })
        return events

    def session(self, session_id: str) -> SessionRef:
        year, rnd, kind = self._parse_id(session_id)
        for race in self._schedule(year):
            if int(race["round"]) == rnd:
                return self._ref(race, kind)
        raise KeyError(session_id)

    def capabilities(self, s: SessionRef) -> Capabilities:
        is_gp_race = s.id.endswith("-R")
        return Capabilities(
            lap_times=is_gp_race,
            pit=is_gp_race,
            notes=[
                "Telemetry, racing lines, sector times and tyre compounds are not publicly available for this "
                "season: F1's timing archive requires an F1 TV subscription since Oct 2026. Source: Jolpica-F1 "
                "(lap times and pit stops only).",
                "No race-control data for this season: safety-car, VSC and red-flag laps cannot be detected and "
                "are only removed if they fail the lap-time outlier test.",
            ],
        )

    def drivers(self, s: SessionRef) -> pd.DataFrame:
        year, rnd, kind = self._parse_id(s.id)
        _, _, endpoint, table = SESSION_KINDS[kind]
        races = self._get(f"{year}/{rnd}/{endpoint}/", s.cache_ttl())["RaceTable"]["Races"]
        if not races:
            return empty(DRIVER_COLUMNS)
        rows = [{
            "driver_number": int(r["number"]),
            "code": r["Driver"].get("code") or r["Driver"]["familyName"][:3].upper(),
            "full_name": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
            "team": r["Constructor"]["name"],
            "team_colour": None,  # Jolpica has no colours; the UI uses driver A/B colours anyway.
            "_driver_id": r["Driver"]["driverId"],
        } for r in races[0][table]]
        return pd.DataFrame(rows).sort_values("driver_number").reset_index(drop=True)

    def _driver_ids(self, s: SessionRef) -> dict[str, int]:
        d = self.drivers(s)
        return dict(zip(d["_driver_id"], d["driver_number"]))

    def laps(self, s: SessionRef) -> pd.DataFrame:
        if not s.id.endswith("-R"):
            raise DataUnavailable("lap-by-lap times (Jolpica only has them for Grand Prix races)")
        year, rnd, _ = self._parse_id(s.id)
        ids = self._driver_ids(s)
        rows = []
        for race in self._paged_races(f"{year}/{rnd}/laps/", s.cache_ttl()):
            for lap in race.get("Laps", []):
                for t in lap["Timings"]:
                    rows.append({"driver_number": ids.get(t["driverId"]), "lap_number": int(lap["number"]),
                                 "lap_time_s": _lap_seconds(t.get("time"))})
        if not rows:
            return empty(LAP_COLUMNS)
        df = pd.DataFrame(rows).dropna(subset=["driver_number"])
        df["driver_number"] = df["driver_number"].astype(int)
        for col in ("s1_s", "s2_s", "s3_s", "i1_speed", "i2_speed", "st_speed"):
            df[col] = float("nan")
        df["lap_start"] = pd.NaT
        pits = self.pits(s)
        pit_in = set(zip(pits["driver_number"], pits["lap_number"]))
        df["is_pit_in"] = [(d, n) in pit_in for d, n in zip(df["driver_number"], df["lap_number"])]
        df["is_pit_out"] = [(d, n - 1) in pit_in for d, n in zip(df["driver_number"], df["lap_number"])]
        return df[LAP_COLUMNS].sort_values(["driver_number", "lap_number"]).reset_index(drop=True)

    def pits(self, s: SessionRef) -> pd.DataFrame:
        if not s.id.endswith("-R"):
            raise DataUnavailable("pit stops")
        year, rnd, _ = self._parse_id(s.id)
        ids = self._driver_ids(s)
        rows = []
        for race in self._paged_races(f"{year}/{rnd}/pitstops/", s.cache_ttl()):
            for p in race.get("PitStops", []):
                rows.append({
                    "driver_number": ids.get(p["driverId"]),
                    "lap_number": int(p["lap"]),
                    "date": pd.NaT,
                    # Jolpica "duration" is pit-lane time (entry to exit), not stationary time.
                    "lane_duration_s": _lap_seconds(p.get("duration")),
                    "stop_duration_s": None,
                })
        if not rows:
            return empty(PIT_COLUMNS)
        df = pd.DataFrame(rows).dropna(subset=["driver_number"])
        df["driver_number"] = df["driver_number"].astype(int)
        return df[PIT_COLUMNS]
