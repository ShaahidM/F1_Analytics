"""OpenF1 adapter (2023+). Field names verified 2026-11-14 — see docs/DATA_SOURCES.md."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.config import OPENF1_BASE
from app.sources.base import (
    CAR_COLUMNS, DRIVER_COLUMNS, LAP_COLUMNS, PIT_COLUMNS, POS_COLUMNS, STINT_COLUMNS,
    Capabilities, DataUnavailable, SessionRef, SessionSource, empty, season_ttl,
)
from app.sources.http import NotFound, http
from app.storage.cache import cached_frame, parquet_path

SESSION_TYPES = {"Race", "Qualifying", "Practice"}


def _ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="ISO8601")


class OpenF1Source(SessionSource):
    name = "openf1"
    prefix = "of"
    provides_telemetry = True

    def _get(self, endpoint: str, params: dict, ttl: timedelta | None = None) -> list[dict]:
        try:
            return http.get_json(f"{OPENF1_BASE}/{endpoint}", params, ttl=ttl)
        except NotFound:
            return []

    def _frame(self, endpoint: str, s: SessionRef, **params) -> pd.DataFrame:
        return pd.DataFrame(self._get(endpoint, {"session_key": self._key(s), **params}, ttl=s.cache_ttl()))

    @staticmethod
    def _key(s: SessionRef) -> int:
        return int(s.id.split("-", 1)[1])

    # ---- catalog -----------------------------------------------------------------
    def has_season(self, year: int) -> bool:
        return bool(self._get("sessions", {"year": year}, ttl=season_ttl(year)))

    def _session_ref(self, row: dict, meeting: dict | None) -> SessionRef:
        return SessionRef(
            id=f"{self.prefix}-{row['session_key']}",
            source=self.name,
            year=int(row["year"]),
            round=None,
            meeting_name=(meeting or {}).get("meeting_name") or row.get("location", ""),
            country=row.get("country_name", ""),
            location=row.get("location", ""),
            circuit_key=row.get("circuit_key"),
            circuit_name=row.get("circuit_short_name", ""),
            session_name=row["session_name"],
            session_type=row["session_type"],
            date_start=pd.Timestamp(row["date_start"]).to_pydatetime() if row.get("date_start") else None,
            date_end=pd.Timestamp(row["date_end"]).to_pydatetime() if row.get("date_end") else None,
        )

    def events(self, year: int) -> list[dict]:
        ttl = season_ttl(year)
        meetings = {m["meeting_key"]: m for m in self._get("meetings", {"year": year}, ttl=ttl)}
        by_meeting: dict[int, list[SessionRef]] = {}
        for row in self._get("sessions", {"year": year}, ttl=ttl):
            if row.get("session_type") not in SESSION_TYPES or row.get("is_cancelled"):
                continue
            by_meeting.setdefault(row["meeting_key"], []).append(self._session_ref(row, meetings.get(row["meeting_key"])))
        events = []
        for mk, sessions in by_meeting.items():
            sessions.sort(key=lambda r: r.date_start or pd.Timestamp.max)
            m = meetings.get(mk, {})
            events.append({
                "meeting_key": mk,
                "meeting_name": m.get("meeting_name") or sessions[0].meeting_name,
                "country": sessions[0].country,
                "location": sessions[0].location,
                "circuit_key": sessions[0].circuit_key,
                "date_start": sessions[0].date_start,
                "sessions": sessions,
            })
        events.sort(key=lambda e: e["date_start"] or pd.Timestamp.max)
        # Only meetings with a race are championship rounds; pre-season testing (practice-only) gets no number.
        rnd = 0
        for e in events:
            is_round = any(s.session_type == "Race" for s in e["sessions"])
            rnd += is_round
            e["round"] = rnd if is_round else None
            for s in e["sessions"]:
                s.round = e["round"]
        return events

    def session(self, session_id: str) -> SessionRef:
        key = int(session_id.split("-", 1)[1])
        rows = self._get("sessions", {"session_key": key})
        if not rows:
            raise KeyError(session_id)
        row = rows[0]
        meetings = self._get("meetings", {"meeting_key": row["meeting_key"]})
        return self._session_ref(row, meetings[0] if meetings else None)

    def capabilities(self, s: SessionRef) -> Capabilities:
        caps = Capabilities(
            lap_times=True, sectors=True, compounds=True, pit=s.is_race, telemetry=True,
            position=True, weather=True, race_control=True, intervals=s.is_race,
        )
        if s.session_type == "Practice":
            caps.notes.append(
                "Practice session: trend analyses use detected long runs only (5+ laps at consistent pace on one tyre "
                "set). Fuel loads, engine modes and run plans are unknown and differ between teams, so compare trends "
                "within a driver or between teammates rather than absolute pace between teams."
            )
        if s.year >= 2026:
            caps.notes.append(
                "2026+ regulations: no DRS (field is null); throttle/coasting are strongly affected by energy "
                "management, so interpret throttle-based indicators with caution."
            )
        return caps

    # ---- session tables -------------------------------------------------------------
    def drivers(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("drivers", s)
        if df.empty:
            return empty(DRIVER_COLUMNS)
        out = pd.DataFrame({
            "driver_number": df["driver_number"].astype(int),
            "code": df["name_acronym"],
            "full_name": df["full_name"],
            "team": df["team_name"],
            "team_colour": df["team_colour"].map(lambda c: f"#{c}" if isinstance(c, str) and c else None),
        })
        return out.drop_duplicates("driver_number").sort_values("driver_number").reset_index(drop=True)

    def laps(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("laps", s)
        if df.empty:
            return empty(LAP_COLUMNS)
        out = pd.DataFrame({
            "driver_number": df["driver_number"].astype(int),
            "lap_number": df["lap_number"].astype(int),
            "lap_start": _ts(df["date_start"]),
            "lap_time_s": pd.to_numeric(df["lap_duration"], errors="coerce"),
            "s1_s": pd.to_numeric(df["duration_sector_1"], errors="coerce"),
            "s2_s": pd.to_numeric(df["duration_sector_2"], errors="coerce"),
            "s3_s": pd.to_numeric(df["duration_sector_3"], errors="coerce"),
            "i1_speed": pd.to_numeric(df["i1_speed"], errors="coerce"),
            "i2_speed": pd.to_numeric(df["i2_speed"], errors="coerce"),
            "st_speed": pd.to_numeric(df["st_speed"], errors="coerce"),
            "is_pit_out": df["is_pit_out_lap"].fillna(False).astype(bool),
            "is_pit_in": False,  # derived from pit stops in processing.laps
        })
        return out.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)

    def stints(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("stints", s)
        if df.empty:
            return empty(STINT_COLUMNS)
        out = pd.DataFrame({
            "driver_number": df["driver_number"].astype(int),
            "stint": df["stint_number"].astype(int),
            "lap_start": pd.to_numeric(df["lap_start"], errors="coerce").astype("Int64"),
            "lap_end": pd.to_numeric(df["lap_end"], errors="coerce").astype("Int64"),
            "compound": df["compound"].where(df["compound"].notna(), None),
            "tyre_age_at_start": pd.to_numeric(df["tyre_age_at_start"], errors="coerce").astype("Int64"),
        })
        return out.sort_values(["driver_number", "stint"]).reset_index(drop=True)

    def pits(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("pit", s) if s.is_race else pd.DataFrame()
        if df.empty:
            return empty(PIT_COLUMNS)
        return pd.DataFrame({
            "driver_number": df["driver_number"].astype(int),
            "lap_number": df["lap_number"].astype(int),
            "date": _ts(df["date"]),
            "lane_duration_s": pd.to_numeric(df.get("lane_duration", df.get("pit_duration")), errors="coerce"),
            "stop_duration_s": pd.to_numeric(df.get("stop_duration"), errors="coerce"),
        })

    def race_control(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("race_control", s)
        if df.empty:
            return df
        df["date"] = _ts(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def intervals(self, s: SessionRef) -> pd.DataFrame:
        if not s.is_race:
            raise DataUnavailable("intervals (race only)")

        def build() -> pd.DataFrame:
            df = self._frame("intervals", s)
            if df.empty:
                return pd.DataFrame(columns=["date", "driver_number", "interval_s", "gap_to_leader_s"])
            return pd.DataFrame({
                "date": _ts(df["date"]),
                "driver_number": df["driver_number"].astype(int),
                # Non-numeric values such as "+1 LAP" become NaN (lapped, not a time gap).
                # The leader's interval is reported as 0, not null: it has no car ahead, so treat it as missing.
                "interval_s": pd.to_numeric(df["interval"], errors="coerce").replace(0.0, float("nan")),
                "gap_to_leader_s": pd.to_numeric(df["gap_to_leader"], errors="coerce"),
            })

        return cached_frame(parquet_path(self.name, self._key(s), "intervals"), build, persist=s.is_settled())

    def weather(self, s: SessionRef) -> pd.DataFrame:
        df = self._frame("weather", s)
        if not df.empty:
            df["date"] = _ts(df["date"])
        return df

    # ---- telemetry (whole session per driver, persisted as Parquet) -------------------
    def _telemetry(self, s: SessionRef, endpoint: str, driver_number: int, table: str, build_cols) -> pd.DataFrame:
        def build() -> pd.DataFrame:
            try:
                raw = http.get_csv(f"{OPENF1_BASE}/{endpoint}", {"session_key": self._key(s), "driver_number": driver_number, "csv": "true"})
            except NotFound:
                raise DataUnavailable(f"{endpoint} for car {driver_number}")
            raw["date"] = _ts(raw["date"])
            return build_cols(raw).sort_values("date").reset_index(drop=True)

        return cached_frame(parquet_path(self.name, self._key(s), f"{table}_{driver_number}"), build, persist=s.is_settled())

    def car_data(self, s: SessionRef, driver_number: int) -> pd.DataFrame:
        def cols(raw: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({
                "date": raw["date"],
                "speed": pd.to_numeric(raw["speed"], errors="coerce"),
                "throttle": pd.to_numeric(raw["throttle"], errors="coerce"),
                "brake": pd.to_numeric(raw["brake"], errors="coerce"),
                "gear": pd.to_numeric(raw["n_gear"], errors="coerce"),
                "rpm": pd.to_numeric(raw["rpm"], errors="coerce"),
                "drs": pd.to_numeric(raw["drs"], errors="coerce"),
            })[CAR_COLUMNS]

        return self._telemetry(s, "car_data", driver_number, "car", cols)

    def position_data(self, s: SessionRef, driver_number: int) -> pd.DataFrame:
        def cols(raw: pd.DataFrame) -> pd.DataFrame:
            df = raw[["date", "x", "y", "z"]].apply(lambda c: c if c.name == "date" else pd.to_numeric(c, errors="coerce"))
            # (0,0,0) samples are placeholders emitted before the car is on track.
            return df[~((df["x"] == 0) & (df["y"] == 0) & (df["z"] == 0))][POS_COLUMNS]

        return self._telemetry(s, "location", driver_number, "pos", cols)
